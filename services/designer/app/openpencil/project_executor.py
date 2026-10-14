import re
from contextlib import suppress
from pathlib import Path
from typing import Any

from ..generation.jsx import compile_palette_jsx
from ..models import ComponentBindingSet, OpenPencilProfile, ProjectSpecification, UiSpecification
from .media import is_stock_media
from .page_agent import design_page


def page_name(screen_name: str, platform: str) -> str:
    clean = re.sub(r"\s+", " ", screen_name).strip() or "Screen"
    label = {
        "desktop": "Desktop",
        "tablet": "Tablet",
        "mobile": "Mobile",
        "responsive": "Responsive",
    }[platform]
    return f"{clean[:70]} · {label}"


def specification_for_platform(specification: UiSpecification, platform: str) -> UiSpecification:
    viewports = {
        "mobile": (390, 844),
        "tablet": (768, 1024),
        "desktop": (1440, 1024),
        # Responsive pages use a desktop reference canvas. Adaptation belongs
        # in the composition; a 390px reference silently turns enterprise UI
        # into a cramped mobile mockup and also breaks retries of older specs.
        "responsive": (1440, 1024),
    }
    width, height = viewports.get(platform, (specification.viewport_width, specification.viewport_height))
    return specification.model_copy(
        deep=True,
        update={"platform": platform, "viewport_width": width, "viewport_height": height},
    )


def binding_subset(bindings: ComponentBindingSet, specification: UiSpecification) -> ComponentBindingSet:
    node_ids: set[str] = set()

    def collect(node: Any) -> None:
        node_ids.add(node.id)
        for child in node.children:
            collect(child)

    collect(specification.root)
    return ComponentBindingSet(bindings=[item for item in bindings.bindings if item.node_id in node_ids])


def media_count(specification: UiSpecification) -> int:
    count = 0

    def collect(node: Any) -> None:
        nonlocal count
        if is_stock_media(node):
            count += 1
        for child in node.children:
            collect(child)

    collect(specification.root)
    return count


def flow_canvas_position(index: int, width: int = 390, height: int = 844) -> tuple[int, int]:
    """Return a deterministic, non-overlapping position for a flow screen."""
    columns = 3
    gap = 96
    return (index % columns) * (width + gap), (index // columns) * (height + gap)


async def assemble_project(
    gateway: Any,
    profile: OpenPencilProfile,
    project: ProjectSpecification,
    bindings: ComponentBindingSet,
    *,
    run_id: str | None,
    llm: Any,
    prompts: Any,
    checkpoint: dict[str, Any] | None = None,
    on_checkpoint: Any = None,
    component_candidates: list[dict[str, Any]] | None = None,
    exact_assets: list[dict[str, Any]] | None = None,
    on_event: Any = None,
) -> dict[str, Any]:
    component_ids = list(
        dict.fromkeys(
            item.component_id for item in bindings.bindings if item.status == "resolved" and item.component_id
        )
    )
    pack = await gateway.source.pack(profile.source_file, component_ids)
    component_media = dict(gateway.source.packed_media)
    checkpoint = checkpoint or {}
    completed = set(checkpoint.get("completed", []))
    screen_results: list[dict[str, Any]] = list(checkpoint.get("screens", []))
    preview_urls: dict[str, str] = {
        item["key"]: item["telemetry"]["preview"] for item in screen_results if item.get("telemetry", {}).get("preview")
    }

    async with gateway.session(profile.endpoint) as session:
        (
            document_id,
            local,
            palette_page_id,
            resumed,
            palette_needs_render,
            checkpoint_reset,
        ) = await _prepare_project_document(gateway, session, profile, pack, checkpoint)
        if checkpoint_reset:
            checkpoint = {}
            completed.clear()
            screen_results.clear()
            preview_urls.clear()
        local_bindings = bindings.model_copy(deep=True)
        for binding in local_bindings.bindings:
            if binding.component_id in local:
                binding.component_id = local[binding.component_id]
        for source_id, local_id in local.items():
            if source_id in component_media:
                component_media[local_id] = component_media[source_id]

        await gateway._call(
            session,
            "switch_page",
            {"page": palette_page_id, "page_id": palette_page_id, "document_id": document_id},
        )
        if palette_needs_render:
            await gateway._call(
                session,
                "render",
                {
                    "jsx": compile_palette_jsx(
                        project.brief.product_name or "Project",
                        project.design_context.style_manifest,
                    ),
                    "document_id": document_id,
                    "page_id": palette_page_id,
                },
            )
        # Persist the document skeleton before generating any screen. A failed
        # render/refinement must still leave a real file that Retry can reopen.
        await gateway._call(
            session,
            "save_file",
            {"path": profile.output_file, "document_id": document_id, "page_id": palette_page_id},
        )
        if on_checkpoint:
            await on_checkpoint(
                {
                    **checkpoint,
                    "document_id": document_id,
                    "local_components": local,
                    "palette_page_id": palette_page_id,
                    "completed": sorted(completed),
                    "screens": screen_results,
                }
            )

        flow_page_name = f"{project.brief.product_name or 'Design'} · Flow"
        listed_flow_pages = await gateway._call(
            session,
            "list_pages",
            {"document_id": document_id, "page_id": palette_page_id},
        )
        flow_page = next(
            (item for item in listed_flow_pages.get("pages", []) if item.get("name") == flow_page_name),
            None,
        )
        if flow_page:
            flow_page_id = str(flow_page["id"])
        else:
            created_flow_page = await gateway._call(
                session,
                "create_page",
                {"name": flow_page_name, "document_id": document_id, "page_id": palette_page_id},
            )
            flow_page_id = str(created_flow_page["id"])

        for screen in project.screens:
            for platform in screen.platforms:
                key = f"{screen.screen_id}:{platform}"
                if key in completed:
                    continue
                spec = specification_for_platform(screen.specification, platform)
                name = flow_page_name
                page_id = flow_page_id
                await gateway._call(
                    session,
                    "switch_page",
                    {
                        "page": page_id,
                        "page_id": page_id,
                        "document_id": document_id,
                    },
                )
                previous_result = next((item for item in screen_results if item.get("key") == key), None)
                existing_root = str(previous_result.get("root_node_id") or "") if previous_result else ""
                existing_jsx = ""
                if existing_root:
                    current = await gateway._call(
                        session,
                        "get_jsx",
                        {
                            "id": existing_root,
                            "document_id": document_id,
                            "page_id": page_id,
                        },
                    )
                    existing_jsx = str(current.get("jsx", ""))
                progress_checkpoint = {
                    "document_id": document_id,
                    "local_components": local,
                    "palette_page_id": palette_page_id,
                    "completed": sorted(completed),
                    "screens": screen_results,
                    "last_screen": key,
                    "in_progress_page_id": page_id,
                    "in_progress_page_name": name,
                    "flow_page_id": flow_page_id,
                }
                if on_checkpoint:
                    await on_checkpoint(progress_checkpoint)
                page_bindings = binding_subset(local_bindings, spec)
                try:
                    result = await design_page(
                        gateway,
                        session,
                        llm=llm,
                        prompts=prompts,
                        document_id=document_id,
                        page_id=page_id,
                        specification=spec,
                        bindings=page_bindings,
                        component_context={
                            "definitions": dict(pack),
                            "local_components": local,
                            "candidates": component_candidates or [],
                        },
                        source_file=profile.source_file,
                        request=project.design_context.model_dump_json(),
                        on_event=on_event,
                        root_id=existing_root,
                        current_jsx=existing_jsx,
                        exact_assets=exact_assets,
                        component_media=component_media,
                    )
                except Exception:
                    # Keep successful native edits when a later model/tool call fails.
                    with suppress(Exception):
                        await gateway._call(
                            session,
                            "save_file",
                            {"path": profile.output_file, "document_id": document_id, "page_id": palette_page_id},
                        )
                    raise
                root_id = result["root_id"]
                telemetry = result["telemetry"]
                screen_index = sum(
                    1
                    for item in screen_results
                    if item.get("key") != key
                )
                x, y = flow_canvas_position(screen_index, spec.viewport_width, spec.viewport_height)
                await gateway._call(
                    session,
                    "node_move",
                    {"id": root_id, "x": x, "y": y, "document_id": document_id, "page_id": page_id},
                )
                root_name = f"{screen.screen_id} · {spec.screen_name}"
                await gateway._call(
                    session,
                    "rename_node",
                    {
                        "id": root_id,
                        "name": root_name,
                        "document_id": document_id,
                        "page_id": page_id,
                    },
                )
                bounds_result = await gateway._call(
                    session,
                    "node_bounds",
                    {"id": root_id, "document_id": document_id, "page_id": page_id},
                )
                bounds = bounds_result.get("bounds", {}) if isinstance(bounds_result, dict) else {}
                expected = sum(item.status == "resolved" for item in page_bindings.bindings)
                telemetry["expected_photos"] = media_count(spec)
                repairs = []
                inspection_status = "reviewed" if result["inspected"] else "unavailable"
                preview = await gateway._capture_preview(session, document_id, page_id, root_id, scale=0.5)
                if preview and run_id:
                    url = _write_preview(run_id, key, preview)
                    preview_urls[key] = url
                    telemetry["preview"] = url
                telemetry["repairs"] = repairs
                telemetry["inspection_status"] = inspection_status
                telemetry["design_trace"] = result["trace"]
                screen_results.append(
                    {
                        "key": key,
                        "screen_id": screen.screen_id,
                        "screen_name": spec.screen_name,
                        "platform": platform,
                        "page_id": page_id,
                        "page_name": name,
                        "canvas_x": x,
                        "canvas_y": y,
                        "root_node_id": root_id,
                        "root_name": root_name,
                        "width": float(bounds.get("width") or spec.viewport_width),
                        "height": float(bounds.get("height") or spec.viewport_height),
                        "expected_instances": expected,
                        "telemetry": telemetry,
                    }
                )
                completed.add(key)
                await gateway._call(
                    session,
                    "save_file",
                    {"path": profile.output_file, "document_id": document_id, "page_id": palette_page_id},
                )
                if on_checkpoint:
                    await on_checkpoint(
                        {
                            "document_id": document_id,
                            "local_components": local,
                            "palette_page_id": palette_page_id,
                            "completed": sorted(completed),
                            "screens": screen_results,
                            "last_screen": key,
                            "flow_page_id": flow_page_id,
                        }
                    )

        await gateway._call(
            session,
            "save_file",
            {"path": profile.output_file, "document_id": document_id, "page_id": palette_page_id},
        )

    first = screen_results[0] if screen_results else {}
    return {
        "document_id": document_id,
        "page_id": first.get("page_id", palette_page_id),
        "page_name": first.get("page_name", "Design Tokens"),
        "output_file": profile.output_file,
        "root_node_id": first.get("root_node_id", ""),
        "created_nodes": sum(item["telemetry"]["instances"] + 1 for item in screen_results),
        "screens": screen_results,
        "completed": sorted(completed),
        "previews": preview_urls,
        "media_assets": [
            asset for item in screen_results for asset in item.get("telemetry", {}).get("media_assets", [])
        ],
    }


async def _prepare_project_document(
    gateway: Any,
    session: Any,
    profile: OpenPencilProfile,
    pack: list[tuple[str, str]],
    checkpoint: dict[str, Any],
) -> tuple[str, dict[str, str], str, bool, bool, bool]:
    resumed = (
        bool(checkpoint.get("document_id") or checkpoint.get("completed")) or profile.target_mode == "existing_file"
    )
    live_document = None
    if checkpoint.get("document_id"):
        opened = await gateway._call(session, "list_documents", {})
        live_document = next(
            (item for item in opened.get("documents", []) if str(item.get("id")) == str(checkpoint["document_id"])),
            None,
        )
    if live_document:
        result = {"documentId": str(live_document["id"])}
    elif resumed:
        result = await gateway._call(session, "open_file", {"path": profile.output_file})
    else:
        result = await gateway._call(session, "new_document", {"path": profile.output_file})
    document_id, _ = gateway._target(result)
    if not document_id:
        raise RuntimeError("OpenPencil did not return a document id")
    target = {"document_id": document_id}
    if live_document and checkpoint.get("palette_page_id"):
        target["page_id"] = str(checkpoint["palette_page_id"])
    listed = await gateway._call(session, "list_pages", target)
    pages = listed.get("pages", [])
    checkpoint_reset = bool(checkpoint and not _checkpoint_matches_pages(checkpoint, pages))
    named_pages = {str(item.get("name")): str(item.get("id")) for item in pages}
    palette_needs_render = False
    if "Design Tokens" in named_pages:
        palette_page_id = named_pages["Design Tokens"]
    elif resumed:
        page = await gateway._call(
            session,
            "create_page",
            {"name": "Design Tokens", "document_id": document_id},
        )
        palette_page_id = str(page["id"])
        palette_needs_render = True
    elif pages:
        palette_page_id = str(pages[0]["id"])
        await gateway._call(
            session,
            "rename_node",
            {"id": palette_page_id, "name": "Design Tokens", "document_id": document_id},
        )
        palette_needs_render = True
    else:
        page = await gateway._call(session, "create_page", {"name": "Design Tokens", "document_id": document_id})
        palette_page_id = str(page["id"])
        palette_needs_render = True

    local = (
        {}
        if checkpoint_reset
        else {str(key): str(value) for key, value in checkpoint.get("local_components", {}).items()}
    )
    component_page_id = named_pages.get("Components", "")
    if local and component_page_id:
        tree = await gateway._call(
            session,
            "get_page_tree",
            {
                "document_id": document_id,
                "page_id": component_page_id,
                "depth": 1,
            },
        )
        master_ids = {str(node["id"]) for node in tree.get("children", []) if node.get("type") == "COMPONENT"}
        local = {source: node for source, node in local.items() if node in master_ids}
    elif local:
        local = {}
    if any(source_id not in local for source_id, _ in pack):
        if not component_page_id:
            page = await gateway._call(
                session,
                "create_page",
                {
                    "name": "Components",
                    "document_id": document_id,
                    "page_id": palette_page_id,
                },
            )
            component_page_id = str(page["id"])
        await gateway._call(
            session,
            "switch_page",
            {"page": component_page_id, "page_id": component_page_id, "document_id": document_id},
        )
        for source_id, source_jsx in pack:
            if source_id in local:
                continue
            jsx = source_jsx
            for old_id, new_id in local.items():
                jsx = jsx.replace(old_id, new_id)
            rendered = await gateway._call(
                session,
                "render",
                {"jsx": jsx, "document_id": document_id, "page_id": component_page_id},
            )
            local[source_id] = str(rendered["id"])
    return (
        document_id,
        local,
        palette_page_id,
        resumed,
        palette_needs_render,
        checkpoint_reset,
    )


def _checkpoint_matches_pages(checkpoint: dict[str, Any], pages: list[dict[str, Any]]) -> bool:
    """Saved .fig files can remap IDs; names alone cannot validate a checkpoint."""
    page_ids = {str(item.get("id")) for item in pages}
    expected = {str(item["page_id"]) for item in checkpoint.get("screens", []) if item.get("page_id")}
    if checkpoint.get("palette_page_id"):
        expected.add(str(checkpoint["palette_page_id"]))
    return expected <= page_ids


def _write_preview(run_id: str, key: str, preview: tuple[bytes, str]) -> str:
    raw, extension = preview
    safe_key = re.sub(r"[^a-zA-Z0-9_-]", "_", key)
    previews_dir = Path(__file__).resolve().parent.parent / "data" / "previews"
    previews_dir.mkdir(parents=True, exist_ok=True)
    (previews_dir / f"{run_id}_{safe_key}.{extension}").write_bytes(raw)
    return f"/api/v1/runs/{run_id}/preview?screen={safe_key}"

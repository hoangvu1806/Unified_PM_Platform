"""Shared tool-driven designer for project pages and workspace edits."""

import asyncio
import hashlib
import json
import re
from typing import Any

from google.adk.agents.invocation_context import LlmCallsLimitExceededError
from google.adk.tools import ToolContext
from google.genai import types

from ..core.errors import AppError, unwrap_app_error
from ..generation.design_skills import load_openpencil_jsx_knowledge
from ..models import ComponentBindingSet, UiSpecification
from .media import apply_uploaded_asset_markers, apply_uploaded_component_media, apply_unsplash_media, is_stock_media
from .qa import blocking_findings, measure_screen, required_content_gaps

# The visual agent gets one batch editor instead of a wrapper per MCP method.
# These are mechanical canvas operations, not aesthetic rules.
OPENPENCIL_EDIT_TOOLS = {
    "update_node",
    "set_fill",
    "set_stroke",
    "set_radius",
    "set_opacity",
    "set_text",
    "set_text_properties",
    "set_text_resize",
    "set_layout",
    "set_layout_child",
    "set_minmax",
    "node_resize",
    "node_move",
    "reparent_node",
    "create_shape",
    "insert_icon",
    "delete_node",
    "create_instance",
    "clone_node",
    "rename_node",
    "node_replace_with",
}


def _compact_schema(value: Any) -> Any:
    """Keep the executable part of an MCP schema and discard prompt-heavy prose."""
    if isinstance(value, list):
        return [_compact_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    keep = {"type", "enum", "required", "properties", "items", "anyOf", "oneOf", "allOf"}
    return {key: _compact_schema(item) for key, item in value.items() if key in keep}


MAX_REFINEMENT_ROUNDS = 3


def _acceptable_canvas(state: dict[str, Any], specification: UiSpecification) -> bool:
    """A rendered, inspected page with a preview and no blocking geometry."""
    return bool(
        state.get("rendered")
        and state.get("inspected")
        and state.get("preview_available")
        and not blocking_findings(state.get("telemetry") or {}, specification.viewport_width)
    )


async def design_page(
    gateway: Any,
    session: Any,
    *,
    llm: Any,
    prompts: Any,
    document_id: str,
    page_id: str,
    specification: UiSpecification,
    bindings: ComponentBindingSet,
    component_context: Any,
    source_file: str = "",
    request: str = "",
    root_id: str = "",
    current_jsx: str = "",
    edit_mode: bool = False,
    edit_contract: dict[str, Any] | None = None,
    exact_assets: list[dict[str, Any]] | None = None,
    component_media: dict[str, str] | None = None,
    on_event: Any = None,
) -> dict[str, Any]:
    """Run one continuous design conversation over the real OpenPencil canvas."""
    target = {"document_id": document_id, "page_id": page_id}
    resolved = [item for item in bindings.bindings if item.status == "resolved"]
    state: dict[str, Any] = {
        "root_id": root_id,
        "jsx": current_jsx,
        "rendered": False,
        "inspected": False,
        "finished": False,
        "catalog_read": False,
        "plan": "",
        "telemetry": {},
        "instance_ids": {},
        "inspection_id": 0,
        "reflection": None,
        "preview_available": False,
        "blocking_error": "",
        "summary": "",
        "last_fingerprint": "",
        "unchanged_inspections": 0,
        "refined": False,
        "edit_count": 0,
        "edit_tool_schemas": {},
        "last_failed_action": "",
        "repeated_failure": 0,
        "stall_error": "",
        "trace": [],
    }
    available_icons: set[str] = set()
    exact_assets = exact_assets or []
    asset_ids = {
        str(item.get("id"))
        for item in exact_assets
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    asset_manifest_lines: list[str] = []
    for item in exact_assets:
        if not isinstance(item, dict) or not str(item.get("id") or "").strip():
            continue
        item_id = str(item["id"])
        dimensions = (
            f"{item.get('width')}x{item.get('height')} px, aspect {item.get('aspect_ratio')}"
            if item.get("width") and item.get("height")
            else "dimensions unavailable"
        )
        colors = ", ".join(str(value) for value in item.get("dominant_colors", [])) or "unknown"
        asset_manifest_lines.append(
            f"- token `asset::{item_id}`; original file `{item.get('name', item_id)}`; "
            f"role `{item.get('visual_role', 'image')}`; {dimensions}; colors `{colors}`; "
            f"background `{item.get('background_type', 'unknown')}`; preferred fit "
            f"`{item.get('recommended_fit', 'contain')}`; suggested placement "
            f"`{item.get('recommended_placement', 'content area')}`; safe padding "
            f"`{item.get('safe_padding_percent', 0)}%`; rationale: "
            f"{item.get('placement_reason', '') or 'Match the current screen hierarchy.'}"
        )
    asset_manifest = "\n".join(asset_manifest_lines) or "- No uploaded assets"
    asset_instruction = (
        "Uploaded images are already attached to this request. Select them by semantic role "
        "(for example, the mascot/logo image), visible content, aspect ratio, colors, and the "
        "current screen hierarchy. When several images exist, match by original filename and "
        "visual role; never pick the first asset by position. Preserve source aspect ratio, use "
        "the recommended fit, respect safe padding, and place the image where its role best "
        "supports the existing composition. Resolve the internal token yourself; "
        "the user does not need to provide an asset ID. Render each selected upload as a "
        "Rectangle or Ellipse whose name is exactly `asset::<id>` so the backend can replace "
        "it with the original bytes. Do not draw a solid-color image placeholder and do not "
        "route an uploaded image through the design-system component catalog unless the "
        "specification explicitly requests that binding.\n"
        "Available internal asset manifest:\n" + asset_manifest
    )
    preview_parts: list[types.Part] = []
    lock = asyncio.Lock()
    nodes_by_id: dict[str, Any] = {}

    def index_nodes(node: Any) -> None:
        nodes_by_id[node.id] = node
        for child in node.children:
            index_nodes(child)

    index_nodes(specification.root)

    # A retry continues from the saved canvas when all real instances exist.
    if root_id and current_jsx:
        mounted: dict[str, str] = {}
        for binding in resolved:
            matches = await gateway._call(session, "find_nodes", {**target, "name": f"component::{binding.node_id}"})
            for match in matches.get("nodes", []):
                mount = await gateway._call(session, "get_node", {**target, "id": match["id"], "depth": 1})
                instance = next((child for child in mount.get("children", []) if child.get("type") == "INSTANCE"), None)
                if instance:
                    mounted[binding.node_id] = str(instance["id"])
                    break
        # The page exists on the canvas, so it is inspectable and editable even when some
        # mounts are missing (they surface as blocking findings). Without this, edit mode —
        # which has no render_page tool — could never inspect the page and always stalled.
        state.update(rendered=True, instances=len(mounted), instance_ids=mounted)
        if len(mounted) == len(resolved):
            state.update(refined=True)
            uploaded_media = await apply_uploaded_component_media(
                gateway,
                session,
                **target,
                bindings=bindings,
                instance_ids=mounted,
                exact_assets=exact_assets,
                asset_node_ids={
                    node_id: str(node.content.get("asset_id") or "")
                    for node_id, node in nodes_by_id.items()
                    if node.kind == "component"
                    and str(node.content.get("asset_binding") or "") == "design_system_component"
                },
                component_media=component_media,
            )
            if uploaded_media.get("failed"):
                raise ValueError(
                    "Uploaded asset application failed: "
                    + json.dumps(uploaded_media, ensure_ascii=False)
                )
            marker_media = await apply_uploaded_asset_markers(
                gateway, session, **target, exact_assets=exact_assets
            )
            if marker_media.get("failed"):
                raise ValueError(
                    "Uploaded asset marker application failed: "
                    + json.dumps(marker_media, ensure_ascii=False)
                )
            state["uploaded_media"] = {**uploaded_media, "uploaded_markers": marker_media}

    async def load_edit_tool_schemas() -> dict[str, Any]:
        if state["edit_tool_schemas"]:
            return state["edit_tool_schemas"]
        list_tools = getattr(session, "list_tools", None)
        if not list_tools:
            return {}
        try:
            listed = await list_tools()
            state["edit_tool_schemas"] = {
                tool.name: _compact_schema(tool.inputSchema)
                for tool in listed.tools
                if tool.name in OPENPENCIL_EDIT_TOOLS
            }
        except Exception:
            state["edit_tool_schemas"] = {}
        return state["edit_tool_schemas"]

    async def perform(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        # ADK can dispatch several calls in one response. Serialize canvas writes.
        async with lock:
            if on_event:
                await on_event({"tool": name, "message": f"Designer is running {name}", "status": "running"})
            try:
                result = await execute(name, arguments)
                record = {
                    "tool": name,
                    "ok": bool(result.get("ok", True)),
                    "message": (
                        f"Designer completed {name}"
                        if result.get("ok", True)
                        else f"Designer will correct failed operations from {name}"
                    ),
                }
                if name == "inspect":
                    record.update(
                        inspection_id=result.get("inspection_id"),
                        preview_attached=result.get("preview_attached", False),
                        live_jsx_chars=len(result.get("live_jsx", "")),
                    )
                elif name == "reflect":
                    record.update(
                        inspection_id=result.get("inspection_id"),
                        needs_refinement=result.get("needs_refinement"),
                        issue_count=len(result.get("remaining_issues", [])),
                    )
                elif name == "edit_canvas":
                    failed = [item for item in result.get("operations", []) if not item.get("ok", False)]
                    record.update(
                        operation_count=len(result.get("operations", [])),
                        failed_operations=len(failed),
                        failed_details=[
                            {"tool": item.get("tool"), "error": item.get("error")}
                            for item in failed[:12]
                        ],
                        inspection_id=(result.get("observation") or {}).get("inspection_id"),
                        canvas_progress=(result.get("observation") or {}).get("canvas_progress"),
                    )
            except Exception as error:
                actual = unwrap_app_error(error) or error
                if isinstance(actual, AppError) and actual.code in {
                    "OPENPENCIL_MCP_TIMEOUT",
                    "OPENPENCIL_MCP_UNAVAILABLE",
                    "OPENPENCIL_APP_DISCONNECTED",
                    "OPENPENCIL_SOURCE_UNAVAILABLE",
                }:
                    raise actual from error
                result = {
                    "ok": False,
                    "error": getattr(actual, "detail", str(actual)),
                    "error_type": type(error).__name__,
                    "next_step": "Inspect the current state if needed, then correct the tool arguments. Preserve the plan.",
                }
                record = {"tool": name, **result}
                record["message"] = f"Designer will correct {name}: {result['error']}"
            stagnant = (
                not result.get("ok", True)
                or bool(result.get("unchanged"))
                or (name == "inspect" and result.get("canvas_progress") == "unchanged_since_previous_inspection")
                or (
                    name == "edit_canvas"
                    and (result.get("observation") or {}).get("canvas_progress")
                    == "unchanged_since_previous_inspection"
                )
            )
            if not stagnant:
                state["last_failed_action"] = ""
                state["repeated_failure"] = 0
            else:
                signature = hashlib.sha256(
                    json.dumps([name, arguments, state["last_fingerprint"]], sort_keys=True, default=str).encode()
                ).hexdigest()
                state["repeated_failure"] = (
                    int(state["repeated_failure"]) + 1
                    if signature == state["last_failed_action"] else 1
                )
                state["last_failed_action"] = signature
                if state["repeated_failure"] >= 3:
                    failed = result.get("operations") or []
                    detail = result.get("error") or (failed[0].get("error") if failed else "No canvas change")
                    state["stall_error"] = f"The same {name} call failed repeatedly: {detail}"
                    result["next_step"] = "Continue from the saved canvas in a fresh designer context."
            state["trace"].append(record)
            if on_event:
                await on_event(record)
            return result

    async def execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if edit_mode and name == "render":
            raise ValueError(
                "Full-page render is disabled for an existing-page edit. "
                "Use inspect_nodes, edit_node, edit_canvas, or node_replace_with."
            )
        if name == "design_system":
            state["catalog_read"] = True
            definitions = component_context.get("definitions", {})
            local = component_context.get("local_components", {})
            source_by_local = {value: key for key, value in local.items()}
            candidates_by_id = {
                str(item.get("component_id")): item for item in component_context.get("candidates", [])
            }
            inspected_bindings = []
            for binding in bindings.bindings:
                source_id = source_by_local.get(binding.component_id, binding.component_id)
                definition = definitions.get(source_id, "")
                target_node = nodes_by_id.get(binding.node_id)
                candidate = candidates_by_id.get(str(source_id), {})
                inspected_bindings.append(
                    {
                        **binding.model_dump(mode="json"),
                        "target_content": target_node.content if target_node else {},
                        "writable_text_names": list(
                            dict.fromkeys(re.findall(r'<Text\b[^>]*\bname=["\']([^"\']+)', definition))
                        ),
                        "component": {
                            key: candidate.get(key)
                            for key in (
                                "component_id",
                                "canonical_path",
                                "variant_name",
                                "width",
                                "height",
                                "text_slots",
                                "slot_candidates",
                            )
                            if candidate.get(key) is not None
                        },
                    }
                )
            unresolved = [item for item in inspected_bindings if item["status"] == "unresolved"]
            candidates = component_context.get("candidates", [])
            families: dict[str, int] = {}
            for candidate in candidates:
                path = str(candidate.get("canonical_path") or candidate.get("name") or "Other")
                family = path.split("/", 1)[0].strip() or "Other"
                families[family] = families.get(family, 0) + 1
            return {
                "coverage": {
                    "requirements": len(inspected_bindings),
                    "resolved": len(inspected_bindings) - len(unresolved),
                    "unresolved": len(unresolved),
                },
                "bindings": inspected_bindings,
                "unresolved_bindings": unresolved,
                "components": {
                    "candidate_count": len(candidates),
                    "families": dict(sorted(families.items())),
                },
                "canvas_tools": sorted(OPENPENCIL_EDIT_TOOLS),
                "next_step": (
                    "Search focused alternatives if needed, then plan and render. "
                    "Before native edits, request schemas only for the tools you intend to use."
                ),
            }
        if name == "canvas_tools":
            requested = list(dict.fromkeys(str(item).strip() for item in arguments["names"] if str(item).strip()))
            schemas = await load_edit_tool_schemas()
            unknown = [item for item in requested if item not in OPENPENCIL_EDIT_TOOLS]
            return {
                "schemas": {item: schemas[item] for item in requested if item in schemas},
                "unknown": unknown,
                "available": sorted(OPENPENCIL_EDIT_TOOLS),
                "next_step": "Use these exact property names and enum values in edit_canvas.",
            }
        if name == "search_components":
            if not state["catalog_read"]:
                raise ValueError("Call inspect_design_system before searching alternatives.")
            query = str(arguments["query"]).strip()
            node_id = str(arguments.get("node_id", "")).strip()
            target_node = nodes_by_id.get(node_id)
            context = (
                f"{query} {target_node.name if target_node else ''} "
                f"{target_node.requirement if target_node else ''}"
            ).lower()
            words = set(re.findall(r"[a-z0-9]+", context))

            def score(candidate: dict[str, Any]) -> tuple[int, int, str]:
                identity = json.dumps(candidate, ensure_ascii=True).lower()
                matched = sum(word in identity for word in words)
                return (-matched, -int(candidate.get("knowledge_score") or 0), identity)

            matches = sorted(component_context.get("candidates", []), key=score)[:24]
            return {
                "node_id": node_id,
                "query": query,
                "matches": matches,
                "next_step": "Use an exact component_id with bind_component, or keep the current binding.",
            }
        if name == "plan":
            plan = str(arguments["plan"]).strip()
            if not plan:
                raise ValueError("Write a concise, concrete design plan.")
            state["plan"] = plan
            return {
                "ok": True,
                "plan": plan,
                "next_step": "Execute this direction. Change the plan only when canvas evidence justifies it.",
            }
        if name == "icons":
            names = arguments["names"]
            result = await gateway._call(session, "fetch_icons", {**target, "names": names})
            missing = set(result.get("not_found", []))
            available_icons.update(set(names) - missing)
            if missing:
                result["alternatives"] = await gateway._call(
                    session,
                    "search_icons",
                    {
                        **target,
                        "queries": [value.split(":")[-1].replace("-", " ") for value in missing],
                        "limit": 8,
                    },
                )
            return result
        if name == "bind":
            binding = next((item for item in bindings.bindings if item.node_id == arguments["node_id"]), None)
            if binding is None:
                raise ValueError(f"Unknown node_id. Choose one of: {[item.node_id for item in bindings.bindings]}")
            values = json.loads(arguments["text_values_json"])
            if not isinstance(values, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in values.items()
            ):
                raise ValueError("text_values_json must map inspected text slots to string values.")
            component_id = arguments["component_id"]
            local = component_context.setdefault("local_components", {})
            candidates = {item["component_id"] for item in component_context.get("candidates", [])}
            if component_id == binding.component_id or component_id in local.values():
                local_id = component_id
            elif component_id in local:
                local_id = local[component_id]
            elif component_id in candidates and source_file:
                pack = await gateway.source.pack(source_file, [component_id])
                pages = await gateway._call(session, "list_pages", {"document_id": document_id})
                page = next((item for item in pages.get("pages", []) if item.get("name") == "Components"), None)
                if page is None:
                    page = await gateway._call(
                        session, "create_page", {"document_id": document_id, "name": "Components"}
                    )
                for source_id, jsx in pack:
                    if source_id in local:
                        continue
                    for old, new in local.items():
                        jsx = jsx.replace(old, new)
                    root = await gateway._call(
                        session,
                        "render",
                        {
                            "document_id": document_id,
                            "page_id": str(page["id"]),
                            "jsx": jsx,
                        },
                    )
                    local[source_id] = str(root["id"])
                component_context.setdefault("definitions", {}).update(dict(pack))
                local_id = local[component_id]
            else:
                raise ValueError("Choose an inspected component ID from inspect_design_system.")
            binding.component_id = local_id
            binding.status = "resolved"
            binding.text_values = values
            resolved[:] = [item for item in bindings.bindings if item.status == "resolved"]
            state.update(
                inspected=False,
                finished=False,
                rendered=False,
                instance_ids={},
                reflection=None,
                preview_available=False,
                refined=False,
                edit_count=0,
            )
            return {
                "binding": binding.model_dump(mode="json"),
                "imported_component_id": local_id,
                "next_step": "Render again to apply this binding.",
            }
        if name == "render":
            if not state["catalog_read"]:
                raise ValueError("Call inspect_design_system before designing the page.")
            if not state["plan"]:
                raise ValueError("Call plan_design after inspecting the design system, then render.")
            jsx = arguments["jsx"].strip()
            if state["rendered"] and jsx == state["jsx"]:
                return {
                    "ok": True,
                    "unchanged": True,
                    "root_id": state["root_id"],
                    "instances": state["instances"],
                    "component_instances": state["instance_ids"],
                    "next_step": "The JSX is unchanged. Use the latest inspection to reflect now.",
                }
            if state["refined"] and not arguments.get("reset_refinements", False):
                raise ValueError(
                    "A full render would replace the live component instances and discard successful canvas "
                    "refinements. Continue with edit_canvas, or pass reset_refinements=true only for an "
                    "intentional structural rebuild and then restyle every mounted component again."
                )
            # Validate only the integration contract, never rewrite aesthetics.
            missing = [
                binding.node_id
                for binding in resolved
                if not re.search(
                    r"""name\s*=\s*(?:\{\s*)?["']slot::""" + re.escape(binding.node_id) + r"""["']""",
                    jsx,
                )
            ]
            if missing:
                raise ValueError(
                    f"Missing component mounts: {', '.join('slot::' + node for node in missing)}. "
                    'Add an empty <Frame name="slot::<node_id>" w={...} h={...} /> for each, '
                    "using the inspected dimensions."
                )
            photo_markers = set(
                re.findall(r"""name\s*=\s*(?:\{\s*)?[\"']photo::([^\"']+)[\"']""", jsx)
            )
            stock_media_ids = {
                node_id for node_id, node in nodes_by_id.items() if is_stock_media(node)
            }
            invalid_photo_markers = sorted(photo_markers - stock_media_ids)
            if invalid_photo_markers:
                raise ValueError(
                    "Invalid stock-photo markers: "
                    + ", ".join(f"photo::{node_id}" for node_id in invalid_photo_markers)
                    + ". User assets and placeholders must use local asset references or vector "
                    "primitives; only explicitly requested stock media may use photo::<id>."
                )
            if asset_ids:
                asset_markers = set(
                    re.findall(r"asset::([A-Za-z0-9_-]+)", jsx)
                )
                asset_component_ids = {
                    node.id
                    for node in nodes_by_id.values()
                    if node.kind == "component"
                    and node.content.get("asset_binding") == "design_system_component"
                }
                invalid_assets = sorted(asset_markers - asset_ids)
                selected_asset_ids = {
                    str(node.content.get("asset_id") or "")
                    for node in nodes_by_id.values()
                    if node.kind in {"media", "graphic", "component"}
                    and str(node.content.get("asset_id") or "") in asset_ids
                }
                required_marker_ids = selected_asset_ids - {
                    str(nodes_by_id[node_id].content.get("asset_id") or "")
                    for node_id in asset_component_ids
                }
                missing_assets = sorted(required_marker_ids - asset_markers)
                if invalid_assets or missing_assets:
                    details = []
                    if invalid_assets:
                        details.append("unknown asset IDs: " + ", ".join(invalid_assets))
                    if missing_assets:
                        details.append("uploaded assets not used: " + ", ".join(missing_assets))
                    raise ValueError(
                        "Use uploaded images by their exact asset ID, never by filename. "
                        + "; ".join(details)
                        + ". Required tokens: "
                        + ", ".join(f"asset::{item_id}" for item_id in sorted(asset_ids))
                    )
            icons = set(re.findall(r"""<Icon\b[^>]*\bname=["']([^"']+)["']""", jsx))
            invalid_icons = sorted(icon for icon in icons if ":" not in icon)
            if invalid_icons:
                raise ValueError(
                    f"Invalid Iconify names {invalid_icons}. Use exact family:name from fetch_icons, "
                    "or replace the icon with a supported element."
                )
            if icons - available_icons:
                raise ValueError(f"Fetch these icons first: {sorted(icons - available_icons)}")
            args = {**target, "jsx": jsx}
            if state["root_id"]:
                args["replace_id"] = state["root_id"]
            state.update(
                inspected=False,
                finished=False,
                rendered=False,
                instance_ids={},
                reflection=None,
                preview_available=False,
                refined=False,
                edit_count=0,
            )
            preview_parts.clear()
            root = await gateway._call(session, "render", args)
            state.update(root_id=str(root["id"]), jsx=jsx)
            # Record root immediately: a later insertion failure is repaired in
            # place rather than appending duplicate screens on the next attempt.
            inserted = (
                await gateway._insert_instances(
                    session,
                    document_id,
                    page_id,
                    bindings,
                )
                if resolved
                else {}
            )
            instance_ids = inserted if isinstance(inserted, dict) else {}
            count = len(inserted) if isinstance(inserted, dict) else int(inserted)
            if count != len(resolved):
                raise ValueError(
                    f"Inserted {count}/{len(resolved)} required components. Inspect the page and repair the mounts."
                )
            uploaded_media = await apply_uploaded_component_media(
                gateway,
                session,
                **target,
                bindings=bindings,
                instance_ids=instance_ids,
                exact_assets=exact_assets,
                asset_node_ids={
                    node_id: str(node.content.get("asset_id") or "")
                    for node_id, node in nodes_by_id.items()
                    if node.kind == "component"
                    and str(node.content.get("asset_binding") or "") == "design_system_component"
                },
                component_media=component_media,
            )
            if uploaded_media.get("failed"):
                raise ValueError(
                    "Uploaded asset application failed: "
                    + json.dumps(uploaded_media, ensure_ascii=False)
                )
            marker_media = await apply_uploaded_asset_markers(
                gateway, session, **target, exact_assets=exact_assets
            )
            if marker_media.get("failed"):
                raise ValueError(
                    "Uploaded asset marker application failed: "
                    + json.dumps(marker_media, ensure_ascii=False)
                )
            media = await apply_unsplash_media(
                gateway,
                session,
                **target,
                specification=specification,
            )
            if media.get("failed", 0):
                raise ValueError(f"Media application failed: {json.dumps(media, ensure_ascii=False)}")
            state.update(
                rendered=True,
                instances=count,
                instance_ids=instance_ids,
                media={**media, "uploaded": uploaded_media, "uploaded_markers": marker_media},
            )
            return {
                "ok": True,
                "root_id": state["root_id"],
                "instances": count,
                "component_instances": instance_ids,
                "uploaded_media": {
                    "components": uploaded_media,
                    "markers": marker_media,
                },
                "next_step": (
                    "Inspect the rendered page, then use OpenPencil node tools for precise visual corrections."
                ),
            }
        if name == "inspect_nodes":
            if not state["rendered"]:
                raise ValueError("Render the page before reading or editing its live nodes.")
            ids = [str(value).strip() for value in arguments["ids"] if str(value).strip()]
            if not ids:
                raise ValueError("Pass at least one live node ID from inspect_page or component_instances.")
            nodes = [
                await gateway._call(session, "get_node", {**target, "id": node_id, "depth": 4})
                for node_id in ids[:20]
            ]
            return {"ok": True, "nodes": nodes, "next_step": "Use these exact IDs in edit_canvas."}
        if name == "edit_canvas":
            if not state["rendered"]:
                raise ValueError("Render the page before editing its live nodes.")
            operations = arguments["operations"]
            if not operations:
                raise ValueError("Pass at least one edit operation.")
            results: list[dict[str, Any]] = []
            changed = False
            for operation in operations:
                if not isinstance(operation, dict):
                    results.append({"ok": False, "tool": "", "error": "Each operation must be a JSON object."})
                    continue
                tool = str(operation.get("tool") or operation.get("name") or "").strip()
                supplied = operation.get("arguments", operation.get("args", {}))
                if tool not in OPENPENCIL_EDIT_TOOLS or not isinstance(supplied, dict):
                    results.append(
                        {
                            "ok": False,
                            "tool": tool,
                            "error": (
                                'Use {"tool":"set_fill","arguments":{"id":"0:1","color":"#2563EB"}}. '
                                "For a simple property change, call edit_node instead."
                            ),
                        }
                    )
                    continue
                supplied = {key: value for key, value in supplied.items() if key not in {"document_id", "page_id"}}
                try:
                    value = await gateway._call(session, tool, {**supplied, **target})
                    item = {"ok": True, "tool": tool, "arguments": supplied}
                    if tool in {
                        "create_shape",
                        "insert_icon",
                        "create_instance",
                        "clone_node",
                        "node_replace_with",
                    }:
                        item["result"] = value
                    results.append(item)
                    changed = True
                except Exception as error:
                    actual = unwrap_app_error(error) or error
                    if isinstance(actual, AppError) and actual.code in {
                        "OPENPENCIL_MCP_TIMEOUT",
                        "OPENPENCIL_MCP_UNAVAILABLE",
                        "OPENPENCIL_APP_DISCONNECTED",
                    }:
                        raise actual from error
                    schemas = await load_edit_tool_schemas()
                    results.append(
                        {
                            "ok": False,
                            "tool": tool,
                            "arguments": supplied,
                            "error": getattr(actual, "detail", str(actual)),
                            "expected_schema": schemas.get(tool, {}),
                        }
                    )
            observation = None
            if changed:
                successful_edits = sum(item["ok"] for item in results)
                state.update(
                    inspected=False,
                    finished=False,
                    reflection=None,
                    preview_available=False,
                    refined=True,
                    edit_count=int(state["edit_count"]) + successful_edits,
                )
                inspected = await execute("inspect", {})
                observation = {
                    key: inspected[key]
                    for key in (
                        "inspection_id",
                        "telemetry",
                        "blocking_findings",
                        "canvas_progress",
                        "unchanged_inspections",
                        "preview_attached",
                    )
                }
            return {
                "ok": all(item["ok"] for item in results),
                "operations": results,
                "observation": observation,
                "component_instances": state["instance_ids"],
                "next_step": "Correct failed operations if any. Successful edits were inspected automatically.",
            }
        if name == "inspect":
            if not state["root_id"]:
                raise ValueError("Render the page first.")
            telemetry = await measure_screen(gateway, session, **target, root_node_id=state["root_id"])
            live = await gateway._call(session, "get_jsx", {**target, "id": state["root_id"]})
            preview = await gateway._capture_preview(
                session,
                document_id,
                page_id,
                state["root_id"],
                scale=0.65 if specification.viewport_width > 800 else 1,
            )
            preview_parts.clear()
            if preview and preview[1].lower() in {"png", "jpg", "jpeg", "webp", "svg"}:
                extension = preview[1].lower()
                mime = (
                    "image/jpeg"
                    if extension in {"jpg", "jpeg"}
                    else "image/svg+xml"
                    if extension == "svg"
                    else f"image/{extension}"
                )
                preview_parts.append(types.Part.from_bytes(data=preview[0], mime_type=mime))
            media = state.get("media", {"applied": 0, "assets": []})
            live_jsx = str(live.get("jsx", ""))
            uploaded = media.get("uploaded", {}) if isinstance(media, dict) else {}
            marker_assets = (
                uploaded.get("uploaded_markers", {}).get("assets", [])
                if isinstance(uploaded, dict)
                else []
            )
            component_assets = uploaded.get("assets", []) if isinstance(uploaded, dict) else []
            telemetry.update(
                instances=state.get("instances", 0),
                fallbacks=0,
                stock_photos=media["applied"],
                media_assets=[*media["assets"], *component_assets, *marker_assets],
                content_gaps=required_content_gaps(
                    specification,
                    live_jsx,
                    [value for binding in resolved for value in binding.text_values.values()],
                    telemetry.get("visible_text", []),
                ),
            )
            blockers = blocking_findings(telemetry, specification.viewport_width)
            model_telemetry = {
                key: telemetry.get(key)
                for key in (
                    "root_bounds",
                    "placeholders",
                    "component_styles",
                    "clipped_instance_text",
                    "visible_text",
                    "content_gaps",
                    "small_touch_targets",
                    "instances",
                    "design_lint",
                )
            }
            model_telemetry["overlaps"] = {
                "summary": (telemetry.get("overlaps") or {}).get("summary"),
                "overlaps": [
                    item for item in (telemetry.get("overlaps") or {}).get("overlaps", [])
                    if item.get("severity") in {"major", "critical"}
                ][:12],
            }
            digest = hashlib.sha256(
                json.dumps(
                    {
                        "jsx": live_jsx,
                        "bounds": telemetry.get("root_bounds"),
                        "components": telemetry.get("component_styles"),
                    },
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")
            ).hexdigest()
            unchanged = bool(state["last_fingerprint"] and digest == state["last_fingerprint"])
            inspection_id = int(state["inspection_id"]) + 1
            state.update(
                telemetry=telemetry,
                inspected=True,
                inspection_id=inspection_id,
                reflection=None,
                preview_available=bool(preview_parts),
                blocking_error="" if preview_parts else state["blocking_error"],
                last_fingerprint=digest,
                unchanged_inspections=(int(state["unchanged_inspections"]) + 1 if unchanged else 0),
            )
            return {
                "inspection_id": inspection_id,
                "telemetry": model_telemetry,
                "blocking_findings": blockers,
                "live_jsx": live_jsx,
                "design_plan": state["plan"],
                "component_instances": state["instance_ids"],
                "canvas_edits": state["edit_count"],
                "canvas_progress": (
                    "unchanged_since_previous_inspection" if unchanged else "changed_since_previous_inspection"
                ),
                "unchanged_inspections": state["unchanged_inspections"],
                "preview_attached": bool(preview_parts),
                "visual_evidence": "Screenshot attached to the next model turn."
                if preview_parts
                else "No visual preview available. Retry inspection; visual completion cannot be accepted yet.",
            }
        if name == "reflect":
            if not state["inspected"]:
                raise ValueError("Inspect the latest material change before reflecting.")
            assessment = str(arguments["assessment"]).strip()
            issues = [str(item).strip() for item in arguments["remaining_issues"] if str(item).strip()]
            needs_refinement = bool(arguments["needs_refinement"])
            if not assessment:
                raise ValueError("Give a concise assessment grounded in the latest JSX, telemetry and screenshot.")
            if issues and not needs_refinement:
                raise ValueError("remaining_issues is not empty. Refine them or set needs_refinement=true.")
            if not needs_refinement:
                if not state["preview_available"]:
                    state["blocking_error"] = (
                        "No visual preview was available for this inspection. Inspect again before accepting "
                        "the design; do not approve visual quality from JSX alone."
                    )
                    raise ValueError(state["blocking_error"])
                blockers = blocking_findings(state["telemetry"], specification.viewport_width)
                if blockers:
                    raise ValueError(
                        "The latest inspection still has blocking geometry. Repair the live nodes with "
                        "edit_node or edit_canvas, then reinspect: "
                        f"{json.dumps(blockers, ensure_ascii=False)}"
                    )
            rounds = int(state.get("refinement_rounds") or 0) + (1 if needs_refinement else 0)
            state["refinement_rounds"] = rounds
            if needs_refinement and rounds >= MAX_REFINEMENT_ROUNDS and _acceptable_canvas(state, specification):
                # Polish is subjective past this point: hand the open items to the human reviewer.
                needs_refinement = False
            reflection = {
                "inspection_id": state["inspection_id"],
                "assessment": assessment,
                "remaining_issues": issues,
                "needs_refinement": needs_refinement,
            }
            state.update(
                reflection=reflection,
                finished=not needs_refinement,
                summary=assessment if not needs_refinement else "",
            )
            return {
                **reflection,
                "next_step": (
                    "Use the appropriate tools to resolve the listed issues, then inspect and reflect again."
                    if needs_refinement
                    else "Design complete."
                ),
            }
        raise ValueError(f"Unknown tool: {name}")

    async def inspect_design_system() -> dict[str, Any]:
        """Read the retrieved component definitions and every skeleton binding before rendering."""
        return await perform("design_system", {})

    async def plan_design(plan: str) -> dict[str, Any]:
        """Record the chosen visual direction, composition, signature idea and concrete success checks.

        Keep it concise. Base it on the approved skeleton and the inspected component library.
        """
        return await perform("plan", {"plan": plan})

    async def search_design_system(query: str, node_id: str = "") -> dict[str, Any]:
        """Search the retrieved real catalog for focused alternatives to one binding.

        Use a semantic query such as "default radio with text" or "primary large
        button" and optionally the specification node ID. Results retain exact
        component IDs, variants, dimensions and text slots for bind_component.
        """
        return await perform("search_components", {"query": query, "node_id": node_id})

    async def inspect_canvas_tools(names: list[str]) -> dict[str, Any]:
        """Return compact live MCP schemas for the native edit tools needed next.

        Request the small set you are about to call. This keeps unrelated schemas
        out of context while preserving OpenPencil as the schema authority.
        """
        return await perform("canvas_tools", {"names": names})

    async def fetch_icons(names: list[str]) -> dict[str, Any]:
        """Fetch exact Iconify names before using them; missing names return search alternatives."""
        return await perform("icons", {"names": names})

    async def render_page(
        jsx: str, reset_refinements: bool = False, tool_context: ToolContext = None
    ) -> dict[str, Any]:
        """Render or replace this whole page with static JSX, then mount real components and photos.

        Include an empty Frame name="slot::<node_id>" for each resolved binding.
        On renderer errors, correct the JSX and call again. After edit_canvas has
        changed live nodes, prefer more native edits: another full render would
        recreate default instances. Set reset_refinements=true only when a real
        structural rebuild is necessary, then inspect and restyle the new instances.
        """
        result = await perform("render", {"jsx": jsx, "reset_refinements": reset_refinements})
        if tool_context is not None and state["stall_error"]:
            tool_context.actions.skip_summarization = True
        return result

    async def bind_component(node_id: str, component_id: str, text_values_json: str) -> dict[str, Any]:
        """Choose another inspected component or repair its text-slot mapping. Render to apply.

        Use exact catalog IDs and a JSON object mapping writable slot names to text.
        Alternative components are imported with their dependencies before use.
        """
        return await perform(
            "bind", {"node_id": node_id, "component_id": component_id, "text_values_json": text_values_json}
        )

    async def inspect_nodes(ids: list[str]) -> dict[str, Any]:
        """Read full properties and nested children for live node IDs from inspect_page."""
        return await perform("inspect_nodes", {"ids": ids})

    async def edit_node(
        id: str,
        fill: str = "",
        stroke: str = "",
        text: str = "",
        width: float = 0,
        height: float = 0,
        corner_radius: float = -1,
        font_size: float = 0,
        font_weight: float = 0,
        tool_context: ToolContext = None,
    ) -> dict[str, Any]:
        """Edit one live node's common properties and inspect the resulting canvas.

        Use IDs from inspect_page or inspect_nodes. For a TEXT node, fill sets
        its text color. For advanced layout or structural edits use edit_canvas.
        """
        update: dict[str, Any] = {"id": id}
        for key, value in (
            ("text", text),
            ("width", width),
            ("height", height),
            ("font_size", font_size),
            ("font_weight", font_weight),
        ):
            if value:
                update[key] = value
        if corner_radius >= 0:
            update["corner_radius"] = corner_radius
        operations = ([{"tool": "update_node", "arguments": update}] if len(update) > 1 else [])
        if fill:
            operations.append({"tool": "set_fill", "arguments": {"id": id, "color": fill}})
        if stroke:
            operations.append({"tool": "set_stroke", "arguments": {"id": id, "color": stroke}})
        result = await perform("edit_canvas", {"operations": operations})
        if tool_context is not None and state["stall_error"]:
            tool_context.actions.skip_summarization = True
        return result

    async def edit_canvas(
        operations: list[dict[str, Any]], tool_context: ToolContext = None
    ) -> dict[str, Any]:
        """Apply a group of native OpenPencil edits, then automatically inspect the result.

        Each item is {"tool": "set_fill", "arguments": {"id": "0:1", "color": "#4F46E5"}}.
        Call inspect_canvas_tools for the operations you intend to use and follow
        those schemas exactly; do not translate JSX property names into MCP
        arguments. Prefer 5-12 related operations, observe,
        then continue. node_replace_with can repair one local subtree without
        recreating the whole page.
        Allowed tools: update_node, set_fill, set_stroke, set_radius,
        set_opacity, set_text, set_text_properties, set_text_resize, set_layout,
        set_layout_child, set_minmax, node_resize, node_move, reparent_node,
        create_shape, insert_icon, delete_node, create_instance, clone_node,
        rename_node, node_replace_with. Every operation returns its own
        success/error; successful edits remain applied.
        """
        result = await perform("edit_canvas", {"operations": operations})
        if tool_context is not None and state["stall_error"]:
            tool_context.actions.skip_summarization = True
        return result

    async def inspect_page() -> dict[str, Any]:
        """Inspect layout, current JSX, screenshot and exact mounted component IDs."""
        return await perform("inspect", {})

    async def reflect_page(
        assessment: str,
        remaining_issues: list[str],
        needs_refinement: bool,
        tool_context: ToolContext = None,
    ) -> dict[str, Any]:
        """Reflect on the latest screenshot, live JSX, telemetry and approved plan.

        Check content and navigation completeness, visual hierarchy, component fit,
        spacing, readability and product character. List concrete remaining issues;
        set needs_refinement=true whenever the page needs another material change.
        A clean reflection completes the page without a redundant confirmation turn.
        """
        result = await perform(
            "reflect",
            {
                "assessment": assessment,
                "remaining_issues": remaining_issues,
                "needs_refinement": needs_refinement,
            },
        )
        if tool_context is not None:
            if state["blocking_error"] or (
                "error" not in result and result.get("needs_refinement") is False
            ):
                tool_context.actions.skip_summarization = True
        return result

    async def attach_preview(callback_context: Any, llm_request: Any) -> None:
        if on_event:
            await on_event(
                {
                    "tool": "model",
                    "status": "running",
                    "message": "Designer is choosing the next action from the plan and tool results",
                }
            )
        if preview_parts:
            llm_request.contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text="Latest page screenshot. Review against the plan before finishing."),
                        *preview_parts,
                    ],
                )
            )
            preview_parts.clear()

    prompt = prompts.render(
        "page-designer",
        request=request + "\n\n" + asset_instruction,
        specification=specification.model_dump_json(),
        current_jsx=current_jsx,
        edit_mode=("true" if edit_mode else "false"),
        edit_contract=json.dumps(edit_contract or {}, ensure_ascii=False, indent=2),
        jsx_knowledge=(
            load_openpencil_jsx_knowledge()
            + "\n\nEXACT UPLOADED ASSET TOKENS (use these exact IDs):\n"
            + asset_manifest
        ),
    )
    designer_model = getattr(getattr(llm, "settings", None), "effective_designer_model", None)
    if not isinstance(designer_model, str):
        designer_model = None
    tools = [
        inspect_design_system, search_design_system, inspect_canvas_tools, plan_design,
        bind_component, fetch_icons, inspect_nodes, edit_node,
        edit_canvas, inspect_page, reflect_page,
    ]
    if not edit_mode:
        tools.insert(6, render_page)

    def progress_token() -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "root_id": state["root_id"], "rendered": state["rendered"],
                    "catalog_read": state["catalog_read"], "inspected": state["inspected"],
                    "icons": sorted(available_icons), "plan": state["plan"],
                    "bindings": [(item.node_id, item.status, item.component_id, item.text_values)
                                 for item in bindings.bindings],
                    "canvas": state["last_fingerprint"], "edits": state["edit_count"],
                    "finished": state["finished"], "blocking_error": state["blocking_error"],
                    "stall_error": state["stall_error"],
                }, ensure_ascii=True, sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    settings = getattr(llm, "settings", None)
    max_steps = int(getattr(settings, "designer_page_max_steps", 45) or 45)
    page_timeout = float(getattr(settings, "designer_page_timeout_seconds", 720) or 720)
    reply = ""
    budget_hit = False
    for restart in range(2):
        try:
            reply = await llm.run_tools(
                prompt=prompt,
                tools=tools,
                before_model_callback=attach_preview,
                stop_when=lambda: bool(state["finished"] or state["blocking_error"] or state["stall_error"]),
                progress_token=progress_token,
                continuation_message=(
                    "The page is not complete. Continue with actual tool calls in this same session. "
                    "Use the returned MCP schemas and live node IDs, correct failed operations in a small batch, "
                    "inspect the changed canvas, and finish only through reflect_page. Do not return prose, "
                    "Markdown code, Python, or proposed operations."
                ),
                max_turns=max_steps,
                timeout_seconds=page_timeout,
                **({"model": designer_model} if designer_model else {}),
            )
        except (TimeoutError, LlmCallsLimitExceededError):
            budget_hit = True  # bounded loop: judge the saved canvas below instead of polishing forever
            break
        except AppError as exc:
            if exc.code != "AGENT_STALLED":
                raise
            # The model stopped calling tools: keep a canvas that already passes the blocking checks.
            state["stall_error"] = exc.detail
            budget_hit = True
            break
        if not state["stall_error"] or restart:
            break
        prompt += (
            "\n\nThe previous tool context stalled: " + state["stall_error"] +
            "\nContinue from the existing canvas; call inspect_page, use different valid tools or IDs, "
            "then reflect. Do not repeat the failed call. Current root: " + str(state["root_id"])
        )
        state.update(stall_error="", last_failed_action="", repeated_failure=0)
    if (budget_hit or state["stall_error"]) and not state["finished"] and _acceptable_canvas(state, specification):
        # The page is rendered, inspected and free of blocking geometry: hand it to the human
        # reviewer with the open polish items instead of failing the whole run.
        open_items = (state.get("reflection") or {}).get("remaining_issues") or []
        state.update(
            finished=True,
            stall_error="",
            summary="Step budget reached; the page passed the blocking checks. "
            + (f"Open polish items for review: {open_items}" if open_items else ""),
        )
    if state["blocking_error"]:
        raise AppError(
            "OPENPENCIL_PREVIEW_UNAVAILABLE",
            "OpenPencil screenshot is unavailable",
            state["blocking_error"],
            502,
            True,
            action="Bring the OpenPencil tab to the foreground, then retry this stage.",
        )
    if state["stall_error"]:
        blockers = blocking_findings(state.get("telemetry") or {}, specification.viewport_width)
        raise AppError(
            "AGENT_STALLED",
            "Designer repeated an action without progress",
            state["stall_error"][:600]
            + f" | rendered={state.get('rendered')} inspected={state.get('inspected')}"
            f" preview={state.get('preview_available')} blocking={json.dumps(blockers, ensure_ascii=False)[:900]}",
            502,
            True,
            action="Retry this stage to continue from the saved OpenPencil canvas.",
        )
    if not state["finished"]:
        raise AppError(
            "DESIGN_INCOMPLETE",
            "Designer did not finish the page",
            json.dumps({"trace": state["trace"][-4:], "reply": reply}, ensure_ascii=False),
            502,
            True,
        )
    return state

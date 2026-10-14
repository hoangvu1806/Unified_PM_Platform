import json
import re
from typing import Any

from ..generation.adk_hierarchical import generate_ui_specification
from ..models import (
    RunStage,
    RunStatus,
    SessionWorkspace,
    WorkspaceActionDecision,
    WorkspaceActionTarget,
    WorkspacePagePlan,
)
from ..openpencil.page_agent import design_page
from .build import prepare_workspace_components

RASTER_MIME_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
SYSTEM_PAGES = {"design tokens", "components", "color palette"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _ids(value: Any) -> set[str]:
    result: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            if item.get("id"):
                result.add(str(item["id"]))
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return result


def _structure_manifest(tree: dict[str, Any], root_id: str = "", max_nodes: int = 500) -> dict[str, Any]:
    """Create a compact, stable node map for edit prompts."""
    nodes: list[dict[str, Any]] = []

    def visit(value: Any, parent_id: str = "", depth: int = 0) -> None:
        if len(nodes) >= max_nodes or not isinstance(value, dict):
            return
        node_id = str(value.get("id") or "")
        if not node_id:
            return
        children = value.get("children", [])
        child_ids = [str(item.get("id")) for item in children if isinstance(item, dict) and item.get("id")]
        nodes.append(
            {
                "id": node_id,
                "parent_id": parent_id,
                "name": str(value.get("name") or ""),
                "type": str(value.get("type") or value.get("kind") or ""),
                "visible": value.get("visible", True),
                "children": child_ids,
                "depth": depth,
            }
        )
        for child in children if isinstance(children, list) else []:
            visit(child, node_id, depth + 1)

    roots = tree.get("children", []) if isinstance(tree, dict) else []
    for item in roots if isinstance(roots, list) else []:
        visit(item)
    return {"root_id": root_id, "nodes": nodes, "truncated": len(nodes) >= max_nodes}


def _edit_contract(
    manifest: dict[str, Any],
    *,
    page_id: str,
    root_id: str,
    instruction: str,
    action: str,
) -> dict[str, Any]:
    """Describe the smallest safe edit scope for an existing page."""
    tokens = {
        token
        for token in re.findall(r"[a-z0-9À-ỹ]+", instruction.casefold())
        if len(token) > 2
    }
    candidates = [
        item
        for item in manifest.get("nodes", [])
        if tokens.intersection(set(re.findall(r"[a-z0-9À-ỹ]+", str(item.get("name", "")).casefold())))
    ]
    target_ids = [str(item["id"]) for item in candidates[:12]] or ([root_id] if root_id else [])
    target_set = set(target_ids)
    protected_ids = [
        str(item["id"])
        for item in manifest.get("nodes", [])
        if str(item.get("id")) not in target_set and str(item.get("id")) != root_id
    ]
    return {
        "mode": "local_edit" if action in {"edit_page", "refine_page"} else "new_page",
        "page_id": page_id,
        "root_id": root_id,
        "instruction": instruction,
        "target_node_ids": target_ids,
        "protected_node_ids": protected_ids,
        "allowed_operations": [
            "edit_node",
            "edit_canvas",
            "node_replace_with",
            "inspect_nodes",
            "inspect_page",
        ],
        "forbidden_operations": ["render_page", "replace_root", "delete_unrelated_nodes"],
    }


def _selection_ids(selection: dict[str, Any]) -> list[str]:
    values = selection.get("selection", [])
    result: list[str] = []
    for item in values if isinstance(values, list) else []:
        node_id = item.get("id") if isinstance(item, dict) else item
        if node_id:
            result.append(str(node_id))
    return result


def _page_by_id(pages: list[dict[str, Any]], page_id: str) -> dict[str, Any] | None:
    wanted = page_id.strip()
    return next(
        (page for page in pages if wanted and str(page.get("id") or "") == wanted),
        None,
    )


def _exact_page_match(pages: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Resolve identity only; semantic similarity belongs to the workspace router."""
    wanted = " ".join(name.casefold().split())
    if not wanted:
        return None
    exact = [page for page in pages if " ".join(str(page.get("name", "")).casefold().split()) == wanted]
    if len(exact) == 1:
        return exact[0]
    return None


def _screen_registry(
    brief: Any,
    pages: list[dict[str, Any]],
    persisted: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    screens = getattr(brief, "screens", []) if brief else []
    persisted = persisted or {}
    registry: list[dict[str, Any]] = []
    seen: set[str] = set()
    for screen in screens:
        seen.add(screen.id)
        reference = persisted.get(screen.id)
        registered_page_id = ""
        if isinstance(reference, dict):
            registered_page_id = str(reference.get("page_id") or "")
        elif reference:
            registered_page_id = str(getattr(reference, "page_id", "") or "")
        page = _page_by_id(pages, registered_page_id)
        registry.append(
            {
                "screen_id": screen.id,
                "name": screen.name,
                "purpose": screen.purpose,
                "platforms": screen.platforms,
                "source_ui_ids": screen.source_ui_ids,
                "status": "created" if page else "pending",
                "page_id": str(page.get("id") or "") if page else "",
                "page_name": str(page.get("name") or "") if page else "",
                "root_node_id": str(reference.get("root_node_id") or "") if isinstance(reference, dict) else "",
                "root_name": str(reference.get("root_name") or "") if isinstance(reference, dict) else "",
                "x": float(reference.get("x") or 0) if isinstance(reference, dict) else 0,
                "y": float(reference.get("y") or 0) if isinstance(reference, dict) else 0,
                "width": float(reference.get("width") or 0) if isinstance(reference, dict) else 0,
                "height": float(reference.get("height") or 0) if isinstance(reference, dict) else 0,
            }
        )
    for screen_id, reference in persisted.items():
        if screen_id in seen:
            continue
        value = reference if isinstance(reference, dict) else reference.model_dump(mode="json")
        page = _page_by_id(pages, str(value.get("page_id") or ""))
        registry.append(
            {
                "screen_id": screen_id,
                "name": str(value.get("page_name") or screen_id),
                "purpose": "",
                "platforms": [str(value.get("platform") or "responsive")],
                "status": "created" if page else "missing",
                "page_id": str(page.get("id") or "") if page else "",
                "page_name": str(page.get("name") or "") if page else "",
                "root_node_id": str(value.get("root_node_id") or ""),
                "root_name": str(value.get("root_name") or ""),
                "x": float(value.get("x") or 0),
                "y": float(value.get("y") or 0),
                "width": float(value.get("width") or 0),
                "height": float(value.get("height") or 0),
            }
        )
    return registry


def _planned_page_name(registry: list[dict[str, Any]], screen_id: str) -> str:
    wanted = screen_id.casefold().strip()
    item = next(
        (entry for entry in registry if str(entry.get("screen_id") or "").casefold() == wanted),
        None,
    )
    if not item:
        return ""
    name = str(item.get("name") or "").strip()
    platforms = item.get("platforms") or []
    if name and len(platforms) == 1:
        return f"{name} · {str(platforms[0]).title()}"
    return name


def _compact_recovery_trace(value: dict[str, Any]) -> dict[str, Any]:
    """Keep only page identity and completion state needed for an agent retry."""
    actions = value.get("actions", [])
    if not isinstance(actions, list):
        return {}
    compact = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        compact.append(
            {
                key: action.get(key)
                for key in (
                    "screen_id",
                    "action",
                    "requested_page_name",
                    "page_id",
                    "page_name",
                    "status",
                    "actual_change_verified",
                )
                if action.get(key) not in {None, ""}
            }
        )
    return {"actions": compact} if compact else {}


async def _set_pending(owner: Any, session_id: Any, decision: Any | None) -> None:
    setter = getattr(owner.store, "set_pending_workspace_action", None)
    if setter:
        await setter(session_id, decision)


async def _finish(owner: Any, run: Any, intent: str, message: str) -> None:
    await owner.store.update_run(
        run.id,
        stage=RunStage.FINISHED,
        status=RunStatus.COMPLETED,
        intent=intent,
        assistant_message=message,
    )
    await owner.events.emit(run.id, run.revision, "assistant.message", {"message": message})


async def _inspect(
    owner: Any,
    session: Any,
    document_id: str,
    page_id: str,
    root_id: str = "",
) -> tuple[dict[str, Any], str, dict[str, Any], str]:
    target = {"document_id": document_id, "page_id": page_id}
    await owner.openpencil._call(session, "switch_page", {"page": page_id, **target})
    tree = await owner.openpencil._call(session, "get_page_tree", {**target, "depth": 5})
    roots = tree.get("children", [])
    if not root_id and len(roots) > 1:
        raise RuntimeError(
            "This page contains multiple screen frames. Select a screen or provide its screen_id before editing."
        )
    root_id = root_id or (str(roots[0].get("id", "")) if roots else "")
    if not root_id:
        return tree, "", {}, ""
    jsx_result = await owner.openpencil._call(session, "get_jsx", {"id": root_id, **target})
    description = await owner.openpencil._call(session, "describe", {"id": root_id, "depth": 4, **target})
    return tree, str(jsx_result.get("jsx", "")), description, root_id


async def _visual_input(
    owner: Any,
    session: Any,
    document_id: str,
    page_id: str,
    root_id: str,
) -> tuple[bytes | None, str]:
    preview = await owner.openpencil._capture_preview(session, document_id, page_id, root_id, scale=1.25)
    if not preview:
        return None, "image/jpeg"
    raw, extension = preview
    mime = RASTER_MIME_TYPES.get(extension.lower())
    return (raw, mime) if mime else (None, "image/jpeg")


async def handle_workspace_message(
    owner: Any,
    run: Any,
    *,
    conversation_history: str,
) -> bool:
    """Handle follow-up design work against the session's live OpenPencil file."""
    session_state = await owner.store.get_session(run.session_id)
    workspace = session_state.workspace if session_state else None
    profile = getattr(run, "mcp_profile", None)
    if not isinstance(workspace, SessionWorkspace) or not workspace.document_id or not profile:
        return False
    project_brief = getattr(session_state, "design_brief", None)
    pending = getattr(session_state, "pending_workspace_action", None)
    # An open editor alone must not turn a brand-new design brief into an edit.
    # Only an existing project/pending action is eligible for workspace edits.
    if project_brief is None and pending is None:
        return False

    async with owner.openpencil.session(profile.endpoint) as mcp:
        try:
            pages_result = await owner.openpencil._call(mcp, "list_pages", {"document_id": workspace.document_id})
        except Exception as original_error:
            if not workspace.document_path:
                raise
            opened = await owner.openpencil._call(mcp, "open_file", {"path": workspace.document_path})
            document_id, _ = owner.openpencil._target(opened)
            if not document_id:
                raise RuntimeError("OpenPencil did not reopen the session document") from original_error
            workspace = workspace.model_copy(update={"document_id": document_id})
            await owner.store.update_session_workspace(run.session_id, workspace)
            pages_result = await owner.openpencil._call(mcp, "list_pages", {"document_id": workspace.document_id})
        pages = pages_result.get("pages", [])
        selected_page = next(
            (item for item in pages if str(item.get("id")) == workspace.page_id),
            None,
        )
        selection: dict[str, Any] = {"selection": []}
        if selected_page:
            try:
                selection = await owner.openpencil._call(
                    mcp,
                    "get_selection",
                    {
                        "document_id": workspace.document_id,
                        "page_id": workspace.page_id,
                    },
                )
            except Exception:
                selection = {"selection": []}
        persisted_registry = getattr(session_state, "screen_registry", {}) or {}
        registry = _screen_registry(project_brief, pages, persisted_registry)
        recovery_trace: dict[str, Any] = {}
        get_artifact = getattr(owner.store, "get_artifact", None)
        if get_artifact:
            stored_trace = await get_artifact(run.id, run.revision, "workspace_action_trace")
            if isinstance(stored_trace, dict):
                recovery_trace = _compact_recovery_trace(stored_trace)
        router_prompt = owner.prompts.render(
            "workspace-router",
            workspace_context=workspace.model_dump_json(indent=2),
            project_context=(project_brief.model_dump_json(indent=2) if project_brief else "{}"),
            screen_registry=_json(registry),
            pending_action=(pending.model_dump_json(indent=2) if pending else "null"),
            recovery_trace=_json(recovery_trace),
            pages=_json(pages),
            selection=_json(selection),
            conversation_history=conversation_history,
            user_request=run.prompt,
        )
        decision = await owner.llm.structured(prompt=router_prompt, schema=WorkspaceActionDecision)
        if decision.action == "chat":
            await _set_pending(owner, run.session_id, None)
            await _finish(
                owner,
                run,
                "chat",
                decision.reply or "Tôi đang theo dõi workspace hiện tại.",
            )
            return True
        if decision.action == "clarify" or decision.requires_confirmation:
            if decision.normalized_targets():
                await _set_pending(
                    owner,
                    run.session_id,
                    decision.model_copy(update={"requires_confirmation": True}),
                )
            await _finish(
                owner,
                run,
                "clarify_design",
                decision.reply
                or f"Bạn xác nhận thao tác trên `{workspace.page_name}` trong `{workspace.document_name}` nhé?",
            )
            return True
        targets = decision.normalized_targets()
        if not targets:
            await _finish(
                owner,
                run,
                "clarify_design",
                decision.reply or "Bạn muốn tôi thay đổi hoặc tạo screen nào?",
            )
            return True

        non_system_pages = [item for item in pages if str(item.get("name", "")).casefold() not in SYSTEM_PAGES]
        selected_page = selected_page or (non_system_pages[-1] if len(non_system_pages) == 1 else None)
        prepared: list[tuple[WorkspaceActionTarget, dict[str, Any] | None, dict[str, Any] | None, str]] = []
        prepared_keys: set[tuple[str, str, str]] = set()
        for target in targets:
            if target.action == "add_page":
                new_name = (
                    target.new_page_name.strip()
                    or target.page_name.strip()
                    or _planned_page_name(registry, target.screen_id)
                    or target.screen_id.strip()
                )
                if not new_name:
                    pending_decision = decision.model_copy(update={"requires_confirmation": True})
                    await _set_pending(owner, run.session_id, pending_decision)
                    await _finish(
                        owner,
                        run,
                        "clarify_design",
                        "Bạn muốn đặt tên và mục đích cho page mới là gì?",
                    )
                    return True
                registered = persisted_registry.get(target.screen_id)
                registered_page_id = ""
                if isinstance(registered, dict):
                    registered_page_id = str(registered.get("page_id") or "")
                elif registered:
                    registered_page_id = str(getattr(registered, "page_id", "") or "")
                existing = _page_by_id(pages, target.page_id)
                existing = existing or _page_by_id(pages, registered_page_id)
                existing = existing or _exact_page_match(pages, new_name)
                key = (
                    target.action,
                    " ".join(new_name.casefold().split()),
                    target.screen_id.casefold().strip(),
                )
                if key in prepared_keys:
                    continue
                prepared_keys.add(key)
                reference = None
                if target.reference_page_id.strip():
                    reference = _page_by_id(pages, target.reference_page_id)
                    if reference is None:
                        await _finish(
                            owner,
                            run,
                            "clarify_design",
                            "OpenPencil reference page changed before the action could run. "
                            "Please select the reference page again.",
                        )
                        return True
                reference = reference or selected_page
                if existing and reference and str(reference.get("id") or "") == str(existing.get("id") or ""):
                    reference = next(
                        (
                            page
                            for page in reversed(non_system_pages)
                            if str(page.get("id") or "") != str(existing.get("id") or "")
                        ),
                        None,
                    )
                prepared.append((target, existing, reference, new_name))
                continue

            page = _page_by_id(pages, target.page_id)
            registered = persisted_registry.get(target.screen_id)
            if page is None and registered:
                registered_page_id = (
                    str(registered.get("page_id") or "")
                    if isinstance(registered, dict)
                    else str(getattr(registered, "page_id", "") or "")
                )
                page = _page_by_id(pages, registered_page_id)
            if page is None and not target.page_id.strip() and target.page_name.strip():
                page = _exact_page_match(pages, target.page_name)
            if page is None and not target.page_id.strip() and not target.page_name.strip():
                page = selected_page
            if page is None:
                pending_decision = decision.model_copy(update={"requires_confirmation": True})
                await _set_pending(owner, run.session_id, pending_decision)
                await _finish(
                    owner,
                    run,
                    "clarify_design",
                    decision.reply
                    or f"Tôi chưa xác định được page `{target.page_name}` trong "
                    f"`{workspace.document_name}`. Bạn xác nhận page cần sửa nhé?",
                )
                return True
            # Several screens intentionally share one Flow page. Include the
            # screen identity or an edit for SCR-02 can suppress SCR-01/03.
            key = (target.action, str(page.get("id") or ""), target.screen_id.casefold().strip())
            if key in prepared_keys:
                continue
            prepared_keys.add(key)
            prepared.append((target, page, page, str(page.get("name") or "Page")))

        await _set_pending(owner, run.session_id, None)
        await owner.store.update_run(
            run.id,
            stage=RunStage.ASSEMBLY,
            status=RunStatus.RUNNING,
            intent="design",
        )
        await owner.events.emit(
            run.id,
            run.revision,
            "workspace.inspecting",
            {
                "document": workspace.document_name,
                "pages": [item[3] for item in prepared],
                "message": f"Inspecting {len(prepared)} requested workspace action(s)",
            },
        )
        style_name = (
            project_brief.style_name if project_brief and project_brief.style_name else run.style_name or "custom"
        )
        exact_assets = await owner.store.get_artifact(run.id, run.revision, "exact_assets") or []
        if not exact_assets:
            exact_assets = await owner.store.get_latest_session_artifact(
                run.session_id, "exact_assets"
            ) or []
            if exact_assets:
                await owner.store.set_artifact(
                    run.id, run.revision, "exact_assets", exact_assets
                )
        records: list[dict[str, Any]] = []
        trace_records: list[dict[str, Any]] = []
        updated_workspace = workspace
        for index, (target, existing, reference, requested_name) in enumerate(prepared, start=1):
            registered = persisted_registry.get(target.screen_id) if target.screen_id else None
            registered_root_id = (
                str(registered.get("root_node_id") or "")
                if isinstance(registered, dict)
                else str(getattr(registered, "root_node_id", "") or "")
            )
            registered_platform = (
                str(registered.get("platform") or "")
                if isinstance(registered, dict)
                else str(getattr(registered, "platform", "") or "")
            )
            registered_x = (
                float(registered.get("x") or 0)
                if isinstance(registered, dict)
                else float(getattr(registered, "x", 0) or 0)
            )
            registered_y = (
                float(registered.get("y") or 0)
                if isinstance(registered, dict)
                else float(getattr(registered, "y", 0) or 0)
            )
            resume_empty_page = False
            if target.action == "add_page" and existing is not None:
                existing_page_id = str(existing.get("id") or "")
                _, _, _, existing_root_id = await _inspect(owner, mcp, workspace.document_id, existing_page_id)
                resume_empty_page = not existing_root_id
            is_new = target.action == "add_page" and (existing is None or resume_empty_page)
            context_page = reference if is_new else existing
            if context_page:
                context_page_id = str(context_page["id"])
                _tree, current_jsx, description, root_id = await _inspect(
                    owner,
                    mcp,
                    workspace.document_id,
                    context_page_id,
                    root_id=registered_root_id if not is_new else "",
                )
                image_bytes, _mime_type = await _visual_input(
                    owner, mcp, workspace.document_id, context_page_id, root_id
                )
            else:
                context_page_id = ""
                _tree, current_jsx, description, root_id = {}, "", {}, ""
                image_bytes, _mime_type = None, "image/jpeg"

            selection_ids = (
                _selection_ids(selection) if context_page_id == workspace.page_id and target.use_selection else []
            )
            preferred_target = selection_ids[0] if selection_ids else root_id
            instruction = target.instruction.strip() or run.prompt
            structure_manifest = _structure_manifest(_tree, root_id)
            edit_contract = _edit_contract(
                structure_manifest,
                page_id=context_page_id,
                root_id=root_id,
                instruction=instruction,
                action=target.action,
            )
            page_plan: WorkspacePagePlan | None = None
            if is_new:
                page_plan = await owner.llm.structured(
                    prompt=owner.prompts.render(
                        "workspace-page-plan",
                        target_context=target.model_dump_json(indent=2),
                        user_request=instruction,
                        project_context=(project_brief.model_dump_json(indent=2) if project_brief else "{}"),
                        reference_page=(str(context_page.get("name") or "") if context_page else "None"),
                        reference_description=_json(description),
                        style_name=style_name,
                    ),
                    schema=WorkspacePagePlan,
                )
                page_plan = page_plan.model_copy(
                    update={
                        "screen_id": target.screen_id or page_plan.screen_id,
                        "page_name": requested_name,
                    }
                )
            trace_record: dict[str, Any] = {
                "screen_id": target.screen_id,
                "action": target.action,
                "requested_page_name": requested_name,
                "existing_page_id": str(existing.get("id") or "") if existing else "",
                "resuming_empty_page": resume_empty_page,
                "reference_page_id": context_page_id if is_new else "",
                "inspected_page_id": context_page_id,
                "inspected_root_id": root_id,
                "page_plan": (page_plan.model_dump(mode="json") if page_plan else None),
                "visual_context_attached": image_bytes is not None,
                "status": "planned",
            }
            trace_records.append(trace_record)
            await owner.store.set_artifact(
                run.id,
                run.revision,
                "workspace_action_trace",
                {
                    "decision": decision.model_dump(mode="json"),
                    "actions": trace_records,
                },
            )
            # New pages and edits share the same skeleton → whole-screen composer.
            # The current raster/JSX is the style source of truth for workspace edits.
            specification = await generate_ui_specification(
                owner.llm,
                owner.prompts,
                user_request=(
                    f"{instruction}\nPreserve unrelated content when editing.\n"
                    f"Chosen style: {style_name}."
                ),
                screen_name=requested_name,
                platform=(
                    registered_platform
                    or (page_plan.platform if page_plan else getattr(run, "platform", "responsive"))
                ),
                project_context=_json(
                    {
                        "project": project_brief.model_dump(mode="json") if project_brief else {},
                        "page_plan": page_plan.model_dump(mode="json") if page_plan else {},
                        "current_jsx": current_jsx,
                        "current_description": description,
                        "structure_manifest": structure_manifest,
                        "edit_contract": edit_contract,
                        "style_source": "Current page raster and JSX" if current_jsx else style_name,
                    }
                ),
                conversation_history=conversation_history,
                image_bytes=image_bytes,
                image_mime_type=_mime_type,
            )
            if registered_platform == "mobile":
                specification = specification.model_copy(
                    update={
                        "platform": "mobile",
                        "viewport_width": 390,
                        "viewport_height": 844,
                    }
                )
            trace_record["specification"] = specification.model_dump(mode="json")
            bindings, component_context = await prepare_workspace_components(
                owner,
                run,
                specification,
                mcp,
                workspace.document_id,
            )
            trace_record["component_bindings"] = bindings.model_dump(mode="json")
            if is_new:
                if resume_empty_page and existing:
                    page_id = str(existing["id"])
                else:
                    created = await owner.openpencil._call(
                        mcp,
                        "create_page",
                        {
                            "name": requested_name,
                            "document_id": workspace.document_id,
                        },
                    )
                    page_id = str(created["id"])
                    pages.append({"id": page_id, "name": requested_name})
                page_name = requested_name
                root_id = ""
                baseline_jsx = ""
            else:
                page_id = str(existing["id"])
                page_name = str(existing.get("name") or requested_name)
                baseline_jsx = current_jsx
            trace_record.update(page_id=page_id, page_name=page_name, status="page_created_pending_render")
            # A newly-created page must be persisted before a retry. Existing
            # pages already have stable identity; saving them here is redundant
            # and can fail before the requested edit even starts.
            if is_new and workspace.document_path:
                await owner.openpencil._call(
                    mcp,
                    "save_file",
                    {
                        "path": workspace.document_path,
                        "document_id": workspace.document_id,
                    },
                )
            await owner.store.set_artifact(
                run.id,
                run.revision,
                "workspace_action_trace",
                {
                    "decision": decision.model_dump(mode="json"),
                    "actions": trace_records,
                },
            )

            async def record_tool(event: dict[str, Any], record: dict[str, Any] = trace_record) -> None:
                record.setdefault("tools", []).append(event)
                await owner.store.set_artifact(
                    run.id,
                    run.revision,
                    "workspace_action_trace",
                    {
                        "decision": decision.model_dump(mode="json"),
                        "actions": trace_records,
                    },
                )
                await owner.events.emit(run.id, run.revision, "design.tool", event)

            result = await design_page(
                owner.openpencil,
                mcp,
                llm=owner.llm,
                prompts=owner.prompts,
                document_id=workspace.document_id,
                page_id=page_id,
                specification=specification,
                bindings=bindings,
                component_context=component_context,
                source_file=profile.source_file,
                request=f"{instruction}\nSelected target: {preferred_target}. Preserve unrelated content.",
                root_id=root_id,
                current_jsx=baseline_jsx,
                edit_mode=not is_new,
                edit_contract=edit_contract,
                exact_assets=exact_assets,
                on_event=record_tool,
            )
            root_id = result["root_id"]
            design_trace = result["trace"]
            if target.screen_id:
                root_name = f"{target.screen_id} · {requested_name}"
                await owner.openpencil._call(
                    mcp,
                    "rename_node",
                    {
                        "id": root_id,
                        "name": root_name,
                        "document_id": workspace.document_id,
                        "page_id": page_id,
                    },
                )
            else:
                root_name = requested_name
            if not is_new and registered_root_id:
                await owner.openpencil._call(
                    mcp,
                    "node_move",
                    {
                        "id": root_id,
                        "x": registered_x,
                        "y": registered_y,
                        "document_id": workspace.document_id,
                        "page_id": page_id,
                    },
                )
            mutation = {
                "strategy": "create_page" if is_new else "replace_target",
                "target_id": root_id,
                "jsx": result["jsx"],
                "summary": result["summary"] or instruction,
            }
            _, final_jsx, _, final_root_id = await _inspect(
                owner,
                mcp,
                workspace.document_id,
                page_id,
                root_id=root_id,
            )
            root_id = final_root_id or root_id
            changed = bool(final_jsx.strip()) if is_new else final_jsx != baseline_jsx
            if not changed:
                raise RuntimeError(
                    "OpenPencil accepted the edit call but the page JSX did not change; "
                    "the requested update was not applied."
                )
            if workspace.document_path:
                await owner.openpencil._call(
                    mcp,
                    "save_file",
                    {
                        "path": workspace.document_path,
                        "document_id": workspace.document_id,
                    },
                )
            updated_workspace = SessionWorkspace(
                document_id=workspace.document_id,
                document_path=workspace.document_path,
                document_name=workspace.document_name,
                page_id=page_id,
                page_name=page_name,
            )
            await owner.store.update_session_workspace(run.session_id, updated_workspace)
            record = {
                "document_id": workspace.document_id,
                "page_id": page_id,
                "page_name": page_name,
                "screen_id": target.screen_id,
                "root_node_id": root_id,
                "request": instruction,
                "actual_change_verified": changed,
                "created": is_new,
                "mutation": mutation,
                "design_trace": design_trace,
            }
            records.append(record)
            trace_record.update(
                {
                    "page_id": page_id,
                    "page_name": page_name,
                    "root_node_id": root_id,
                    "actual_change_verified": changed,
                    "status": "completed",
                }
            )
            update_registry = getattr(owner.store, "update_session_screen_registry", None)
            if update_registry and target.screen_id:
                bounds_result = await owner.openpencil._call(
                    mcp,
                    "node_bounds",
                    {"id": root_id, "document_id": workspace.document_id, "page_id": page_id},
                )
                bounds = bounds_result.get("bounds", {}) if isinstance(bounds_result, dict) else {}
                registry_value = {
                    "screen_id": target.screen_id,
                    "page_id": page_id,
                    "page_name": page_name,
                    "platform": registered_platform or (page_plan.platform if page_plan else "responsive"),
                    "root_node_id": root_id,
                    "root_name": root_name,
                    "x": float(bounds.get("x") or 0),
                    "y": float(bounds.get("y") or 0),
                    "width": float(bounds.get("width") or 0),
                    "height": float(bounds.get("height") or 0),
                }
                await update_registry(run.session_id, {target.screen_id: registry_value})
                persisted_registry[target.screen_id] = registry_value
            artifact_payload = (
                records[0]
                if len(records) == 1
                else {
                    "document_id": workspace.document_id,
                    "request": run.prompt,
                    "actual_change_verified": all(item["actual_change_verified"] for item in records),
                    "mutations": records,
                }
            )
            # Persist after every page. If a later page fails, retry can discover
            # the completed page and continue without creating a duplicate.
            await owner.store.set_artifact(
                run.id,
                run.revision,
                "workspace_mutation",
                artifact_payload,
            )
            await owner.store.set_artifact(
                run.id,
                run.revision,
                "workspace_action_trace",
                {
                    "decision": decision.model_dump(mode="json"),
                    "actions": trace_records,
                },
            )
            await owner.events.emit(
                run.id,
                run.revision,
                "workspace.page_updated",
                {
                    "workspace": updated_workspace.model_dump(mode="json"),
                    "current": index,
                    "total": len(prepared),
                    "created": is_new,
                    "message": mutation["summary"],
                },
            )

        await owner.events.emit(
            run.id,
            run.revision,
            "workspace.updated",
            {
                "workspace": updated_workspace.model_dump(mode="json"),
                "message": f"Updated {len(records)} page(s)",
            },
        )
        await _finish(
            owner,
            run,
            "design",
            "\n".join(
                [
                    f"Đã {'tạo' if item['created'] else 'cập nhật'} "
                    f"`{item['page_name']}` và xác minh trực tiếp trong OpenPencil."
                    for item in records
                ]
            ),
        )
        return True

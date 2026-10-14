import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from ..core.errors import AppError, unwrap_app_error
from ..core.logger import log_agent_error
from ..generation.cohesion import normalize_project_cohesion
from ..generation.layout import (
    deterministic_layout_review,
    is_icon_internal_overlap,
    is_ignorable_overlap,
)
from ..models import (
    ComponentBindingSet,
    OpenPencilArtifact,
    ProjectSpecification,
    ComponentRequirement,
    RunStage,
    RunStatus,
    SessionWorkspace,
    UiNode,
    UiSpecification,
)
from ..openpencil.binding import semantic_family_matches, validate_bindings

COMPONENT_RESOLVER_BATCH_SIZE = 24


def _asset_for_node(node: UiNode, exact_assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    explicit_id = str(node.content.get("asset_id") or "").strip()
    if explicit_id.startswith("asset::"):
        explicit_id = explicit_id.removeprefix("asset::")
    if explicit_id:
        return next((item for item in exact_assets if str(item.get("id") or "") == explicit_id), None)
    haystack = " ".join(
        str(node.content.get(key) or "")
        for key in ("src", "file", "filename", "description", "alt", "asset_role")
    ).casefold()
    haystack += " " + f"{node.id} {node.name}".casefold()
    by_name = [
        item
        for item in exact_assets
        if str(item.get("name") or "").casefold() in haystack
        or Path(str(item.get("name") or "")).stem.casefold() in haystack
    ]
    if len(by_name) == 1:
        return by_name[0]
    by_role = [
        item
        for item in exact_assets
        if str(item.get("visual_role") or "").casefold() not in {"", "image"}
        and str(item.get("visual_role") or "").casefold() in haystack
    ]
    if len(by_role) == 1:
        return by_role[0]
    return exact_assets[0] if len(exact_assets) == 1 else None


def _promote_uploaded_brand_media(node: UiNode, exact_assets: list[dict[str, Any]]) -> None:
    """Attach upload metadata to real image nodes without changing their semantics.

    Uploaded PNG/JPEG bytes are applied after JSX rendering through an
    ``asset::<id>`` marker. A previous implementation promoted every graphic on a
    screen to a design-system component whenever any upload existed. That turned
    loading dots and home indicators into image bindings and left the real mascot
    as an empty placeholder when the library had no mascot component.
    """
    # Repair project specifications persisted by the short-lived buggy version.
    # It stamped every graphic as an ``asset_visual`` component, so retries would
    # otherwise keep reproducing the failure even after the code was fixed.
    legacy_requirement = node.requirement
    legacy_asset_component = (
        node.kind == "component"
        and str(node.content.get("asset_binding") or "") == "design_system_component"
        and legacy_requirement is not None
        and legacy_requirement.role == "asset_visual"
        and legacy_requirement.capabilities == ["image"]
    )
    if legacy_asset_component:
        original_graphic = any(
            key in node.content
            for key in ("shape", "background_color", "box_shadow", "border_radius")
        )
        node.kind = "graphic" if original_graphic else "media"
        node.requirement = None
        node.content.pop("asset_binding", None)
        if original_graphic:
            for key in ("asset_id", "asset_name", "asset_role", "asset_fit", "asset_placement"):
                node.content.pop(key, None)

    explicit_binding = str(node.content.get("asset_binding") or "").strip()
    explicit_role = str(node.content.get("asset_role") or "").strip()
    graphic_type = str(node.content.get("graphic_type") or "").strip().casefold()
    explicit_asset_id = str(node.content.get("asset_id") or "").strip()
    explicit_asset_ref = any(
        "asset::" in str(node.content.get(key) or "")
        for key in ("src", "file", "filename", "image_ref", "asset_ref")
    )
    opted_in = (
        bool(explicit_asset_id)
        or explicit_asset_ref
        or node.content.get("use_uploaded_asset") is True
        or str(node.content.get("asset_source") or "").casefold() in {"uploaded", "user", "exact"}
    )
    is_asset_visual = opted_in or (
        node.kind == "graphic"
        and (
            explicit_binding == "design_system_component"
            and bool(explicit_role)
        )
    )
    if is_asset_visual:
        selected_asset = _asset_for_node(node, exact_assets)
        if selected_asset:
            node.content["asset_id"] = str(selected_asset.get("id") or "")
            node.content["asset_name"] = str(selected_asset.get("name") or "")
            node.content["asset_role"] = str(selected_asset.get("visual_role") or "image")
            node.content["asset_fit"] = str(selected_asset.get("recommended_fit") or "contain")
            node.content["asset_placement"] = str(
                selected_asset.get("recommended_placement") or "content area"
            )
        # Only an explicit caller request may route an upload through a mounted
        # design-system component. Normal media stays media and is imported by
        # the direct marker pipeline.
        if explicit_binding == "design_system_component":
            existing = node.requirement
            node.kind = "component"
            node.requirement = ComponentRequirement(
                role=(existing.role if existing else explicit_role) or "asset_visual",
                variant_intent=(existing.variant_intent if existing else None)
                or str(node.content.get("variant_intent") or node.name),
                required_slots=list(existing.required_slots) if existing else [],
                capabilities=list(existing.capabilities) if existing else ["image"],
            )
    for child in node.children:
        _promote_uploaded_brand_media(child, exact_assets)


def component_requirements(node: UiNode) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    if node.kind == "component" and node.requirement:
        values.append({"node_id": node.id, "content": node.content, **node.requirement.model_dump(mode="json")})
    for child in node.children:
        values.extend(component_requirements(child))
    return values


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _resolver_context(
    requirements: list[dict[str, Any]],
    candidates: list[Any],
    knowledge: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Keep only inspected candidates and catalog facts relevant to this batch.

    The complete candidate and knowledge snapshots remain persisted as artifacts. The
    resolver only needs a normalized candidate catalog plus the ranked relationship
    between each requirement and those candidates.
    """
    candidate_by_id = {str(item.component_id): item for item in candidates}
    requirement_ids = {str(item["node_id"]) for item in requirements}
    matches_by_node: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in requirement_ids}
    relevant_candidate_ids: set[str] = set()

    for match in knowledge.get("matches", []):
        node_id = str(match.get("node_id") or "")
        component_id = str(match.get("component_id") or "")
        if node_id not in matches_by_node or component_id not in candidate_by_id or len(matches_by_node[node_id]) >= 12:
            continue
        matches_by_node[node_id].append(
            {
                "component_id": component_id,
                "knowledge_score": int(match.get("knowledge_score") or 0),
                "family": str(match.get("family") or ""),
                "variant_axes": match.get("variant_axes") or {},
                "slot_candidates": match.get("slot_candidates") or [],
            }
        )
        relevant_candidate_ids.add(component_id)

    # Fill each node's shortlist with inspected alternatives. Knowledge matches
    # lead, while lexical relevance keeps custom libraries useful.
    for requirement in requirements:
        node_id = str(requirement["node_id"])
        options = matches_by_node[node_id]
        compatible = [item for item in candidates if semantic_family_matches(requirement, item)]
        if compatible:
            allowed = {item.component_id for item in compatible}
            options[:] = [item for item in options if item["component_id"] in allowed]
        seen = {str(item["component_id"]) for item in options}
        words = set(
            re.findall(
                r"[a-z0-9]+",
                json.dumps(requirement, ensure_ascii=True).lower(),
            )
        )
        ranked = sorted(
            compatible or candidates,
            key=lambda item: (
                -len(
                    words
                    & set(
                        re.findall(
                            r"[a-z0-9]+",
                            f"{item.canonical_path} {item.name} {item.variant_name or ''}".lower(),
                        )
                    )
                ),
                item.canonical_path,
            ),
        )
        for candidate in ranked:
            if candidate.component_id in seen:
                continue
            options.append({"component_id": candidate.component_id, "knowledge_score": 0})
            seen.add(candidate.component_id)
            if len(options) == 12:
                break
        relevant_candidate_ids.update(seen)

    compact_candidates = []
    for component_id in relevant_candidate_ids:
        item = candidate_by_id[component_id]
        compact_candidates.append(
            {
                "component_id": item.component_id,
                "library_id": item.library_id,
                "name": item.name,
                "canonical_path": item.canonical_path,
                "width": item.width,
                "height": item.height,
                "text_slots": item.text_slots,
                "variant_name": item.variant_name,
            }
        )
    compact_candidates.sort(key=lambda item: (item["canonical_path"], item["component_id"]))
    return compact_candidates, matches_by_node


async def resolve_component_bindings(
    owner: Any,
    run: Any,
    project: ProjectSpecification,
    candidates: list[Any],
    knowledge: dict[str, Any],
) -> ComponentBindingSet:
    """Resolve components in screen-local batches instead of sending the whole project."""
    resolved = ComponentBindingSet(bindings=[])
    batches: list[tuple[Any, list[dict[str, Any]]]] = []
    for screen in project.screens:
        requirements = component_requirements(screen.specification.root)
        for start in range(0, len(requirements), COMPONENT_RESOLVER_BATCH_SIZE):
            batches.append((screen, requirements[start : start + COMPONENT_RESOLVER_BATCH_SIZE]))

    for index, (screen, requirements) in enumerate(batches, start=1):
        compact_candidates, candidate_matches = _resolver_context(requirements, candidates, knowledge)
        designer_model = getattr(getattr(owner.llm, "settings", None), "effective_designer_model", None)
        if not isinstance(designer_model, str):
            designer_model = None
        batch = await owner.llm.structured(
            prompt=owner.prompts.render(
                "resolver",
                screen_context=_compact_json(
                    {
                        "screen_id": screen.screen_id,
                        "screen_name": screen.specification.screen_name,
                        "platforms": screen.platforms,
                        "summary": screen.specification.summary,
                    }
                ),
                component_requirements=_compact_json(requirements),
                component_candidates=_compact_json(compact_candidates),
                candidate_matches=_compact_json(candidate_matches),
            ),
            schema=ComponentBindingSet,
            **({"model": designer_model} if designer_model else {}),
        )
        validated = validate_bindings(requirements, candidates, batch)
        resolved.bindings.extend(validated.bindings)
        await owner.events.emit(
            run.id,
            run.revision,
            "component.batch_resolved",
            {
                "screen_id": screen.screen_id,
                "screen_name": screen.specification.screen_name,
                "current": index,
                "total": len(batches),
                "requirements": len(requirements),
            },
        )
    return resolved


async def prepare_workspace_components(
    owner: Any,
    run: Any,
    specification: UiSpecification,
    session: Any,
    document_id: str,
) -> tuple[ComponentBindingSet, dict[str, Any]]:
    """Use the same retrieval and binding path for a workspace page as a project."""
    requirements = component_requirements(specification.root)
    libraries = list(getattr(run, "library_ids", []))
    knowledge = owner.knowledge.shortlist(requirements, libraries, run.mcp_profile.source_file)
    candidates = await owner.openpencil.components(run.mcp_profile, requirements, knowledge)
    if requirements and not candidates:
        raise AppError(
            "COMPONENT_CATALOG_EMPTY",
            "No design-system components found",
            "Inspect the selected source library before designing this screen.",
            409,
            True,
        )
    project = SimpleNamespace(
        screens=[
            SimpleNamespace(
                screen_id=specification.root.id,
                specification=specification,
                platforms=[specification.platform],
            )
        ]
    )
    bindings = await resolve_component_bindings(owner, run, project, candidates, knowledge)
    pack = await owner.openpencil.source.pack(
        run.mcp_profile.source_file,
        [item.component_id for item in bindings.bindings if item.status == "resolved" and item.component_id],
    )
    local = {}
    if pack:
        listed = await owner.openpencil._call(session, "list_pages", {"document_id": document_id})
        page = next((item for item in listed.get("pages", []) if item.get("name") == "Components"), None)
        if page is None:
            page = await owner.openpencil._call(
                session, "create_page", {"document_id": document_id, "name": "Components"}
            )
        for source_id, jsx in pack:
            for old, new in local.items():
                jsx = jsx.replace(old, new)
            result = await owner.openpencil._call(
                session,
                "render",
                {
                    "document_id": document_id,
                    "page_id": str(page["id"]),
                    "jsx": jsx,
                },
            )
            local[source_id] = str(result["id"])
        for binding in bindings.bindings:
            if binding.component_id in local:
                binding.component_id = local[binding.component_id]
    return bindings, {
        "candidates": [item.model_dump(mode="json") for item in candidates],
        "definitions": dict(pack),
        "local_components": local,
    }


async def build_after_review(owner: Any, run_id: UUID) -> None:
    run = await owner.store.get_run(run_id)
    if not run or not run.specification or not run.mcp_profile:
        return
    try:
        project = await _project_for_run(owner, run)
        exact_assets = await owner.store.get_artifact(run.id, run.revision, "exact_assets") or []
        for screen in project.screens:
            _promote_uploaded_brand_media(screen.specification.root, exact_assets)
        project, cohesion = normalize_project_cohesion(project)
        if cohesion["status"] != "valid":
            raise AppError(
                "PROJECT_COHESION_INVALID",
                "Project screen identity is ambiguous",
                f"Duplicate screen ids: {cohesion['duplicate_screen_ids']}",
                409,
                retryable=True,
            )
        await owner.store.set_artifact(run.id, run.revision, "cohesion_review", cohesion)
        await owner.store.set_artifact(
            run.id,
            run.revision,
            "project_specification",
            project.model_dump(mode="json"),
        )
        requirements = [
            requirement
            for screen in project.screens
            for requirement in component_requirements(screen.specification.root)
        ]
        libraries = list(run.library_ids)
        if run.mcp_profile.knowledge_id != "auto":
            libraries.append(run.mcp_profile.knowledge_id)
        knowledge = owner.knowledge.shortlist(requirements, libraries, run.mcp_profile.source_file)
        await owner.store.set_artifact(run.id, run.revision, "knowledge_snapshot", knowledge)
        await owner.store.update_run(run.id, stage=RunStage.COMPONENTS, status=RunStatus.RUNNING)
        await owner.events.emit(
            run.id,
            run.revision,
            "stage.changed",
            {"stage": "components", "message": "Inspecting components for every requested screen"},
        )
        candidates = await owner.openpencil.components(run.mcp_profile, requirements, knowledge)
        if requirements and not candidates:
            raise AppError(
                "COMPONENT_CATALOG_EMPTY",
                "No design-system components found",
                "Inspect the selected source library before designing this project.",
                409,
                True,
            )
        candidate_data = [item.model_dump(mode="json") for item in candidates]
        await owner.store.set_artifact(run.id, run.revision, "component_candidates", candidate_data)
        await owner.events.emit(
            run.id,
            run.revision,
            "components.discovered",
            {
                "count": len(candidates),
                "message": f"Inspected {len(candidates)} real design-system components",
            },
        )
        await owner.store.update_run(run.id, stage=RunStage.BINDING, status=RunStatus.RUNNING)
        await owner.events.emit(
            run.id,
            run.revision,
            "stage.changed",
            {
                "stage": "binding",
                "message": "Binding the planned controls to inspected components",
            },
        )
        bindings = ComponentBindingSet(bindings=[])
        if requirements and candidates:
            saved = await owner.store.get_artifact(run.id, run.revision, "component_bindings")
            previous = ComponentBindingSet.model_validate(saved) if saved else None
            by_id = {item.component_id: item for item in candidates}
            if (
                previous
                and {item.node_id for item in previous.bindings} == {item["node_id"] for item in requirements}
                and all(
                    item.status != "resolved"
                    or (item.component_id in by_id and item.library_id == by_id[item.component_id].library_id)
                    for item in previous.bindings
                )
            ):
                checked = validate_bindings(requirements, candidates, previous)
                checked_by_id = {item.node_id: item for item in checked.bindings}
                if all(
                    checked_by_id[old.node_id].status == "resolved"
                    for old in previous.bindings
                ):
                    bindings = checked
                else:
                    bindings = await resolve_component_bindings(owner, run, project, candidates, knowledge)
            else:
                bindings = await resolve_component_bindings(owner, run, project, candidates, knowledge)
        await owner.store.set_artifact(run.id, run.revision, "component_bindings", bindings.model_dump(mode="json"))

        await owner.store.update_run(run.id, stage=RunStage.ASSEMBLY, status=RunStatus.RUNNING)
        await owner.events.emit(
            run.id,
            run.revision,
            "stage.changed",
            {
                "stage": "assembly",
                "message": "Building the page with real components and icons",
            },
        )
        checkpoint = await owner.store.get_artifact(run.id, run.revision, "openpencil_checkpoint")

        async def save_checkpoint(value: dict[str, Any]) -> None:
            await owner.store.set_artifact(run.id, run.revision, "openpencil_checkpoint", value)
            workspace_payload: dict[str, Any] | None = None
            document_id = str(value.get("document_id") or "")
            if document_id and run.mcp_profile and run.mcp_profile.output_file:
                screens = value.get("screens", [])
                registry_entries = {
                    str(item.get("screen_id")): {
                        "screen_id": str(item.get("screen_id")),
                        "page_id": str(item.get("page_id") or ""),
                        "page_name": str(item.get("page_name") or ""),
                        "platform": str(item.get("platform") or "responsive"),
                        "root_node_id": str(item.get("root_node_id") or ""),
                        "root_name": str(item.get("root_name") or ""),
                        "x": float(item.get("canvas_x") or 0),
                        "y": float(item.get("canvas_y") or 0),
                        "width": float(item.get("width") or 0),
                        "height": float(item.get("height") or 0),
                    }
                    for item in screens
                    if item.get("screen_id") and item.get("page_id")
                }
                update_registry = getattr(owner.store, "update_session_screen_registry", None)
                if update_registry and registry_entries:
                    await update_registry(run.session_id, registry_entries)
                latest_screen = screens[-1] if screens else {}
                session = await owner.store.update_session_workspace(
                    run.session_id,
                    SessionWorkspace(
                        document_id=document_id,
                        document_path=run.mcp_profile.output_file,
                        document_name=Path(run.mcp_profile.output_file).stem,
                        page_id=str(value.get("in_progress_page_id") or latest_screen.get("page_id") or ""),
                        page_name=str(value.get("in_progress_page_name") or latest_screen.get("page_name") or ""),
                    ),
                )
                if session.workspace:
                    workspace_payload = session.workspace.model_dump(mode="json")
            await owner.events.emit(
                run.id,
                run.revision,
                "openpencil.checkpoint",
                {
                    "message": "Saved design progress" if value.get("completed") else "Workspace ready for page design",
                    "completed": value.get("completed", []),
                    "last_screen": value.get("last_screen"),
                    "workspace": workspace_payload,
                },
            )

        async def design_progress(value: dict[str, Any]) -> None:
            await owner.events.emit(run.id, run.revision, "design.tool", value)

        result = await owner.openpencil.assemble_project(
            run.mcp_profile,
            project,
            bindings,
            run_id=str(run.id),
            llm=owner.llm,
            prompts=owner.prompts,
            checkpoint=checkpoint,
            on_checkpoint=save_checkpoint,
            component_candidates=candidate_data,
            exact_assets=exact_assets,
            on_event=design_progress,
        )
        if not result.get("screens"):
            raise AppError(
                "DESIGN_INCOMPLETE",
                "No screen completed",
                "The page designer stopped before any inspected screen was completed.",
                502,
                True,
            )
        artifact = OpenPencilArtifact.model_validate(result)
        await owner.store.set_artifact(run.id, run.revision, "openpencil_artifact", result)
        await owner.store.set_artifact(
            run.id,
            run.revision,
            "media_manifest",
            {"assets": result.get("media_assets", [])},
        )
        await owner.events.emit(
            run.id,
            run.revision,
            "openpencil.assembled",
            {
                **artifact.model_dump(mode="json"),
                "screens": len(result.get("screens", [])),
                "message": "All requested OpenPencil pages were saved",
            },
        )
        await review_project_layout(owner, run, project, result)
    except Exception as error:
        log_agent_error("workflow_build", f"Workflow execution error on run {run.id} rev {run.revision}", error)
        app_err = unwrap_app_error(error)
        failure = app_err or AppError("WORKFLOW_FAILED", "Workflow failed", str(error) or repr(error), 500, True)
        if failure.code.startswith(("MCP_", "OPENPENCIL_", "COMPONENT", "TARGET_")):
            await owner._block(run.id, run.revision, failure)
        else:
            await owner._fail(run.id, run.revision, failure)


async def _project_for_run(owner: Any, run: Any) -> ProjectSpecification:
    value = await owner.store.get_artifact(run.id, run.revision, "project_specification")
    if value:
        return ProjectSpecification.model_validate(value)
    raise AppError(
        "PROJECT_SPECIFICATION_MISSING",
        "Project specification is missing",
        "Regenerate and approve the project specification before building.",
        409,
        retryable=True,
    )


def _summarize_layout_reviews(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep measured findings visible for final human review.

    Rendering, MCP, binding, and persistence failures are raised before this point.
    The page agent already inspected and corrected the live design before finishing,
    so this final pass reports objective telemetry without starting another LLM loop.
    """
    if not reviews:
        return {
            "status": "invalid",
            "summary": "No completed screens were available for layout review.",
            "screens": [],
            "findings": [],
        }
    invalid = [item for item in reviews if item["status"] == "invalid"]
    return {
        "status": "advisory" if invalid else "valid",
        "summary": (
            f"{len(invalid)} of {len(reviews)} screen/platform layouts retain "
            "findings after the page agent's final inspection; review them before approval."
            if invalid
            else f"All {len(reviews)} screen/platform layouts passed."
        ),
        "screens": reviews,
        "findings": [finding for item in reviews for finding in item.get("findings", [])],
    }


async def review_project_layout(
    owner: Any,
    run: Any,
    project: ProjectSpecification,
    result: dict[str, Any],
) -> None:
    await owner.store.update_run(run.id, stage=RunStage.LAYOUT_CHECK, status=RunStatus.RUNNING)
    spec_by_key = {
        f"{screen.screen_id}:{platform}": screen.specification.model_copy(
            update={
                "platform": platform,
                "viewport_width": _viewport(platform, screen.specification),
                "viewport_height": _viewport_height(platform, screen.specification),
            }
        )
        for screen in project.screens
        for platform in screen.platforms
    }
    reviews: list[dict[str, Any]] = []
    for screen_result in result.get("screens", []):
        key = screen_result["key"]
        specification = spec_by_key[key]
        telemetry = screen_result.get("telemetry", {})
        cleaned_telemetry = dict(telemetry)
        if "overlaps" in telemetry and isinstance(telemetry["overlaps"], dict):
            raw_overlaps = telemetry["overlaps"].get("overlaps", [])
            if isinstance(raw_overlaps, list):
                filtered_overlaps = [
                    dict(item)
                    for item in raw_overlaps
                    if not is_icon_internal_overlap(item) and not is_ignorable_overlap(item)
                ]
                by_sev: dict[str, int] = {}
                for o in filtered_overlaps:
                    sev = str(o.get("severity", "minor")).lower()
                    by_sev[sev] = by_sev.get(sev, 0) + 1
                    area = o.get("area")
                    msg = o.get("message", "")
                    if area and "extends" in msg and "px outside" in msg:
                        o["message"] = msg.replace(f"{round(area)}px outside", f"{round(area)} px² (area) outside")
                cleaned_telemetry["overlaps"] = {
                    **telemetry["overlaps"],
                    "overlaps": filtered_overlaps,
                    "summary": {
                        **(telemetry["overlaps"].get("summary") or {}),
                        "overlapCount": len(filtered_overlaps),
                        "bySeverity": by_sev,
                    },
                }

        deterministic = deterministic_layout_review(
            specification, cleaned_telemetry, int(screen_result.get("expected_instances", 0))
        )
        reviews.append(
            {
                "key": key,
                "screen_name": screen_result["screen_name"],
                "platform": screen_result["platform"],
                **deterministic.model_dump(mode="json"),
            }
        )
    overall = _summarize_layout_reviews(reviews)
    await owner.store.set_artifact(run.id, run.revision, "layout_review", overall)

    await owner.store.update_run(run.id, stage=RunStage.REVIEW_FINAL, status=RunStatus.WAITING_REVIEW)
    await owner.events.emit(run.id, run.revision, "layout.checked", overall)
    await owner.events.emit(
        run.id,
        run.revision,
        "review.required",
        {"checkpoint": "final", "message": "Review all saved OpenPencil screens."},
    )
    await _deliver(owner, run, project, result)


def _viewport(platform: str, specification: UiSpecification) -> int:
    return {"mobile": 390, "tablet": 768, "desktop": 1440, "responsive": 1440}.get(
        platform, specification.viewport_width
    )


def _viewport_height(platform: str, specification: UiSpecification) -> int:
    return {"mobile": 844, "tablet": 1024, "desktop": 1024, "responsive": 1024}.get(
        platform, specification.viewport_height
    )


async def _deliver(owner: Any, run: Any, project: ProjectSpecification, result: dict[str, Any]) -> None:
    try:
        reply = await owner.llm.text(
            prompt=owner.prompts.render(
                "delivery",
                user_request=run.prompt,
                screen_name=project.brief.product_name,
                summary=project.design_context.product_summary,
                style_name=project.brief.style_name or "custom",
                sections=", ".join(item.specification.screen_name for item in project.screens),
            )
        )
    except Exception:
        reply = f"Đã hoàn thành {len(result.get('screens', []))} màn hình/viewport."
    reply = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf\ufe0f]", "", reply).strip()
    links = "\n".join(f"- {key}: ![{key}]({url})" for key, url in result.get("previews", {}).items())
    message = f"{reply}\n\n{links}\n\nFile thiết kế: `{result.get('output_file', '')}`".strip()
    await owner.store.update_run(run.id, assistant_message=message)
    await owner.events.emit(run.id, run.revision, "assistant.message", {"message": message})


# Compatibility for imports during the migration window.
review_layout = review_project_layout

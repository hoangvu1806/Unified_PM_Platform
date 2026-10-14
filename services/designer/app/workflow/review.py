import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from ..core.errors import AppError, not_found
from ..generation.layout import deterministic_layout_review
from .publish import publish_design
from ..models import OpenPencilProfile, ProjectSpecification, ReviewCreate, RunStage, RunStatus, UiSpecification
from ..openpencil.qa import measure_screen
from .build import _summarize_layout_reviews


class HumanReviewFlow:
    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.store = owner.store
        self.events = owner.events
        self.llm = owner.llm
        self.prompts = owner.prompts

    async def review(self, run_id: UUID, request: ReviewCreate) -> None:
        run = await self.store.get_run(run_id)
        if run is None:
            raise not_found("Run")
        if request.revision != run.revision:
            raise AppError("STALE_REVISION", "Review is stale", "Reload the current revision.", 409)
        expected = (
            "specification"
            if run.stage == RunStage.REVIEW_SPEC
            else "final"
            if run.stage == RunStage.REVIEW_FINAL
            else None
        )
        if request.checkpoint != expected or run.status != RunStatus.WAITING_REVIEW:
            raise AppError(
                "INVALID_REVIEW_CHECKPOINT",
                "Review is not available",
                f"Run is currently at {run.stage} ({run.status}).",
                409,
            )
        if request.checkpoint == "specification" and request.mcp_profile:
            run = await self.store.update_mcp_profile(run.id, request.mcp_profile)
        if request.decision == "approved" and request.checkpoint == "final":
            # Check before recording the review: a refused approval must not look approved.
            await self._require_valid_layout(run)
        await self.store.add_review(
            run.id,
            run.revision,
            request.checkpoint,
            request.decision,
            request.feedback,
        )
        if request.decision == "approved" and request.checkpoint == "specification":
            await self._approve_specification(run)
        elif request.decision == "approved":
            await self._approve_final(run, request)
        elif request.decision == "changes_requested":
            await self._request_changes(run, request)
        else:
            await self.store.update_run(
                run.id,
                stage=RunStage.BLOCKED,
                status=RunStatus.CANCELLED,
            )
            await self.events.emit(
                run.id,
                run.revision,
                "run.cancelled",
                {
                    "message": "The current design was rejected.",
                },
            )

    async def recheck_layout(self, run_id: UUID) -> dict[str, Any]:
        """Re-read the live OpenPencil pages after a manual .fig edit."""
        run = await self.store.get_run(run_id)
        if run is None:
            raise not_found("Run")
        if run.stage != RunStage.REVIEW_FINAL or run.status != RunStatus.WAITING_REVIEW:
            raise AppError(
                "LAYOUT_RECHECK_UNAVAILABLE",
                "Layout recheck is not available",
                f"Run is currently at {run.stage} ({run.status}).",
                409,
            )
        if not run.mcp_profile:
            raise AppError(
                "MCP_CONTEXT_REQUIRED",
                "OpenPencil context is required",
                "Configure the MCP endpoint before rechecking the layout.",
                409,
            )

        await self.sync_live_canvas(run_id)
        run = await self.store.get_run(run_id)
        if run is None or not run.mcp_profile:
            raise not_found("Run")

        project_value = await self.store.get_artifact(run.id, run.revision, "project_specification")
        checkpoint = await self.store.get_artifact(run.id, run.revision, "openpencil_checkpoint") or {}
        artifact = await self.store.get_artifact(run.id, run.revision, "openpencil_artifact") or {}
        project = ProjectSpecification.model_validate(project_value) if project_value else None
        screen_records = checkpoint.get("screens") or artifact.get("screens") or []
        if not project or not screen_records:
            raise AppError(
                "OPENPENCIL_CHECKPOINT_MISSING",
                "Saved OpenPencil pages are unavailable",
                "Rebuild the design before rechecking the layout.",
                409,
            )

        old_layout = await self.store.get_artifact(run.id, run.revision, "layout_review") or {}
        old_screens = {str(item.get("key")): item for item in old_layout.get("screens", [])}
        reviews: list[dict[str, Any]] = []
        async with self.owner.openpencil.session(run.mcp_profile.endpoint) as session:
            for record in screen_records:
                screen_id = str(record.get("screen_id") or "")
                project_screen = next(
                    (item for item in project.screens if item.screen_id == screen_id),
                    None,
                )
                if project_screen is None:
                    continue
                page_id = str(record.get("page_id") or "")
                root_id = str(record.get("root_node_id") or "")
                if not page_id or not root_id:
                    continue
                telemetry = await measure_screen(
                    self.owner.openpencil,
                    session,
                    document_id=str(record.get("document_id") or checkpoint.get("document_id") or artifact.get("document_id") or ""),
                    page_id=page_id,
                    root_node_id=root_id,
                )
                key = str(record.get("key") or f"{screen_id}:{record.get('platform', 'responsive')}")
                expected = int(record.get("expected_instances") or old_screens.get(key, {}).get("expected_instances", 0))
                review = deterministic_layout_review(
                    project_screen.specification,
                    telemetry,
                    expected,
                )
                reviews.append(
                    {
                        "key": key,
                        "screen_name": project_screen.specification.screen_name,
                        "platform": record.get("platform", project_screen.specification.platform),
                        **review.model_dump(mode="json"),
                    }
                )

        overall = _summarize_layout_reviews(reviews)
        overall["source"] = "live_openpencil"
        comparable = {key: value for key, value in overall.items() if key != "source"}
        previous_comparable = {
            key: value for key, value in old_layout.items() if key not in {"source", "unchanged"}
        }
        if previous_comparable and json.dumps(comparable, sort_keys=True, default=str) == json.dumps(
            previous_comparable, sort_keys=True, default=str
        ):
            return {**old_layout, "source": "live_openpencil", "unchanged": True}
        await self.store.set_artifact(run.id, run.revision, "layout_review", overall)
        await self.events.emit(
            run.id,
            run.revision,
            "layout.checked",
            {**overall, "message": "Rechecked the live OpenPencil layout"},
        )
        return overall

    async def sync_live_canvas(self, run_id: UUID) -> dict[str, Any]:
        """Persist the current OpenPencil canvas before QA or export.

        The live canvas is authoritative after a manual edit. The semantic JSON
        remains the agent plan, while this snapshot records the actual node tree
        and creates a durable manual-edit boundary for export.
        """
        run = await self.store.get_run(run_id)
        if run is None:
            raise not_found("Run")
        if not run.mcp_profile:
            raise AppError(
                "MCP_CONTEXT_REQUIRED",
                "OpenPencil context is required",
                "Configure the MCP endpoint before syncing the canvas.",
                409,
            )
        checkpoint = await self.store.get_artifact(run.id, run.revision, "openpencil_checkpoint") or {}
        artifact = await self.store.get_artifact(run.id, run.revision, "openpencil_artifact") or {}
        records = checkpoint.get("screens") or artifact.get("screens") or []
        if not records:
            raise AppError(
                "OPENPENCIL_CHECKPOINT_MISSING",
                "Saved OpenPencil pages are unavailable",
                "Build the design before syncing the canvas.",
                409,
            )

        synced_at = datetime.now(UTC).isoformat()
        snapshots: list[dict[str, Any]] = []
        async with self.owner.openpencil.session(run.mcp_profile.endpoint) as session:
            for record in records:
                document_id = str(record.get("document_id") or checkpoint.get("document_id") or artifact.get("document_id") or "")
                page_id = str(record.get("page_id") or "")
                root_id = str(record.get("root_node_id") or "")
                if not document_id or not page_id or not root_id:
                    continue
                if run.mcp_profile.output_file:
                    await self.owner.openpencil._call(
                        session,
                        "save_file",
                        {"path": run.mcp_profile.output_file, "document_id": document_id, "page_id": page_id},
                    )
                root = await self.owner.openpencil._call(
                    session,
                    "get_node",
                    {"document_id": document_id, "page_id": page_id, "id": root_id, "depth": 32},
                )
                snapshots.append(
                    {
                        "key": record.get("key"),
                        "screen_id": record.get("screen_id"),
                        "platform": record.get("platform"),
                        "document_id": document_id,
                        "page_id": page_id,
                        "root_node_id": root_id,
                        "root": root,
                    }
                )

        snapshot = {
            "source": "live_openpencil",
            "synced_at": synced_at,
            "revision": run.revision,
            "document_id": artifact.get("document_id") or checkpoint.get("document_id"),
            "screens": snapshots,
        }
        sync = {
            "status": "synced",
            "source": "live_openpencil",
            "synced_at": synced_at,
            "manual_edit_boundary": True,
            "screen_count": len(snapshots),
        }
        manual_overrides = {
            "source": "live_openpencil",
            "synced_at": synced_at,
            "revision": run.revision,
            "screens": [
                {
                    "key": item.get("key"),
                    "screen_id": item.get("screen_id"),
                    "page_id": item.get("page_id"),
                    "root_node_id": item.get("root_node_id"),
                }
                for item in snapshots
            ],
            "note": "Live canvas is authoritative for visual export; agent specification remains the semantic plan.",
        }
        await self.store.set_artifact(run.id, run.revision, "live_canvas_snapshot", snapshot)
        await self.store.set_artifact(run.id, run.revision, "canvas_sync", sync)
        await self.store.set_artifact(run.id, run.revision, "manual_overrides", manual_overrides)
        await self.events.emit(
            run.id,
            run.revision,
            "canvas.synced",
            {**sync, "message": "Live OpenPencil canvas synchronized"},
        )
        return sync

    async def _approve_specification(self, run: Any) -> None:
        await self.store.update_run(
            run.id,
            stage=run.stage,
            status=RunStatus.RUNNING,
        )
        await self.events.emit(
            run.id,
            run.revision,
            "review.accepted",
            {
                "checkpoint": "specification",
            },
        )
        if not run.mcp_profile:
            await self.owner._block(
                run.id,
                run.revision,
                AppError(
                    "MCP_CONTEXT_REQUIRED",
                    "OpenPencil context is required",
                    "Configure the MCP endpoint and component source before continuing.",
                    409,
                    action="Open Settings, complete OpenPencil configuration, then approve again.",
                ),
            )
            return
        capability = await self.owner.openpencil.probe(run.mcp_profile.endpoint)
        await self.store.set_artifact(
            run.id,
            run.revision,
            "openpencil_capability",
            capability.model_dump(mode="json"),
        )
        if not capability.reachable or not capability.file_operations:
            await self.owner._block(
                run.id,
                run.revision,
                AppError(
                    "OPENPENCIL_MCP_UNAVAILABLE",
                    "OpenPencil MCP is not ready",
                    f"{capability.message} Endpoint: {run.mcp_profile.endpoint}",
                    502,
                    retryable=True,
                    action="Open Connections, test the current endpoint, then retry this stage.",
                ),
            )
            return
        self.owner._spawn(
            run.id,
            self.owner.continue_after_review(run.id),
            f"continue:{run.id}",
        )

    async def _require_valid_layout(self, run: Any) -> None:
        layout = await self.store.get_artifact(run.id, run.revision, "layout_review")
        if not layout or layout.get("status") != "valid":
            raise AppError(
                "LAYOUT_NOT_VALID",
                "Layout cannot be approved yet",
                "Blocking layout findings must be corrected before final approval.",
                409,
                action="Request changes and address the layout findings.",
            )

    async def _approve_final(self, run: Any, request: ReviewCreate) -> None:
        await self._require_valid_layout(run)
        await self.store.update_run(
            run.id,
            stage=RunStage.FINISHED,
            status=RunStatus.COMPLETED,
        )
        artifact = await self.store.get_artifact(
            run.id,
            run.revision,
            "openpencil_artifact",
        )
        await self.events.emit(
            run.id,
            run.revision,
            "run.finished",
            {
                "message": "Final design approved.",
                "artifact": artifact,
            },
        )
        out_file = artifact.get("output_file") if isinstance(artifact, dict) else getattr(artifact, "output_file", "")
        approved_msg = (
            f"✅ **Thiết kế đã được phê duyệt thành công!**\n\n"
            f"File OpenPencil đã được lưu hoàn tất tại:\n`{out_file}`\n\n"
            f"Bản .fig cũng được lưu vào **Assets** của dự án (đánh dấu đã duyệt).\n\n"
            f"Bạn có thể mở trực tiếp trong OpenPencil Studio để xem, chỉnh sửa hoặc xuất mã nguồn bất cứ lúc nào."
        )
        await self.store.update_run(run.id, assistant_message=approved_msg)
        await self.events.emit(run.id, run.revision, "assistant.message", {"message": approved_msg})
        # No task runs after an approval: publish the approved file to Assets here.
        asyncio.get_running_loop().create_task(publish_design(self.owner, run.id))

    async def _request_changes(self, run: Any, request: ReviewCreate) -> None:
        await self.events.emit(
            run.id,
            run.revision,
            "review.changes_requested",
            {
                "checkpoint": request.checkpoint,
                "feedback": request.feedback,
            },
        )
        await self.store.bump_revision(run.id)
        self.owner._spawn(
            run.id,
            self.revise(run.id, request.feedback, request.checkpoint),
            f"revise:{run.id}",
        )

    async def retry(
        self,
        run_id: UUID,
        profile: OpenPencilProfile | None = None,
    ) -> None:
        run = await self.store.get_run(run_id)
        if run is None:
            raise not_found("Run")
        if run.status not in {RunStatus.FAILED, RunStatus.BLOCKED, RunStatus.CANCELLED}:
            raise AppError(
                "RUN_NOT_RETRYABLE",
                "Run cannot be retried",
                f"Current status is {run.status}.",
                409,
            )
        if profile:
            run = await self.store.update_mcp_profile(run.id, profile)
        failed_stage = str((run.error or {}).get("stage", ""))
        build_stages = {"components", "binding", "assembly", "layout_check"}
        resume_workspace = run.intent == "design"
        resume_build = (
            not resume_workspace
            and run.specification is not None
            and run.mcp_profile is not None
            and (failed_stage in build_stages or run.status == RunStatus.CANCELLED)
        )
        stage = RunStage.COMPONENTS if resume_build else RunStage.REQUIREMENT
        await self.store.update_run(run.id, stage=stage, status=RunStatus.QUEUED)
        await self.events.emit(
            run.id,
            run.revision,
            "run.retrying",
            {
                "stage": stage,
                "message": (
                    "Re-inspecting the live OpenPencil workspace"
                    if resume_workspace
                    else "Retrying the last recoverable workflow section"
                ),
            },
        )
        if resume_build:
            self.owner._spawn(
                run.id,
                self.owner.continue_after_review(run.id),
                f"retry:{run.id}",
            )
        else:
            self.owner.start(run.id)

    async def cancel(self, run_id: UUID) -> None:
        run = await self.store.get_run(run_id)
        if run is None:
            raise not_found("Run")
        task = self.owner.tasks.pop(run.id, None)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self.store.update_run(
            run.id,
            stage=RunStage.BLOCKED,
            status=RunStatus.CANCELLED,
        )
        await self.events.emit(
            run.id,
            run.revision,
            "run.cancelled",
            {
                "message": "Run cancelled by the user.",
            },
        )

    async def revise(self, run_id: UUID, feedback: str, checkpoint: str) -> None:
        run = await self.store.get_run(run_id)
        if not run or not run.specification:
            return
        try:
            await self.store.update_run(
                run.id,
                stage=RunStage.SPECIFICATION,
                status=RunStatus.RUNNING,
            )
            await self.events.emit(
                run.id,
                run.revision,
                "stage.changed",
                {
                    "stage": "specification",
                    "message": "Applying review feedback",
                },
            )
            bindings = await self.store.get_artifact(
                run.id,
                max(1, run.revision - 1),
                "component_bindings",
            )
            layout = await self.store.get_artifact(
                run.id,
                max(1, run.revision - 1),
                "layout_review",
            )
            project_value = await self.store.get_artifact(
                run.id,
                max(1, run.revision - 1),
                "project_specification",
            )
            prompt = self.prompts.render(
                "revision",
                feedback=feedback or "No written notes were provided.",
                ui_specification=run.specification.model_dump_json(),
                checkpoint=checkpoint,
                findings=json.dumps(layout or {}, ensure_ascii=False),
                immutable_bindings=json.dumps(bindings or {}, ensure_ascii=False),
            )
            specification = await self.llm.structured(prompt=prompt, schema=UiSpecification)
            if project_value:
                project = ProjectSpecification.model_validate(project_value)
                target = next(
                    (
                        screen
                        for screen in project.screens
                        if screen.specification.screen_name == run.specification.screen_name
                    ),
                    project.screens[0] if len(project.screens) == 1 else None,
                )
                if target:
                    target.specification = specification
                    await self.store.set_artifact(
                        run.id,
                        run.revision,
                        "project_specification",
                        project.model_dump(mode="json"),
                    )
            await self.store.update_run(
                run.id,
                stage=RunStage.REVIEW_SPEC,
                status=RunStatus.WAITING_REVIEW,
                specification=specification,
            )
            await self.events.emit(
                run.id,
                run.revision,
                "specification.ready",
                {
                    "specification": specification.model_dump(mode="json"),
                    "revision": run.revision,
                },
            )
            await self.events.emit(
                run.id,
                run.revision,
                "review.required",
                {
                    "checkpoint": "specification",
                    "message": "Review the revised structure before rebuilding.",
                },
            )
        except AppError as error:
            await self.owner._fail(run.id, run.revision, error)
        except Exception as error:
            await self.owner._fail(
                run.id,
                run.revision,
                AppError(
                    "REVISION_FAILED",
                    "Revision failed",
                    str(error),
                    500,
                    True,
                ),
            )

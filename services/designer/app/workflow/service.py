import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any
from uuid import UUID

from ..api.stream import EventStream
from ..core.config import Settings
from ..core.errors import AppError, unwrap_app_error
from ..core.llm import AdkProvider
from ..core.prompts import PromptLibrary
from ..models import ReviewCreate, RunStage, RunStatus
from ..render import Renderer
from ..storage.store import Store
from .designer import HtmlDesigner
from .publish import publish_design


class RunService:
    def __init__(
        self,
        store: Store,
        events: EventStream,
        llm: AdkProvider,
        prompts: PromptLibrary,
        settings: Settings,
        renderer: Renderer,
    ) -> None:
        self.store = store
        self.events = events
        self.llm = llm
        self.prompts = prompts
        self.settings = settings
        self.renderer = renderer
        self.tasks: dict[UUID, asyncio.Task[None]] = {}
        self.designer = HtmlDesigner(self)

    def _spawn(
        self, run_id: UUID, operation: Coroutine[Any, Any, None], name: str
    ) -> None:
        existing = self.tasks.get(run_id)
        if existing and not existing.done():
            existing.cancel()
        task = asyncio.create_task(self._guard(run_id, operation), name=name)
        self.tasks[run_id] = task

        def discard(completed: asyncio.Task[None]) -> None:
            if self.tasks.get(run_id) is completed:
                self.tasks.pop(run_id, None)
            if not completed.cancelled():
                # Platform Assets: the spec and the design bundle are published to the project.
                asyncio.get_running_loop().create_task(publish_design(self, run_id))

        task.add_done_callback(discard)

    async def _guard(self, run_id: UUID, operation: Coroutine[Any, Any, None]) -> None:
        """Errors end the run as blocked (configuration) or failed (retryable), never silently."""
        try:
            await operation
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001
            run = await self.store.get_run(run_id)
            if run is None:
                return
            app_error = unwrap_app_error(error) or AppError(
                "DESIGNER_FAILED", "Designer failed", f"{type(error).__name__}: {error}", 500, True,
                action="Retry the run.",
            )
            if app_error.code in {"LLM_NOT_CONFIGURED"}:
                await self._block(run_id, run.revision, app_error)
            else:
                await self._fail(run_id, run.revision, app_error)

    def _run(self, run_id: UUID, step: Callable[[], Awaitable[None]], name: str) -> None:
        self._spawn(run_id, step(), f"{name}:{run_id}")

    def start(self, run_id: UUID, feedback: str = "None") -> None:
        self._run(run_id, lambda: self.designer.analyze(run_id, feedback), "analyze")

    async def review(self, run_id: UUID, request: ReviewCreate) -> None:
        run = await self._require_run(run_id)
        if request.revision != run.revision:
            raise AppError("REVISION_CONFLICT", "Review is for an older revision", f"Current revision is {run.revision}.", 409)
        expected = {"specification": RunStage.REVIEW_SPEC, "final": RunStage.REVIEW_FINAL}[request.checkpoint]
        if run.status != RunStatus.WAITING_REVIEW or run.stage != expected:
            raise AppError("REVIEW_NOT_EXPECTED", "Nothing to review", f"Run is {run.stage}/{run.status}.", 409)
        await self.store.add_review(run_id, run.revision, request.checkpoint, request.decision, request.feedback)
        await self.events.emit(run_id, run.revision, "review.recorded", request.model_dump(mode="json"))
        if request.decision == "rejected":
            await self.store.update_run(run_id, stage=RunStage.FINISHED, status=RunStatus.CANCELLED,
                                        assistant_message="Đã dừng theo yêu cầu.")
            return
        if request.checkpoint == "specification":
            if request.decision == "approved":
                self._run(run_id, lambda: self.designer.build(run_id), "build")
            else:
                self._run(run_id, lambda: self.designer.write_spec(run_id, request.feedback or "Revise it."), "spec")
            return
        if request.decision == "approved":
            await self.store.update_run(run_id, stage=RunStage.FINISHED, status=RunStatus.COMPLETED)
            await self.events.emit(run_id, run.revision, "stage.changed", {"stage": "finished", "status": "completed"})
            asyncio.get_running_loop().create_task(publish_design(self, run_id))
            return
        targets = await self.designer.targets_for(run, request.feedback)
        self._run(run_id, lambda: self.designer.build(run_id, targets, instruction=request.feedback, review=True), "rebuild")

    async def retry(self, run_id: UUID) -> None:
        run = await self._require_run(run_id)
        if run.status not in {RunStatus.BLOCKED, RunStatus.FAILED, RunStatus.CANCELLED}:
            raise AppError("RUN_NOT_RETRYABLE", "Run is not retryable", f"Run status is {run.status}.", 409)
        failed_at = (run.error or {}).get("stage") or ""
        if run.specification and failed_at in {"assembly", "review_final"}:
            self._run(run_id, lambda: self.designer.build(run_id, review=run.intent != "design"), "build")
        elif failed_at in {"specification", "review_spec"}:
            self._run(run_id, lambda: self.designer.write_spec(run_id), "spec")
        else:
            self.start(run_id)

    async def cancel(self, run_id: UUID) -> None:
        run = await self._require_run(run_id)
        task = self.tasks.pop(run_id, None)
        if task and not task.done():
            task.cancel()
        await self.store.update_run(run_id, status=RunStatus.CANCELLED)
        await self.events.emit(run_id, run.revision, "run.cancelled", {"stage": run.stage.value})

    async def _require_run(self, run_id: UUID):
        run = await self.store.get_run(run_id)
        if run is None:
            raise AppError("RUN_NOT_FOUND", "Run not found", str(run_id), 404)
        return run

    async def delete_session(self, session_id: UUID) -> None:
        session = await self.store.get_session(session_id)
        if session is None:
            raise AppError("SESSION_NOT_FOUND", "Session not found", str(session_id), 404)
        runs = await self.store.list_runs(session_id)
        tasks: list[asyncio.Task[None]] = []
        for run in runs:
            task = self.tasks.pop(run.id, None)
            if task and not task.done():
                task.cancel()
                tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if not await self.store.delete_session(session_id):
            raise AppError("SESSION_NOT_FOUND", "Session not found", str(session_id), 404)

    async def _block(self, run_id: UUID, revision: int, error: AppError) -> None:
        run = await self.store.get_run(run_id)
        payload = self._problem(error, run.stage if run else None)
        await self.store.update_run(
            run_id, stage=RunStage.BLOCKED, status=RunStatus.BLOCKED, error=payload
        )
        await self.events.emit(run_id, revision, "action.required", payload)

    async def _fail(self, run_id: UUID, revision: int, error: AppError) -> None:
        run = await self.store.get_run(run_id)
        payload = self._problem(error, run.stage if run else None)
        await self.store.update_run(
            run_id, stage=RunStage.FAILED, status=RunStatus.FAILED, error=payload
        )
        await self.events.emit(run_id, revision, "run.failed", payload)

    @staticmethod
    def _problem(error: AppError, stage: RunStage | None = None) -> dict[str, Any]:
        return {
            "code": error.code,
            "title": error.title,
            "detail": error.detail,
            "retryable": error.retryable,
            "action": error.action,
            "stage": stage.value if stage else None,
        }

    async def shutdown(self) -> None:
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

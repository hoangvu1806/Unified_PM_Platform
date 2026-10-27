import asyncio
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from ..api.stream import EventStream
from ..core.errors import AppError
from ..core.llm import AdkProvider
from ..core.prompts import PromptLibrary
from ..models import ReviewCreate, RunStage, RunStatus
from ..storage.store import Store
from .publish import publish_design

# Until the HTML designer lands, accepted runs stop here with a clear, retryable message.
REBUILDING = AppError(
    "DESIGNER_REBUILDING",
    "Designer đang được xây lại",
    "Designer agent đang chuyển sang thiết kế bằng HTML + Tailwind; run đã được lưu.",
    503,
    True,
    action="Thử lại khi phiên bản mới được triển khai.",
)


class RunService:
    def __init__(
        self,
        store: Store,
        events: EventStream,
        llm: AdkProvider,
        prompts: PromptLibrary,
    ) -> None:
        self.store = store
        self.events = events
        self.llm = llm
        self.prompts = prompts
        self.tasks: dict[UUID, asyncio.Task[None]] = {}

    def _spawn(
        self, run_id: UUID, operation: Coroutine[Any, Any, None], name: str
    ) -> None:
        existing = self.tasks.get(run_id)
        if existing and not existing.done():
            existing.cancel()
        task = asyncio.create_task(operation, name=name)
        self.tasks[run_id] = task

        def discard(completed: asyncio.Task[None]) -> None:
            if self.tasks.get(run_id) is completed:
                self.tasks.pop(run_id, None)
            if not completed.cancelled():
                # Platform Assets: a finished design is published to the project.
                asyncio.get_running_loop().create_task(publish_design(self, run_id))

        task.add_done_callback(discard)

    def start(self, run_id: UUID, feedback: str = "None") -> None:
        self._spawn(run_id, self.analyze(run_id, feedback), f"analyze:{run_id}")

    async def analyze(self, run_id: UUID, feedback: str = "None") -> None:
        run = await self._require_run(run_id)
        await self._block(run_id, run.revision, REBUILDING)

    async def review(self, run_id: UUID, request: ReviewCreate) -> None:
        run = await self._require_run(run_id)
        if request.revision != run.revision:
            raise AppError("REVISION_CONFLICT", "Review is for an older revision", f"Current revision is {run.revision}.", 409)
        await self.store.add_review(run_id, run.revision, request.checkpoint, request.decision, request.feedback)
        await self.events.emit(run_id, run.revision, "review.recorded", request.model_dump(mode="json"))
        self.start(run_id, request.feedback or "None")

    async def retry(self, run_id: UUID) -> None:
        run = await self._require_run(run_id)
        if run.status not in {RunStatus.BLOCKED, RunStatus.FAILED, RunStatus.CANCELLED}:
            raise AppError("RUN_NOT_RETRYABLE", "Run is not retryable", f"Run status is {run.status}.", 409)
        await self.store.update_run(run_id, status=RunStatus.QUEUED, stage=RunStage.REQUIREMENT)
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

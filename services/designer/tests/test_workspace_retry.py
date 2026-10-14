import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from app.models import RunStage, RunStatus
from app.workflow.review import HumanReviewFlow


def test_failed_workspace_action_retries_through_live_context_agent() -> None:
    async def scenario() -> None:
        run = SimpleNamespace(
            id=uuid4(),
            revision=1,
            status=RunStatus.FAILED,
            stage=RunStage.FAILED,
            intent="design",
            specification=object(),
            mcp_profile=object(),
            error={"stage": "assembly"},
        )
        store = SimpleNamespace(
            get_run=AsyncMock(return_value=run),
            update_run=AsyncMock(),
        )
        owner = SimpleNamespace(
            store=store,
            events=SimpleNamespace(emit=AsyncMock()),
            llm=SimpleNamespace(),
            prompts=SimpleNamespace(),
            start=Mock(),
            continue_after_review=Mock(),
            _spawn=Mock(),
        )

        await HumanReviewFlow(owner).retry(run.id)

        store.update_run.assert_awaited_once_with(
            run.id,
            stage=RunStage.REQUIREMENT,
            status=RunStatus.QUEUED,
        )
        owner.start.assert_called_once_with(run.id)
        owner._spawn.assert_not_called()

    asyncio.run(scenario())


def test_failed_project_build_still_resumes_from_components() -> None:
    async def scenario() -> None:
        run = SimpleNamespace(
            id=uuid4(),
            revision=1,
            status=RunStatus.FAILED,
            stage=RunStage.FAILED,
            intent="start_design",
            specification=object(),
            mcp_profile=object(),
            error={"stage": "assembly"},
        )
        store = SimpleNamespace(
            get_run=AsyncMock(return_value=run),
            update_run=AsyncMock(),
        )
        owner = SimpleNamespace(
            store=store,
            events=SimpleNamespace(emit=AsyncMock()),
            llm=SimpleNamespace(),
            prompts=SimpleNamespace(),
            start=Mock(),
            continue_after_review=Mock(return_value=SimpleNamespace()),
            _spawn=Mock(),
        )

        await HumanReviewFlow(owner).retry(run.id)

        store.update_run.assert_awaited_once_with(
            run.id,
            stage=RunStage.COMPONENTS,
            status=RunStatus.QUEUED,
        )
        owner._spawn.assert_called_once()
        owner.start.assert_not_called()

    asyncio.run(scenario())


def test_cancelled_project_build_can_resume_saved_checkpoint() -> None:
    async def scenario() -> None:
        run = SimpleNamespace(
            id=uuid4(),
            revision=1,
            status=RunStatus.CANCELLED,
            stage=RunStage.BLOCKED,
            intent="start_design",
            specification=object(),
            mcp_profile=object(),
            error=None,
        )
        store = SimpleNamespace(get_run=AsyncMock(return_value=run), update_run=AsyncMock())
        owner = SimpleNamespace(
            store=store,
            events=SimpleNamespace(emit=AsyncMock()),
            llm=SimpleNamespace(),
            prompts=SimpleNamespace(),
            start=Mock(),
            continue_after_review=Mock(return_value=SimpleNamespace()),
            _spawn=Mock(),
        )

        await HumanReviewFlow(owner).retry(run.id)

        store.update_run.assert_awaited_once_with(
            run.id,
            stage=RunStage.COMPONENTS,
            status=RunStatus.QUEUED,
        )
        owner._spawn.assert_called_once()
        owner.start.assert_not_called()

    asyncio.run(scenario())

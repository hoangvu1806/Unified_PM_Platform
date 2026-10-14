import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.openpencil.client import OpenPencilClient


def test_mcp_session_does_not_relabel_workflow_error_as_connection_failure() -> None:
    async def scenario() -> None:
        @asynccontextmanager
        async def transport(_url: str, **_kwargs: object):
            yield object(), object(), object()

        class Session:
            def __init__(self, *_args: object) -> None:
                pass

            async def __aenter__(self) -> "Session":
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def initialize(self) -> None:
                return None

        client = OpenPencilClient(
            SimpleNamespace(openpencil_mcp_auth_token="")
        )
        with (
            patch("app.openpencil.client.streamablehttp_client", transport),
            patch("app.openpencil.client.ClientSession", Session),
        ):
            try:
                async with client.session("http://127.0.0.1:7600/mcp"):
                    raise RuntimeError("visual refinement exhausted")
            except Exception as error:
                assert isinstance(error, RuntimeError)
                assert str(error) == "visual refinement exhausted"
            else:
                raise AssertionError("Expected the workflow error to propagate")

    asyncio.run(scenario())


def client_with_responses(responses: dict[str, dict[str, object]]) -> tuple[OpenPencilClient, AsyncMock]:
    client = OpenPencilClient(SimpleNamespace())
    client._require_app = AsyncMock()  # type: ignore[method-assign]

    @asynccontextmanager
    async def session(_endpoint: str):
        yield object()

    call = AsyncMock(side_effect=lambda _session, tool, _args: responses[tool])
    client.session = session  # type: ignore[method-assign]
    client._call = call  # type: ignore[method-assign]
    return client, call


def test_create_document_saves_and_returns_the_new_tab() -> None:
    async def scenario() -> None:
        client, call = client_with_responses(
            {
                "new_document": {"target": {"document_id": "tab-9"}},
                "save_file": {},
                "list_documents": {
                    "documents": [
                        {
                            "id": "tab-9",
                            "name": "Student portal",
                            "active": True,
                            "pages": [{"id": "0:1", "name": "Page 1"}],
                        }
                    ]
                },
            }
        )

        document = await client.create_document(
            "http://127.0.0.1:7600/mcp", "Student portal"
        )

        assert document.id == "tab-9"
        assert document.name == "Student portal"
        assert document.path == "/data/workspace/Student portal.fig"
        assert call.await_args_list[0].args[2] == {
            "path": "workspace/Student portal.fig"
        }
        assert [item.args[1] for item in call.await_args_list] == [
            "new_document",
            "save_file",
            "list_documents",
        ]

    asyncio.run(scenario())


def test_create_page_switches_to_the_named_page() -> None:
    async def scenario() -> None:
        client, call = client_with_responses(
            {
                "create_page": {"id": "0:22"},
                "switch_page": {},
                "save_file": {},
                "list_documents": {
                    "documents": [
                        {
                            "id": "tab-2",
                            "name": "Student portal",
                            "active": True,
                            "path": "/data/workspace/Student portal.fig",
                            "current_page_id": "0:22",
                            "current_page_name": "Schedule",
                            "pages": [{"id": "0:22", "name": "Schedule"}],
                        }
                    ]
                },
            }
        )

        document = await client.create_page(
            "http://127.0.0.1:7600/mcp", "tab-2", "Schedule"
        )

        assert document.current_page_id == "0:22"
        assert call.await_args_list[1].args[2] == {
            "page": "0:22",
            "document_id": "tab-2",
        }

    asyncio.run(scenario())

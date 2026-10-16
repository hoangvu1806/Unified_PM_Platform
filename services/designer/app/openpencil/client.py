import asyncio
import json
from pathlib import Path
import re
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel, Field

from ..core.config import Settings
from ..core.errors import AppError
from ..models import OpenPencilDocumentView


class OpenPencilCapability(BaseModel):
    reachable: bool
    endpoint: str
    tools: list[str] = Field(default_factory=list)
    file_operations: bool = False
    server_version: str | None = None
    message: str


class OpenPencilClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _token(self, endpoint: str) -> str:
        # Platform: per-instance token when the endpoint is a registered
        # designer instance, else the default instance token from .env.
        from .instances import token_for

        return token_for(endpoint) or self.settings.openpencil_mcp_auth_token

    @asynccontextmanager
    async def session(self, endpoint: str) -> AsyncIterator[ClientSession]:
        url = endpoint.strip()
        if not url:
            raise AppError(
                "MCP_PROFILE_REQUIRED",
                "OpenPencil endpoint is required",
                "Configure the MCP endpoint in frontend Settings.",
                409,
            )
        parsed = urlsplit(url)
        if parsed.hostname == "localhost":
            url = urlunsplit(parsed._replace(netloc=f"127.0.0.1:{parsed.port or 7600}"))
        headers = {}
        if self._token(endpoint):
            headers["Authorization"] = f"Bearer {self._token(endpoint)}"
        body_error: Exception | None = None
        try:
            async with streamablehttp_client(url, headers=headers) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    try:
                        yield session
                    except Exception as error:
                        body_error = error
                        raise
        except AppError:
            raise
        except Exception as error:
            # Errors raised by the workflow while an MCP session is open are not
            # connection failures. Async context cleanup may wrap them in an
            # ExceptionGroup, so preserve the original body exception explicitly.
            if body_error is not None:
                raise body_error from error
            nested = self._find_app_error(error)
            if nested:
                raise nested from error
            raise AppError(
                "OPENPENCIL_MCP_UNAVAILABLE",
                "OpenPencil MCP is unavailable",
                self._exception_detail(error),
                502,
                retryable=True,
                action="Start OpenPencil and its HTTP MCP runtime, then retry.",
            ) from error

    async def probe(self, endpoint: str) -> OpenPencilCapability:
        url = endpoint.strip()
        parsed = urlsplit(url)
        if parsed.hostname == "localhost":
            url = urlunsplit(parsed._replace(netloc=f"127.0.0.1:{parsed.port or 7600}"))
        health = await self._health_info(url)
        if health.get("status") == "no_app":
            return OpenPencilCapability(
                reachable=False,
                endpoint=url,
                server_version=health.get("version"),
                message=(
                    "MCP server is running, but the OpenPencil app bridge is disconnected. "
                    "Refresh the OpenPencil browser tab."
                ),
            )
        try:
            async with asyncio.timeout(self.settings.mcp_timeout_seconds):
                async with self.session(url) as session:
                    result = await session.list_tools()
                    tools = sorted(tool.name for tool in result.tools)
        except (AppError, TimeoutError) as error:
            return OpenPencilCapability(
                reachable=False,
                endpoint=url,
                message=getattr(error, "detail", "OpenPencil MCP timed out."),
            )
        required = {
            "open_file",
            "new_document",
            "save_file",
            "create_page",
            "switch_page",
            "render",
            "list_pages",
            "get_node",
            "create_instance",
            "find_nodes",
            "node_ancestors",
            "reparent_node",
            "delete_node",
            "node_tree",
            "set_text",
            "page_bounds",
            "node_bounds",
            "describe",
            "update_node",
            "get_selection",
            "get_page_tree",
            "get_jsx",
            "batch_update",
            "set_image_fill",
            "analyze_overlaps",
        }
        available = required.issubset(tools)
        return OpenPencilCapability(
            reachable=True,
            endpoint=url,
            tools=tools,
            file_operations=available,
            server_version=health.get("version"),
            message=(
                f"OpenPencil MCP connected ({len(tools)} tools available)."
                if available
                else "Connected, but required file tools are missing."
            ),
        )

    async def download_workspace_file(self, endpoint: str, path: str) -> tuple[bytes, str]:
        """Read a saved OpenPencil workspace file through its data endpoint."""
        clean = path.replace("\\", "/").lstrip("/")
        if not clean or ".." in clean.split("/"):
            raise AppError("INVALID_OUTPUT_FILE", "Invalid output file", path, 422)
        local_root = (self.settings.openpencil_data_dir or "").strip()
        if local_root:
            local = Path(local_root) / clean
            if local.is_file():
                return await asyncio.to_thread(local.read_bytes), "application/octet-stream"
        parsed = urlsplit(endpoint.strip())
        if not parsed.scheme or not parsed.netloc:
            raise AppError("MCP_PROFILE_REQUIRED", "OpenPencil endpoint is required", endpoint, 409)
        base = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        url = f"{base}/data/{clean}"
        headers = {}
        if self._token(endpoint):
            headers["Authorization"] = f"Bearer {self._token(endpoint)}"

        def read() -> tuple[bytes, str]:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=self.settings.mcp_timeout_seconds) as response:
                return response.read(), response.headers.get_content_type()

        try:
            return await asyncio.to_thread(read)
        except Exception as error:
            raise AppError(
                "OPENPENCIL_FILE_UNAVAILABLE",
                "Saved OpenPencil file is unavailable",
                f"Could not download {path}: {error}",
                502,
                retryable=True,
                action="Save the OpenPencil document, then try download again.",
            ) from error

    async def documents(self, endpoint: str) -> list[OpenPencilDocumentView]:
        """Return the tabs currently connected to the OpenPencil editor."""
        await self._require_app(endpoint)
        async with self.session(endpoint) as session:
            value = await self._call(session, "list_documents", {})
        documents = value.get("documents", [])
        if not isinstance(documents, list):
            raise AppError(
                "OPENPENCIL_INVALID_RESULT",
                "OpenPencil returned an invalid document list",
                str(value),
                502,
            )
        return [OpenPencilDocumentView.model_validate(item) for item in documents]

    async def create_document(
        self, endpoint: str, name: str
    ) -> OpenPencilDocumentView:
        """Create, persist, and return a new named OpenPencil document."""
        await self._require_app(endpoint)
        clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", name)
        clean_name = re.sub(r"\s+", " ", clean_name).strip(" .")
        if clean_name.lower().endswith(".fig"):
            clean_name = clean_name[:-4].rstrip(" .")
        if not clean_name:
            raise AppError(
                "OPENPENCIL_DOCUMENT_NAME_REQUIRED",
                "Document name is required",
                "Enter a valid name for the new document.",
                422,
            )
        path = f"workspace/{clean_name[:100]}.fig"
        async with self.session(endpoint) as session:
            created = await self._call(session, "new_document", {"path": path})
            document_id, _ = self._target(created)
            if not document_id:
                raise AppError(
                    "OPENPENCIL_INVALID_RESULT",
                    "OpenPencil did not return the new document",
                    str(created),
                    502,
                )
            await self._call(
                session,
                "save_file",
                {"path": path, "document_id": document_id},
            )
            documents = await self._documents_from_session(session)
        document = self._find_document(documents, document_id)
        # Browser tabs cannot bind the server's filesystem path directly. Keep
        # that path in the API response while trusting OpenPencil's real tab name.
        return document.model_copy(update={"path": f"/data/{path}"})

    async def create_page(
        self, endpoint: str, document_id: str, name: str
    ) -> OpenPencilDocumentView:
        """Create a named page and make it current in the target document."""
        await self._require_app(endpoint)
        clean_name = re.sub(r"\s+", " ", name).strip()
        if not clean_name:
            raise AppError(
                "OPENPENCIL_PAGE_NAME_REQUIRED",
                "Page name is required",
                "Enter a valid name for the new page.",
                422,
            )
        async with self.session(endpoint) as session:
            created = await self._call(
                session,
                "create_page",
                {"name": clean_name[:120], "document_id": document_id},
            )
            page_id = str(created.get("id") or created.get("page_id") or "")
            if not page_id:
                _, page_id = self._target(created)
            if not page_id:
                raise AppError(
                    "OPENPENCIL_INVALID_RESULT",
                    "OpenPencil did not return the new page",
                    str(created),
                    502,
                )
            await self._call(
                session,
                "switch_page",
                {"page": page_id, "document_id": document_id},
            )
            documents = await self._documents_from_session(session)
            document = self._find_document(documents, document_id)
            if document.path:
                await self._call(
                    session,
                    "save_file",
                    {"path": document.path, "document_id": document_id},
                )
        return document

    async def _documents_from_session(
        self, session: ClientSession
    ) -> list[OpenPencilDocumentView]:
        value = await self._call(session, "list_documents", {})
        documents = value.get("documents", [])
        if not isinstance(documents, list):
            raise AppError(
                "OPENPENCIL_INVALID_RESULT",
                "OpenPencil returned an invalid document list",
                str(value),
                502,
            )
        return [OpenPencilDocumentView.model_validate(item) for item in documents]

    @staticmethod
    def _find_document(
        documents: list[OpenPencilDocumentView], document_id: str
    ) -> OpenPencilDocumentView:
        document = next((item for item in documents if item.id == document_id), None)
        if document is None:
            raise AppError(
                "OPENPENCIL_DOCUMENT_NOT_FOUND",
                "OpenPencil document is no longer open",
                document_id,
                404,
                retryable=True,
            )
        return document

    async def _require_app(self, endpoint: str) -> None:
        if await self._health_status(endpoint) != "no_app":
            return
        raise AppError(
            "OPENPENCIL_APP_DISCONNECTED",
            "OpenPencil app is disconnected",
            "The MCP server is running, but no browser editor is connected.",
            409,
            retryable=True,
            action="Refresh the OpenPencil browser tab, then retry.",
        )

    async def _health_status(self, endpoint: str) -> str | None:
        return (await self._health_info(endpoint)).get("status")

    async def _health_info(self, endpoint: str) -> dict[str, str]:
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return {}
        netloc = parsed.netloc
        if parsed.hostname == "localhost":
            netloc = f"127.0.0.1:{parsed.port}" if parsed.port else "127.0.0.1"
        health_url = urlunsplit((parsed.scheme, netloc, "/health", "", ""))

        def fetch() -> dict[str, str]:
            headers = {}
            if self._token(endpoint):
                headers["Authorization"] = f"Bearer {self._token(endpoint)}"
            with urlopen(Request(health_url, headers=headers), timeout=3) as response:
                value = json.loads(response.read().decode("utf-8"))
            if not isinstance(value, dict):
                return {}
            return {
                key: str(value[key])
                for key in ("status", "version")
                if value.get(key) is not None
            }

        try:
            return await asyncio.wait_for(asyncio.to_thread(fetch), timeout=4)
        except Exception:
            return {}

    async def _call(
        self,
        session: ClientSession,
        tool: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            async with asyncio.timeout(self.settings.mcp_timeout_seconds):
                response = await session.call_tool(tool, arguments=arguments)
        except TimeoutError as error:
            raise AppError(
                "OPENPENCIL_MCP_TIMEOUT",
                "OpenPencil MCP timed out",
                tool,
                504,
                True,
            ) from error
        text_parts: list[str] = []
        for item in response.content:
            value = getattr(item, "text", None)
            if isinstance(value, str):
                text_parts.append(value)
        text = "\n".join(text_parts)
        if getattr(response, "isError", False):
            if "RPC timeout" in text:
                raise AppError("OPENPENCIL_MCP_TIMEOUT", "OpenPencil editor did not answer",
                               f"Tool {tool}: {text}", 504, True,
                               action="Bring the OpenPencil tab to the foreground and let loading finish, then retry this stage.")
            if "Browser disconnected" in text or "no browser" in text.lower():
                raise AppError(
                    "OPENPENCIL_APP_DISCONNECTED",
                    "OpenPencil browser tab disconnected",
                    "The OpenPencil editor at http://localhost:1420 disconnected during tool execution.",
                    502,
                    True,
                    action=(
                        "Make sure the OpenPencil tab (http://localhost:1420) is open "
                        "and active in your browser, then retry."
                    ),
                )
            if tool == "open_file":
                raise AppError(
                    "OPENPENCIL_SOURCE_UNAVAILABLE",
                    "OpenPencil could not open the design file",
                    text,
                    409,
                    True,
                    action=(
                        "Check the requested output file and the OpenPencil editor connection."
                    ),
                )
            raise AppError(
                "OPENPENCIL_TOOL_FAILED",
                f"OpenPencil tool {tool} failed",
                text,
                502,
                True,
            )
        try:
            value = json.loads(text) if text else {}
        except json.JSONDecodeError as error:
            raise AppError(
                "OPENPENCIL_INVALID_RESULT",
                "OpenPencil returned invalid JSON",
                text,
                502,
            ) from error
        if isinstance(value, dict) and "result" in value and isinstance(value["result"], dict):
            value = value["result"]
        if not isinstance(value, dict) or value.get("error"):
            err_val = value.get("error") if isinstance(value, dict) else value
            err_str = str(err_val)
            if "Browser disconnected" in err_str or "no browser" in err_str.lower():
                raise AppError(
                    "OPENPENCIL_APP_DISCONNECTED",
                    "OpenPencil browser tab disconnected",
                    "The OpenPencil editor at http://localhost:1420 disconnected during tool execution.",
                    502,
                    True,
                    action=(
                        "Make sure the OpenPencil tab (http://localhost:1420) is open "
                        "and active in your browser, then retry."
                    ),
                )
            raise AppError(
                "OPENPENCIL_TOOL_FAILED",
                f"OpenPencil tool {tool} failed",
                str(value),
                502,
                True,
            )
        return value

    @staticmethod
    def _target(value: Any) -> tuple[str, str]:
        if isinstance(value, dict):
            target = value.get("target", value)
            document_id = target.get("document_id") or target.get("documentId") or ""
            page_id = target.get("page_id") or target.get("pageId") or ""
            if document_id:
                return str(document_id), str(page_id)
            for nested in value.values():
                found = OpenPencilClient._target(nested)
                if found[0]:
                    return found
        if isinstance(value, list):
            for nested in value:
                found = OpenPencilClient._target(nested)
                if found[0]:
                    return found
        return "", ""

    @staticmethod
    def _exception_detail(error: BaseException) -> str:
        nested = getattr(error, "exceptions", None)
        if nested:
            details = [OpenPencilClient._exception_detail(item) for item in nested]
            return "; ".join(dict.fromkeys(detail for detail in details if detail))
        return str(error) or error.__class__.__name__

    @staticmethod
    def _find_app_error(error: BaseException) -> AppError | None:
        if isinstance(error, AppError):
            return error
        for nested in getattr(error, "exceptions", ()):
            found = OpenPencilClient._find_app_error(nested)
            if found:
                return found
        return None

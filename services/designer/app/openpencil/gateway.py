import asyncio
import base64
import logging
import re
from typing import Any

from mcp import ClientSession

from ..core.config import Settings
from ..models import (
    ComponentBindingSet,
    ComponentCandidate,
    OpenPencilProfile,
)
from .client import OpenPencilClient
from .components import ComponentSource
from .project_executor import assemble_project as execute_project

logger = logging.getLogger("designer_agent.openpencil_gateway")


class OpenPencilGateway(OpenPencilClient):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.source = ComponentSource(settings)

    async def components(
        self,
        profile: OpenPencilProfile,
        requirements: list[dict[str, Any]] | None = None,
        knowledge: dict[str, Any] | None = None,
    ) -> list[ComponentCandidate]:
        return await self.source.discover(profile, requirements, knowledge)

    async def assemble_project(
        self,
        profile: OpenPencilProfile,
        project: Any,
        bindings: ComponentBindingSet,
        *,
        run_id: str | None = None,
        llm: Any = None,
        prompts: Any = None,
        checkpoint: dict[str, Any] | None = None,
        on_checkpoint: Any = None,
        component_candidates: list[dict[str, Any]] | None = None,
        exact_assets: list[dict[str, Any]] | None = None,
        on_event: Any = None,
    ) -> dict[str, Any]:
        return await execute_project(
            self,
            profile,
            project,
            bindings,
            run_id=run_id,
            llm=llm,
            prompts=prompts,
            checkpoint=checkpoint,
            on_checkpoint=on_checkpoint,
            component_candidates=component_candidates,
            exact_assets=exact_assets,
            on_event=on_event,
        )

    async def _capture_preview(
        self,
        session: ClientSession,
        document_id: str,
        page_id: str,
        root_node_id: str | None = None,
        scale: float = 0.4,
    ) -> tuple[bytes, str] | None:
        """Capture the requested screen without falling back to another document."""
        page_target = {"document_id": document_id, "page_id": page_id}
        target = dict(page_target)
        if root_node_id:
            target["ids"] = [root_node_id]
        last_error: Exception | None = None
        raster_targets = [target, page_target] if root_node_id else [target]
        for raster_target in raster_targets:
            for attempt in range(2):
                try:
                    async with asyncio.timeout(30):
                        result = await session.call_tool(
                            "export_image", arguments={**raster_target, "format": "JPG", "scale": scale}
                        )
                        for item in result.content:
                            data = getattr(item, "data", None)
                            if data:
                                raw = base64.b64decode(data) if isinstance(data, str) else bytes(data)
                                return raw, "jpg"
                except Exception as error:
                    last_error = error
                if attempt == 0:
                    await asyncio.sleep(0.25)
        logger.warning("Raster preview unavailable for page %s: %s", page_id, last_error or "empty export")
        try:
            async with asyncio.timeout(15):
                result = await self._call(session, "export_svg", target)
                if result.get("svg"):
                    return result["svg"].encode("utf-8"), "svg"
        except Exception as error:
            logger.warning("Vector preview unavailable for page %s: %s", page_id, error)
        return None

    async def _insert_instances(
        self,
        session: ClientSession,
        document_id: str,
        page_id: str,
        bindings: ComponentBindingSet,
    ) -> dict[str, str]:
        created: dict[str, str] = {}
        for binding in bindings.bindings:
            if binding.status != "resolved" or not binding.component_id:
                continue
            matches = await self._call(
                session,
                "find_nodes",
                {
                    "name": f"slot::{binding.node_id}",
                    "document_id": document_id,
                    "page_id": page_id,
                },
            )
            nodes = matches.get("nodes", [])
            if not nodes:
                continue
            placeholder = nodes[0]
            mount = await self._call(
                session,
                "get_node",
                {"id": placeholder["id"], "document_id": document_id, "page_id": page_id},
            )
            instance = await self._call(
                session,
                "create_instance",
                {
                    "component_id": binding.component_id,
                    "x": placeholder.get("x", 0),
                    "y": placeholder.get("y", 0),
                    "document_id": document_id,
                    "page_id": page_id,
                },
            )
            if not instance.get("id"):
                raise ValueError("OpenPencil did not return the component instance ID")
            await self._call(
                session,
                "reparent_node",
                {
                    "id": instance["id"],
                    "parent_id": placeholder["id"],
                    "document_id": document_id,
                    "page_id": page_id,
                },
            )
            await self._call(
                session,
                "update_node",
                {
                    "id": instance["id"],
                    "x": 0,
                    "y": 0,
                    "document_id": document_id,
                    "page_id": page_id,
                },
            )
            # An empty slot is not auto-layout. FILL has no effect there, so
            # resize the real instance to the slot's measured dimensions.
            width = mount.get("width", mount.get("w"))
            height = mount.get("height", mount.get("h"))
            if isinstance(width, int | float) and isinstance(height, int | float) and width > 0 and height > 0:
                await self._call(
                    session,
                    "node_resize",
                    {
                        "id": instance["id"],
                        "width": width,
                        "height": height,
                        "document_id": document_id,
                        "page_id": page_id,
                    },
                )
            await self._bind_text(
                session,
                document_id,
                page_id,
                str(instance["id"]),
                binding.text_values,
            )
            # Keep the mount in its original layout position; appending to its
            # parent would move every button to the end of the row/column.
            await self._call(
                session,
                "rename_node",
                {
                    "id": placeholder["id"],
                    "name": f"component::{binding.node_id}",
                    "document_id": document_id,
                    "page_id": page_id,
                },
            )
            created[binding.node_id] = str(instance["id"])
        return created

    async def _bind_text(
        self,
        session: ClientSession,
        document_id: str,
        page_id: str,
        instance_id: str,
        values: dict[str, str],
    ) -> None:
        if not values:
            return
        tree = await self._call(
            session,
            "node_tree",
            {
                "id": instance_id,
                "document_id": document_id,
                "page_id": page_id,
            },
        )

        text_nodes: list[tuple[str, str, str]] = []

        def collect(node: Any, prefix: str = "") -> None:
            if not isinstance(node, dict):
                return
            name = str(node.get("name", node.get("type", "node")))
            path = f"{prefix}/{name}".strip("/")
            if node.get("type") == "TEXT" and node.get("id"):
                text_nodes.append((str(node["id"]), path, name))
            for child in node.get("children", []):
                collect(child, path)

        collect(tree)
        unused = list(text_nodes)

        for slot, content in values.items():
            normalized = self._normalized(slot.removeprefix("text:"))
            match = next((item for item in unused if self._normalized(item[1]) == normalized), None)
            match = match or next((item for item in unused if self._normalized(item[2]) == normalized), None)
            if match is None and len(unused) == 1 and len(values) == 1:
                match = unused[0]
            if match is None:
                raise ValueError(f"Text slot {slot!r} was not found in component {instance_id}")
            unused.remove(match)
            await self._call(
                session,
                "set_text",
                {
                    "id": match[0],
                    "text": content,
                    "document_id": document_id,
                    "page_id": page_id,
                },
            )

    @staticmethod
    def _normalized(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", value.lower()))

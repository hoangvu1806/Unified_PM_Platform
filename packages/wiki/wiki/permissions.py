from __future__ import annotations

import json
from pathlib import Path

from wiki.models import Actor, WikiError
from wiki.paths import manifest_path

HUMAN_TOOLS = {
    "wiki.search_pages",
    "wiki.fetch_page",
    "wiki.ingest_source",
    "wiki.propose_page",
    "wiki.approve_page",
    "wiki.demote_page",
    "wiki.delete_page",
    "wiki.read_source",
}


def load_manifest(root: Path) -> dict:
    path = manifest_path(root)
    if not path.exists():
        raise WikiError("COMMON_SCHEMA_INVALID", f"manifest missing: {path}", 500)
    return json.loads(path.read_text(encoding="utf-8"))


def require_tool(root: Path, actor: Actor, tool: str) -> None:
    if actor.actor_type == "human":
        if tool not in HUMAN_TOOLS:
            raise WikiError("COMMON_PERMISSION_DENIED", f"human cannot call {tool}", 403)
        return

    if tool in {"wiki.approve_page", "wiki.demote_page", "wiki.delete_page"}:
        raise WikiError(
            "COMMON_PERMISSION_DENIED",
            f"{tool} is not granted to agents",
            403,
        )

    name = actor.agent_name or actor.actor
    agents = load_manifest(root).get("agents", {})
    spec = agents.get(name)
    if spec is None:
        raise WikiError("COMMON_PERMISSION_DENIED", f"unknown agent {name}", 403)

    denied = set(spec.get("tools.denied", []))
    allowed = set(spec.get("tools.allowed", []))
    if tool in denied or tool not in allowed:
        raise WikiError("COMMON_PERMISSION_DENIED", f"{name} cannot call {tool}", 403)


def require_project_scope(
    actor: Actor,
    *,
    namespace: str,
    project_id: str | None,
) -> None:
    if namespace == "project" and not project_id:
        raise WikiError(
            "COMMON_SCHEMA_INVALID",
            "project_id is required when namespace=project",
            400,
        )
    if actor.actor_type != "agent":
        return
    if namespace == "project":
        if not actor.project_id:
            raise WikiError(
                "COMMON_SCHEMA_INVALID",
                "agent must send project_id",
                400,
            )
        if project_id and actor.project_id != project_id:
            raise WikiError(
                "COMMON_PERMISSION_DENIED",
                "agent cannot access another project_id",
                403,
            )

from __future__ import annotations

import os
from typing import Any

from mcp.server.mcpserver import MCPServer

from wiki.llm_config import build_sorter, load_dotenv
from wiki.models import Actor, ProposePageIn, SearchQuery, WikiError
from wiki.paths import MVP_ROOT
from wiki.service import WikiService

load_dotenv()

svc = WikiService(MVP_ROOT, sorter=build_sorter())
mcp = MCPServer(name="wiki-knowledge")


def _agent(arguments: dict[str, Any] | None = None) -> Actor:
    extra = arguments or {}
    name = extra.get("agent_name") or os.environ.get("WIKI_AGENT_NAME", "ba-agent")
    return Actor(
        actor=str(extra.get("actor") or name),
        actor_type="agent",
        project_id=extra.get("project_id") or os.environ.get("WIKI_PROJECT_ID"),
        agent_run_id=extra.get("agent_run_id"),
        agent_name=name,
    )


def _dump(err: WikiError) -> dict:
    return err.as_dict()


@mcp.tool(name="wiki.search_pages")
def wiki_search_pages(
    query: str,
    namespace: str,
    project_id: str | None = None,
    bucket_id: str | None = None,
    status: str = "approved",
    limit: int = 5,
    actor: str | None = None,
    agent_name: str | None = None,
    agent_run_id: str | None = None,
) -> dict:
    who = _agent(
        {
            "actor": actor,
            "agent_name": agent_name,
            "agent_run_id": agent_run_id,
            "project_id": project_id,
        }
    )
    try:
        hits = svc.search_pages(
            who,
            SearchQuery(
                query=query,
                namespace=namespace,
                project_id=project_id or who.project_id,
                bucket_id=bucket_id,
                status=status,
                limit=limit,
            ),
        )
        return {"hits": [h.model_dump() for h in hits]}
    except WikiError as exc:
        return _dump(exc)


@mcp.tool(name="wiki.fetch_page")
def wiki_fetch_page(
    page_id: str,
    version: str | None = None,
    project_id: str | None = None,
    actor: str | None = None,
    agent_name: str | None = None,
    agent_run_id: str | None = None,
) -> dict:
    who = _agent(
        {
            "actor": actor,
            "agent_name": agent_name,
            "agent_run_id": agent_run_id,
            "project_id": project_id,
        }
    )
    try:
        return svc.fetch_page(who, page_id, version).model_dump()
    except WikiError as exc:
        return _dump(exc)


@mcp.tool(name="wiki.ingest_source")
def wiki_ingest_source(
    path: str,
    namespace: str,
    project_id: str | None = None,
    actor: str | None = None,
    agent_name: str | None = None,
    agent_run_id: str | None = None,
) -> dict:
    who = _agent(
        {
            "actor": actor,
            "agent_name": agent_name,
            "agent_run_id": agent_run_id,
            "project_id": project_id,
        }
    )
    try:
        data = open(path, "rb").read()
        filename = path.rsplit("/", 1)[-1]
        return svc.ingest_source(
            who,
            filename=filename,
            data=data,
            namespace=namespace,
            project_id=project_id,
        )
    except WikiError as exc:
        return _dump(exc)
    except OSError as exc:
        return {"code": "COMMON_SCHEMA_INVALID", "message": str(exc)}


@mcp.tool(name="wiki.propose_page")
def wiki_propose_page(
    namespace: str,
    body: str,
    bucket_id: str,
    project_id: str | None = None,
    page_id: str | None = None,
    title: str | None = None,
    abbrev: str | None = None,
    expansion: str | None = None,
    source_ids: list[str] | None = None,
    actor: str | None = None,
    agent_name: str | None = None,
    agent_run_id: str | None = None,
) -> dict:
    who = _agent(
        {
            "actor": actor,
            "agent_name": agent_name,
            "agent_run_id": agent_run_id,
            "project_id": project_id,
        }
    )
    try:
        return svc.propose_page(
            who,
            ProposePageIn(
                page_id=page_id,
                namespace=namespace,
                project_id=project_id,
                bucket_id=bucket_id,
                title=title,
                abbrev=abbrev,
                expansion=expansion,
                body=body,
                source_ids=source_ids or [],
            ),
        ).model_dump()
    except WikiError as exc:
        return _dump(exc)


@mcp.tool(name="wiki.approve_page")
def wiki_approve_page(page_id: str, version: str | None = None) -> dict:
    return {
        "code": "COMMON_PERMISSION_DENIED",
        "message": "wiki.approve_page is not granted to agents",
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

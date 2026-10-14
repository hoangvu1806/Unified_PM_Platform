from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from wiki.llm_config import build_sorter, load_dotenv
from wiki.models import Actor, ProposePageIn, SearchQuery, WikiError
from wiki.paths import MVP_ROOT, templates_dir
from wiki.service import WikiService
from wiki.sim import bootstrap_ssot, reset_sim_pages, sim_state

load_dotenv()

app = FastAPI(title="Wiki Knowledge MVP", version="0.1.0")
templates = Jinja2Templates(directory=str(templates_dir()))


@lru_cache(maxsize=1)
def default_service() -> WikiService:
    return WikiService(MVP_ROOT, sorter=build_sorter())


def get_service() -> WikiService:
    return default_service()


def raise_wiki(exc: WikiError) -> None:
    raise HTTPException(
        status_code=exc.http_status,
        detail=exc.as_dict(),
    ) from exc


def actor_from_headers(
    x_actor: Annotated[str, Header()] = "ba.lead",
    x_actor_type: Annotated[str, Header()] = "human",
    x_project_id: Annotated[str | None, Header()] = None,
    x_agent_run_id: Annotated[str | None, Header()] = None,
    x_agent_name: Annotated[str | None, Header()] = None,
) -> Actor:
    if x_actor_type not in {"human", "agent"}:
        raise HTTPException(
            status_code=400,
            detail={"code": "COMMON_SCHEMA_INVALID", "message": "X-Actor-Type must be human or agent"},
        )
    return Actor(
        actor=x_actor,
        actor_type=x_actor_type,  # type: ignore[arg-type]
        project_id=x_project_id,
        agent_run_id=x_agent_run_id,
        agent_name=x_agent_name,
    )


class ApproveBody(BaseModel):
    actor: str | None = None
    version: str | None = None


class ProposeBody(ProposePageIn):
    pass


@app.exception_handler(WikiError)
async def wiki_error_handler(_request: Request, exc: WikiError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content=exc.as_dict())


@app.get("/sim", response_class=HTMLResponse)
def sim_home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "sim.html", {})


@app.get("/sim/state")
def sim_get_state(svc: WikiService = Depends(get_service)) -> dict:
    return sim_state(svc)


@app.post("/sim/bootstrap")
def sim_bootstrap(
    svc: WikiService = Depends(get_service),
) -> dict:
    return bootstrap_ssot(svc)


@app.post("/sim/reset")
def sim_reset(svc: WikiService = Depends(get_service)) -> dict:
    return reset_sim_pages(svc)


@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    svc: WikiService = Depends(get_service),
    notice: str | None = None,
) -> HTMLResponse:
    drafts = svc.list_pages(status="draft") + svc.list_pages(status="proposed")
    approved = svc.list_pages(status="approved")
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "drafts": drafts,
            "approved": approved,
            "hits": None,
            "query": "",
            "notice": notice,
        },
    )


@app.post("/ui/reset")
def ui_reset(
    request: Request,
    svc: WikiService = Depends(get_service),
):
    info = svc.reset_store()
    return home(
        request,
        svc,
        notice=f"Wiki cleared ({info['removed_blobs']} blobs removed). Upload lại để so sánh.",
    )


@app.post("/ui/upload")
async def ui_upload(
    request: Request,
    file: UploadFile = File(...),
    namespace: str = Form("project"),
    project_id: str = Form("PRJ-MES-01"),
    actor: str = Form("ba.lead"),
    sort_mode: str = Form("both"),
    svc: WikiService = Depends(get_service),
):
    human = Actor(actor=actor, actor_type="human", project_id=project_id or None)
    data = await file.read()
    mode = (sort_mode or "both").strip().lower()
    if mode not in {"heuristic", "llm", "auto", "both"}:
        mode = "both"
    try:
        result = svc.ingest_source(
            human,
            filename=file.filename or "upload.pdf",
            data=data,
            namespace=namespace,
            project_id=project_id or None,
            sort_mode=mode,
        )
    except WikiError as exc:
        raise_wiki(exc)
    backend = result.get("sort_backend") or result.get("sort_status")
    n = len(result.get("proposed_page_ids") or [])
    return home(
        request,
        svc,
        notice=f"Ingest OK — sort={backend}, drafts+={n}, source={result.get('source_id')}",
    )


@app.post("/ui/approve/{page_id}")
def ui_approve(
    page_id: str,
    request: Request,
    actor: str = Form("ba.lead"),
    project_id: str = Form("PRJ-MES-01"),
    svc: WikiService = Depends(get_service),
):
    human = Actor(actor=actor, actor_type="human", project_id=project_id or None)
    try:
        svc.approve_page(human, page_id)
    except WikiError as exc:
        raise_wiki(exc)
    return home(request, svc)


@app.post("/ui/search")
def ui_search(
    request: Request,
    query: str = Form(""),
    namespace: str = Form("project"),
    project_id: str = Form("PRJ-MES-01"),
    bucket_id: str = Form(""),
    actor: str = Form("ba.lead"),
    svc: WikiService = Depends(get_service),
):
    human = Actor(actor=actor, actor_type="human", project_id=project_id or None)
    try:
        hits = svc.search_pages(
            human,
            SearchQuery(
                query=query,
                namespace=namespace,
                project_id=project_id or None,
                bucket_id=bucket_id or None,
                status="approved",
                limit=10,
            ),
        )
    except WikiError as exc:
        raise_wiki(exc)
    drafts = svc.list_pages(status="draft") + svc.list_pages(status="proposed")
    approved = svc.list_pages(status="approved")
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "drafts": drafts,
            "approved": approved,
            "hits": hits,
            "query": query,
            "notice": None,
        },
    )


@app.post("/v1/wiki/sources")
async def post_sources(
    file: UploadFile = File(...),
    namespace: str = Form(...),
    project_id: str | None = Form(None),
    actor: str = Form("ba.lead"),
    x_actor: Annotated[str | None, Header()] = None,
    x_actor_type: Annotated[str, Header()] = "human",
    x_project_id: Annotated[str | None, Header()] = None,
    x_agent_run_id: Annotated[str | None, Header()] = None,
    x_agent_name: Annotated[str | None, Header()] = None,
    svc: WikiService = Depends(get_service),
):
    who = Actor(
        actor=x_actor or actor,
        actor_type=x_actor_type,  # type: ignore[arg-type]
        project_id=x_project_id or project_id,
        agent_run_id=x_agent_run_id,
        agent_name=x_agent_name,
    )
    data = await file.read()
    try:
        return svc.ingest_source(
            who,
            filename=file.filename or "upload.pdf",
            data=data,
            namespace=namespace,
            project_id=project_id,
        )
    except WikiError as exc:
        raise_wiki(exc)


@app.get("/v1/wiki/sources/{source_id}")
def get_source(
    source_id: str,
    actor: Actor = Depends(actor_from_headers),
    svc: WikiService = Depends(get_service),
):
    try:
        return svc.get_source(actor, source_id).model_dump()
    except WikiError as exc:
        raise_wiki(exc)


@app.get("/v1/wiki/pages")
def get_pages(
    namespace: str = Query(...),
    query: str = Query(""),
    project_id: str | None = Query(None),
    bucket_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(5),
    actor: Actor = Depends(actor_from_headers),
    svc: WikiService = Depends(get_service),
):
    try:
        hits = svc.search_pages(
            actor,
            SearchQuery(
                query=query,
                namespace=namespace,
                project_id=project_id or actor.project_id,
                bucket_id=bucket_id,
                status=status,
                limit=limit,
            ),
        )
        return {"hits": [h.model_dump() for h in hits]}
    except WikiError as exc:
        raise_wiki(exc)


@app.get("/v1/wiki/pages/{page_id}")
def get_page(
    page_id: str,
    version: str | None = Query(None),
    actor: Actor = Depends(actor_from_headers),
    svc: WikiService = Depends(get_service),
):
    try:
        return svc.fetch_page(actor, page_id, version).model_dump()
    except WikiError as exc:
        raise_wiki(exc)


@app.post("/v1/wiki/pages")
def post_page(
    body: ProposeBody,
    actor: Actor = Depends(actor_from_headers),
    svc: WikiService = Depends(get_service),
):
    try:
        return svc.propose_page(actor, body).model_dump()
    except WikiError as exc:
        raise_wiki(exc)


@app.post("/v1/wiki/pages/{page_id}/approve")
def post_approve(
    page_id: str,
    body: ApproveBody | None = None,
    actor: Actor = Depends(actor_from_headers),
    svc: WikiService = Depends(get_service),
):
    if actor.actor_type == "agent":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "COMMON_PERMISSION_DENIED",
                "message": "wiki.approve_page is not granted to agents",
            },
        )
    if body and body.actor:
        actor = actor.model_copy(update={"actor": body.actor})
    try:
        return svc.approve_page(actor, page_id, body.version if body else None).model_dump()
    except WikiError as exc:
        raise_wiki(exc)


@app.post("/v1/wiki/pages/{page_id}/demote")
def post_demote(
    page_id: str,
    body: ApproveBody | None = None,
    actor: Actor = Depends(actor_from_headers),
    svc: WikiService = Depends(get_service),
):
    """Human-only: approved → draft (hides from BA/VA until re-approved)."""
    if actor.actor_type == "agent":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "COMMON_PERMISSION_DENIED",
                "message": "wiki.demote_page is not granted to agents",
            },
        )
    if body and body.actor:
        actor = actor.model_copy(update={"actor": body.actor})
    try:
        return svc.demote_page(actor, page_id).model_dump()
    except WikiError as exc:
        raise_wiki(exc)


@app.delete("/v1/wiki/pages/{page_id}")
def delete_page(
    page_id: str,
    actor: Actor = Depends(actor_from_headers),
    svc: WikiService = Depends(get_service),
):
    """Human-only hard delete of one page."""
    if actor.actor_type == "agent":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "COMMON_PERMISSION_DENIED",
                "message": "wiki.delete_page is not granted to agents",
            },
        )
    try:
        return svc.delete_page(actor, page_id)
    except WikiError as exc:
        raise_wiki(exc)


@app.post("/ui/demote/{page_id}")
def ui_demote(
    page_id: str,
    request: Request,
    actor: str = Form("ba.lead"),
    project_id: str = Form("PRJ-MES-01"),
    svc: WikiService = Depends(get_service),
):
    human = Actor(actor=actor, actor_type="human", project_id=project_id or None)
    try:
        svc.demote_page(human, page_id)
    except WikiError as exc:
        raise_wiki(exc)
    return home(request, svc, notice=f"Demoted {page_id} → draft. Re-Validate BA after removing the violator.")


@app.post("/ui/delete/{page_id}")
def ui_delete(
    page_id: str,
    request: Request,
    actor: str = Form("ba.lead"),
    project_id: str = Form("PRJ-MES-01"),
    svc: WikiService = Depends(get_service),
):
    human = Actor(actor=actor, actor_type="human", project_id=project_id or None)
    try:
        svc.delete_page(human, page_id)
    except WikiError as exc:
        raise_wiki(exc)
    return home(request, svc, notice=f"Deleted {page_id}. Re-Validate BA after removing the violator.")


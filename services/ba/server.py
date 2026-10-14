"""BA Agent — FastAPI Backend Service (Entry Point).

Assembles the application by mounting routers from ``managers/service/``
and initializing the ADK runtime via ``managers/runner_context``.

Endpoints are defined in:
- ``managers/service/api.py``      — V1 Chat (sync + SSE)
- ``managers/service/features.py`` — Feature CRUD + Chat History
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv()

from platform_core.logs import RequestLogMiddleware, setup_logging  # noqa: E402

setup_logging("ba-api")

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config.base_config import settings
from config.llm_resolve import resolve_llm_endpoint
from managers.database.connection import SessionLocal
from managers.runner_context import get_runner, init_adk
from managers.service import chat_router, features_router, va_router, wiki_router
from managers.service.access import ba_access

logger = logging.getLogger(__name__)


# ── Application Lifespan ─────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — init ADK on startup."""
    from platform_core.settings import startup_report

    startup_report("ba-api")
    await init_adk()
    yield
    logger.info("Shutting down BA Agent server")


# ── FastAPI App ───────────────────────────────────────────────

app = FastAPI(
    title="BA Agent API",
    version="0.1.0",
    docs_url="/docs" if settings.swagger_enabled else None,
    lifespan=lifespan,
)

app.add_middleware(RequestLogMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Platform: every BA route needs a logged-in user; routes with {session_id}
# are also checked against the feature's project (managers/service/access.py).
_ba_guard = [Depends(ba_access)]
app.include_router(chat_router, dependencies=_ba_guard)
app.include_router(features_router, dependencies=_ba_guard)
app.include_router(wiki_router, dependencies=_ba_guard)
app.include_router(va_router, dependencies=_ba_guard)


# ── Health Check ──────────────────────────────────────────────


async def _llm_endpoint_ready() -> bool:
    """LiteLLM /health/readiness, or company-gate /v1/models when no proxy."""
    endpoint = resolve_llm_endpoint()
    base = endpoint.api_base_url.rstrip("/")
    proxy_root = base.removesuffix("/v1")
    headers = {}
    if endpoint.api_key:
        headers["Authorization"] = f"Bearer {endpoint.api_key}"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{proxy_root}/health/readiness", headers=headers)
            if response.status_code == 200:
                return True
            models = await client.get(f"{base}/models", headers=headers)
            return models.status_code == 200
    except Exception:  # noqa: BLE001
        return False


@app.get("/api/health")
async def health_check():
    """Demo is ready when ADK and Postgres are up. LLM is diagnostic only."""
    try:
        runner = get_runner()
        adk_ready = runner is not None
    except Exception:  # noqa: BLE001
        adk_ready = False

    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        database_ready = True
    except Exception:  # noqa: BLE001
        database_ready = False

    llm_proxy_ready = await _llm_endpoint_ready()
    endpoint = resolve_llm_endpoint()

    # Chat still needs an LLM, but a down company-gate / missing LiteLLM image
    # must not take the manager, wiki, or feature CRUD down with it.
    ready = adk_ready and database_ready
    payload = {
        "status": "ok" if ready else "not_ready",
        "app": "ba-agent",
        "adk_ready": adk_ready,
        "database_ready": database_ready,
        "llm_proxy_ready": llm_proxy_ready,
        "llm_provider": endpoint.provider,
        "llm_endpoint": endpoint.api_base_url,
    }
    return JSONResponse(payload, status_code=200 if ready else 503)

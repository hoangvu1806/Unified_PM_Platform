import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from platform_core.logs import RequestLogMiddleware, setup_logging
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.access import designer_access, handoff_secret
from .api.routes import router
from .api.handoff_routes import router as handoff_router
from .api.screens import router as screens_router
from .api.stream import EventStream
from .core.config import get_settings
from .core.errors import AppError
from .core.llm import AdkProvider
from .core.prompts import PromptLibrary
from .models import Problem
from .render import Renderer
from .storage.store import Store
from .workflow.service import RunService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # Keep the loaded configuration observable without ever logging the secret.
    # This makes stale-process/configuration problems diagnosable from startup logs.
    import logging

    logging.getLogger("designer_agent.config").info(
        "LLM config loaded: model=%s designer=%s base_url=%s api_key=%s (fingerprint=%s)",
        settings.llm_model,
        settings.effective_designer_model,
        settings.cleaned_base_url,
        settings.masked_api_key,
        settings.api_key_fingerprint,
    )
    from platform_core.settings import startup_report

    startup_report("designer-api")
    store = Store(settings.postgres_dsn)
    await store.initialize()
    interrupted = await store.interrupt_unfinished_runs()
    if interrupted:
        logging.getLogger("designer_agent.runs").warning("Marked %s interrupted run(s) as retryable", interrupted)
    events = EventStream(store)
    llm = AdkProvider(settings)
    runs = RunService(store, events, llm, PromptLibrary())
    app.state.settings = settings
    app.state.store = store
    app.state.events = events
    app.state.runs = runs
    app.state.llm = llm
    # Chromium starts on the first render, so the API is up even before a browser is needed.
    app.state.renderer = Renderer()

    # Pre-warm LLM connection in background so the first message is fast
    asyncio.create_task(llm.prewarm())

    yield
    await runs.shutdown()
    await app.state.renderer.close()
    await store.close()


def create_app() -> FastAPI:
    setup_logging("designer-api")
    settings = get_settings()
    app = FastAPI(
        title="Agentic Designer API",
        version="2.0.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(RequestLogMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Platform: users must log in and are checked against the session's
    # project; BA -> Designer handoffs authenticate with X-Agent-Secret.
    app.include_router(router, dependencies=[Depends(designer_access)])
    app.include_router(screens_router, dependencies=[Depends(designer_access)])
    app.include_router(handoff_router, dependencies=[Depends(handoff_secret)])

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, error: AppError) -> JSONResponse:
        problem = Problem(
            code=error.code,
            title=error.title,
            detail=error.detail,
            retryable=error.retryable,
            action=error.action,
        )
        return JSONResponse(
            status_code=error.status_code,
            content=problem.model_dump(),
            media_type="application/problem+json",
        )

    return app


app = create_app()

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from platform_core.auth import get_auth_settings

from .db import close_pool, open_pool
from .routes import private, public
from .seed import seed_demo

logger = logging.getLogger("core-api")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_auth_settings()
    if settings.auth_mode == "mock" and len(settings.auth_jwt_secret) < 32:
        raise RuntimeError("AUTH_JWT_SECRET must be at least 32 characters")
    open_pool()
    if settings.auth_mode == "mock":
        seed_demo()
        logger.info("Mock auth: demo users and projects seeded")
    yield
    close_pool()


app = FastAPI(
    title="Platform Core API",
    version="0.1.0",
    docs_url="/api/core/docs",
    openapi_url="/api/core/openapi.json",
    lifespan=lifespan,
)
app.include_router(public)
app.include_router(private)

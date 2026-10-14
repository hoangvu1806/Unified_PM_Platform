"""Postgres connection helpers: one database, one schema per service.

Every service connects to the same ``POSTGRES_DB`` with ``search_path`` set to
its own schema, so existing SQL keeps unqualified table names (``sessions``,
``ba_packages``...) while tables never collide across services.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from platform_core.settings import CommonSettings, get_common_settings

SCHEMAS = ("core", "ba", "designer", "wiki")

_DRIVERS = {
    "asyncpg": "postgresql+asyncpg",
    "psycopg2": "postgresql+psycopg2",
    "psycopg": "postgresql+psycopg",
    "libpq": "postgresql",
}


def _check_schema(schema: str) -> None:
    if schema not in SCHEMAS:
        raise ValueError(f"unknown schema {schema!r}; expected one of {SCHEMAS}")


def database_url(
    schema: str,
    driver: str = "psycopg2",
    settings: CommonSettings | None = None,
) -> str:
    """SQLAlchemy/libpq URL for ``schema``.

    Sync drivers (psycopg2, psycopg, libpq) carry ``search_path`` in the URL
    ``options`` parameter. asyncpg ignores that parameter, so callers must also
    pass :func:`engine_kwargs` to ``create_async_engine``.
    """
    _check_schema(schema)
    s = settings or get_common_settings()
    scheme = _DRIVERS[driver]
    user = urllib.parse.quote_plus(s.postgres_user)
    password = urllib.parse.quote_plus(s.postgres_password)
    url = f"{scheme}://{user}:{password}@{s.postgres_host}:{s.postgres_port}/{s.postgres_db}"
    if driver != "asyncpg":
        url += "?options=" + urllib.parse.quote(f"-csearch_path={schema}")
    return url


def engine_kwargs(schema: str, driver: str = "asyncpg") -> dict[str, Any]:
    """Extra ``create_engine``/``create_async_engine`` kwargs pinning ``search_path``."""
    _check_schema(schema)
    if driver == "asyncpg":
        return {"connect_args": {"server_settings": {"search_path": schema}}}
    return {}


def ensure_schemas(settings: CommonSettings | None = None) -> None:
    """Create every platform schema if missing (idempotent, safe at startup)."""
    import psycopg2

    conn = psycopg2.connect(database_url("core", "libpq", settings))
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            for schema in SCHEMAS:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    finally:
        conn.close()

"""Connection pool pinned to schema ``core``."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from platform_core.db import database_url
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .schema import SCHEMA

_pool: ConnectionPool | None = None


def open_pool() -> None:
    global _pool
    with Connection.connect(database_url("core", "libpq"), autocommit=True) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS core")
        conn.execute("SET search_path TO core")
        conn.execute(SCHEMA)
    _pool = ConnectionPool(
        database_url("core", "libpq"), min_size=1, max_size=10, kwargs={"row_factory": dict_row}, open=True
    )


def close_pool() -> None:
    if _pool is not None:
        _pool.close()


@contextmanager
def connection() -> Iterator[Connection]:
    assert _pool is not None, "pool not opened"
    with _pool.connection() as conn:
        yield conn

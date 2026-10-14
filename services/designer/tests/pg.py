"""Postgres helpers for tests: each Store gets a throwaway schema."""

from uuid import uuid4

from app.storage.store import Store

TEST_SCHEMA_PREFIX = "designer_test_"


def pg_test_dsn() -> str:
    from platform_core.db import database_url

    return database_url("designer", "libpq")


def make_test_store() -> Store:
    return Store(pg_test_dsn(), schema=f"{TEST_SCHEMA_PREFIX}{uuid4().hex[:12]}", max_size=2)

"""Platform: the wiki store is Postgres (schema per test), files in a temp storage root."""

from __future__ import annotations

import os
import uuid

import pytest


@pytest.fixture(autouse=True)
def isolated_wiki_store(monkeypatch: pytest.MonkeyPatch, tmp_path):
    schema = f"wiki_test_{uuid.uuid4().hex[:12]}"
    monkeypatch.setenv("WIKI_DB_SCHEMA", schema)
    monkeypatch.setenv("STORAGE_LOCAL_ROOT", str(tmp_path / "storage"))
    yield
    try:
        import psycopg2

        from factory_wiki.paths import ensure_mvp_importable

        ensure_mvp_importable()
        from wiki.db import dsn

        conn = psycopg2.connect(dsn())
        conn.autocommit = True
        try:
            conn.cursor().execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        finally:
            conn.close()
    except Exception:
        if os.environ.get("POSTGRES_HOST"):
            raise

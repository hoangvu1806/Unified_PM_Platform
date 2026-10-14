"""Wiki store on the shared platform Postgres (schema ``wiki``).

The MVP was written against ``sqlite3``. To keep ``wiki.service`` and the BA
adapter (``factory_wiki``) unchanged, :func:`connect` returns a small
sqlite3-compatible wrapper around a psycopg2 connection:

* ``?`` placeholders become ``%s``; ``ifnull(`` becomes ``COALESCE(``;
* ``LIKE`` becomes ``ILIKE`` — SQLite's LIKE is case-insensitive, Postgres'
  is not, and wiki search must keep returning the same hits;
* ``PRAGMA`` statements are no-ops;
* rows support ``row["col"]``, ``row[0]``, ``row.keys()`` and ``dict(row)``;
* ``isolation_level = None`` switches to autocommit, like sqlite3.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
from pathlib import Path
from typing import Any, Iterable, Sequence

import psycopg2
import psycopg2.extensions

SCHEMA = """
CREATE TABLE IF NOT EXISTS wiki_source (
  source_id TEXT PRIMARY KEY,
  filename TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  namespace TEXT NOT NULL,
  project_id TEXT,
  storage_uri TEXT NOT NULL,
  markdown_extract TEXT NOT NULL,
  page_map TEXT NOT NULL DEFAULT '[]',
  ingested_at TEXT NOT NULL,
  ingested_by TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_wiki_source_sha_scope
  ON wiki_source(sha256, namespace, COALESCE(project_id, ''));

CREATE TABLE IF NOT EXISTS wiki_page (
  page_id TEXT PRIMARY KEY,
  namespace TEXT NOT NULL,
  project_id TEXT,
  bucket_id TEXT NOT NULL,
  title TEXT NOT NULL,
  abbrev TEXT,
  expansion TEXT,
  disambiguation TEXT,
  status TEXT NOT NULL,
  version TEXT NOT NULL,
  body TEXT NOT NULL,
  source_ids TEXT NOT NULL DEFAULT '[]',
  owner TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wiki_revision (
  revision_id TEXT PRIMARY KEY,
  page_id TEXT NOT NULL REFERENCES wiki_page(page_id),
  version TEXT NOT NULL,
  status TEXT NOT NULL,
  body_snapshot TEXT NOT NULL,
  diff_ref TEXT,
  actor TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY,
  ts TEXT NOT NULL,
  operation TEXT NOT NULL,
  actor TEXT NOT NULL,
  actor_type TEXT NOT NULL,
  project_id TEXT,
  agent_run_id TEXT,
  extra TEXT NOT NULL DEFAULT '{}'
);
"""

TABLES = ("wiki_revision", "wiki_page", "wiki_source", "audit_log")


def schema_name() -> str:
    name = os.environ.get("WIKI_DB_SCHEMA", "wiki").strip() or "wiki"
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", name):
        raise ValueError(f"invalid WIKI_DB_SCHEMA {name!r}")
    return name


def dsn() -> str:
    env = os.environ
    user = urllib.parse.quote_plus(env.get("POSTGRES_USER", "platform"))
    password = urllib.parse.quote_plus(env.get("POSTGRES_PASSWORD", ""))
    host = env.get("POSTGRES_HOST", "localhost")
    port = env.get("POSTGRES_PORT", "5432")
    db = env.get("POSTGRES_DB", "platform")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


_PLACEHOLDER = re.compile(r"\?")
_IFNULL = re.compile(r"\bifnull\(", re.IGNORECASE)
_LIKE = re.compile(r"(?<![A-Za-z_])LIKE(?![A-Za-z_])", re.IGNORECASE)


def translate(sql: str, has_params: bool) -> str:
    sql = _IFNULL.sub("COALESCE(", sql)
    sql = _LIKE.sub("ILIKE", sql)
    if has_params:
        sql = sql.replace("%", "%%")
        sql = _PLACEHOLDER.sub("%s", sql)
    return sql


class Row(dict):
    """dict row that also answers ``row[0]`` like sqlite3.Row."""

    def __init__(self, columns: Sequence[str], values: Sequence[Any]) -> None:
        super().__init__(zip(columns, values))
        self._values = tuple(values)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


class Cursor:
    def __init__(self, cursor: psycopg2.extensions.cursor) -> None:
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    def _columns(self) -> list[str]:
        return [d[0] for d in (self._cursor.description or [])]

    def fetchone(self) -> Row | None:
        if self._cursor.description is None:
            return None
        values = self._cursor.fetchone()
        return Row(self._columns(), values) if values is not None else None

    def fetchall(self) -> list[Row]:
        if self._cursor.description is None:
            return []
        cols = self._columns()
        return [Row(cols, values) for values in self._cursor.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class Connection:
    """The subset of ``sqlite3.Connection`` used by wiki.service and factory_wiki."""

    def __init__(self, raw: psycopg2.extensions.connection) -> None:
        self._raw = raw

    @property
    def isolation_level(self) -> str | None:
        return None if self._raw.autocommit else "DEFERRED"

    @isolation_level.setter
    def isolation_level(self, value: str | None) -> None:
        if self._raw.status != psycopg2.extensions.STATUS_READY:
            self._raw.commit()
        self._raw.autocommit = value is None

    def execute(self, sql: str, params: Iterable[Any] | None = None) -> Cursor:
        cursor = self._raw.cursor()
        if sql.lstrip().upper().startswith("PRAGMA"):
            return Cursor(cursor)
        args = tuple(params) if params is not None else ()
        cursor.execute(translate(sql, bool(args)), args or None)
        return Cursor(cursor)

    def executescript(self, script: str) -> None:
        self._raw.cursor().execute(script)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()


_initialized: set[str] = set()


def connect(root: Path | None = None) -> Connection:
    """Open a wiki connection. ``root`` is kept for API compatibility (manifest)."""
    schema = schema_name()
    raw = psycopg2.connect(dsn(), options=f"-csearch_path={schema}")
    if schema not in _initialized:
        raw.autocommit = True
        with raw.cursor() as cur:
            # Serialize first-time DDL across processes (concurrent CREATE races).
            cur.execute("SELECT pg_advisory_lock(hashtext('wiki-schema-init'))")
            try:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
                cur.execute(f'SET search_path TO "{schema}"')
                cur.execute(SCHEMA)
            finally:
                cur.execute("SELECT pg_advisory_unlock(hashtext('wiki-schema-init'))")
        _initialized.add(schema)
    raw.autocommit = False
    return Connection(raw)


def row_to_dict(row: Row | None) -> dict | None:
    if row is None:
        return None
    data = dict(row)
    for key in ("page_map", "source_ids"):
        if key in data and isinstance(data[key], str):
            data[key] = json.loads(data[key])
    return data

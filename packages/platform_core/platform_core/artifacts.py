"""Project Assets: published artifacts registered in ``core.artifacts`` (Sprint 4).

Only metadata lives here; bytes are in platform storage under ``storage_key``.

* ``ba_package``      — one row per content version of a BA feature
  (``source_ref`` = BA session id).
* ``designer_output`` — a finished Designer run's .fig
  (``source_ref`` = run id, ``version`` = run revision), with
  ``derived_from`` = the BA package version it was designed from.

A design is *stale* when a newer version of the BA package it derives from
exists (computed on read, no background job).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from platform_core.db import database_url

DDL = """
CREATE TABLE IF NOT EXISTS core.artifacts (
  id               TEXT PRIMARY KEY,
  project_id       TEXT NOT NULL REFERENCES core.projects(id),
  kind             TEXT NOT NULL,
  source_module    TEXT NOT NULL,
  source_ref       TEXT NOT NULL,
  version          INTEGER NOT NULL,
  title            TEXT NOT NULL,
  storage_key      TEXT,
  content_hash     TEXT,
  derived_from_id  TEXT REFERENCES core.artifacts(id),
  meta             JSONB NOT NULL DEFAULT '{}',
  created_by       TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (kind, source_ref, version)
);
CREATE INDEX IF NOT EXISTS idx_artifacts_project ON core.artifacts(project_id, kind);
"""

KINDS = ("ba_package", "bpmn", "ui_spec", "designer_output")


_schema_ready = False


def _raw_connect():
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(database_url("core", "libpq"), row_factory=dict_row)


def ensure_schema() -> None:
    global _schema_ready
    with _raw_connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('core-artifacts-ddl'))")
        conn.execute(DDL)
    _schema_ready = True


def _connect():
    # BA/Designer may publish before core-api has created the table.
    if not _schema_ready:
        ensure_schema()
    return _raw_connect()


def latest(kind: str, source_ref: str) -> dict[str, Any] | None:
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM core.artifacts WHERE kind=%s AND source_ref=%s ORDER BY version DESC LIMIT 1",
            (kind, source_ref),
        ).fetchone()


def register(
    *,
    project_id: str,
    kind: str,
    source_module: str,
    source_ref: str,
    title: str,
    storage_key: str | None = None,
    content_hash: str | None = None,
    version: int | None = None,
    derived_from_id: str | None = None,
    meta: dict[str, Any] | None = None,
    created_by: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Insert a new artifact version. Returns (row, created).

    With ``version=None`` the next version is allocated, unless the latest
    version has the same ``content_hash`` (re-export of unchanged content).
    With an explicit ``version`` the call is idempotent on (kind, source_ref, version).
    """
    if kind not in KINDS:
        raise ValueError(f"unknown artifact kind {kind!r}")
    with _connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{kind}:{source_ref}",))
        last = conn.execute(
            "SELECT * FROM core.artifacts WHERE kind=%s AND source_ref=%s ORDER BY version DESC LIMIT 1",
            (kind, source_ref),
        ).fetchone()
        if version is None:
            if last and content_hash and last["content_hash"] == content_hash:
                return last, False
            version = (last["version"] + 1) if last else 1
        else:
            same = conn.execute(
                "SELECT * FROM core.artifacts WHERE kind=%s AND source_ref=%s AND version=%s",
                (kind, source_ref, version),
            ).fetchone()
            if same:
                return same, False
        row = conn.execute(
            """
            INSERT INTO core.artifacts (id, project_id, kind, source_module, source_ref, version, title,
                                        storage_key, content_hash, derived_from_id, meta, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *
            """,
            (
                f"ART-{uuid.uuid4().hex[:12].upper()}", project_id, kind, source_module, source_ref, version,
                title, storage_key, content_hash, derived_from_id, json.dumps(meta or {}), created_by,
            ),
        ).fetchone()
        return row, True


def update(
    artifact_id: str,
    *,
    storage_key: str | None = None,
    content_hash: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Refresh one version in place: new file / hash, and ``meta`` keys merged in."""
    with _connect() as conn:
        return conn.execute(
            """
            UPDATE core.artifacts
               SET storage_key = COALESCE(%s, storage_key),
                   content_hash = COALESCE(%s, content_hash),
                   meta = COALESCE(meta, '{}'::jsonb) || %s::jsonb
             WHERE id = %s RETURNING *
            """,
            (storage_key, content_hash, json.dumps(meta or {}), artifact_id),
        ).fetchone()


def list_for_project(project_id: str) -> list[dict[str, Any]]:
    """Artifacts of a project, newest first, with ``stale`` / ``latest_version``."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT a.*,
                   (SELECT max(x.version) FROM core.artifacts x
                     WHERE x.kind = a.kind AND x.source_ref = a.source_ref) AS latest_version,
                   src.kind AS derived_kind, src.version AS derived_version, src.title AS derived_title,
                   (SELECT max(y.version) FROM core.artifacts y
                     WHERE y.kind = src.kind AND y.source_ref = src.source_ref) AS derived_latest_version
            FROM core.artifacts a
            LEFT JOIN core.artifacts src ON src.id = a.derived_from_id
            WHERE a.project_id = %s
            ORDER BY a.created_at DESC
            """,
            (project_id,),
        ).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        r["created_at"] = r["created_at"].isoformat()
        r["stale"] = bool(r["derived_from_id"]) and (r["derived_latest_version"] or 0) > (r["derived_version"] or 0)
        out.append(r)
    return out


def get(artifact_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        return conn.execute("SELECT * FROM core.artifacts WHERE id=%s", (artifact_id,)).fetchone()

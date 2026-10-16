"""Assign pre-platform data to a project, then enforce project foreign keys.

    docker compose exec core-api python -m app.legacy

Idempotent. Rows without ``project_id`` (created before Sprint 3) go to
``PRJ-LEGACY``; every seeded user becomes a member so nothing disappears.
Wiki pages scoped to the old per-feature id (``PRJ-<sha256(session)>``) follow
the feature they belonged to. Foreign keys are added afterwards, so new rows
can only reference real projects.
"""

from __future__ import annotations

import hashlib
import logging

from platform_core.db import database_url
from psycopg import Connection

from .seed import seed_users

LEGACY_ID = "PRJ-LEGACY"
log = logging.getLogger("legacy")

FOREIGN_KEYS = [
    ("ba.ba_packages", "fk_ba_packages_project"),
    ("ba.designer_handoffs", "fk_ba_handoffs_project"),
    ("designer.sessions", "fk_designer_sessions_project"),
]


def _exists(conn: Connection, table: str) -> bool:
    return conn.execute("SELECT to_regclass(%s) IS NOT NULL", (table,)).fetchone()[0]


def _has_column(conn: Connection, table: str, column: str) -> bool:
    schema, name = table.split(".")
    return bool(
        conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_schema=%s AND table_name=%s AND column_name=%s",
            (schema, name, column),
        ).fetchone()
    )


def run() -> dict[str, int]:
    report: dict[str, int] = {}
    with Connection.connect(database_url("core", "libpq")) as conn:
        conn.execute(
            "INSERT INTO core.projects (id, name, description) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (LEGACY_ID, "Legacy", "Data created before projects existed"),
        )
        for uid, *_rest in seed_users():
            conn.execute(
                "INSERT INTO core.project_members (project_id, user_id, project_role) "
                "SELECT %s, id, 'ADMIN' FROM core.users WHERE id=%s ON CONFLICT DO NOTHING",
                (LEGACY_ID, uid),
            )
            for role in ("BA", "DESIGNER"):
                conn.execute(
                    "INSERT INTO core.project_members (project_id, user_id, project_role) "
                    "SELECT %s, id, %s FROM core.users WHERE id=%s ON CONFLICT DO NOTHING",
                    (LEGACY_ID, role, uid),
                )

        for table in ("ba.ba_packages", "ba.designer_handoffs", "designer.sessions"):
            if _exists(conn, table) and _has_column(conn, table, "project_id"):
                cur = conn.execute(
                    f"UPDATE {table} SET project_id=%s "
                    "WHERE project_id IS NULL OR project_id NOT IN (SELECT id FROM core.projects)",
                    (LEGACY_ID,),
                )
                report[table] = cur.rowcount

        if _exists(conn, "wiki.wiki_page"):
            mapping: dict[str, str] = {}
            if _exists(conn, "ba.ba_packages"):
                for session_id, project_id in conn.execute(
                    "SELECT session_id, project_id FROM ba.ba_packages"
                ).fetchall():
                    old = "PRJ-" + hashlib.sha256(str(session_id).encode()).hexdigest()[:12].upper()
                    mapping[old] = project_id
            moved = 0
            for table in ("wiki.wiki_page", "wiki.wiki_source"):
                rows = conn.execute(
                    f"SELECT DISTINCT project_id FROM {table} "
                    "WHERE namespace='project' AND project_id IS NOT NULL "
                    "AND project_id NOT IN (SELECT id FROM core.projects)"
                ).fetchall()
                for (old,) in rows:
                    cur = conn.execute(
                        f"UPDATE {table} SET project_id=%s WHERE namespace='project' AND project_id=%s",
                        (mapping.get(old, LEGACY_ID), old),
                    )
                    moved += cur.rowcount
            report["wiki"] = moved

        for table, name in FOREIGN_KEYS:
            if not (_exists(conn, table) and _has_column(conn, table, "project_id")):
                continue
            present = conn.execute(
                "SELECT 1 FROM pg_constraint WHERE conname=%s", (name,)
            ).fetchone()
            if not present:
                conn.execute(
                    f"ALTER TABLE {table} ADD CONSTRAINT {name} "
                    "FOREIGN KEY (project_id) REFERENCES core.projects(id)"
                )
                report[f"fk:{table}"] = 1
        conn.commit()
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run())

"""Wipe all run data for a clean end-to-end test (keeps user accounts).

    docker compose exec -T core-api python - --yes < scripts/reset_platform_data.py

Deletes: projects + members + artifacts (core), BA features / chat (ba),
Designer sessions / runs (designer), wiki pages and sources (wiki), and every
object in the platform bucket (projects/, shared/). Demo projects are seeded
again when core-api restarts (AUTH_MODE=mock).
"""

import sys

import psycopg
from platform_core.db import database_url
from platform_core.storage import get_storage

if "--yes" not in sys.argv:
    raise SystemExit("refusing to wipe without --yes")

TABLES = {
    "core": ["artifacts", "project_members", "projects"],
    "ba": [
        "designer_handoffs", "ba_package_sections", "ba_packages",
        "events", "sessions", "app_states", "user_states",
    ],
    "designer": ["artifacts", "reviews", "events", "runs", "sessions"],
    "wiki": ["audit_log", "wiki_revision", "wiki_page", "wiki_source"],
}

with psycopg.connect(database_url("core", "libpq"), autocommit=True) as conn:
    for schema, tables in TABLES.items():
        present = [
            t for t in tables
            if conn.execute("SELECT to_regclass(%s) IS NOT NULL", (f"{schema}.{t}",)).fetchone()[0]
        ]
        if present:
            conn.execute("TRUNCATE " + ", ".join(f'{schema}."{t}"' for t in present) + " CASCADE")
            print(f"truncated {schema}: {', '.join(present)}")

storage = get_storage()
removed = 0
for prefix in ("projects/", "shared/", "_probe/"):
    for key in list(storage.keys(prefix)):
        storage.delete(key)
        removed += 1
print(f"deleted {removed} storage objects ({getattr(storage, 'bucket', 'local')})")

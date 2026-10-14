"""Wipe only the Wiki MVP 3-table store. Never touch BA / ADK SQLite."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from factory_wiki.paths import ensure_mvp_importable, wiki_service_root

WIKI_TABLES = ("wiki_revision", "wiki_page", "wiki_source")
FOREIGN_TABLES = frozenset(
    {
        "ba_packages",
        "ba_package_sections",
        "sessions",
        "events",
        "app_states",
        "user_states",
        "adk_internal_metadata",
    }
)
_FORBIDDEN_DB_NAMES = frozenset(
    {
        "ba-demo-sync.db",
        "ba-demo-adk.db",
        "session.db",
    }
)


class WikiResetError(RuntimeError):
    """Raised when a wiki clear would escape the 3-table wiki.db store."""


def _wiki_paths(root: Path):
    ensure_mvp_importable()
    from wiki.paths import audit_path, blob_dir, db_path

    return db_path(root), blob_dir(root), audit_path(root)


def reset_wiki_store(root: Path | None = None) -> dict:
    """DELETE wiki_page / wiki_source / wiki_revision and wiki blobs only.

    Opens ``<root>/data/wiki.db``. Never unlinks that file, never ``rmtree``s
    a parent directory, and refuses if the path looks like a BA/ADK database.
    """
    store_root = wiki_service_root(root)
    db, blobs, audit = _wiki_paths(store_root)
    db = db.resolve()
    blobs = blobs.resolve()
    if db.name != "wiki.db" or db.name in _FORBIDDEN_DB_NAMES:
        raise WikiResetError(f"refusing to clear non-wiki database: {db}")
    if blobs.name != "blobs" or blobs.parent.name != "data":
        raise WikiResetError(f"refusing to clear blobs outside data/blobs: {blobs}")
    if blobs in {Path("/"), Path("/tmp")}:
        raise WikiResetError(f"refusing to clear filesystem root blobs: {blobs}")

    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        foreign = sorted(tables & FOREIGN_TABLES)
        if foreign:
            raise WikiResetError(
                f"refusing to clear {db}: contains BA/ADK tables {foreign}"
            )
        for table in WIKI_TABLES:
            if table in tables:
                conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()

    removed_blobs = 0
    if blobs.is_dir():
        for path in blobs.iterdir():
            if not path.is_file():
                continue
            if path.suffix.lower() in {".db", ".db-wal", ".db-shm"}:
                continue
            path.unlink()
            removed_blobs += 1
    if audit.is_file():
        audit.unlink()
    return {
        "pages": 0,
        "sources": 0,
        "removed_blobs": removed_blobs,
        "wiki_db": str(db),
    }

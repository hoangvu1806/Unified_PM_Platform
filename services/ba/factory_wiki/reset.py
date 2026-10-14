"""Wipe only the wiki store (Postgres schema ``wiki``). Never touch BA / ADK tables."""

from __future__ import annotations

from pathlib import Path

from factory_wiki.paths import ensure_manifest, ensure_mvp_importable, wiki_service_root

WIKI_TABLES = ("wiki_revision", "wiki_page", "wiki_source", "audit_log")
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


class WikiResetError(RuntimeError):
    """Raised when a wiki clear would escape the wiki schema."""


def reset_wiki_store(root: Path | None = None) -> dict:
    """DELETE the wiki tables and their storage blobs only.

    Platform: the store is the shared Postgres schema ``WIKI_DB_SCHEMA``
    (default ``wiki``). ``WikiService.reset_store`` refuses when the schema also
    holds BA/ADK tables, so a misconfigured search_path cannot wipe BA data.
    """
    ensure_mvp_importable()
    from wiki.models import WikiError
    from wiki.service import WikiService
    from wiki.sort import HeuristicSorter

    store_root = wiki_service_root(root)
    ensure_manifest(store_root)
    service = WikiService(store_root, sorter=HeuristicSorter())
    try:
        return service.reset_store()
    except WikiError as exc:
        raise WikiResetError(str(getattr(exc, "message", exc))) from exc
    finally:
        service.close()

"""Authorization: what the caller may do in a project (core.project_members).

Rules (refactor-plan/03-database.md, "Quyền xem chat"):
* any member reads everything in the project (sessions, chat, artifacts);
* writing in a module needs that module's role in the project (BA or
  DESIGNER); PM (product owner doing both) and ADMIN count as both;
* non-members get nothing.
"""

from __future__ import annotations

import threading
import time

from platform_core.auth import CurrentUser
from platform_core.db import database_url

PROJECT_ROLES = ("PM", "BA", "DESIGNER", "REVIEWER", "ADMIN")
ALL_MODULE_ROLES = frozenset({"PM", "ADMIN"})
_CACHE_TTL_S = 30.0
_cache: dict[tuple[str, str], tuple[float, frozenset[str]]] = {}
_lock = threading.Lock()


class ProjectAccessError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _query_roles(user_id: str, project_id: str) -> frozenset[str]:
    import psycopg

    with psycopg.connect(database_url("core", "libpq")) as conn:
        rows = conn.execute(
            "SELECT m.project_role FROM core.project_members m "
            "JOIN core.projects p ON p.id = m.project_id "
            "WHERE m.user_id = %s AND m.project_id = %s AND p.archived_at IS NULL",
            (user_id, project_id),
        ).fetchall()
    return frozenset(r[0] for r in rows)


def project_roles(user: CurrentUser, project_id: str) -> frozenset[str]:
    """Roles of ``user`` in ``project_id`` (empty = not a member). Cached 30s."""
    key = (user.id, project_id)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _CACHE_TTL_S:
            return hit[1]
    roles = _query_roles(user.id, project_id)
    with _lock:
        _cache[key] = (now, roles)
    return roles


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def check_project(user: CurrentUser, project_id: str | None, write_role: str | None = None) -> frozenset[str]:
    """Raise :class:`ProjectAccessError` unless ``user`` may read (or write) the project."""
    if not project_id:
        raise ProjectAccessError(400, "PROJECT_REQUIRED", "project_id is required")
    roles = project_roles(user, project_id)
    if not roles:
        raise ProjectAccessError(403, "PROJECT_FORBIDDEN", "You are not a member of this project")
    if write_role and write_role not in roles and not roles & ALL_MODULE_ROLES:
        raise ProjectAccessError(
            403, "ROLE_FORBIDDEN", f"Role {write_role} is required in this project for this action"
        )
    return roles

"""core-api routes, mounted under /api/core (the gateway forwards the full path)."""

from __future__ import annotations

import re
import uuid
from typing import Any

import mimetypes
import unicodedata
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from platform_core import artifacts
from platform_core.auth import CurrentUser, get_auth_settings, issue_token
from platform_core.fastapi import authenticate, get_current_user
from platform_core.logs import bind
from platform_core.projects import PROJECT_ROLES, clear_cache
from pydantic import BaseModel, Field

from .db import connection
from .passwords import verify_password
from .seed import DEMO_PASSWORD, USERS

public = APIRouter(prefix="/api/core")


def _disposition(filename: str) -> str:
    """attachment header that survives non-ASCII names (RFC 5987)."""
    ascii_name = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode() or "download"
    ascii_name = ascii_name.replace('"', "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
private = APIRouter(prefix="/api/core", dependencies=[Depends(authenticate)])


class LoginIn(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class MemberIn(BaseModel):
    user_id: str = Field(min_length=1)
    project_role: str


def _user_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "name": row["display_name"],
        "roles": list(row["platform_roles"]),
    }


def _current_view(user: CurrentUser) -> dict[str, Any]:
    return {"id": user.id, "username": user.username, "name": user.name, "roles": sorted(user.roles)}


def _require_mock() -> None:
    if get_auth_settings().auth_mode != "mock":
        raise HTTPException(404, detail={"code": "NOT_AVAILABLE", "message": "Mock login is disabled"})


def _my_roles(conn, project_id: str, user_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT project_role FROM project_members WHERE project_id=%s AND user_id=%s ORDER BY project_role",
        (project_id, user_id),
    ).fetchall()
    return [r["project_role"] for r in rows]


def _require_member(conn, project_id: str, user: CurrentUser, admin: bool = False) -> list[str]:
    bind(project_id=project_id)
    project = conn.execute(
        "SELECT id FROM projects WHERE id=%s AND archived_at IS NULL", (project_id,)
    ).fetchone()
    roles = _my_roles(conn, project_id, user.id) if project else []
    if not project or not roles:
        # Same answer for "missing" and "not a member": do not leak project ids.
        raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND", "message": "Project not found"})
    if admin and "ADMIN" not in roles:
        raise HTTPException(403, detail={"code": "ADMIN_REQUIRED", "message": "Project ADMIN role required"})
    return roles


# ── Public ───────────────────────────────────────────────


@public.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "auth_mode": get_auth_settings().auth_mode}


@public.get("/auth/mock-users")
def mock_users() -> list[dict[str, Any]]:
    _require_mock()
    return [
        {"username": username, "name": name, "roles": roles, "password": DEMO_PASSWORD}
        for _uid, username, name, roles in USERS
    ]


@public.post("/auth/login")
def login(body: LoginIn, response: Response) -> dict[str, Any]:
    _require_mock()
    with connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=%s", (body.username.strip(),)).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, detail={"code": "LOGIN_FAILED", "message": "Wrong username or password"})
    user = CurrentUser(row["id"], row["username"], row["display_name"], frozenset(row["platform_roles"]))
    settings = get_auth_settings()
    token = issue_token(user, settings)
    response.set_cookie(
        settings.auth_cookie_name,
        token,
        max_age=settings.auth_jwt_ttl_minutes * 60,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {"user": _user_view(row), "token": token}


@public.post("/auth/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(get_auth_settings().auth_cookie_name, path="/")
    return {"ok": True}


# ── Authenticated ────────────────────────────────────────


@private.get("/me")
def me() -> dict[str, Any]:
    return _current_view(get_current_user())


@private.get("/users")
def list_users() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY display_name").fetchall()
    return [_user_view(r) for r in rows]


@private.get("/projects")
def list_projects() -> list[dict[str, Any]]:
    user = get_current_user()
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.name, p.description, p.created_at,
                   array_agg(DISTINCT m.project_role ORDER BY m.project_role) AS my_roles,
                   (SELECT count(DISTINCT user_id) FROM project_members x WHERE x.project_id = p.id) AS member_count
            FROM projects p JOIN project_members m ON m.project_id = p.id AND m.user_id = %s
            WHERE p.archived_at IS NULL
            GROUP BY p.id ORDER BY p.name
            """,
            (user.id,),
        ).fetchall()
    return [{**r, "my_roles": list(r["my_roles"]), "created_at": r["created_at"].isoformat()} for r in rows]


@private.post("/projects", status_code=201)
def create_project(body: ProjectIn) -> dict[str, Any]:
    user = get_current_user()
    slug = re.sub(r"[^A-Z0-9]+", "-", body.name.upper()).strip("-")[:16] or "PROJECT"
    project_id = f"PRJ-{slug}-{uuid.uuid4().hex[:4].upper()}"
    # Default: the creator runs the whole journey (PM = BA + Designer) and administers it.
    roles = ["ADMIN", "PM"]
    with connection() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, description, created_by) VALUES (%s, %s, %s, %s)",
            (project_id, body.name.strip(), body.description.strip(), user.id),
        )
        for role in roles:
            conn.execute(
                "INSERT INTO project_members (project_id, user_id, project_role) VALUES (%s, %s, %s)",
                (project_id, user.id, role),
            )
    clear_cache()
    return {"id": project_id, "name": body.name.strip(), "description": body.description.strip(), "my_roles": roles}


@private.get("/projects/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    user = get_current_user()
    with connection() as conn:
        roles = _require_member(conn, project_id, user)
        project = conn.execute("SELECT * FROM projects WHERE id=%s", (project_id,)).fetchone()
        members = conn.execute(
            """
            SELECT u.id, u.username, u.display_name,
                   array_agg(m.project_role ORDER BY m.project_role) AS project_roles
            FROM project_members m JOIN users u ON u.id = m.user_id
            WHERE m.project_id = %s GROUP BY u.id ORDER BY u.display_name
            """,
            (project_id,),
        ).fetchall()
    return {
        "id": project["id"],
        "name": project["name"],
        "description": project["description"],
        "created_at": project["created_at"].isoformat(),
        "my_roles": roles,
        "members": [
            {"id": m["id"], "username": m["username"], "name": m["display_name"], "roles": list(m["project_roles"])}
            for m in members
        ],
    }


@private.post("/projects/{project_id}/members", status_code=201)
def add_member(project_id: str, body: MemberIn) -> dict[str, Any]:
    if body.project_role not in PROJECT_ROLES:
        raise HTTPException(422, detail={"code": "ROLE_INVALID", "message": f"project_role must be one of {PROJECT_ROLES}"})
    with connection() as conn:
        _require_member(conn, project_id, get_current_user(), admin=True)
        if not conn.execute("SELECT 1 FROM users WHERE id=%s", (body.user_id,)).fetchone():
            raise HTTPException(404, detail={"code": "USER_NOT_FOUND", "message": "User not found"})
        conn.execute(
            "INSERT INTO project_members (project_id, user_id, project_role) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (project_id, body.user_id, body.project_role),
        )
    clear_cache()
    return {"project_id": project_id, "user_id": body.user_id, "project_role": body.project_role}


@private.delete("/projects/{project_id}/members/{user_id}")
def remove_member(project_id: str, user_id: str, role: str | None = None) -> dict[str, Any]:
    user = get_current_user()
    with connection() as conn:
        _require_member(conn, project_id, user, admin=True)
        if user_id == user.id and (role in (None, "ADMIN")):
            raise HTTPException(409, detail={"code": "SELF_ADMIN", "message": "Admins cannot remove their own ADMIN role"})
        if role:
            cur = conn.execute(
                "DELETE FROM project_members WHERE project_id=%s AND user_id=%s AND project_role=%s",
                (project_id, user_id, role),
            )
        else:
            cur = conn.execute(
                "DELETE FROM project_members WHERE project_id=%s AND user_id=%s", (project_id, user_id)
            )
    clear_cache()
    return {"removed": cur.rowcount}


# ── Assets (Sprint 4) ────────────────────────────────────


@private.get("/projects/{project_id}/artifacts")
def list_artifacts(project_id: str) -> list[dict[str, Any]]:
    """Published artifacts of the project, newest first; any member may read."""
    with connection() as conn:
        _require_member(conn, project_id, get_current_user())
    rows = artifacts.list_for_project(project_id)
    return [{k: v for k, v in r.items() if k not in {"content_hash"}} for r in rows]


@private.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str) -> Response:
    from platform_core.storage import get_storage

    row = artifacts.get(artifact_id)
    if not row:
        raise HTTPException(404, detail={"code": "ARTIFACT_NOT_FOUND", "message": "Artifact not found"})
    with connection() as conn:
        _require_member(conn, row["project_id"], get_current_user())
    if not row["storage_key"]:
        raise HTTPException(404, detail={"code": "ARTIFACT_NO_FILE", "message": "Artifact has no stored file"})
    try:
        data = get_storage().get(row["storage_key"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, detail={"code": "STORAGE_ERROR", "message": str(exc)}) from exc
    filename = row["storage_key"].rsplit("/", 1)[-1]
    media = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return Response(data, media_type=media, headers={"Content-Disposition": _disposition(filename)})


# ── Project files (shared files for agents and chats) ────


def _file_name(storage_key: str | None, fallback: str) -> str:
    return (storage_key or "").rsplit("/", 1)[-1] or fallback


@private.get("/projects/{project_id}/files")
def list_project_files(project_id: str) -> list[dict[str, Any]]:
    """Every shared file a member can cite: published artifacts + wiki sources.

    ``citable`` says whether the Designer attachment parser can read it
    (wiki sources are served as their Markdown extract; .fig designs are not).
    """
    with connection() as conn:
        _require_member(conn, project_id, get_current_user())
        users = {
            r["username"]: r["display_name"]
            for r in conn.execute("SELECT username, display_name FROM users").fetchall()
        }
        has_wiki = conn.execute("SELECT to_regclass('wiki.wiki_source') IS NOT NULL AS ok").fetchone()["ok"]
        sources = (
            conn.execute(
                "SELECT source_id, filename, namespace, project_id, ingested_by, ingested_at, "
                "length(markdown_extract) AS chars FROM wiki.wiki_source "
                "WHERE (namespace = 'project' AND project_id = %s) OR namespace = 'company' "
                "ORDER BY ingested_at DESC",
                (project_id,),
            ).fetchall()
            if has_wiki
            else []
        )
    files: list[dict[str, Any]] = []
    for a in artifacts.list_for_project(project_id):
        name = _file_name(a["storage_key"], a["title"])
        files.append({
            "id": a["id"],
            "kind": a["kind"],
            "name": name,
            "title": a["title"],
            "version": a["version"],
            "stale": a["stale"],
            "created_by": a["created_by"],
            "created_by_name": users.get(a["created_by"] or "", a["created_by"]),
            "created_at": a["created_at"],
            "scope": "project",
            "citable": a["kind"] == "ba_package",
            "download_url": f"/api/core/artifacts/{a['id']}/download",
        })
    for s in sources:
        stem = s["filename"].rsplit(".", 1)[0] or s["source_id"]
        files.append({
            "id": s["source_id"],
            "kind": "wiki_source",
            "name": f"{stem}.md",
            "title": s["filename"],
            "version": None,
            "stale": False,
            "created_by": s["ingested_by"],
            "created_by_name": users.get(s["ingested_by"], s["ingested_by"]),
            "created_at": s["ingested_at"],
            "scope": s["namespace"],
            "citable": True,
            "download_url": f"/api/core/projects/{project_id}/wiki-sources/{s['source_id']}/markdown",
        })
    files.sort(key=lambda f: str(f["created_at"]), reverse=True)
    return files


@private.get("/projects/{project_id}/wiki-sources/{source_id}/markdown")
def wiki_source_markdown(project_id: str, source_id: str) -> Response:
    """The lossless Markdown extract of a wiki source (company or this project)."""
    with connection() as conn:
        _require_member(conn, project_id, get_current_user())
        row = conn.execute(
            "SELECT filename, markdown_extract FROM wiki.wiki_source WHERE source_id = %s "
            "AND ((namespace = 'project' AND project_id = %s) OR namespace = 'company')",
            (source_id, project_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, detail={"code": "FILE_NOT_FOUND", "message": "File not found"})
    stem = row["filename"].rsplit(".", 1)[0] or source_id
    return Response(
        row["markdown_extract"].encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": _disposition(f"{stem}.md")},
    )


# ── Journey (guided BA -> Design path of one feature) ────


@private.get("/projects/{project_id}/features/{feature_id}/journey")
def feature_journey(project_id: str, feature_id: str) -> dict[str, Any]:
    from .journey import build_journey

    with connection() as conn:
        roles = _require_member(conn, project_id, get_current_user())
        journey = build_journey(conn, project_id, feature_id)
    if journey is None:
        raise HTTPException(404, detail={"code": "FEATURE_NOT_FOUND", "message": "Feature not found in this project"})
    journey["my_roles"] = roles
    return journey

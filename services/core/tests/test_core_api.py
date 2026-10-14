"""core-api against the real Postgres (schema core), via TestClient."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def login(client: TestClient, username: str) -> TestClient:
    client.cookies.clear()
    r = client.post("/api/core/auth/login", json={"username": username, "password": "demo123"})
    assert r.status_code == 200, r.text
    assert "platform_token" in r.cookies
    return client


def test_login_rejects_wrong_password(client):
    r = client.post("/api/core/auth/login", json={"username": "ba.an", "password": "nope"})
    assert r.status_code == 401


def test_me_requires_login(client):
    client.cookies.clear()
    assert client.get("/api/core/me").status_code == 401


def test_projects_follow_membership(client):
    login(client, "ba.an")
    ids = {p["id"] for p in client.get("/api/core/projects").json()}
    assert {"PRJ-AURORA", "PRJ-DEMO"} <= ids
    login(client, "ba.chi")
    ids = {p["id"] for p in client.get("/api/core/projects").json()}
    assert "PRJ-DEMO" in ids and "PRJ-AURORA" not in ids
    assert client.get("/api/core/projects/PRJ-AURORA").status_code == 404


def test_create_project_and_admin_only_membership(client):
    login(client, "designer.binh")
    created = client.post("/api/core/projects", json={"name": "Test Shop"}).json()
    assert set(created["my_roles"]) == {"ADMIN", "PM"}  # PM = BA + DESIGNER
    pid = created["id"]
    r = client.post(f"/api/core/projects/{pid}/members", json={"user_id": "u-ba-chi", "project_role": "BA"})
    assert r.status_code == 201
    login(client, "ba.chi")
    assert pid in {p["id"] for p in client.get("/api/core/projects").json()}
    r = client.post(f"/api/core/projects/{pid}/members", json={"user_id": "u-ba-an", "project_role": "BA"})
    assert r.status_code == 403
    # Tests run on the shared core schema: remove the project they created.
    from app.db import connection

    with connection() as conn:
        conn.execute("DELETE FROM projects WHERE id = %s", (pid,))


def test_project_files_members_only(client):
    login(client, "ba.an")
    r = client.get("/api/core/projects/PRJ-AURORA/files")
    assert r.status_code == 200
    for f in r.json():
        assert {"id", "kind", "name", "created_by_name", "citable", "download_url"} <= set(f)
    login(client, "ba.chi")
    assert client.get("/api/core/projects/PRJ-AURORA/files").status_code == 404

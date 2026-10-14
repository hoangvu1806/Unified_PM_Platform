import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from platform_core import projects
from platform_core.auth import AuthError, AuthSettings, CurrentUser, decode_token, issue_token
from platform_core.fastapi import authenticate, require_project

S = AuthSettings(auth_mode="mock", auth_jwt_secret="x" * 32, auth_jwt_ttl_minutes=5)
AN = CurrentUser("u-ba-an", "ba.an", "An", frozenset({"BA"}))


def test_token_roundtrip_keeps_keycloak_shaped_claims():
    user = decode_token(issue_token(AN, S), S)
    assert user == AN


def test_bad_signature_rejected():
    token = issue_token(AN, S)
    with pytest.raises(AuthError):
        decode_token(token, AuthSettings(auth_mode="mock", auth_jwt_secret="y" * 32))


@pytest.fixture()
def roles(monkeypatch):
    table = {("u-ba-an", "P1"): frozenset({"BA"}), ("u-ba-an", "P2"): frozenset({"DESIGNER"})}
    monkeypatch.setattr(projects, "_query_roles", lambda uid, pid: table.get((uid, pid), frozenset()))
    projects.clear_cache()


def test_check_project_rules(roles):
    assert projects.check_project(AN, "P1", "BA") == {"BA"}
    assert projects.check_project(AN, "P2") == {"DESIGNER"}            # any member reads
    with pytest.raises(projects.ProjectAccessError) as e:
        projects.check_project(AN, "P2", "BA")                          # wrong role writes
    assert e.value.code == "ROLE_FORBIDDEN"
    with pytest.raises(projects.ProjectAccessError) as e:
        projects.check_project(AN, "P3")                                # not a member
    assert e.value.status == 403


def test_fastapi_dependency_cookie_and_header(roles, monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", S.auth_jwt_secret)
    monkeypatch.setenv("AUTH_MODE", "mock")
    from platform_core.auth import get_auth_settings

    get_auth_settings.cache_clear()
    app = FastAPI(dependencies=[Depends(authenticate)])

    @app.get("/p/{pid}")
    def read(pid: str):
        require_project(pid)
        return {"ok": pid}

    client = TestClient(app)
    token = issue_token(AN, S)
    assert client.get("/p/P1").status_code == 401
    assert client.get("/p/P1", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    client.cookies.set("platform_token", token)
    assert client.get("/p/P2").status_code == 200
    assert client.get("/p/P3").status_code == 403
    get_auth_settings.cache_clear()

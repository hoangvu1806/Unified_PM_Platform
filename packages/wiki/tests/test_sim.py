from __future__ import annotations

from fastapi.testclient import TestClient

from wiki.http_app import app, get_service
from wiki.seed import run as seed_run
from wiki.service import WikiService
from wiki.sim import ALL_SIM_IDS, BOOTSTRAP_IDS, PROPOSE_IDS


def _client(svc: WikiService) -> TestClient:
    app.dependency_overrides[get_service] = lambda: svc
    return TestClient(app)


def _clear(client: TestClient) -> None:
    client.close()
    app.dependency_overrides.clear()


def test_sim_page_renders(svc: WikiService) -> None:
    client = _client(svc)
    res = client.get("/sim")
    _clear(client)
    assert res.status_code == 200
    assert "Mô phỏng" in res.text
    assert "btn-next" in res.text


def test_sim_bootstrap_then_agent_search(svc: WikiService) -> None:
    client = _client(svc)
    boot = client.post("/sim/bootstrap")
    assert boot.status_code == 200
    assert boot.json()["seeded"] is True
    assert boot.json()["approved_count"] == 4
    st = client.get("/sim/state")
    ids = {p["page_id"] for p in st.json()["sim_pages"]}
    assert set(BOOTSTRAP_IDS) <= ids
    search = client.get(
        "/v1/wiki/pages",
        params={"namespace": "project", "project_id": "PRJ-MES-01", "query": "PO", "limit": 8},
        headers={
            "X-Actor": "ba-agent",
            "X-Actor-Type": "agent",
            "X-Agent-Name": "ba-agent",
            "X-Project-Id": "PRJ-MES-01",
        },
    )
    _clear(client)
    assert search.status_code == 200
    assert search.json()["hits"]


def test_sim_bootstrap_skips_when_approved_exist(svc: WikiService, root) -> None:
    seed_run(root, approve=True)
    client = _client(svc)
    boot = client.post("/sim/bootstrap")
    _clear(client)
    assert boot.json()["seeded"] is False
    assert boot.json()["reason"] == "approved_already_present"


def test_sim_propose_agent_cannot_approve_human_can(svc: WikiService) -> None:
    client = _client(svc)
    client.post("/sim/bootstrap")
    page_id = PROPOSE_IDS[0]
    proposed = client.post(
        "/v1/wiki/pages",
        headers={
            "X-Actor": "ba-agent",
            "X-Actor-Type": "agent",
            "X-Agent-Name": "ba-agent",
            "X-Project-Id": "PRJ-MES-01",
        },
        json={
            "page_id": page_id,
            "namespace": "project",
            "project_id": "PRJ-MES-01",
            "bucket_id": "org",
            "title": "PO spend",
            "body": "sim propose",
        },
    )
    assert proposed.status_code == 200
    assert proposed.json()["status"] in {"draft", "proposed"}
    denied = client.post(
        f"/v1/wiki/pages/{page_id}/approve",
        headers={
            "X-Actor": "ba-agent",
            "X-Actor-Type": "agent",
            "X-Agent-Name": "ba-agent",
            "X-Project-Id": "PRJ-MES-01",
        },
        json={},
    )
    assert denied.status_code == 403
    ok = client.post(
        f"/v1/wiki/pages/{page_id}/approve",
        headers={"X-Actor": "ba.lead", "X-Actor-Type": "human", "X-Project-Id": "PRJ-MES-01"},
        json={},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "approved"
    _clear(client)


def test_sim_reset_removes_only_sim_ids(svc: WikiService, root) -> None:
    seed_run(root, approve=True)
    client = _client(svc)
    client.post("/sim/reset")
    client.post(
        "/v1/wiki/pages",
        headers={
            "X-Actor": "ba-agent",
            "X-Actor-Type": "agent",
            "X-Agent-Name": "ba-agent",
            "X-Project-Id": "PRJ-MES-01",
        },
        json={
            "page_id": "SIM-PROGRESS-F-KHO",
            "namespace": "project",
            "project_id": "PRJ-MES-01",
            "bucket_id": "progress",
            "title": "progress",
            "body": "x",
        },
    )
    reset = client.post("/sim/reset")
    assert reset.json()["removed"] >= 1
    leftover = {p["page_id"] for p in reset.json()["sim_pages"]}
    assert leftover.isdisjoint(set(ALL_SIM_IDS))
    home = client.get("/")
    _clear(client)
    assert "PG-GLOSS-AC" in home.text

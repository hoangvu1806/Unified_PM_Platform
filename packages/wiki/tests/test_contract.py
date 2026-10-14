from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wiki.http_app import app, get_service
from wiki.mcp_server import wiki_approve_page
from wiki.models import Actor, SearchQuery
from wiki.seed import run as seed_run
from wiki.service import WikiService


def test_ingest_txt_creates_drafts(svc: WikiService, human: Actor) -> None:
    result = svc.ingest_source(
        human,
        filename="policy.txt",
        data=b"Constraint: stock cannot go negative.\nConvention: lot code is required.\n",
        namespace="project",
        project_id="PRJ-MES-01",
        sort_mode="heuristic",
    )
    assert result["extract_status"] == "complete"
    assert result["sort_status"] == "draft_pending_review"
    assert result["proposed_page_ids"]
    pages = {p.page_id: p for p in svc.list_pages(status="draft")}
    for page_id in result["proposed_page_ids"]:
        assert pages[page_id].status == "draft"


def test_extract_keeps_ac_po(svc: WikiService, human: Actor, root: Path) -> None:
    seed_run(root, approve=False)
    src = svc.get_source(human, "SRC-BRD-001")
    assert "AC" in src.markdown_extract
    assert "PO" in src.markdown_extract
    assert len(src.page_map) >= 4


def test_seed_writes_multiple_sources(svc: WikiService, human: Actor, root: Path) -> None:
    seed_run(root, approve=False)
    company = Actor(actor="ba.lead", actor_type="human")
    assert svc.get_source(human, "SRC-BRD-001").filename.startswith("BRD-F-001")
    assert svc.get_source(company, "SRC-CONV-001").namespace == "company"
    assert svc.get_source(human, "SRC-BRD-002").filename.startswith("BRD-F-002")
    assert svc.get_source(company, "SRC-POL-001").filename.startswith("POL-WH-001")
    assert svc.get_source(company, "SRC-POL-001").namespace == "company"
    samples = root / "data" / "samples"
    assert (samples / "BRD-F-001-phe-duyet.pdf").exists()
    assert (samples / "CONV-ENG-001-company.pdf").exists()
    assert (samples / "BRD-F-002-kho-vat-tu.pdf").exists()
    assert (samples / "POL-WH-001-kho-spend.pdf").exists()


def test_search_has_no_body_fetch_has_body(svc: WikiService, human: Actor, agent: Actor, root: Path) -> None:
    seed_run(root, approve=True)
    hits = svc.search_pages(
        agent,
        SearchQuery(query="phe duyet", namespace="project", project_id="PRJ-MES-01", status="approved"),
    )
    assert hits
    dumped = hits[0].model_dump()
    assert "body" not in dumped
    assert "snippet" in dumped
    page = svc.fetch_page(agent, "PG-GLOSS-AC")
    assert page.body
    assert page.status == "approved"


def test_agent_cannot_approve(svc: WikiService, agent: Actor, human: Actor, root: Path) -> None:
    seed_run(root, approve=False)
    with pytest.raises(Exception) as exc:
        svc.approve_page(agent, "PG-GLOSS-AC")
    assert exc.value.code == "COMMON_PERMISSION_DENIED"
    approved = svc.approve_page(human, "PG-GLOSS-AC")
    assert approved.status == "approved"
    rows = svc.conn.execute(
        "SELECT COUNT(*) AS c FROM wiki_revision WHERE page_id = ?",
        ("PG-GLOSS-AC",),
    ).fetchone()
    assert rows["c"] >= 2


def test_human_demote_and_agent_denied(
    svc: WikiService, agent: Actor, human: Actor, root: Path
) -> None:
    seed_run(root, approve=True)
    with pytest.raises(Exception) as exc:
        svc.demote_page(agent, "PG-GLOSS-AC")
    assert exc.value.code == "COMMON_PERMISSION_DENIED"
    demoted = svc.demote_page(human, "PG-GLOSS-AC")
    assert demoted.status == "draft"
    with pytest.raises(Exception) as exc2:
        svc.fetch_page(agent, "PG-GLOSS-AC")
    assert exc2.value.code == "COMMON_PRECONDITION_FAILED"


def test_human_delete_page(svc: WikiService, human: Actor, root: Path) -> None:
    seed_run(root, approve=True)
    result = svc.delete_page(human, "PG-GLOSS-AC")
    assert result["deleted"] == 1
    assert svc.list_pages(status="approved") == [
        p for p in svc.list_pages(status="approved") if p.page_id != "PG-GLOSS-AC"
    ]
    assert not any(p.page_id == "PG-GLOSS-AC" for p in svc.list_pages())


def test_agent_cannot_fetch_other_project(svc: WikiService, human: Actor, agent: Actor, root: Path) -> None:
    seed_run(root, approve=True)
    other = agent.model_copy(update={"project_id": "PRJ-OTHER"})
    with pytest.raises(Exception) as exc:
        svc.fetch_page(other, "PG-GLOSS-AC")
    assert exc.value.code == "COMMON_PERMISSION_DENIED"


def test_agent_cannot_fetch_draft(svc: WikiService, agent: Actor, root: Path) -> None:
    seed_run(root, approve=False)
    with pytest.raises(Exception) as exc:
        svc.fetch_page(agent, "PG-GLOSS-AC")
    assert exc.value.code == "COMMON_PRECONDITION_FAILED"


def test_http_agent_approve_denied(svc: WikiService, root: Path) -> None:
    seed_run(root, approve=False)
    app.dependency_overrides[get_service] = lambda: svc
    client = TestClient(app)
    res = client.post(
        "/v1/wiki/pages/PG-GLOSS-AC/approve",
        headers={
            "X-Actor": "ba-agent",
            "X-Actor-Type": "agent",
            "X-Agent-Name": "ba-agent",
            "X-Project-Id": "PRJ-MES-01",
        },
        json={"actor": "ba-agent", "version": "1.0.0"},
    )
    app.dependency_overrides.clear()
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "COMMON_PERMISSION_DENIED"


def test_mcp_approve_tool_denied() -> None:
    out = wiki_approve_page("PG-GLOSS-AC")
    assert out["code"] == "COMMON_PERMISSION_DENIED"


def test_reset_store_empties_approved_and_drafts(svc: WikiService, human: Actor) -> None:
    first = svc.ingest_source(
        human,
        filename="before-clear.txt",
        data=b"Constraint: stock cannot go negative.\nConvention: lot code is required.\n",
        namespace="project",
        project_id="PRJ-MES-01",
        sort_mode="heuristic",
    )
    assert first["proposed_page_ids"]
    svc.approve_page(human, first["proposed_page_ids"][0])
    assert svc.list_pages(status="draft") or svc.list_pages(status="approved")

    wiped = svc.reset_store()
    assert wiped["pages"] == 0
    assert wiped["sources"] == 0
    assert svc.list_pages(status="draft") == []
    assert svc.list_pages(status="proposed") == []
    assert svc.list_pages(status="approved") == []

    again = svc.ingest_source(
        human,
        filename="after-clear.txt",
        data=b"Constraint: lot cannot split after pick.\nConvention: bin code is required.\n",
        namespace="project",
        project_id="PRJ-MES-01",
        sort_mode="heuristic",
    )
    assert again["proposed_page_ids"]
    assert svc.list_pages(status="draft")


def test_ui_home(svc: WikiService, root: Path) -> None:
    seed_run(root, approve=False)
    app.dependency_overrides[get_service] = lambda: svc
    client = TestClient(app)
    res = client.get("/")
    app.dependency_overrides.clear()
    assert res.status_code == 200
    assert "PG-GLOSS-AC" in res.text
    assert "Approve" in res.text

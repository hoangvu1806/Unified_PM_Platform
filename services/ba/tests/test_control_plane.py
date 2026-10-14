"""Unified control plane: status, export envelope, wiki queries, read-only."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import PropertyMock, patch

import anyio
import pytest
from fastapi.testclient import TestClient

from agents.ba_agent.section_gate import REQUIRED_BLOCKERS, section_is_complete
from agents.sub_graph.validation_agent.logic import (
    run_validation,
    wiki_queries_from_artifacts,
)
from config.base_config import Settings
from factory_wiki.reset import WikiResetError, reset_wiki_store
from factory_wiki.store import WikiStore
from managers.control.export import build_export_envelope
from managers.control.session import persist_control_delta, project_id_for_session
from managers.control.status import can_export, can_validate, is_chat_frozen, is_readonly
import managers.runner_context as rc
from server import app


@pytest.fixture(autouse=True)
def setup_adk_runner():
    test_db_url = "sqlite+aiosqlite:///:memory:"
    with patch.object(Settings, "database_url", new_callable=PropertyMock, return_value=test_db_url):
        anyio.run(rc.init_adk)
    yield
    rc._runner = None
    rc._session_service = None


@pytest.fixture
def sqlite_sync_db():
    from managers.database.connection import (
        configure_sync_engine,
        get_sync_database_url,
        init_db,
    )

    configure_sync_engine("sqlite:///:memory:")
    init_db()
    yield
    configure_sync_engine(get_sync_database_url())


def test_required_blockers_cover_tier1():
    assert REQUIRED_BLOCKERS["fd"] == frozenset({"FD-F1", "FD-F2", "FD-F3", "FD-F5"})
    assert REQUIRED_BLOCKERS["br"] == frozenset({"BR-F1", "BR-F4"})
    assert REQUIRED_BLOCKERS["wf"] == frozenset({"WF-F1", "WF-F2", "WF-F4"})
    assert REQUIRED_BLOCKERS["uc"] == frozenset(
        {"UC-F1", "UC-F2", "UC-F3", "UC-F5", "UC-F7", "UC-F8"}
    )
    assert section_is_complete({"flags": {"br": {"BR-F1": {"status": "PASS"}}}}, "business_rules") is False
    assert (
        section_is_complete(
            {
                "flags": {
                    "br": {
                        "BR-F1": {"status": "PASS"},
                        "BR-F4": {"status": "PENDING_SEMANTIC"},
                    }
                }
            },
            "business_rules",
        )
        is False
    )


def test_wiki_queries_come_from_artifacts_not_fixtures():
    queries = wiki_queries_from_artifacts(
        {
            "feature_definition": {
                "goal": "Thanh toán đơn hàng nội bộ",
                "actors": ["ACT-KE-TOAN: Kế toán"],
            },
            "business_rules": [{"id": "BR-01", "statement": "Giao dịch phải ghi sổ"}],
        }
    )
    blob = " ".join(queries).lower()
    assert "phê duyệt" not in blob
    assert "momo" not in blob
    assert "ví điện tử" not in blob
    assert any("giao dịch" in q.lower() or "ghi sổ" in q.lower() for q in queries)


def test_va_wiki_contradiction_uses_seeded_mvp_page():
    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        store.seed_page(
            page_id="PAGE-THRESHOLD-001",
            title="Ngưỡng phê duyệt",
            body="Mọi giao dịch trên 5 triệu VND phải có phê duyệt cấp PO.",
            project_id="PRJ-MES-01",
            bucket_id="business_rule",
        )
        state = {
            "session_id": "sid-va-1",
            "project_id": "PRJ-MES-01",
            "artifacts": {
                "feature_definition": {
                    "goal": "Theo dõi giao dịch chi tiêu",
                    "actors": ["ACT-PO: Product Owner"],
                },
                "business_rules": [
                    {"id": "BR-01", "statement": "Giao dịch phải được ghi nhận trên hệ thống"}
                ],
            },
        }
        run_validation(state, store)
        assert state["_va_result"]["status"] == "failed"
        assert any(c.get("check_id") == "V-WIKI-01" for c in state["_va_result"]["failed_checks"])
        assert state["_va_envelope"]["agent"]["id"] == "validation-agent"
        assert state["_va_envelope"]["contract"]["name"] == "validation-report"


def _va_state(session_id: str = "sid-va") -> dict:
    return {
        "session_id": session_id,
        "project_id": "PRJ-MES-01",
        "artifacts": {
            "feature_definition": {
                "goal": "Theo dõi phiếu chi nội bộ",
                "actors": ["ACT-KE-TOAN: Kế toán"],
            },
            "business_rules": [
                {"id": "BR-01", "statement": "Phiếu chi phải có mục đích"}
            ],
        },
    }


def test_va_lists_approved_wiki_pages_even_when_queries_miss():
    """VA evidence is live approved MVP pages, not MoMo fixtures."""
    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        store.seed_page(
            page_id="PAGE-FINANCE-ORG",
            title="Finance",
            body="Finance owns spend policy for the project.",
            project_id="PRJ-MES-01",
            bucket_id="org",
        )
        store.seed_page(
            page_id="PAGE-DRAFT-SKIP",
            title="Draft only",
            body="Should not appear.",
            project_id="PRJ-MES-01",
            bucket_id="org",
            status="draft",
        )
        state = {
            "session_id": "sid-va-2",
            "project_id": "PRJ-MES-01",
            "artifacts": {
                "feature_definition": {
                    "goal": "Theo dõi phiếu chi nội bộ",
                    "actors": ["ACT-KE-TOAN: Kế toán"],
                },
                "business_rules": [
                    {"id": "BR-01", "statement": "Phiếu chi phải có mục đích"}
                ],
            },
        }
        run_validation(state, store)
        evidence_ids = {e["page_id"] for e in state["_va_result"]["evidence_references"]}
        assert "PAGE-FINANCE-ORG" in evidence_ids
        assert "PAGE-DRAFT-SKIP" not in evidence_ids
        blob = json.dumps(state["_va_result"], ensure_ascii=False).lower()
        assert "momo" not in blob
        assert "ví điện tử" not in blob


def test_va_second_validate_sees_new_and_updated_approved_pages():
    """Re-validate after a second connection writes approved wiki — not the old 5 rowids."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        reader = WikiStore(root)
        for i in range(6):
            reader.seed_page(
                page_id=f"PAGE-OLD-{i + 1:02d}",
                title=f"Old page {i + 1}",
                body=f"Canonical old wiki page {i + 1} for PRJ-MES-01.",
                project_id="PRJ-MES-01",
            )
        state = _va_state("sid-va-wiki-refresh")
        run_validation(state, reader)
        first_ids = {e["page_id"] for e in state["_va_result"]["evidence_references"]}
        assert "PAGE-OLD-01" in first_ids
        assert "PAGE-NEW-TOKEN-ZZZ" not in first_ids

        writer = WikiStore(root)
        writer.seed_page(
            page_id="PAGE-NEW-TOKEN-ZZZ",
            title="New approved token page",
            body="UNIQUE_TOKEN_WIKI_UPDATE_2026 visible after approve.",
            project_id="PRJ-MES-01",
        )
        writer.seed_page(
            page_id="PAGE-OLD-01",
            title="Old page 1",
            body="UPDATED_BODY_TOKEN_ON_APPROVED_PAGE after human approve.",
            project_id="PRJ-MES-01",
        )
        writer.seed_page(
            page_id="PAGE-DRAFT-STILL-HIDDEN",
            title="Draft only",
            body="DRAFT_TOKEN_MUST_NOT_LEAK",
            project_id="PRJ-MES-01",
            status="draft",
        )
        writer.close()

        run_validation(state, reader)
        result = state["_va_result"]
        assert result["status"] != "no_change"
        evidence_ids = {e["page_id"] for e in result["evidence_references"]}
        assert "PAGE-NEW-TOKEN-ZZZ" in evidence_ids
        assert "PAGE-DRAFT-STILL-HIDDEN" not in evidence_ids
        report = json.dumps(result, ensure_ascii=False)
        assert "PAGE-NEW-TOKEN-ZZZ" in report
        assert "UNIQUE_TOKEN_WIKI_UPDATE_2026" in report
        assert "UPDATED_BODY_TOKEN_ON_APPROVED_PAGE" in report
        assert "DRAFT_TOKEN_MUST_NOT_LEAK" not in report
        assert "PAGE-DRAFT-STILL-HIDDEN" not in report
        last = state["last_validation"]
        last_ids = {e["page_id"] for e in last["evidence_references"]}
        assert "PAGE-NEW-TOKEN-ZZZ" in last_ids
        reader.close()


def test_export_envelope_is_common_envelope():
    envelope = build_export_envelope(
        {
            "session_id": "sid-1",
            "project_id": "PRJ-MES-01",
            "feature_title": "Demo",
            "feature_status": "VALIDATED",
            "artifacts": {"feature_definition": {"goal": "x"}},
            "flags": {},
            "last_validation": {"status": "passed", "evidence_references": []},
        }
    )
    assert envelope["correlation_id"] == "sid-1"
    assert envelope["feature_id"] == "sid-1"
    assert envelope["artifact"]["type"] == "business_analysis_package"
    assert envelope["handoff"]["to"] == "designer-agent"
    assert envelope["payload"]["artifacts"]["feature_definition"]["goal"] == "x"


def test_export_and_readonly_lifecycle(sqlite_sync_db):
    client = TestClient(app)
    created = client.post(
        "/api/features/",
        json={"title": "Export demo", "description": "control plane"},
    )
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    denied = client.post(f"/api/features/{session_id}/export")
    assert denied.status_code == 409
    assert "VALIDATED" in denied.json()["detail"]

    anyio.run(persist_control_delta, session_id, {"feature_status": "VALIDATED"})

    exported = client.post(f"/api/features/{session_id}/export")
    assert exported.status_code == 200
    body = exported.json()
    assert body["correlation_id"] == session_id
    assert body["artifact"]["type"] == "business_analysis_package"
    assert body["handoff"]["to"] == "designer-agent"

    again = client.post(f"/api/features/{session_id}/export")
    assert again.status_code == 200
    assert again.json()["correlation_id"] == session_id

    chat = client.post(
        f"/api/v1/chat/{session_id}/message",
        json={
            "user_id": "ba-user",
            "ticket_type": "NEW_FEATURE",
            "user_message": "still chatting",
        },
    )
    assert chat.status_code == 409

    revalidate = client.post(
        f"/api/v1/chat/{session_id}/message",
        json={
            "user_id": "ba-user",
            "ticket_type": "NEW_FEATURE",
            "user_message": "[VALIDATE] Validate BA package",
            "action": "validate",
        },
    )
    assert revalidate.status_code == 200

    deleted = client.delete(f"/api/features/{session_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/features/{session_id}").status_code == 404


def test_project_id_for_session_stable_and_unique():
    a = project_id_for_session("session-aaa")
    b = project_id_for_session("session-bbb")
    assert a == project_id_for_session("session-aaa")
    assert a.startswith("PRJ-")
    assert len(a) == len("PRJ-") + 12
    assert all(c in "0123456789ABCDEF" for c in a[4:])
    assert a != b


def test_feature_documents_uses_wiki_adapter(sqlite_sync_db, tmp_path, monkeypatch):
    monkeypatch.setenv("WIKI_DATA_DIR", str(tmp_path))

    client = TestClient(app)
    created = client.post(
        "/api/features/",
        json={"title": "Docs demo", "description": "wiki"},
    )
    assert created.status_code == 201
    created_body = created.json()
    session_id = created_body["session_id"]
    project_id = project_id_for_session(session_id)
    assert created_body["project_id"] == project_id
    assert project_id != "PRJ-MES-01"

    store = WikiStore(tmp_path)
    store.seed_page(
        page_id="PAGE-DOC-001",
        title="Quy tắc ghi sổ",
        body="Mọi giao dịch phải được ghi sổ.",
        project_id=project_id,
        bucket_id="business_rule",
    )
    store.close()

    docs = client.get(f"/api/features/{session_id}/documents", params={"q": "ghi sổ"})
    assert docs.status_code == 200
    payload = docs.json()
    assert payload["session_id"] == session_id
    assert payload["project_id"] == project_id
    assert any(d["page_id"] == "PAGE-DOC-001" for d in payload["documents"])

    extra = WikiStore(tmp_path)
    for i in range(6):
        extra.seed_page(
            page_id=f"PAGE-DOC-EXTRA-{i + 1:02d}",
            title=f"Extra {i + 1}",
            body=f"Additional approved page {i + 1}.",
            project_id=project_id,
        )
    extra.close()
    listed = client.get(f"/api/features/{session_id}/documents")
    assert listed.status_code == 200
    body = listed.json()
    ids = {d["page_id"] for d in body["documents"]}
    assert "PAGE-DOC-001" in ids
    assert "PAGE-DOC-EXTRA-06" in ids
    assert len(ids) >= 7
    assert "company_documents" in body
    assert "project_documents" in body
    assert body["project_id"] == project_id
    for hit in body["company_documents"]:
        assert hit.get("namespace") == "company"
    for hit in body["project_documents"]:
        assert hit.get("namespace") != "company"
    assert {d["page_id"] for d in body["documents"]} == (
        {d["page_id"] for d in body["company_documents"]}
        | {d["page_id"] for d in body["project_documents"]}
    )
    # Never validated → every approved page is unchecked (not silent pass).
    assert "wiki_validation" in body
    assert body["wiki_validation"]["has_run"] is False
    assert body["wiki_validation"]["overall"] == "unchecked"
    assert all(d.get("validation_status") == "unchecked" for d in body["documents"])
    assert all(d.get("status") == "approved" for d in body["documents"])


def test_wiki_human_list_and_approve(tmp_path, monkeypatch):
    """BA wiki page talks to the same MVP store. Approve stays human-only."""
    store = WikiStore(tmp_path)
    store.seed_page(
        page_id="PAGE-DRAFT-UI",
        title="Draft policy",
        body="Draft body for human approve.",
        project_id="PRJ-MES-01",
        bucket_id="business_rule",
        status="draft",
    )
    store.close()
    monkeypatch.setenv("WIKI_DATA_DIR", str(tmp_path))

    client = TestClient(app)
    listed = client.get("/api/wiki/pages", params={"project_id": "PRJ-MES-01"})
    assert listed.status_code == 200
    body = listed.json()
    assert "upload → draft → human approve" in body["import_flow"]
    assert any(p["page_id"] == "PAGE-DRAFT-UI" for p in body["drafts"])
    assert not any(p["page_id"] == "PAGE-DRAFT-UI" for p in body["approved"])

    approved = client.post(
        "/api/wiki/pages/PAGE-DRAFT-UI/approve",
        data={"actor": "ba.lead", "project_id": "PRJ-MES-01"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    again = client.get("/api/wiki/pages", params={"project_id": "PRJ-MES-01"})
    again_body = again.json()
    assert any(p["page_id"] == "PAGE-DRAFT-UI" for p in again_body["approved"])
    assert "company_approved" in again_body and "project_approved" in again_body
    assert any(p["page_id"] == "PAGE-DRAFT-UI" for p in again_body["project_approved"])
    assert not any(p["page_id"] == "PAGE-DRAFT-UI" for p in again_body["company_approved"])

    demoted = client.post(
        "/api/wiki/pages/PAGE-DRAFT-UI/demote",
        data={"actor": "ba.lead", "project_id": "PRJ-MES-01"},
    )
    assert demoted.status_code == 200
    assert demoted.json()["status"] == "draft"
    after_demote = client.get("/api/wiki/pages", params={"project_id": "PRJ-MES-01"})
    assert any(p["page_id"] == "PAGE-DRAFT-UI" for p in after_demote.json()["drafts"])
    assert not any(p["page_id"] == "PAGE-DRAFT-UI" for p in after_demote.json()["approved"])

    # Re-approve then hard-delete
    client.post(
        "/api/wiki/pages/PAGE-DRAFT-UI/approve",
        data={"actor": "ba.lead", "project_id": "PRJ-MES-01"},
    )
    deleted = client.post(
        "/api/wiki/pages/PAGE-DRAFT-UI/delete",
        data={"actor": "ba.lead", "project_id": "PRJ-MES-01"},
    )
    assert deleted.status_code == 200
    assert deleted.json().get("deleted") == 1
    gone = client.get("/api/wiki/pages", params={"project_id": "PRJ-MES-01"})
    assert not any(p["page_id"] == "PAGE-DRAFT-UI" for p in gone.json()["drafts"])
    assert not any(p["page_id"] == "PAGE-DRAFT-UI" for p in gone.json()["approved"])


def test_wiki_human_upload_creates_drafts(tmp_path, monkeypatch):
    monkeypatch.setenv("WIKI_DATA_DIR", str(tmp_path))
    client = TestClient(app)
    uploaded = client.post(
        "/api/wiki/sources",
        files={
            "file": (
                "policy.txt",
                b"Constraint: stock cannot go negative.\nConvention: lot code is required.\n",
                "text/plain",
            )
        },
        data={
            "namespace": "project",
            "project_id": "PRJ-MES-01",
            "actor": "ba.lead",
            "sort_mode": "heuristic",
        },
    )
    assert uploaded.status_code == 200
    body = uploaded.json()
    assert body.get("ok") is True
    assert "import_flow" in body
    assert body.get("proposed_page_ids")
    listed = client.get("/api/wiki/pages", params={"project_id": "PRJ-MES-01"})
    draft_ids = {p["page_id"] for p in listed.json()["drafts"]}
    assert set(body["proposed_page_ids"]) <= draft_ids
    assert all(p["status"] in {"draft", "proposed"} for p in listed.json()["drafts"])


def test_wiki_clear_empties_approved_and_drafts(tmp_path, monkeypatch):
    store = WikiStore(tmp_path)
    store.seed_page(
        page_id="PAGE-CLEAR-DRAFT",
        title="Draft to wipe",
        body="Draft body that must disappear.",
        project_id="PRJ-MES-01",
        bucket_id="business_rule",
        status="draft",
    )
    store.seed_page(
        page_id="PAGE-CLEAR-OK",
        title="Approved to wipe",
        body="Approved body that must disappear.",
        project_id="PRJ-MES-01",
        bucket_id="business_rule",
        status="approved",
    )
    store.close()
    monkeypatch.setenv("WIKI_DATA_DIR", str(tmp_path))

    client = TestClient(app)
    before = client.get("/api/wiki/pages", params={"project_id": "PRJ-MES-01"})
    assert any(p["page_id"] == "PAGE-CLEAR-DRAFT" for p in before.json()["drafts"])
    assert any(p["page_id"] == "PAGE-CLEAR-OK" for p in before.json()["approved"])

    refused = client.post("/api/wiki/clear", data={"confirm": "nope", "actor": "ba.lead"})
    assert refused.status_code == 400

    still_there = client.get("/api/wiki/pages", params={"project_id": "PRJ-MES-01"})
    assert still_there.json()["drafts"]
    assert still_there.json()["approved"]

    cleared = client.post("/api/wiki/clear", data={"confirm": "CLEAR", "actor": "ba.lead"})
    assert cleared.status_code == 200
    assert cleared.json()["ok"] is True
    assert cleared.json()["cleared"] is True

    empty = client.get("/api/wiki/pages", params={"project_id": "PRJ-MES-01"})
    assert empty.json()["drafts"] == []
    assert empty.json()["approved"] == []

    uploaded = client.post(
        "/api/wiki/sources",
        files={
            "file": (
                "after-clear.txt",
                b"Constraint: stock cannot go negative.\nConvention: lot code is required.\n",
                "text/plain",
            )
        },
        data={
            "namespace": "project",
            "project_id": "PRJ-MES-01",
            "actor": "ba.lead",
            "sort_mode": "heuristic",
        },
    )
    assert uploaded.status_code == 200
    assert uploaded.json().get("proposed_page_ids")
    after = client.get("/api/wiki/pages", params={"project_id": "PRJ-MES-01"})
    assert after.json()["drafts"]
    assert after.json()["approved"] == []


def test_wiki_clear_does_not_wipe_ba_packages(sqlite_sync_db, tmp_path, monkeypatch):
    monkeypatch.setenv("WIKI_DATA_DIR", str(tmp_path))
    client = TestClient(app)

    created = client.post(
        "/api/features/",
        json={"title": "Must survive wiki clear", "description": "BA package"},
    )
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    store = WikiStore(tmp_path)
    store.seed_page(
        page_id="PAGE-KEEP-BA",
        title="Wiki page that clear may wipe",
        body="This wiki row should disappear; the feature must not.",
        project_id="PRJ-MES-01",
        bucket_id="business_rule",
        status="approved",
    )
    store.close()

    before_wiki = client.get("/api/wiki/pages", params={"project_id": "PRJ-MES-01"})
    assert any(p["page_id"] == "PAGE-KEEP-BA" for p in before_wiki.json()["approved"])

    cleared = client.post("/api/wiki/clear", data={"confirm": "CLEAR", "actor": "ba.lead"})
    assert cleared.status_code == 200
    assert cleared.json()["cleared"] is True
    # Platform: the wiki store is the Postgres schema WIKI_DB_SCHEMA.
    assert cleared.json()["wiki_db"] == f"postgres:{os.environ['WIKI_DB_SCHEMA']}"

    empty = client.get("/api/wiki/pages", params={"project_id": "PRJ-MES-01"})
    assert empty.json()["drafts"] == []
    assert empty.json()["approved"] == []

    kept = client.get(f"/api/features/{session_id}")
    assert kept.status_code == 200
    assert kept.json()["title"] == "Must survive wiki clear"
    listed = client.get("/api/features/")
    assert listed.status_code == 200
    assert any(item["session_id"] == session_id for item in listed.json())


def test_wiki_reset_refuses_colocated_ba_tables(tmp_path, monkeypatch):
    monkeypatch.setenv("WIKI_DATA_DIR", str(tmp_path))
    store = WikiStore(tmp_path)
    # Platform: a BA table inside the wiki schema must block the clear.
    store.conn.execute("CREATE TABLE ba_packages (session_id TEXT)")
    store.close()
    with pytest.raises(WikiResetError, match="ba_packages"):
        reset_wiki_store(tmp_path)


def test_status_helpers():
    assert can_export("VALIDATED") is True
    assert can_export("PENDING_VALIDATION") is False
    assert can_export("EXPORTED") is True
    assert can_export("EXPORTED", {"status": "passed"}) is True
    assert can_export("EXPORTED", {"status": "failed"}) is False
    assert can_validate("EXPORTED") is True
    assert is_readonly("EXPORTED") is True
    assert is_chat_frozen("VALIDATED", True) is True
    assert is_chat_frozen("VALIDATED", False) is False

"""Group 2 BPMN / UI touchpoints + VA page gating on the same control plane."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import anyio
import pytest
from fastapi.testclient import TestClient

from agents.ba_agent.constants import (
    ROUTE_VALIDATE,
    SECTION_VALIDATION,
    STATE_ACTIVE_SECTION,
    STATE_TICKET_TYPE,
    TICKET_NEW_FEATURE,
)
from agents.ba_agent.router import route_ba_turn
from agents.sub_graph.validation_agent.logic import run_va_turn
from config.base_config import Settings
from factory_wiki.store import WikiStore
from managers.control.bpmn import (
    build_bpmn_xml,
    can_generate_bpmn,
    ensure_bpmn_artifact,
)
from managers.control.export import build_export_envelope
from managers.control.session import persist_control_delta
from managers.control.touchpoints import ensure_touchpoints_artifact
import managers.runner_context as rc
from server import app


COMPLETE_FLAGS = {
    "fd": {
        "FD-F1": {"status": "PASS"},
        "FD-F2": {"status": "PASS"},
        "FD-F3": {"status": "PASS"},
        "FD-F5": {"status": "PASS"},
    },
    "br": {"BR-F1": {"status": "PASS"}, "BR-F4": {"status": "PASS"}},
    "wf": {
        "WF-F1": {"status": "PASS"},
        "WF-F2": {"status": "PASS"},
        "WF-F4": {"status": "PASS"},
    },
    "uc": {
        "UC-F1": {"status": "PASS"},
        "UC-F2": {"status": "PASS"},
        "UC-F3": {"status": "PASS"},
        "UC-F5": {"status": "PASS"},
        "UC-F7": {"status": "PASS"},
        "UC-F8": {"status": "PASS"},
    },
}

WORKFLOW_MD = """
## Main Flow
| Step | Actor | Action | BR | Gateway |
|------|-------|--------|----|---------|
| 1 | ACT-KE-TOAN | Tạo phiếu chi | BR-01 | |
| 2 | ACT-SYSTEM | Kiểm tra ngưỡng | BR-01 | XOR |
| 3 | ACT-PO | Phê duyệt | BR-02 | AND |

## Exception Flows
| ID | Condition | Handling |
|----|-----------|----------|
| E-01 | Timeout | Retry rồi hủy |

## End States
- END-APPROVED: Đã duyệt
- END-CANCELLED: Hủy
"""


def _complete_package() -> dict:
    return {
        "session_id": "sid-g2",
        "feature_title": "Phiếu chi nội bộ",
        "feature_status": "PENDING_VALIDATION",
        "open_questions": [],
        "flags": COMPLETE_FLAGS,
        "artifacts": {
            "feature_definition": {
                "goal": "Theo dõi phiếu chi",
                "actors": ["ACT-KE-TOAN: Kế toán", "ACT-PO: PO"],
                "scope_in": ["Tạo phiếu"],
            },
            "business_rules": [
                {"id": "BR-01", "statement": "Phiếu chi phải có mục đích", "source": "PO"},
                {"id": "BR-02", "statement": "PO phê duyệt khi trên ngưỡng", "source": "Policy"},
            ],
            "workflow": {"workflow_md_content": WORKFLOW_MD},
            "use_cases": [
                {
                    "id": "US-01",
                    "actor_id": "ACT-KE-TOAN",
                    "statement": "Là kế toán, tôi muốn tạo phiếu chi để ghi nhận.",
                    "acceptance_criteria": [
                        {"id": "AC-01", "given": "g", "when": "w", "then": "t"}
                    ],
                }
            ],
        },
    }


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


def test_no_bpmn_before_tier1_complete():
    state = {"flags": {"fd": {"FD-F1": {"status": "PASS"}}}, "artifacts": {}}
    assert can_generate_bpmn(state) is False
    assert ensure_bpmn_artifact(state) is None
    assert "bpmn_reference" not in (state.get("artifacts") or {})


def test_bpmn_xml_contains_definitions_after_uc():
    state = _complete_package()
    artifact = ensure_bpmn_artifact(state)
    assert artifact is not None
    xml = artifact["bpmn_xml_content"]
    assert "xml" in xml.lower()
    assert "definitions" in xml.lower()
    assert "bpmn:process" in xml
    assert "Task_1" in xml
    assert "bpmn:collaboration" in xml
    assert "bpmn:participant" in xml
    assert "bpmn:lane" in xml
    assert "bpmn:userTask" in xml
    assert "exclusiveGateway" in xml
    assert "parallelGateway" in xml
    assert "bpmndi:BPMNShape" in xml
    assert 'isHorizontal="true"' in xml
    assert artifact.get("story_id") == "US-01"
    assert "US-01" in (state.get("artifacts") or {}).get("bpmn_by_story", {})
    assert state["artifacts"]["bpmn_reference"] is state["artifacts"]["bpmn_by_story"]["US-01"]


def test_deterministic_bpmn_from_numbered_steps():
    xml = build_bpmn_xml(
        feature_title="Demo",
        workflow_md="## Main Flow\n1. ACT-A starts\n2. ACT-B reviews\n3. ACT-A ends\n",
        artifact_id="BPMN-DEMO-001",
        allowed_actors=["ACT-A", "ACT-B"],
    )
    assert "<bpmn:definitions" in xml
    assert "ACT-A" in xml or "starts" in xml
    assert "bpmndi:BPMNShape" in xml
    assert "bpmn:collaboration" in xml


def test_bpmn_gateway_column_xor_and():
    xml = build_bpmn_xml(
        feature_title="Gateways",
        workflow_md=WORKFLOW_MD,
        artifact_id="BPMN-GW-001",
        allowed_actors=["ACT-KE-TOAN", "ACT-SYSTEM", "ACT-PO"],
    )
    assert "exclusiveGateway" in xml
    assert "parallelGateway" in xml
    assert 'isMarkerVisible="true"' in xml
    assert "Lane_ACT_KE_TOAN" in xml or "ACT-KE-TOAN" in xml
    # Do not invent Management/Supplier lanes
    assert "Management" not in xml
    assert "Supplier" not in xml


def test_bpmn_does_not_invent_actors_outside_fd():
    xml = build_bpmn_xml(
        feature_title="Scoped",
        workflow_md=(
            "## Main Flow\n"
            "| Step | Actor | Action | BR | Gateway |\n"
            "|------|-------|--------|----|---------|\n"
            "| 1 | ACT-KE-TOAN | Create | BR-01 | |\n"
            "| 2 | ACT-SUPPLIER | Invented | BR-01 | |\n"
        ),
        artifact_id="BPMN-SCOPED",
        allowed_actors=["ACT-KE-TOAN", "ACT-PO"],
    )
    assert "Lane_ACT_SUPPLIER" not in xml
    assert "ACT-SUPPLIER" not in xml
    assert "ACT-KE-TOAN" in xml


def test_touchpoints_schema_and_envelope():
    state = _complete_package()
    ensure_bpmn_artifact(state)
    items = ensure_touchpoints_artifact(state)
    assert items
    first = items[0]
    for key in (
        "id",
        "name",
        "actor",
        "trigger",
        "screen",
        "goal",
        "notes",
        "related_uc_ids",
        "bpmn_node_id",
        "interaction",
    ):
        assert key in first
    envelope = build_export_envelope(state)
    assert envelope["handoff"]["to"] == "designer-agent"
    payload_tp = envelope["payload"]["artifacts"]["ui_touchpoints"]
    assert isinstance(payload_tp, list) and payload_tp
    xml = envelope["payload"]["artifacts"]["bpmn_reference"]["bpmn_xml_content"]
    assert "definitions" in xml.lower()


def test_bpmn_http_409_before_ready(sqlite_sync_db):
    client = TestClient(app)
    created = client.post("/api/features/", json={"title": "No BPMN yet", "description": ""})
    session_id = created.json()["session_id"]
    denied = client.get(f"/api/features/{session_id}/bpmn")
    assert denied.status_code == 409
    assert "FD" in denied.json()["detail"] or "UC" in denied.json()["detail"]


def test_bpmn_http_download_when_ready(sqlite_sync_db):
    client = TestClient(app)
    created = client.post("/api/features/", json={"title": "Ready BPMN", "description": ""})
    session_id = created.json()["session_id"]
    pkg = _complete_package()
    anyio.run(
        persist_control_delta,
        session_id,
        {
            "flags": pkg["flags"],
            "artifacts": pkg["artifacts"],
            "feature_status": "PENDING_VALIDATION",
            "open_questions": [],
            "feature_title": "Ready BPMN",
        },
    )
    resp = client.get(f"/api/features/{session_id}/bpmn")
    assert resp.status_code == 200
    body = resp.text.lower()
    assert "xml" in body
    assert "definitions" in body
    assert "application/xml" in resp.headers.get("content-type", "")


def test_bpmn_http_regenerate_persists_into_feature_state(sqlite_sync_db):
    """regenerate=true rebuilds XML and writes artifacts.bpmn_reference for chat preview."""
    client = TestClient(app)
    created = client.post("/api/features/", json={"title": "Regen BPMN", "description": ""})
    session_id = created.json()["session_id"]
    pkg = _complete_package()
    stale = {
        "artifact_id": "BPMN-STALE",
        "version": "0.0.1",
        "source": "stale",
        "story_id": "US-01",
        "bpmn_xml_path": "stale.bpmn",
        "bpmn_xml_content": (
            '<?xml version="1.0"?><bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
            'exporter="ba-agent"><bpmn:process id="p"/></bpmn:definitions>'
        ),
        "validation_status": "draft",
        "steps": [],
        "exceptions": [],
        "end_states": [],
    }
    arts = dict(pkg["artifacts"])
    arts["bpmn_reference"] = stale
    arts["bpmn_by_story"] = {"US-01": stale}
    anyio.run(
        persist_control_delta,
        session_id,
        {
            "flags": pkg["flags"],
            "artifacts": arts,
            "feature_status": "VALIDATED",
            "open_questions": [],
            "feature_title": "Regen BPMN",
            "active_user_story_id": "US-01",
        },
    )
    before = client.get(f"/api/features/{session_id}")
    assert before.status_code == 200
    before_xml = before.json()["sections"]["bpmn_reference"]["data"]["bpmn_xml_content"]
    assert "BPMN-STALE" in str(before.json()["sections"]["bpmn_reference"]["data"].get("artifact_id"))

    regen = client.get(f"/api/features/{session_id}/bpmn", params={"regenerate": "true"})
    assert regen.status_code == 200
    assert "collaboration" in regen.text.lower() or "definitions" in regen.text.lower()
    assert regen.text != before_xml

    after = client.get(f"/api/features/{session_id}")
    assert after.status_code == 200
    data = after.json()["sections"]["bpmn_reference"]["data"]
    assert data["bpmn_xml_content"] == regen.text
    assert data.get("layout_engine") in {"elk", "diy"}
    assert data.get("artifact_id") != "BPMN-STALE"


def test_bpmn_http_redownload_and_after_export(sqlite_sync_db):
    """GET BPMN is idempotent; after EXPORTED, re-download stays 200 (regenerate is 409)."""
    client = TestClient(app)
    created = client.post("/api/features/", json={"title": "BPMN twice", "description": ""})
    session_id = created.json()["session_id"]
    pkg = _complete_package()
    anyio.run(
        persist_control_delta,
        session_id,
        {
            "flags": pkg["flags"],
            "artifacts": pkg["artifacts"],
            "feature_status": "VALIDATED",
            "open_questions": [],
            "feature_title": "BPMN twice",
        },
    )
    first = client.get(f"/api/features/{session_id}/bpmn")
    second = client.get(f"/api/features/{session_id}/bpmn")
    assert first.status_code == 200
    assert second.status_code == 200
    assert "definitions" in first.text.lower()
    assert "definitions" in second.text.lower()

    exported = client.post(f"/api/features/{session_id}/export")
    assert exported.status_code == 200
    after = client.get(f"/api/features/{session_id}/bpmn")
    assert after.status_code == 200
    regen = client.get(f"/api/features/{session_id}/bpmn", params={"regenerate": "true"})
    assert regen.status_code == 409

    chat = client.post(
        f"/api/v1/chat/{session_id}/message",
        json={
            "user_id": "ba-user",
            "ticket_type": "NEW_FEATURE",
            "user_message": "still chatting",
        },
    )
    assert chat.status_code == 409

    from google.adk.models.llm_response import LlmResponse
    from google.genai import types

    mock_llm_res = LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text="Coverage looks fine. Cite check_id from the last report.")],
        ),
        turn_complete=True,
    )

    async def dummy_lite_llm_gen(*args, **kwargs):
        yield mock_llm_res

    with patch(
        "google.adk.models.lite_llm.LiteLlm.generate_content_async",
        side_effect=dummy_lite_llm_gen,
    ):
        va_discuss = client.post(
            f"/api/v1/chat/{session_id}/message",
            json={
                "user_id": "ba-user",
                "ticket_type": "NEW_FEATURE",
                "active_section": "validation",
                "user_message": "what is the coverage?",
            },
        )
    assert va_discuss.status_code == 200

    refresh_va = client.post(
        f"/api/v1/chat/{session_id}/message",
        json={
            "user_id": "ba-user",
            "ticket_type": "NEW_FEATURE",
            "user_message": "[VALIDATE] Validate BA package",
            "action": "validate",
        },
    )
    assert refresh_va.status_code == 200
    refresh_export = client.post(f"/api/features/{session_id}/export")
    assert refresh_export.status_code == 200


def test_router_validation_section_uses_va_subgraph():
    ctx = MagicMock()
    ctx.state = {
        STATE_TICKET_TYPE: TICKET_NEW_FEATURE,
        STATE_ACTIVE_SECTION: SECTION_VALIDATION,
    }
    ctx.route = None
    part = MagicMock()
    part.text = "What failed?"
    ctx.user_content.parts = [part]
    route_ba_turn(ctx)
    assert ctx.route == ROUTE_VALIDATE


def test_va_too_early_explains_and_does_not_change_status():
    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        artifacts = {"feature_definition": {"goal": "keep"}}
        state = {
            "feature_status": "IN_PROGRESS",
            "artifacts": artifacts,
            "flags": {},
            "open_questions": [],
            "_va_run_validate": True,
        }
        msg = run_va_turn(state, store, "[VALIDATE] now")
        assert "tuần tự" in msg.lower() or "fd" in msg.lower()
        assert state["feature_status"] == "IN_PROGRESS"
        assert state["artifacts"]["feature_definition"]["goal"] == "keep"
        assert state.get("_va_result") is None


def test_va_discuss_does_not_mutate_artifacts():
    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        state = _complete_package()
        state["feature_status"] = "VALIDATED"
        state["last_validation"] = {
            "status": "passed",
            "agent_response": "📋 **Validation PASSED**",
            "failed_checks": [],
            "warnings": [],
            "evidence_references": [
                {"page_id": "PAGE-FINANCE-ORG", "title": "Finance"}
            ],
        }
        original_goal = state["artifacts"]["feature_definition"]["goal"]
        msg = run_va_turn(state, store, "wiki evidence ids?")
        assert "PAGE-FINANCE-ORG" in msg
        assert state["artifacts"]["feature_definition"]["goal"] == original_goal
        assert state["feature_status"] == "VALIDATED"


def test_va_run_works_on_adk_like_state_without_pop():
    """ADK session State is mapping-like and has no dict.pop."""

    class AdkLikeState:
        def __init__(self, data):
            self._d = data

        def get(self, key, default=None):
            return self._d.get(key, default)

        def __getitem__(self, key):
            return self._d[key]

        def __setitem__(self, key, value):
            self._d[key] = value

        def __contains__(self, key):
            return key in self._d

    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        raw = _complete_package()
        raw["_va_run_validate"] = True
        state = AdkLikeState(raw)
        msg = run_va_turn(state, store, "[VALIDATE] Validate BA package")
        assert "Validation" in msg or "blocked" in msg.lower() or "tuần tự" in msg.lower()
        assert state.get("feature_status") in {
            "VALIDATED",
            "VALIDATION_FAILED",
            "PENDING_VALIDATION",
        }


def test_touchpoints_put_requires_group2(sqlite_sync_db):
    client = TestClient(app)
    created = client.post("/api/features/", json={"title": "TP early", "description": ""})
    session_id = created.json()["session_id"]
    denied = client.put(
        f"/api/features/{session_id}/touchpoints",
        json={"ui_touchpoints": [{"id": "UIT-01", "name": "Screen"}]},
    )
    assert denied.status_code == 409

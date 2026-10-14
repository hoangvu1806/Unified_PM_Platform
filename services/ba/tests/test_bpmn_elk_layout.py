"""ELK-BPMN JSON shape + DIY fallback when Node layout is unavailable."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from managers.control.bpmn import (
    assemble_flow_graph,
    build_bpmn_xml,
    render_diy_bpmn_xml,
)
from managers.control.bpmn_elk import (
    build_elk_bpmn_json,
    elk_layout_available,
    layout_elk_bpmn,
    resolve_node_binary,
)

TINY_WF = """
## Main Flow
| Step | Actor | Action | BR | Gateway |
|------|-------|--------|----|---------|
| 1 | ACT-A | Create | BR-01 | |
| 2 | ACT-B | Review | BR-01 | XOR |

## End States
- Done
"""


def test_elk_json_shape_for_tiny_wf():
    graph = assemble_flow_graph(
        feature_title="Tiny",
        workflow_md=TINY_WF,
        artifact_id="BPMN-TINY",
        allowed_actors=["ACT-A", "ACT-B"],
    )
    elk = build_elk_bpmn_json(graph)
    assert elk["id"].startswith("Definitions_")
    collab = elk["children"][0]
    assert collab["bpmn"]["type"] == "collaboration"
    participant = collab["children"][0]
    assert participant["bpmn"]["type"] == "participant"
    assert participant["bpmn"]["processRef"] == graph["process_id"]
    lanes = participant["children"]
    assert len(lanes) == 2
    assert {lane["bpmn"]["name"] for lane in lanes} == {"ACT-A", "ACT-B"}
    assert all(lane["bpmn"]["type"] == "lane" for lane in lanes)
    node_types = {
        child["bpmn"]["type"]
        for lane in lanes
        for child in lane.get("children") or []
    }
    assert "startEvent" in node_types
    assert "userTask" in node_types
    assert "exclusiveGateway" in node_types
    assert "endEvent" in node_types
    edges = participant["edges"]
    assert edges
    assert all(e["bpmn"]["type"] == "sequenceFlow" for e in edges)
    assert all(len(e["sources"]) == 1 and len(e["targets"]) == 1 for e in edges)
    # Never invent Management/Supplier
    names = " ".join(lane["bpmn"]["name"] for lane in lanes)
    assert "Management" not in names
    assert "Supplier" not in names


def test_diy_fallback_when_layout_unavailable(monkeypatch):
    monkeypatch.setenv("BA_BPMN_ELK_DISABLE", "1")
    xml = build_bpmn_xml(
        feature_title="Fallback",
        workflow_md=TINY_WF,
        artifact_id="BPMN-FB",
        allowed_actors=["ACT-A", "ACT-B"],
    )
    assert "bpmn:collaboration" in xml
    assert "bpmn:participant" in xml
    assert "bpmn:lane" in xml
    assert "bpmn:userTask" in xml
    assert "exclusiveGateway" in xml
    assert "bpmndi:BPMNShape" in xml
    assert 'isHorizontal="true"' in xml
    assert "ACT-A" in xml and "ACT-B" in xml
    assert "Management" not in xml


def test_diy_fallback_when_elk_raises():
    with patch(
        "managers.control.bpmn.layout_elk_bpmn",
        side_effect=RuntimeError("boom"),
    ):
        xml = build_bpmn_xml(
            feature_title="Raise",
            workflow_md=TINY_WF,
            artifact_id="BPMN-RAISE",
            allowed_actors=["ACT-A", "ACT-B"],
            prefer_elk=True,
        )
    assert "bpmn:collaboration" in xml
    assert "bpmndi:BPMNShape" in xml


def test_diy_render_matches_forced_path():
    graph = assemble_flow_graph(
        feature_title="DIY",
        workflow_md=TINY_WF,
        artifact_id="BPMN-DIY",
        allowed_actors=["ACT-A", "ACT-B"],
    )
    xml = render_diy_bpmn_xml(graph)
    forced = build_bpmn_xml(
        feature_title="DIY",
        workflow_md=TINY_WF,
        artifact_id="BPMN-DIY",
        allowed_actors=["ACT-A", "ACT-B"],
        prefer_elk=False,
    )
    assert xml == forced


@pytest.mark.skipif(
    os.environ.get("BA_BPMN_ELK_DISABLE", "").strip() in {"1", "true", "yes"},
    reason="BA_BPMN_ELK_DISABLE set",
)
def test_elk_smoke_when_node_present():
    if not elk_layout_available() or not resolve_node_binary():
        pytest.skip("Node / tools/bpmn_elk not available")
    graph = assemble_flow_graph(
        feature_title="ELK smoke",
        workflow_md=TINY_WF,
        artifact_id="BPMN-ELK",
        allowed_actors=["ACT-A", "ACT-B"],
        story_id="US-01",
    )
    elk = build_elk_bpmn_json(graph)
    xml = layout_elk_bpmn(elk)
    assert xml is not None
    assert "bpmndi:BPMNShape" in xml
    assert "bpmn:collaboration" in xml
    assert "bpmn:lane" in xml
    assert "isMarkerVisible=\"true\"" in xml or "isMarkerVisible='true'" in xml
    via_build = build_bpmn_xml(
        feature_title="ELK smoke",
        workflow_md=TINY_WF,
        artifact_id="BPMN-ELK",
        allowed_actors=["ACT-A", "ACT-B"],
        story_id="US-01",
    )
    assert "bpmndi:BPMNShape" in via_build
    assert "ACT-A" in via_build

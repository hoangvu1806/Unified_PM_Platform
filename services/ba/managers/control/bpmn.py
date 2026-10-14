"""Deterministic BPMN 2.0 collaboration XML from a Workflow markdown section.

Emits collaboration + participant + swimlanes (one lane per WF actor),
XOR/AND gateways from the Gateway column, and userTasks for human steps.
BPMNDI prefers ELK layout via Node ``tools/bpmn_elk`` when available; otherwise
DIY horizontal swimlanes (Y=lane, X=sequence). Client ensureBpmnDi remains a
fallback only when DI is missing.
"""

from __future__ import annotations

import logging
import re
from html import escape as xml_escape
from typing import Any

from agents.ba_agent.section_gate import all_required_sections_complete
from managers.control.bpmn_elk import build_elk_bpmn_json, layout_elk_bpmn

logger = logging.getLogger(__name__)

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"

# Horizontal swimlane layout (matches plan: Y = lane, X = sequence)
_LANE_HEIGHT = 140
_ORIGIN_X = 160
_ORIGIN_Y = 80
_COL_GAP = 180
_TASK_W, _TASK_H = 100, 80
_EVENT_W, _EVENT_H = 36, 36
_GW_W, _GW_H = 50, 50
_PARTICIPANT_PAD_X = 30
_PARTICIPANT_PAD_Y = 20
_PARTICIPANT_LABEL_W = 30


def can_generate_bpmn(state: dict[str, Any]) -> bool:
    """Group 2 BPMN unlocks only after sequential FD→BR→WF→UC is complete."""
    return all_required_sections_complete(state)


def _xml(text: str) -> str:
    return xml_escape(str(text or ""), quote=True)


def _slug(text: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", str(text or "").strip())
    cleaned = cleaned.strip("_") or fallback
    if cleaned[0].isdigit():
        cleaned = f"N_{cleaned}"
    return cleaned[:48]


def _heading_section(content: str, heading: str) -> str:
    lines = content.splitlines()
    start = None
    pattern = re.compile(rf"^#{{1,3}}\s*{re.escape(heading)}\b", re.IGNORECASE)
    for i, raw in enumerate(lines):
        if pattern.match(raw.strip()):
            start = i + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start, len(lines)):
        if re.match(r"^#{1,3}\s+\S", lines[j].strip()) and not pattern.match(
            lines[j].strip()
        ):
            end = j
            break
    return "\n".join(lines[start:end])


def _normalize_gateway(raw: str) -> str:
    token = str(raw or "").strip().upper()
    if not token or token in {"-", "—", "N/A", "NA", "NONE", "BLANK"}:
        return ""
    if token in {"XOR", "EXCLUSIVE", "X"} or "XOR" in token:
        return "XOR"
    if token in {"AND", "PARALLEL", "+"} or "AND" in token or "PARALLEL" in token:
        return "AND"
    return ""


def parse_workflow_steps(workflow_md: str) -> dict[str, Any]:
    """Extract main-flow steps, exceptions, and end states from markdown.

    Table columns: ``Step | Actor | Action | BR | Gateway`` (Gateway optional).
    """
    content = str(workflow_md or "")
    main = _heading_section(content, "Main Flow") or content
    steps: list[dict[str, str]] = []
    for raw in main.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not cells or re.match(r"^-+$", cells[0] or ""):
                continue
            header = " ".join(cells).lower()
            if header.startswith("step") or set(header.replace(" ", "")) <= {"-"}:
                continue
            step_no = cells[0]
            actor = cells[1] if len(cells) > 1 else ""
            action = cells[2] if len(cells) > 2 else step_no
            br_ref = cells[3] if len(cells) > 3 else ""
            gateway = _normalize_gateway(cells[4] if len(cells) > 4 else "")
            steps.append(
                {
                    "step": step_no,
                    "actor": actor,
                    "action": action,
                    "br_ref": br_ref,
                    "gateway": gateway,
                }
            )
            continue
        numbered = re.match(r"^(\d+)[.)]\s+(.+)$", line)
        if numbered:
            rest = numbered.group(2)
            actor, action = _split_actor_action(rest)
            steps.append(
                {
                    "step": numbered.group(1),
                    "actor": actor,
                    "action": action,
                    "br_ref": "",
                    "gateway": "",
                }
            )
            continue
        bullet = re.match(r"^[-*•]\s+(.+)$", line)
        if bullet:
            actor, action = _split_actor_action(bullet.group(1))
            steps.append(
                {
                    "step": str(len(steps) + 1),
                    "actor": actor,
                    "action": action,
                    "br_ref": "",
                    "gateway": "",
                }
            )

    exceptions: list[dict[str, str]] = []
    exc_section = _heading_section(content, "Exception Flows")
    for raw in exc_section.splitlines():
        line = raw.strip()
        if not line or line.startswith("|") and "condition" in line.lower():
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not cells or re.match(r"^-+$", cells[0] or ""):
                continue
            header = " ".join(cells).lower()
            if "id" in header and "condition" in header:
                continue
            exceptions.append(
                {
                    "id": cells[0],
                    "condition": cells[1] if len(cells) > 1 else cells[0],
                    "handling": cells[2] if len(cells) > 2 else "",
                }
            )
            continue
        item = re.match(r"^[-*•]?\s*(E-?\d+)?\s*[.—:-]?\s*(.+)$", line)
        if item:
            exceptions.append(
                {
                    "id": item.group(1) or f"E-{len(exceptions) + 1:02d}",
                    "condition": item.group(2),
                    "handling": "",
                }
            )

    end_states: list[str] = []
    end_section = _heading_section(content, "End States")
    for raw in end_section.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^[-*•]\s+", "", line)
        if line.startswith("|"):
            continue
        end_states.append(line)

    return {"steps": steps, "exceptions": exceptions, "end_states": end_states}


def _split_actor_action(text: str) -> tuple[str, str]:
    if ":" in text:
        actor, action = text.split(":", 1)
        return actor.strip(), action.strip()
    parts = text.split(None, 1)
    if len(parts) == 2 and parts[0].upper().startswith("ACT-"):
        return parts[0], parts[1]
    return "", text


def _fd_actor_ids(allowed_actors: list[str] | None) -> list[str]:
    """Normalize FD actor entries to lane labels (prefer ACT- ids)."""
    if not allowed_actors:
        return []
    out: list[str] = []
    for raw in allowed_actors:
        text = str(raw or "").strip()
        if not text:
            continue
        # "ACT-KE-TOAN: Kế toán" → ACT-KE-TOAN
        act_id = text.split(":", 1)[0].strip()
        if act_id and act_id not in out:
            out.append(act_id)
    return out


def _resolve_step_actor(
    raw_actor: str,
    *,
    allowed: list[str],
    fallback: str,
) -> str:
    actor = (raw_actor or "").strip()
    if not actor:
        return fallback
    if not allowed:
        return actor
    # Exact or prefix match against FD actors — never invent Management/Supplier.
    upper = actor.upper()
    for a in allowed:
        if a.upper() == upper or upper.startswith(a.upper()) or a.upper() in upper:
            return a
    # Actor not in FD/story: map to first allowed lane (do not invent new lanes).
    return allowed[0] if allowed else fallback


def _lane_actors(
    steps: list[dict[str, str]],
    *,
    allowed_actors: list[str] | None,
) -> list[str]:
    allowed = _fd_actor_ids(allowed_actors)
    fallback = allowed[0] if allowed else "Actor"
    actors: list[str] = []
    seen: set[str] = set()
    for step in steps:
        actor = _resolve_step_actor(
            step.get("actor") or "",
            allowed=allowed,
            fallback=fallback,
        )
        step["_lane"] = actor
        if actor not in seen:
            seen.add(actor)
            actors.append(actor)
    if not actors:
        actors = [fallback]
    return actors


def build_bpmn_xml(
    *,
    feature_title: str,
    workflow_md: str,
    artifact_id: str = "BPMN-001",
    allowed_actors: list[str] | None = None,
    story_id: str | None = None,
    prefer_elk: bool = True,
) -> str:
    """Build collaboration BPMN with lanes, gateways, and BPMNDI swimlanes.

    Prefers ELK layout (Node ``bpmn-elk-layout``) when available; on any failure
    falls back to DIY DI so generation never breaks.
    """
    xml, _engine = build_bpmn_xml_with_engine(
        feature_title=feature_title,
        workflow_md=workflow_md,
        artifact_id=artifact_id,
        allowed_actors=allowed_actors,
        story_id=story_id,
        prefer_elk=prefer_elk,
    )
    return xml


def build_bpmn_xml_with_engine(
    *,
    feature_title: str,
    workflow_md: str,
    artifact_id: str = "BPMN-001",
    allowed_actors: list[str] | None = None,
    story_id: str | None = None,
    prefer_elk: bool = True,
) -> tuple[str, str]:
    """Return ``(xml, layout_engine)`` where engine is ``elk`` or ``diy``."""
    graph = assemble_flow_graph(
        feature_title=feature_title,
        workflow_md=workflow_md,
        artifact_id=artifact_id,
        allowed_actors=allowed_actors,
        story_id=story_id,
    )
    if prefer_elk:
        try:
            elk_json = build_elk_bpmn_json(graph)
            laid_out = layout_elk_bpmn(elk_json)
            if laid_out:
                logger.info(
                    "bpmn layout path=elk artifact_id=%s story_id=%s",
                    artifact_id,
                    story_id or "",
                )
                return laid_out, "elk"
        except Exception as exc:
            # Never break BPMN generation — DIY path below.
            logger.info(
                "bpmn layout path=diy (elk error) artifact_id=%s err=%s",
                artifact_id,
                exc,
            )
    else:
        logger.info(
            "bpmn layout path=diy (prefer_elk=false) artifact_id=%s",
            artifact_id,
        )
    if prefer_elk:
        logger.info(
            "bpmn layout path=diy (elk unavailable) artifact_id=%s story_id=%s",
            artifact_id,
            story_id or "",
        )
    return render_diy_bpmn_xml(graph), "diy"


def assemble_flow_graph(
    *,
    feature_title: str,
    workflow_md: str,
    artifact_id: str = "BPMN-001",
    allowed_actors: list[str] | None = None,
    story_id: str | None = None,
) -> dict[str, Any]:
    """Parse WF markdown into the shared node/edge graph (semantics only)."""
    parsed = parse_workflow_steps(workflow_md)
    steps = parsed["steps"] or [
        {
            "step": "1",
            "actor": "",
            "action": "Main flow (placeholder)",
            "br_ref": "",
            "gateway": "",
        }
    ]
    exceptions = parsed["exceptions"]
    end_states = parsed["end_states"] or ["Complete"]

    actors = _lane_actors(steps, allowed_actors=allowed_actors)
    process_id = _slug(artifact_id, "Process_1")
    collab_id = f"Collaboration_{process_id}"
    participant_id = f"Participant_{process_id}"
    start_id = "StartEvent_1"

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    # Layout: list of (node_id, kind, lane_index, seq_index) for DIY DI
    layout: list[tuple[str, str, int, int]] = []
    lane_of: dict[str, str] = {}
    seq = 0
    first_lane = actors[0]
    lane_index = {a: i for i, a in enumerate(actors)}

    def _add_node(
        nid: str,
        kind: str,
        actor: str,
        *,
        element: str,
        name: str,
        marker_visible: bool = False,
    ) -> None:
        nonlocal seq
        nodes.append(
            {
                "id": nid,
                "kind": kind,
                "actor": actor,
                "element": element,
                "name": name,
                "marker_visible": marker_visible,
            }
        )
        layout.append((nid, kind, lane_index.get(actor, 0), seq))
        lane_of[nid] = actor
        seq += 1

    def _add_edge(fid: str, source: str, target: str, name: str = "") -> None:
        edges.append({"id": fid, "source": source, "target": target, "name": name})

    _add_node(start_id, "event", first_lane, element="startEvent", name="Start")

    prev = start_id
    flow_n = 1
    last_xor_id: str | None = None
    xor_is_terminal = False

    for i, step in enumerate(steps, start=1):
        actor = step.get("_lane") or first_lane
        task_id = f"Task_{i}"
        name = step.get("action") or step.get("step") or task_id
        _add_node(task_id, "task", actor, element="userTask", name=name)
        fid = f"Flow_{flow_n}"
        flow_n += 1
        _add_edge(fid, prev, task_id)
        prev = task_id

        gw = (step.get("gateway") or "").upper()
        if gw == "XOR":
            gw_id = f"Gateway_XOR_{i}"
            _add_node(
                gw_id,
                "gateway",
                actor,
                element="exclusiveGateway",
                name="XOR",
                marker_visible=True,
            )
            fid = f"Flow_{flow_n}"
            flow_n += 1
            _add_edge(fid, prev, gw_id)
            prev = gw_id
            last_xor_id = gw_id
            xor_is_terminal = i == len(steps)
        elif gw == "AND":
            gw_id = f"Gateway_AND_{i}"
            _add_node(
                gw_id,
                "gateway",
                actor,
                element="parallelGateway",
                name="AND",
            )
            fid = f"Flow_{flow_n}"
            flow_n += 1
            _add_edge(fid, prev, gw_id)
            prev = gw_id

    if exceptions and last_xor_id is None:
        gw_id = "Gateway_Exceptions"
        _add_node(
            gw_id,
            "gateway",
            first_lane,
            element="exclusiveGateway",
            name="Exceptions",
            marker_visible=True,
        )
        fid = f"Flow_{flow_n}"
        flow_n += 1
        _add_edge(fid, prev, gw_id)
        prev = gw_id
        last_xor_id = gw_id
        xor_is_terminal = True

    end_ids: list[str] = []
    for i, end in enumerate(end_states, start=1):
        eid = f"EndEvent_{i}"
        end_ids.append(eid)
        _add_node(eid, "event", first_lane, element="endEvent", name=end)

    if exceptions and last_xor_id and xor_is_terminal and prev == last_xor_id:
        fid = f"Flow_{flow_n}"
        flow_n += 1
        _add_edge(fid, last_xor_id, end_ids[0], name="happy")
    else:
        fid = f"Flow_{flow_n}"
        flow_n += 1
        _add_edge(fid, prev, end_ids[0])

    exc_actor = first_lane
    for i, exc in enumerate(exceptions, start=1):
        tid = f"Task_Exc_{i}"
        eid = f"EndEvent_Exc_{i}"
        label = exc["condition"] or exc["id"]
        _add_node(tid, "task", exc_actor, element="userTask", name=label)
        _add_node(
            eid,
            "event",
            exc_actor,
            element="endEvent",
            name=exc["id"] or f"E-{i}",
        )
        src = last_xor_id or prev
        fid = f"Flow_{flow_n}"
        flow_n += 1
        _add_edge(fid, src, tid, name=exc["id"])
        fid = f"Flow_{flow_n}"
        flow_n += 1
        _add_edge(fid, tid, eid)

    title = feature_title or artifact_id
    if story_id:
        title = f"{title} ({story_id})"

    lane_ids = {actor: "Lane_" + _slug(actor, "Actor") for actor in actors}

    return {
        "title": title,
        "participant_name": title,
        "process_id": process_id,
        "collab_id": collab_id,
        "participant_id": participant_id,
        "actors": actors,
        "lane_ids": lane_ids,
        "nodes": nodes,
        "edges": edges,
        "lane_of": lane_of,
        "layout": layout,
    }


def render_diy_bpmn_xml(graph: dict[str, Any]) -> str:
    """Hand-placed BPMNDI (Y=lane, X=sequence) — fallback when ELK is unavailable."""
    actors: list[str] = list(graph["actors"])
    nodes: list[dict[str, Any]] = list(graph["nodes"])
    edges: list[dict[str, Any]] = list(graph["edges"])
    lane_of: dict[str, str] = dict(graph["lane_of"])
    layout: list[tuple[str, str, int, int]] = list(graph["layout"])
    process_id = str(graph["process_id"])
    collab_id = str(graph["collab_id"])
    participant_id = str(graph["participant_id"])
    title = str(graph["title"])
    participant_name = str(graph["participant_name"])
    lane_ids: dict[str, str] = dict(graph["lane_ids"])

    node_elems = [_diy_node_xml(n) for n in nodes]
    flow_elems = [_diy_edge_xml(e) for e in edges]

    lane_xml: list[str] = []
    for actor in actors:
        lid = lane_ids[actor]
        refs = [
            f"      <bpmn:flowNodeRef>{nid}</bpmn:flowNodeRef>"
            for nid, a in lane_of.items()
            if a == actor
        ]
        lane_xml.append(
            f'      <bpmn:lane id="{lid}" name="{_xml(actor)}">\n'
            + "\n".join(refs)
            + "\n      </bpmn:lane>"
        )

    di_xml = _build_bpmndi(
        collab_id=collab_id,
        participant_id=participant_id,
        process_id=process_id,
        actors=actors,
        lane_ids=lane_ids,
        layout=layout,
        flows=flow_elems,
    )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<bpmn:definitions xmlns:bpmn="{BPMN_NS}" '
        f'xmlns:bpmndi="{BPMNDI_NS}" '
        f'xmlns:dc="{DC_NS}" '
        f'xmlns:di="{DI_NS}" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        f'id="Definitions_{_xml(process_id)}" name="{_xml(title)}" '
        'targetNamespace="https://imespro.ai/bpmn" exporter="ba-agent">\n'
        f'  <bpmn:collaboration id="{collab_id}">\n'
        f'    <bpmn:participant id="{participant_id}" name="{_xml(participant_name)}" '
        f'processRef="{process_id}"/>\n'
        "  </bpmn:collaboration>\n"
        f'  <bpmn:process id="{process_id}" name="{_xml(title)}" isExecutable="false">\n'
        "    <bpmn:laneSet>\n"
        + "\n".join(lane_xml)
        + "\n    </bpmn:laneSet>\n"
        + "\n".join(node_elems)
        + "\n"
        + "\n".join(flow_elems)
        + "\n"
        "  </bpmn:process>\n"
        + di_xml
        + "</bpmn:definitions>\n"
    )


def _diy_node_xml(node: dict[str, Any]) -> str:
    nid = node["id"]
    name = _xml(node.get("name") or "")
    element = node["element"]
    if element == "startEvent":
        return f'    <bpmn:startEvent id="{nid}" name="{name}"/>'
    if element == "endEvent":
        return f'    <bpmn:endEvent id="{nid}" name="{name}"/>'
    if element == "exclusiveGateway":
        return (
            f'    <bpmn:exclusiveGateway id="{nid}" name="{name}" '
            'isMarkerVisible="true"/>'
        )
    if element == "parallelGateway":
        return f'    <bpmn:parallelGateway id="{nid}" name="{name}"/>'
    return f'    <bpmn:userTask id="{nid}" name="{name}"/>'


def _diy_edge_xml(edge: dict[str, Any]) -> str:
    fid = edge["id"]
    src = edge["source"]
    tgt = edge["target"]
    name = edge.get("name") or ""
    if name:
        return (
            f'    <bpmn:sequenceFlow id="{fid}" name="{_xml(name)}" '
            f'sourceRef="{src}" targetRef="{tgt}"/>'
        )
    return f'    <bpmn:sequenceFlow id="{fid}" sourceRef="{src}" targetRef="{tgt}"/>'


def _node_size(kind: str) -> tuple[int, int]:
    if kind == "gateway":
        return _GW_W, _GW_H
    if kind == "event":
        return _EVENT_W, _EVENT_H
    return _TASK_W, _TASK_H


def _parse_flow_refs(flow_elems: list[str]) -> list[tuple[str, str, str]]:
    """Return (flow_id, source, target) from sequenceFlow XML lines."""
    out: list[tuple[str, str, str]] = []
    pat = re.compile(
        r'id="([^"]+)"[^>]*sourceRef="([^"]+)"[^>]*targetRef="([^"]+)"'
    )
    pat2 = re.compile(
        r'id="([^"]+)"[^>]*name="[^"]*"[^>]*sourceRef="([^"]+)"[^>]*targetRef="([^"]+)"'
    )
    for line in flow_elems:
        m = pat.search(line) or pat2.search(line)
        if m:
            out.append((m.group(1), m.group(2), m.group(3)))
    return out


def _build_bpmndi(
    *,
    collab_id: str,
    participant_id: str,
    process_id: str,
    actors: list[str],
    layout: list[tuple[str, str, int, int]],
    flows: list[str],
    lane_ids: dict[str, str] | None = None,
) -> str:
    """Horizontal swimlanes: Y = lane index, X = sequence index."""
    max_seq = max((s for _, _, _, s in layout), default=0)
    n_lanes = max(len(actors), 1)
    pool_w = _ORIGIN_X + (max_seq + 1) * _COL_GAP + 40
    pool_h = n_lanes * _LANE_HEIGHT + _PARTICIPANT_PAD_Y
    pool_x = _PARTICIPANT_PAD_X
    pool_y = _PARTICIPANT_PAD_Y
    resolved_lanes = lane_ids or {a: "Lane_" + _slug(a, "Actor") for a in actors}

    shapes: list[str] = []
    # Participant (pool)
    shapes.append(
        f'      <bpmndi:BPMNShape id="{participant_id}_di" bpmnElement="{participant_id}" isHorizontal="true">\n'
        f'        <dc:Bounds x="{pool_x}" y="{pool_y}" width="{pool_w}" height="{pool_h}"/>\n'
        "      </bpmndi:BPMNShape>"
    )
    # Lanes
    for i, actor in enumerate(actors):
        lid = resolved_lanes[actor]
        ly = pool_y + i * _LANE_HEIGHT
        shapes.append(
            f'      <bpmndi:BPMNShape id="{lid}_di" bpmnElement="{lid}" isHorizontal="true">\n'
            f'        <dc:Bounds x="{pool_x + _PARTICIPANT_LABEL_W}" y="{ly}" '
            f'width="{pool_w - _PARTICIPANT_LABEL_W}" height="{_LANE_HEIGHT}"/>\n'
            "      </bpmndi:BPMNShape>"
        )

    centers: dict[str, tuple[float, float]] = {}
    for nid, kind, lane_i, seq_i in layout:
        w, h = _node_size(kind)
        x = _ORIGIN_X + seq_i * _COL_GAP
        y = pool_y + lane_i * _LANE_HEIGHT + (_LANE_HEIGHT - h) / 2
        if kind == "gateway" and (
            "XOR" in nid.upper() or nid == "Gateway_Exceptions"
        ):
            marker = ' isMarkerVisible="true"'
        else:
            marker = ""
        shapes.append(
            f'      <bpmndi:BPMNShape id="{nid}_di" bpmnElement="{nid}"{marker}>\n'
            f'        <dc:Bounds x="{x:.0f}" y="{y:.0f}" width="{w}" height="{h}"/>\n'
            "      </bpmndi:BPMNShape>"
        )
        centers[nid] = (x + w / 2, y + h / 2)

    edges: list[str] = []
    for fid, src, tgt in _parse_flow_refs(flows):
        sc = centers.get(src)
        tc = centers.get(tgt)
        if not sc or not tc:
            continue
        edges.append(
            f'      <bpmndi:BPMNEdge id="{fid}_di" bpmnElement="{fid}">\n'
            f'        <di:waypoint x="{sc[0]:.0f}" y="{sc[1]:.0f}"/>\n'
            f'        <di:waypoint x="{tc[0]:.0f}" y="{tc[1]:.0f}"/>\n'
            "      </bpmndi:BPMNEdge>"
        )

    return (
        '  <bpmndi:BPMNDiagram id="BPMNDiagram_1">\n'
        f'    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="{collab_id}">\n'
        + "\n".join(shapes)
        + "\n"
        + "\n".join(edges)
        + "\n"
        "    </bpmndi:BPMNPlane>\n"
        "  </bpmndi:BPMNDiagram>\n"
    )


def resolve_active_story_id(state: dict[str, Any]) -> str:
    """Prefer ``active_user_story_id``; else US-01 / first use_cases id."""
    artifacts = state.get("artifacts") or {}
    cases = artifacts.get("use_cases") or []
    cases_list = cases if isinstance(cases, list) else []
    active = state.get("active_user_story_id")
    try:
        from agents.sub_graph.use_cases.merge import resolve_active_user_story_id

        resolved = resolve_active_user_story_id(
            [c for c in cases_list if isinstance(c, dict)],
            str(active).strip() if active else None,
        )
        if resolved:
            return str(resolved).strip()
    except Exception:
        pass
    if active:
        return str(active).strip()
    for case in cases_list:
        if isinstance(case, dict) and case.get("id"):
            cid = str(case["id"]).strip()
            if cid:
                return cid
    return "US-01"


def _allowed_actors_from_state(state: dict[str, Any]) -> list[str]:
    artifacts = state.get("artifacts") or {}
    fd = artifacts.get("feature_definition") or {}
    actors = fd.get("actors") if isinstance(fd, dict) else None
    if isinstance(actors, list) and actors:
        return [str(a) for a in actors]
    # Fall back to actors named on the active story only (do not invent).
    story_id = resolve_active_story_id(state)
    cases = artifacts.get("use_cases") or []
    for case in cases if isinstance(cases, list) else []:
        if isinstance(case, dict) and str(case.get("id") or "") == story_id:
            aid = case.get("actor_id")
            if aid:
                return [str(aid)]
    return []


def bpmn_artifact_from_state(state: dict[str, Any]) -> dict[str, Any]:
    artifacts = state.get("artifacts") or {}
    workflow = artifacts.get("workflow") or {}
    md = str(workflow.get("workflow_md_content") or "")
    title = str(state.get("feature_title") or "BA Feature")
    story_id = resolve_active_story_id(state)
    artifact_id = f"BPMN-{_slug(title, 'FEATURE')}-{_slug(story_id, 'US')}"
    allowed = _allowed_actors_from_state(state)
    xml, layout_engine = build_bpmn_xml_with_engine(
        feature_title=title,
        workflow_md=md,
        artifact_id=artifact_id,
        allowed_actors=allowed or None,
        story_id=story_id,
    )
    parsed = parse_workflow_steps(md)
    return {
        "artifact_id": artifact_id,
        "version": "1.0.0",
        "source": "deterministic_workflow",
        "layout_engine": layout_engine,
        "story_id": story_id,
        "bpmn_xml_path": f"{artifact_id}.bpmn",
        "bpmn_xml_content": xml,
        "validation_status": "draft",
        "steps": parsed["steps"],
        "exceptions": parsed["exceptions"],
        "end_states": parsed["end_states"],
    }


def ensure_bpmn_artifact(state: dict[str, Any], *, force: bool = False) -> dict[str, Any] | None:
    """Write bpmn_by_story[active] + bpmn_reference when Group 2 is unlocked."""
    if not can_generate_bpmn(state):
        return None
    artifacts = dict(state.get("artifacts") or {})
    story_id = resolve_active_story_id(state)
    by_story = dict(artifacts.get("bpmn_by_story") or {})
    existing = by_story.get(story_id)
    if (
        existing
        and isinstance(existing, dict)
        and existing.get("bpmn_xml_content")
        and not force
    ):
        artifacts["bpmn_reference"] = existing
        artifacts["bpmn_by_story"] = by_story
        state["artifacts"] = artifacts
        sections = dict(state.get("sections_status") or {})
        sections["bpmn_reference"] = "completed"
        state["sections_status"] = sections
        return existing

    # Also reuse legacy bpmn_reference if present and not forcing
    legacy = artifacts.get("bpmn_reference")
    if (
        legacy
        and isinstance(legacy, dict)
        and legacy.get("bpmn_xml_content")
        and legacy.get("story_id") == story_id
        and not force
        and "bpmndi:BPMNShape" in str(legacy.get("bpmn_xml_content") or "")
    ):
        by_story[story_id] = legacy
        artifacts["bpmn_by_story"] = by_story
        state["artifacts"] = artifacts
        return legacy

    artifact = bpmn_artifact_from_state(state)
    by_story[story_id] = artifact
    artifacts["bpmn_by_story"] = by_story
    artifacts["bpmn_reference"] = artifact
    state["artifacts"] = artifacts
    sections = dict(state.get("sections_status") or {})
    sections["bpmn_reference"] = "completed"
    state["sections_status"] = sections
    return artifact

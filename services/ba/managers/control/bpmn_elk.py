"""ELK-BPMN JSON emit + Node ``bpmn-elk-layout`` subprocess.

Python still owns diagram semantics; this module only asks Node to position
shapes. Any failure returns ``None`` so callers fall back to DIY BPMNDI.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

HELPER_DIR = Path(__file__).resolve().parents[2] / "tools" / "bpmn_elk"
LAYOUT_SCRIPT = HELPER_DIR / "layout.mjs"

# Prefer BA_NODE (shared with frontend e2e); BA_BPMN_NODE is an alias.
_NODE_ENV_KEYS = ("BA_BPMN_NODE", "BA_NODE")
_DEFAULT_TIMEOUT_S = 30.0


def resolve_node_binary() -> str | None:
    for key in _NODE_ENV_KEYS:
        env = os.environ.get(key)
        if env and Path(env).is_file():
            return env
    which = shutil.which("node")
    if which:
        return which
    for candidate in (
        "/usr/local/bin/node",
        "/usr/bin/node",
        str(Path.home() / ".local" / "node" / "bin" / "node"),
        "/Applications/Cursor.app/Contents/Resources/app/resources/helpers/node",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def elk_layout_available() -> bool:
    if os.environ.get("BA_BPMN_ELK_DISABLE", "").strip() in {"1", "true", "yes"}:
        return False
    if not LAYOUT_SCRIPT.is_file():
        return False
    if not (HELPER_DIR / "node_modules" / "bpmn-elk-layout").is_dir():
        return False
    return resolve_node_binary() is not None


def build_elk_bpmn_json(graph: dict[str, Any]) -> dict[str, Any]:
    """Convert the shared WF flow graph into ELK-BPMN JSON (collaboration + lanes)."""
    actors: list[str] = list(graph["actors"])
    nodes: list[dict[str, Any]] = list(graph["nodes"])
    edges: list[dict[str, Any]] = list(graph["edges"])
    title = str(graph["title"])
    process_id = str(graph["process_id"])
    collab_id = str(graph["collab_id"])
    participant_id = str(graph["participant_id"])
    participant_name = str(graph["participant_name"])

    by_lane: dict[str, list[dict[str, Any]]] = {a: [] for a in actors}
    for node in nodes:
        actor = node["actor"]
        if actor not in by_lane:
            by_lane[actor] = []
            actors.append(actor)
        child: dict[str, Any] = {
            "id": node["id"],
            "bpmn": _elk_node_bpmn(node),
        }
        by_lane[actor].append(child)

    lane_children: list[dict[str, Any]] = []
    for actor in actors:
        lid = graph["lane_ids"][actor]
        lane_children.append(
            {
                "id": lid,
                "bpmn": {"type": "lane", "name": actor},
                "children": by_lane.get(actor) or [],
            }
        )

    elk_edges: list[dict[str, Any]] = []
    for edge in edges:
        flow: dict[str, Any] = {
            "id": edge["id"],
            "sources": [edge["source"]],
            "targets": [edge["target"]],
            "bpmn": {"type": "sequenceFlow"},
        }
        if edge.get("name"):
            flow["bpmn"]["name"] = edge["name"]
        elk_edges.append(flow)

    return {
        "id": f"Definitions_{process_id}",
        "bpmn": {
            "targetNamespace": "https://imespro.ai/bpmn",
            "exporter": "ba-agent",
            "exporterVersion": "1.0.0",
        },
        "layoutOptions": {
            "elk.algorithm": "layered",
            "elk.direction": "RIGHT",
            "elk.edgeRouting": "ORTHOGONAL",
            "elk.spacing.nodeNode": 40,
            "elk.layered.spacing.nodeNodeBetweenLayers": 60,
            "elk.hierarchyHandling": "INCLUDE_CHILDREN",
        },
        "children": [
            {
                "id": collab_id,
                "bpmn": {"type": "collaboration", "name": title},
                "children": [
                    {
                        "id": participant_id,
                        "bpmn": {
                            "type": "participant",
                            "name": participant_name,
                            "processRef": process_id,
                        },
                        "children": lane_children,
                        "edges": elk_edges,
                    }
                ],
            }
        ],
    }


def _elk_node_bpmn(node: dict[str, Any]) -> dict[str, Any]:
    element = node["element"]
    name = node.get("name") or ""
    if element in {"startEvent", "endEvent"}:
        return {
            "type": element,
            "eventDefinitionType": "none",
            "name": name,
        }
    if element == "exclusiveGateway":
        return {"type": "exclusiveGateway", "name": name or "XOR"}
    if element == "parallelGateway":
        return {"type": "parallelGateway", "name": name or "AND"}
    return {"type": "userTask", "name": name}


def layout_elk_bpmn(elk_json: dict[str, Any], *, timeout_s: float | None = None) -> str | None:
    """Run Node helper; return BPMN XML or ``None`` on any failure."""
    if not elk_layout_available():
        logger.info("bpmn ELK layout skipped (helper/node unavailable or disabled)")
        return None
    node = resolve_node_binary()
    if not node:
        logger.info("bpmn ELK layout skipped (no node binary)")
        return None
    if timeout_s is None:
        try:
            timeout_s = float(os.environ.get("BA_BPMN_ELK_TIMEOUT", _DEFAULT_TIMEOUT_S))
        except ValueError:
            timeout_s = _DEFAULT_TIMEOUT_S
    payload = json.dumps(elk_json, ensure_ascii=False)
    try:
        proc = subprocess.run(
            [node, str(LAYOUT_SCRIPT)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(HELPER_DIR),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.info("bpmn ELK layout unavailable: %s", exc)
        return None
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:500]
        logger.info("bpmn ELK layout failed (rc=%s): %s", proc.returncode, err)
        return None
    xml = proc.stdout or ""
    if "bpmndi:BPMN" not in xml or "bpmn:collaboration" not in xml:
        logger.info("bpmn ELK layout missing collaboration/DI")
        return None
    logger.info("bpmn ELK layout ok (%s bytes)", len(xml))
    return _normalize_elk_xml(xml)


def _normalize_elk_xml(xml: str) -> str:
    """Align a few ELK defaults with DIY semantics (XOR marker, non-executable)."""
    import re

    def xor_repl(match: re.Match[str]) -> str:
        attrs = match.group(1)
        if "isMarkerVisible" in attrs:
            return match.group(0)
        return f'<bpmn:exclusiveGateway isMarkerVisible="true"{attrs}>'

    xml = re.sub(r"<bpmn:exclusiveGateway([^>]*)>", xor_repl, xml)
    xml = re.sub(
        r'(<bpmn:process\b[^>]*\bisExecutable=")true(")',
        r'\1false\2',
        xml,
    )
    if not xml.endswith("\n"):
        xml += "\n"
    return xml

import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_MARKDOWN_CHARS = 10_000
SKIPPED_JSON_KEYS = {
    "bpmn_xml_content",
    "agent_response",
    "provenance",
    "input_references",
    "flags",
    "skill_versions",
}


@dataclass(frozen=True)
class ParsedAttachment:
    markdown: str
    truncated: bool = False


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _items(values: Any) -> list[Any]:
    return values if isinstance(values, list) else []


def _section(lines: list[str], title: str) -> None:
    lines.extend(["", f"## {title}"])


def _bullets(lines: list[str], values: Any) -> None:
    for value in _items(values):
        item = _text(value)
        if item:
            lines.append(f"- {item}")


def _ba_package_markdown(data: dict[str, Any]) -> str:
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    artifacts = (
        payload.get("artifacts")
        if isinstance(payload.get("artifacts"), dict)
        else {}
    )
    feature = (
        artifacts.get("feature_definition")
        if isinstance(artifacts.get("feature_definition"), dict)
        else {}
    )
    lines = ["# BA handoff context"]
    title = _text(payload.get("feature_title")) or "Untitled feature"
    lines.extend(
        [
            f"- Feature: {title}",
            f"- Project ID: {_text(data.get('project_id')) or 'n/a'}",
            f"- Feature ID: {_text(data.get('feature_id')) or 'n/a'}",
            f"- Ticket type: {_text(payload.get('ticket_type')) or 'n/a'}",
            f"- Package status: {_text((data.get('artifact') or {}).get('status')) or 'n/a'}",
        ]
    )
    description = _text(payload.get("feature_description"))
    if description:
        _section(lines, "Feature intent")
        lines.append(description)
    goal = _text(feature.get("goal"))
    if goal and goal != description:
        lines.append(f"\n**Goal:** {goal}")

    _section(lines, "Actors")
    _bullets(lines, feature.get("actors"))
    _section(lines, "Scope in")
    _bullets(lines, feature.get("scope_in"))
    _section(lines, "Scope out")
    _bullets(lines, feature.get("scope_out"))

    touchpoints = _items(artifacts.get("ui_touchpoints"))
    _section(lines, "UI touchpoints from BA")
    for item in touchpoints:
        if not isinstance(item, dict):
            continue
        related = ", ".join(map(str, _items(item.get("related_uc_ids")))) or "n/a"
        lines.append(
            f"- **{_text(item.get('id'))} — {_text(item.get('name') or item.get('screen'))}**: "
            f"actor `{_text(item.get('actor'))}`, interaction `{_text(item.get('interaction'))}`, "
            f"related use cases `{related}`. Trigger: {_text(item.get('trigger'))}. "
            f"Notes: {_text(item.get('notes')) or 'none'}."
        )

    use_cases = _items(artifacts.get("use_cases"))
    _section(lines, "User stories and acceptance criteria")
    acceptance_ids: list[str] = []
    for use_case in use_cases:
        if not isinstance(use_case, dict):
            continue
        uid = _text(use_case.get("id"))
        rules = ", ".join(map(str, _items(use_case.get("rule_ids")))) or "none"
        lines.append(
            f"\n### {uid}: {_text(use_case.get('statement'))}\n"
            f"Actor: `{_text(use_case.get('actor_id'))}` · Rules: `{rules}`"
        )
        for criterion in _items(use_case.get("acceptance_criteria")):
            if not isinstance(criterion, dict):
                continue
            cid = _text(criterion.get("id"))
            acceptance_ids.append(cid)
            lines.append(
                f"- **{cid}** — Given {_text(criterion.get('given'))}; "
                f"When {_text(criterion.get('when'))}; Then {_text(criterion.get('then'))}."
            )

    _section(lines, "Business rules")
    for rule in _items(artifacts.get("business_rules")):
        if isinstance(rule, dict):
            lines.append(
                f"- **{_text(rule.get('id'))}**: {_text(rule.get('statement'))} "
                f"(Source: {_text(rule.get('source')) or 'unspecified'})"
            )

    workflow = (
        artifacts.get("bpmn_reference")
        if isinstance(artifacts.get("bpmn_reference"), dict)
        else {}
    )
    _section(lines, "Workflow")
    for step in _items(workflow.get("steps")):
        if isinstance(step, dict):
            lines.append(
                f"{_text(step.get('step'))}. `{_text(step.get('actor'))}` — "
                f"{_text(step.get('action'))} [Rules: {_text(step.get('br_ref')) or 'none'}]"
            )
    if workflow.get("exceptions"):
        lines.append("\n### Exception states")
        for item in _items(workflow.get("exceptions")):
            if isinstance(item, dict):
                lines.append(
                    f"- **{_text(item.get('id'))}**: If {_text(item.get('condition'))}, "
                    f"then {_text(item.get('handling'))}."
                )
    if workflow.get("end_states"):
        lines.append("\n### End states")
        _bullets(lines, workflow.get("end_states"))

    questions = _items(payload.get("open_questions"))
    if questions:
        _section(lines, "Decisions and open questions")
        for item in questions:
            if not isinstance(item, dict):
                continue
            answer = _text(item.get("answer"))
            status = _text(item.get("status")) or "open"
            lines.append(
                f"- **{_text(item.get('id'))} [{status}]**: {_text(item.get('question'))}"
                + (f" Decision: {answer}" if answer else "")
            )

    assumptions = _items(payload.get("assumptions"))
    if assumptions:
        _section(lines, "Assumptions")
        for item in assumptions:
            if isinstance(item, dict):
                lines.append(
                    f"- **{_text(item.get('id'))}**: {_text(item.get('statement'))}"
                )

    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    _section(lines, "Validation signals")
    lines.append(f"- Status: `{_text(validation.get('status')) or 'unknown'}`")
    for warning in _items(validation.get("warnings")):
        if isinstance(warning, dict):
            lines.append(
                f"- **{_text(warning.get('check_id'))} {_text(warning.get('name'))}**: "
                f"{_text(warning.get('detail'))} Suggestion: {_text(warning.get('suggestion'))}"
            )
    duplicates = sorted(
        key for key, count in Counter(acceptance_ids).items() if key and count > 1
    )
    if duplicates:
        lines.append(
            "- Source consistency warning: duplicate acceptance-criterion IDs: "
            + ", ".join(f"`{item}`" for item in duplicates)
        )

    handoff = data.get("handoff") if isinstance(data.get("handoff"), dict) else {}
    if handoff:
        _section(lines, "Handoff")
        lines.append(
            f"- To: `{_text(handoff.get('to'))}` · Gate: `{_text(handoff.get('gate'))}` · "
            f"Mode: `{_text(handoff.get('mode'))}` · Ready: `{handoff.get('ready')}`"
        )
        note = _text(handoff.get("note"))
        if note:
            lines.append(f"- Note: {note}")
    return "\n".join(lines).strip()


def _is_placeholder(value: Any) -> bool:
    normalized = _text(value).casefold()
    return not normalized or normalized in {":---", "---", "n/a", "na", "undefined", "null"}


def _ba_ui_context_markdown(data: dict[str, Any]) -> str:
    """Extract only design-relevant BA facts instead of forwarding the package."""
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else {}
    feature = artifacts.get("feature_definition") if isinstance(artifacts.get("feature_definition"), dict) else {}
    title = _text(payload.get("feature_title")) or "Untitled feature"
    description = _text(payload.get("feature_description"))
    goal = _text(feature.get("goal"))
    lines = [
        "# BA handoff context",
        f"- Feature: {title}",
        f"- Project ID: {_text(data.get('project_id')) or 'n/a'}",
        f"- Feature ID: {_text(data.get('feature_id')) or 'n/a'}",
    ]
    if goal or description:
        lines.extend(["", "## Product intent", goal or description])

    valid_touchpoints: list[dict[str, Any]] = []
    related_use_cases: set[str] = set()
    related_rules: set[str] = set()
    for item in _items(artifacts.get("ui_touchpoints")):
        if not isinstance(item, dict):
            continue
        screen_id = _text(item.get("id"))
        name = _text(item.get("name") or item.get("screen"))
        if _is_placeholder(screen_id) or _is_placeholder(name):
            continue
        valid_touchpoints.append(item)
        related_use_cases.update(
            _text(value) for value in _items(item.get("related_uc_ids")) if not _is_placeholder(value)
        )
        notes = _text(item.get("notes"))
        related_rules.update(part.strip() for part in notes.replace(";", ",").split(",") if part.strip().upper().startswith("BR-"))

    lines.extend(["", "## UI screens to design"])
    for item in valid_touchpoints:
        screen_id = _text(item.get("id"))
        name = _text(item.get("name") or item.get("screen"))
        actor = _text(item.get("actor"))
        interaction = _text(item.get("interaction"))
        use_cases = ", ".join(
            _text(value) for value in _items(item.get("related_uc_ids")) if not _is_placeholder(value)
        )
        notes = _text(item.get("notes"))
        metadata = "; ".join(
            value
            for value in (
                f"actor={actor}" if not _is_placeholder(actor) else "",
                f"interaction={interaction}" if not _is_placeholder(interaction) else "",
                f"use_cases={use_cases}" if use_cases else "",
                f"rules={notes}" if not _is_placeholder(notes) and notes.casefold() != "none" else "",
            )
            if value
        )
        lines.append(f"- {screen_id} — {name}" + (f" ({metadata})" if metadata else ""))

    use_cases = {
        _text(item.get("id")): item
        for item in _items(artifacts.get("use_cases"))
        if isinstance(item, dict) and not _is_placeholder(item.get("id"))
    }
    lines.extend(["", "## UI behavior and states"])
    acceptance_ids: list[str] = []
    for use_case_id in sorted(related_use_cases):
        use_case = use_cases.get(use_case_id)
        if not use_case:
            continue
        for rule_id in _items(use_case.get("rule_ids")):
            if not _is_placeholder(rule_id):
                related_rules.add(_text(rule_id))
        for criterion in _items(use_case.get("acceptance_criteria")):
            if not isinstance(criterion, dict):
                continue
            criterion_id = _text(criterion.get("id"))
            acceptance_ids.append(criterion_id)
            lines.append(
                f"- {use_case_id}/{criterion_id}: Given {_text(criterion.get('given'))}; "
                f"When {_text(criterion.get('when'))}; Then {_text(criterion.get('then'))}."
            )

    rules = {
        _text(item.get("id")): item
        for item in _items(artifacts.get("business_rules"))
        if isinstance(item, dict) and not _is_placeholder(item.get("id"))
    }
    lines.extend(["", "## Referenced UI rules"])
    for rule_id in sorted(related_rules):
        rule = rules.get(rule_id)
        if rule:
            lines.append(f"- {rule_id}: {_text(rule.get('statement'))}")

    workflow = artifacts.get("bpmn_reference") if isinstance(artifacts.get("bpmn_reference"), dict) else {}
    exceptions = [item for item in _items(workflow.get("exceptions")) if isinstance(item, dict)]
    if exceptions:
        lines.extend(["", "## Exception states"])
        for item in exceptions:
            lines.append(
                f"- {_text(item.get('id'))}: If {_text(item.get('condition'))}, "
                f"then {_text(item.get('handling'))}."
            )

    duplicates = sorted(
        key for key, count in Counter(acceptance_ids).items() if key and count > 1
    )
    if duplicates:
        lines.append(
            "- Source consistency warning: duplicate acceptance-criterion IDs: "
            + ", ".join(f"`{item}`" for item in duplicates)
        )
    return "\n".join(lines).strip()


def _generic_json_markdown(data: Any) -> str:
    lines = ["# Attached JSON context"]

    def visit(value: Any, path: str, depth: int) -> None:
        if len("\n".join(lines)) >= MAX_MARKDOWN_CHARS or depth > 5:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                if key in SKIPPED_JSON_KEYS:
                    continue
                label = key.replace("_", " ").strip().title()
                child_path = f"{path}.{key}" if path else key
                if isinstance(child, dict | list):
                    lines.append(f"{'#' * min(depth + 2, 6)} {label}")
                    visit(child, child_path, depth + 1)
                elif child is not None:
                    lines.append(f"- **{label}:** {_text(child)}")
        elif isinstance(value, list):
            for index, child in enumerate(value[:50]):
                if isinstance(child, dict | list):
                    lines.append(f"- Item {index + 1}")
                    visit(child, f"{path}[{index}]", depth + 1)
                else:
                    lines.append(f"- {_text(child)}")

    visit(data, "", 0)
    return "\n".join(lines).strip()


def _limit(markdown: str, max_chars: int = MAX_MARKDOWN_CHARS) -> ParsedAttachment:
    if len(markdown) <= max_chars:
        return ParsedAttachment(markdown=markdown)
    boundary = markdown.rfind("\n", 0, max_chars)
    boundary = boundary if boundary > max_chars // 2 else max_chars
    return ParsedAttachment(
        markdown=markdown[:boundary].rstrip() + "\n\n> Context truncated by attachment parser.",
        truncated=True,
    )


def parse_json_document(raw: bytes) -> ParsedAttachment:
    data = json.loads(raw.decode("utf-8-sig"))
    contract = data.get("contract") if isinstance(data, dict) else None
    artifact = data.get("artifact") if isinstance(data, dict) else None
    if isinstance(data, dict) and (
        (isinstance(contract, dict) and contract.get("name") == "business-analysis-output")
        or (isinstance(artifact, dict) and artifact.get("type") == "business_analysis_package")
    ):
        return ParsedAttachment(markdown=_ba_ui_context_markdown(data))
    return _limit(_generic_json_markdown(data))


def parse_text_document(raw: bytes, suffix: str) -> ParsedAttachment:
    text = raw.decode("utf-8-sig").strip()
    if suffix.casefold() == ".md":
        return _limit(text)
    return _limit("# Attached text context\n\n" + text)


def _local_tag(elem: ET.Element) -> str:
    tag = elem.tag
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _elem_text(elem: ET.Element | None) -> str:
    if elem is None or elem.text is None:
        return ""
    return " ".join(elem.text.split())


@dataclass
class _BpmnNode:
    id: str
    tag: str
    name: str
    documentation: str = ""
    lane: str = ""
    participant: str = ""
    incoming: list[str] = field(default_factory=list)
    outgoing: list[str] = field(default_factory=list)
    attached_to: str = ""


@dataclass
class _BpmnFlow:
    id: str
    name: str
    source_ref: str
    target_ref: str
    condition: str = ""


def _bpmn_document_markdown(raw: bytes) -> str:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        root = ET.fromstring(raw.decode("utf-8-sig", errors="replace"))

    participants: dict[str, str] = {}
    message_flows: list[tuple[str, str, str]] = []

    for elem in root.iter():
        tag = _local_tag(elem)
        if tag == "participant":
            p_id = elem.get("id", "")
            p_name = elem.get("name", "").strip()
            proc_ref = elem.get("processRef", "")
            if p_name:
                if p_id:
                    participants[p_id] = p_name
                if proc_ref:
                    participants[proc_ref] = p_name
        elif tag == "messageFlow":
            mf_name = elem.get("name", "").strip()
            mf_src = elem.get("sourceRef", "")
            mf_tgt = elem.get("targetRef", "")
            message_flows.append((mf_name, mf_src, mf_tgt))

    lines: list[str] = ["# BPMN Business Process Context"]

    if participants:
        lines.append("\n## Participants & Actors (Pools)")
        for pid, pname in participants.items():
            lines.append(f"- Actor `{pname}` (ID: `{pid}`)")

    processes = [e for e in root.iter() if _local_tag(e) == "process"]
    if not processes:
        processes = [root]

    for proc_idx, proc in enumerate(processes):
        proc_id = proc.get("id", f"process_{proc_idx+1}")
        proc_name = proc.get("name", "").strip() or proc_id
        proc_participant = participants.get(proc_id, "")

        proc_doc = ""
        for child in proc:
            if _local_tag(child) == "documentation":
                proc_doc = _elem_text(child)
                break

        lines.append(f"\n## Process: {proc_name}")
        lines.append(f"- **Process ID:** `{proc_id}`")
        if proc_participant:
            lines.append(f"- **Assigned Actor / Pool:** `{proc_participant}`")
        if proc_doc:
            lines.append(f"- **Description:** {proc_doc}")

        node_lane_map: dict[str, str] = {}
        lane_names: list[str] = []
        for child in proc.iter():
            if _local_tag(child) == "lane":
                lane_name = child.get("name", "").strip() or child.get("id", "Lane")
                lane_names.append(lane_name)
                for node_ref in child.iter():
                    if _local_tag(node_ref) == "flowNodeRef":
                        ref_id = _elem_text(node_ref)
                        if ref_id:
                            node_lane_map[ref_id] = lane_name

        if lane_names:
            lines.append(f"- **Lanes (Roles):** {', '.join(f'`{lane}`' for lane in lane_names)}")

        nodes: dict[str, _BpmnNode] = {}
        flows: dict[str, _BpmnFlow] = {}

        for elem in proc.iter():
            tag = _local_tag(elem)
            elem_id = elem.get("id", "")
            elem_name = (elem.get("name") or "").strip()

            if tag == "sequenceFlow":
                source = elem.get("sourceRef", "")
                target = elem.get("targetRef", "")
                cond = ""
                for c in elem:
                    if _local_tag(c) == "conditionExpression":
                        cond = _elem_text(c)
                flows[elem_id] = _BpmnFlow(
                    id=elem_id,
                    name=elem_name,
                    source_ref=source,
                    target_ref=target,
                    condition=cond,
                )
            elif tag in {
                "startEvent",
                "endEvent",
                "intermediateCatchEvent",
                "intermediateThrowEvent",
                "boundaryEvent",
                "userTask",
                "manualTask",
                "serviceTask",
                "scriptTask",
                "businessRuleTask",
                "sendTask",
                "receiveTask",
                "task",
                "subProcess",
                "callActivity",
                "exclusiveGateway",
                "parallelGateway",
                "inclusiveGateway",
                "complexGateway",
                "eventBasedGateway",
            }:
                if not elem_id:
                    continue
                doc = ""
                incomings = []
                outgoings = []
                for c in elem:
                    ctag = _local_tag(c)
                    if ctag == "documentation":
                        doc = _elem_text(c)
                    elif ctag == "incoming":
                        inc = _elem_text(c)
                        if inc:
                            incomings.append(inc)
                    elif ctag == "outgoing":
                        outg = _elem_text(c)
                        if outg:
                            outgoings.append(outg)

                lane = node_lane_map.get(elem_id, proc_participant or "")
                nodes[elem_id] = _BpmnNode(
                    id=elem_id,
                    tag=tag,
                    name=elem_name or elem_id,
                    documentation=doc,
                    lane=lane,
                    participant=proc_participant,
                    incoming=incomings,
                    outgoing=outgoings,
                    attached_to=elem.get("attachedToRef", ""),
                )

        user_tasks = [n for n in nodes.values() if n.tag in {"userTask", "manualTask"}]
        system_tasks = [
            n
            for n in nodes.values()
            if n.tag in {"serviceTask", "scriptTask", "businessRuleTask", "sendTask", "receiveTask", "task"}
        ]
        gateways = [n for n in nodes.values() if "Gateway" in n.tag]
        start_events = [n for n in nodes.values() if n.tag == "startEvent"]
        end_events = [n for n in nodes.values() if n.tag == "endEvent"]
        boundary_events = [n for n in nodes.values() if n.tag == "boundaryEvent"]
        subprocesses = [n for n in nodes.values() if n.tag in {"subProcess", "callActivity"}]

        # 1. UI Touchpoints & User Tasks (Primary screens and user interactions)
        if user_tasks:
            lines.append("\n### UI Touchpoints (User Tasks)")
            for task in user_tasks:
                lane_str = f" | Role: `{task.lane}`" if task.lane else ""
                lines.append(f"- **{task.name}** (`{task.id}`){lane_str}")
                if task.documentation:
                    lines.append(f"  - Purpose: {task.documentation}")
                next_steps = []
                for out_flow_id in task.outgoing:
                    if out_flow_id in flows:
                        fl = flows[out_flow_id]
                        target_node = nodes.get(fl.target_ref)
                        target_name = target_node.name if target_node else fl.target_ref
                        label = fl.name or fl.condition or "Next"
                        next_steps.append(f"`{label}` -> **{target_name}**")
                if next_steps:
                    lines.append(f"  - User Actions / Next: {'; '.join(next_steps)}")

        # 2. Decision Points & Branching (Gateways)
        if gateways:
            lines.append("\n### Decision Points & Branching (Gateways)")
            for gw in gateways:
                gw_type = gw.tag.replace("Gateway", "").capitalize()
                lines.append(f"- **{gw.name}** (`{gw.id}`, Type: `{gw_type}`)")
                for out_id in gw.outgoing:
                    if out_id in flows:
                        fl = flows[out_id]
                        target_node = nodes.get(fl.target_ref)
                        target_name = target_node.name if target_node else fl.target_ref
                        cond_str = fl.name or fl.condition or "default"
                        lines.append(f"  - Option `[{cond_str}]` -> **{target_name}**")

        # 3. Subprocesses & Sub-flows
        if subprocesses:
            lines.append("\n### Subprocesses & Sub-flows")
            for sp in subprocesses:
                lines.append(f"- **{sp.name}** (`{sp.id}`)")
                if sp.documentation:
                    lines.append(f"  - Details: {sp.documentation}")

        # 4. System & Background Actions
        if system_tasks:
            lines.append("\n### System & Automated Actions")
            for st in system_tasks:
                lines.append(f"- `{st.name}` (`{st.id}`, {st.tag})")

        # 5. Traced End-to-End User Flow
        if start_events:
            lines.append("\n### User Flow & Navigation Steps")
            for se in start_events:
                step_idx = 1
                visited: set[str] = set()
                queue = [(se, 1)]
                while queue and len(visited) < 30:
                    curr_node, depth = queue.pop(0)
                    if curr_node.id in visited:
                        continue
                    visited.add(curr_node.id)
                    out_targets = []
                    for out_id in curr_node.outgoing:
                        if out_id in flows:
                            fl = flows[out_id]
                            tn = nodes.get(fl.target_ref)
                            if tn:
                                cond = f" [{fl.name}]" if fl.name else ""
                                out_targets.append((fl, tn, cond))
                                if tn.id not in visited:
                                    queue.append((tn, depth + 1))
                    if out_targets:
                        trans_desc = " | ".join(f"{cond} -> `{tn.name}`" for _, tn, cond in out_targets)
                        lines.append(f"{step_idx}. **{curr_node.name}** ({curr_node.tag}) {trans_desc}")
                        step_idx += 1

        # 6. Boundary Events & Error Handling
        if boundary_events:
            lines.append("\n### Error & Exception Handling (Boundary Events)")
            for be in boundary_events:
                attached = nodes.get(be.attached_to)
                attached_name = attached.name if attached else be.attached_to
                lines.append(f"- On `{attached_name}`: Trigger `{be.name}` (`{be.id}`)")

        # 7. End States / Outcomes
        if end_events:
            lines.append("\n### End States & Outcomes")
            for ee in end_events:
                lines.append(f"- **{ee.name}** (`{ee.id}`)")

    if message_flows:
        lines.append("\n## Inter-Process Message Flows")
        for mname, msrc, mtgt in message_flows:
            label = f" ({mname})" if mname else ""
            lines.append(f"- `{msrc}` -> `{mtgt}`{label}")

    return "\n".join(lines).strip()


def parse_bpmn_document(raw: bytes) -> ParsedAttachment:
    try:
        return _limit(_bpmn_document_markdown(raw))
    except Exception as error:
        raise ValueError(f"Failed to parse BPMN XML: {error}") from error


def main() -> None:
    path = Path(sys.argv[1])
    suffix = path.suffix.casefold()
    if suffix == ".json":
        parsed = parse_json_document(path.read_bytes())
    elif suffix in {".bpmn", ".bpmn2"}:
        parsed = parse_bpmn_document(path.read_bytes())
    else:
        parsed = parse_text_document(path.read_bytes(), path.suffix)
    print(parsed.markdown)


if __name__ == "__main__":
    main()

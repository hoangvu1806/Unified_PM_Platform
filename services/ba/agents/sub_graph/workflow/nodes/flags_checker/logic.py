"""Workflow flag logic."""

from __future__ import annotations

import re
from typing import Any

from agents.ba_agent.section_gate import sync_sections_status_from_flags
from agents.sub_graph.shared.constants import (
    FAIL,
    MISSING_VALUE,
    PASS,
    PENDING_SEMANTIC,
    WARNING,
)
from agents.sub_graph.shared.flag_helpers import apply_not_yet_reset, flag_dict, was_passed


def check_wf_flags_logic(ctx) -> dict[str, Any]:
    wf = ctx.state.get("artifacts", {}).get("workflow", {})
    content = str(wf.get("workflow_md_content", "") or "")
    existing = dict(ctx.state.get("flags", {}).get("wf", {}))
    flags: dict[str, Any] = {}
    has_content = bool(content.strip())
    steps = _count_main_flow_steps(content)

    # WF-F1: Main flow ≥3 steps (blocker) — code count, sticky PASS
    if not has_content:
        flags["WF-F1"] = flag_dict(
            1, "Main flow defined", MISSING_VALUE, "Chưa có workflow markdown."
        )
    elif steps < 3:
        flags["WF-F1"] = flag_dict(
            1, "Main flow defined", FAIL, f"Cần ≥3 bước Main Flow, hiện ~{steps}."
        )
    else:
        flags["WF-F1"] = flag_dict(1, "Main flow defined", PASS)

    # WF-F2: End-to-end coverage (blocker, semantic)
    if not has_content or steps < 3:
        flags["WF-F2"] = flag_dict(
            2, "End-to-end coverage", MISSING_VALUE, "Cần Main Flow đủ bước trước."
        )
    elif was_passed(existing, "WF-F2"):
        flags["WF-F2"] = flag_dict(2, "End-to-end coverage", PASS)
    else:
        flags["WF-F2"] = flag_dict(
            2,
            "End-to-end coverage",
            PENDING_SEMANTIC,
            "Cần xác nhận luồng liên tục từ trigger → End State.",
        )

    # WF-F3: Exception flows (warning) — heuristic + optional sticky
    if "exception" in content.lower():
        flags["WF-F3"] = flag_dict(3, "Exception flows exist", PASS)
    elif has_content:
        flags["WF-F3"] = flag_dict(
            3,
            "Exception flows exist",
            WARNING,
            "Khuyến nghị thêm section Exception Flows.",
        )
    else:
        flags["WF-F3"] = flag_dict(3, "Exception flows exist", WARNING, "Chưa có workflow.")

    # WF-F4: Actor consistency (blocker, semantic) — needs FD actors
    if not has_content:
        flags["WF-F4"] = flag_dict(4, "Actor consistency", MISSING_VALUE)
    elif was_passed(existing, "WF-F4"):
        flags["WF-F4"] = flag_dict(4, "Actor consistency", PASS)
    else:
        flags["WF-F4"] = flag_dict(
            4,
            "Actor consistency",
            PENDING_SEMANTIC,
            "Cần đối chiếu actors trong Workflow với Feature Definition.actors[].",
        )

    # WF-F5: BR references (warning)
    if re.search(r"BR-\d+", content):
        flags["WF-F5"] = flag_dict(5, "BR references", PASS)
    elif has_content:
        flags["WF-F5"] = flag_dict(
            5, "BR references", WARNING, "Khuyến nghị tham chiếu BR-XX trong Main Flow."
        )
    else:
        flags["WF-F5"] = flag_dict(5, "BR references", WARNING)

    # WF-F6: End states (warning)
    if "end state" in content.lower() or "## end states" in content.lower():
        flags["WF-F6"] = flag_dict(6, "End states defined", PASS)
    elif has_content:
        flags["WF-F6"] = flag_dict(
            6, "End states defined", WARNING, "Khuyến nghị thêm section End States."
        )
    else:
        flags["WF-F6"] = flag_dict(6, "End states defined", WARNING)

    apply_not_yet_reset(flags, existing)

    all_flags = dict(ctx.state.get("flags", {}))
    all_flags["wf"] = flags
    ctx.state["flags"] = all_flags
    sync_sections_status_from_flags(ctx.state)
    return flags


def _main_flow_section(content: str) -> str:
    """Slice `## Main Flow` … next heading so exception/end-state lines are ignored."""
    lines = content.splitlines()
    start = None
    for i, raw in enumerate(lines):
        if re.match(r"^#{1,3}\s*main flow\b", raw.strip(), re.IGNORECASE):
            start = i + 1
            break
    if start is None:
        return content
    end = len(lines)
    for j in range(start, len(lines)):
        if re.match(r"^#{1,3}\s+\S", lines[j].strip()) and not re.match(
            r"^#{1,3}\s*main flow\b", lines[j].strip(), re.IGNORECASE
        ):
            end = j
            break
    return "\n".join(lines[start:end])


def _count_main_flow_steps(content: str) -> int:
    """Count Main Flow steps from a markdown table or a numbered/bulleted list."""
    section = _main_flow_section(content)
    table_rows = 0
    list_rows = 0
    for raw in section.splitlines():
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
            table_rows += 1
            continue
        if re.match(r"^\d+[.)]\s+\S", line):
            list_rows += 1
        elif re.match(r"^[-*•]\s+\S", line):
            list_rows += 1
    return max(table_rows, list_rows)

"""Use cases merge and flag logic (one active User Story at a time)."""

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
from agents.sub_graph.use_cases.schemas import UseCasesData


def is_user_story_row_complete(uc: dict[str, Any] | None) -> bool:
    """True when a single US row has statement + actor + ≥1 full AC."""
    if not isinstance(uc, dict):
        return False
    statement = str(uc.get("statement") or "")
    if not re.search(r"muốn.+để", statement, re.I):
        return False
    if not str(uc.get("actor_id") or "").strip():
        return False
    acs = uc.get("acceptance_criteria") or []
    if not isinstance(acs, list) or not acs:
        return False
    for ac in acs:
        if not isinstance(ac, dict):
            continue
        if (
            str(ac.get("given") or "").strip()
            and str(ac.get("when") or "").strip()
            and str(ac.get("then") or "").strip()
        ):
            return True
    return False


def resolve_active_user_story_id(
    cases: list[dict[str, Any]],
    active_id: str | None,
) -> str | None:
    """Pick the locked story id: prefer incomplete active, else first incomplete, else last."""
    by_id = {str(c.get("id") or ""): c for c in cases if c.get("id")}
    if active_id and active_id in by_id:
        if not is_user_story_row_complete(by_id[active_id]):
            return active_id
        # Active complete — keep it until a newer incomplete story appears.
        for c in cases:
            cid = str(c.get("id") or "")
            if cid and not is_user_story_row_complete(c):
                return cid
        return active_id
    for c in cases:
        cid = str(c.get("id") or "")
        if cid and not is_user_story_row_complete(c):
            return cid
    if cases:
        return str(cases[-1].get("id") or "") or None
    return None


def merge_use_cases(
    current: list[dict],
    delta: UseCasesData,
    *,
    active_user_story_id: str | None = None,
) -> tuple[list[dict], str | None]:
    """Merge UC delta with one-active-story lock.

    - Updates to existing rows are allowed.
    - At most one *new* story per turn.
    - A new story is accepted only when the current active story is complete
      (or there are no stories yet).
    """
    cases = [dict(c) for c in current]
    active = resolve_active_user_story_id(cases, active_user_story_id)
    if not delta.use_cases:
        return cases, active

    by_id = {str(c.get("id", "")): c for c in cases if c.get("id")}
    active_row = by_id.get(active or "") if active else None
    active_complete = is_user_story_row_complete(active_row) if active_row else True
    accepted_new = False

    for item in delta.use_cases:
        proposed_id = (item.id or "").strip() or None
        is_new = not proposed_id or proposed_id not in by_id
        if is_new:
            if accepted_new:
                # One new story per turn.
                continue
            if cases and active and not active_complete:
                # Locked on incomplete active story — drop extras.
                continue
            new_id = proposed_id or _next_id(cases)
            uc = {
                "id": new_id,
                "actor_id": item.actor_id,
                "statement": item.statement.strip(),
                "rule_ids": item.rule_ids or [],
                "bpmn_node_ids": item.bpmn_node_ids or [],
                "acceptance_criteria": [ac.model_dump() for ac in item.acceptance_criteria],
            }
            cases.append(uc)
            by_id[new_id] = uc
            active = new_id
            accepted_new = True
            active_complete = is_user_story_row_complete(uc)
            continue

        # Update existing row (including non-active completed stories).
        uc = {
            "id": proposed_id,
            "actor_id": item.actor_id,
            "statement": item.statement.strip(),
            "rule_ids": item.rule_ids or [],
            "bpmn_node_ids": item.bpmn_node_ids or [],
            "acceptance_criteria": [ac.model_dump() for ac in item.acceptance_criteria],
        }
        by_id[proposed_id].update(uc)
        if proposed_id == active:
            active_complete = is_user_story_row_complete(by_id[proposed_id])

    active = resolve_active_user_story_id(cases, active)
    return cases, active


def _next_id(cases: list[dict]) -> str:
    nums = []
    for c in cases:
        cid = str(c.get("id", ""))
        if cid.startswith("US-"):
            try:
                nums.append(int(cid.split("-", 1)[1]))
            except ValueError:
                pass
    return f"US-{max(nums, default=0) + 1:02d}"


def check_uc_flags_logic(ctx) -> dict[str, Any]:
    cases = ctx.state.get("artifacts", {}).get("use_cases", [])
    if not isinstance(cases, list):
        cases = []
    # Keep session lock in sync with artifact list.
    active = resolve_active_user_story_id(
        cases, ctx.state.get("active_user_story_id")
    )
    ctx.state["active_user_story_id"] = active

    fd_actors = ctx.state.get("artifacts", {}).get("feature_definition", {}).get(
        "actors", []
    )
    actor_ids = {_parse_actor_id(a) for a in fd_actors if a}
    br_ids = {
        str(r.get("id"))
        for r in ctx.state.get("artifacts", {}).get("business_rules", [])
        if r.get("id")
    }
    existing = dict(ctx.state.get("flags", {}).get("uc", {}))
    flags: dict[str, Any] = {}

    # UC-F1 min count — still min 1; do not require N stories for Validate.
    if not cases:
        flags["UC-F1"] = flag_dict(1, "Min use cases", MISSING_VALUE, "Chưa có use case.")
    else:
        flags["UC-F1"] = flag_dict(1, "Min use cases", PASS)

    # UC-F2 statement format (code + may soft-pass to semantic later)
    bad_format = [
        c
        for c in cases
        if not re.search(r"muốn.+để", c.get("statement", ""), re.I)
    ]
    if not cases:
        flags["UC-F2"] = flag_dict(2, "Statement format", MISSING_VALUE)
    elif bad_format:
        flags["UC-F2"] = flag_dict(
            2, "Statement format", FAIL, f"{len(bad_format)} UC sai format 'muốn … để …'."
        )
    else:
        flags["UC-F2"] = flag_dict(2, "Statement format", PASS)

    # UC-F3 actor validity
    orphan = [c for c in cases if c.get("actor_id") not in actor_ids]
    if not cases:
        flags["UC-F3"] = flag_dict(3, "Actor validity", MISSING_VALUE)
    elif orphan:
        flags["UC-F3"] = flag_dict(
            3,
            "Actor validity",
            FAIL,
            f"Actor không hợp lệ: {orphan[0].get('actor_id')}",
        )
    else:
        flags["UC-F3"] = flag_dict(3, "Actor validity", PASS)

    # UC-F4 rule linkage (warning) — non-empty + ids exist in BR when BR present
    no_rules = [c for c in cases if not c.get("rule_ids")]
    bad_refs = []
    if br_ids:
        for c in cases:
            for rid in c.get("rule_ids") or []:
                if str(rid) not in br_ids:
                    bad_refs.append(str(rid))
    if not cases:
        flags["UC-F4"] = flag_dict(4, "Rule linkage", WARNING)
    elif no_rules or bad_refs:
        detail_parts = []
        if no_rules:
            detail_parts.append(f"{len(no_rules)} UC chưa map BR")
        if bad_refs:
            detail_parts.append(f"BR id không tồn tại: {', '.join(sorted(set(bad_refs))[:5])}")
        flags["UC-F4"] = flag_dict(4, "Rule linkage", WARNING, "; ".join(detail_parts))
    else:
        flags["UC-F4"] = flag_dict(4, "Rule linkage", PASS)

    # UC-F5 no duplicate (blocker, semantic)
    if len(cases) < 2:
        flags["UC-F5"] = flag_dict(
            5, "No duplicate", PASS if cases else MISSING_VALUE, "Chưa đủ UC để so trùng."
        )
    elif was_passed(existing, "UC-F5"):
        flags["UC-F5"] = flag_dict(5, "No duplicate", PASS)
    else:
        flags["UC-F5"] = flag_dict(
            5,
            "No duplicate",
            PENDING_SEMANTIC,
            "Cần kiểm tra 2 UC có trùng scope ngữ nghĩa không.",
        )

    # UC-F6 actor coverage (warning, code)
    covered = {c.get("actor_id") for c in cases if c.get("actor_id")}
    primary = {a for a in actor_ids if a}
    missing_actors = sorted(primary - covered) if primary else []
    if not cases:
        flags["UC-F6"] = flag_dict(6, "Actor coverage", MISSING_VALUE)
    elif missing_actors:
        flags["UC-F6"] = flag_dict(
            6,
            "Actor coverage",
            WARNING,
            f"Actors chưa có UC: {', '.join(missing_actors[:5])}",
        )
    else:
        flags["UC-F6"] = flag_dict(6, "Actor coverage", PASS)

    # UC-F7 AC exists
    no_ac = [c for c in cases if not c.get("acceptance_criteria")]
    if not cases:
        flags["UC-F7"] = flag_dict(7, "AC exists", MISSING_VALUE)
    elif no_ac:
        flags["UC-F7"] = flag_dict(
            7, "AC exists", FAIL, f"{len(no_ac)} UC thiếu Acceptance Criteria."
        )
    else:
        flags["UC-F7"] = flag_dict(7, "AC exists", PASS)

    # UC-F8 happy path AC (blocker, semantic)
    if not cases or no_ac:
        flags["UC-F8"] = flag_dict(
            8, "Happy path AC", MISSING_VALUE, "Cần AC trước khi đánh giá happy path."
        )
    elif was_passed(existing, "UC-F8"):
        flags["UC-F8"] = flag_dict(8, "Happy path AC", PASS)
    else:
        flags["UC-F8"] = flag_dict(
            8,
            "Happy path AC",
            PENDING_SEMANTIC,
            "Cần xác nhận mỗi UC có ≥1 AC cho happy path.",
        )

    apply_not_yet_reset(flags, existing)

    all_flags = dict(ctx.state.get("flags", {}))
    all_flags["uc"] = flags
    ctx.state["flags"] = all_flags
    sync_sections_status_from_flags(ctx.state)
    return flags


def _parse_actor_id(actor: str) -> str:
    if ":" in actor:
        return actor.split(":", 1)[0].strip()
    return actor.strip()

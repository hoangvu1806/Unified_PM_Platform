"""Business Rules completion flag logic."""

from __future__ import annotations

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


def check_br_flags_logic(ctx) -> dict[str, Any]:
    rules = ctx.state.get("artifacts", {}).get("business_rules", [])
    if not isinstance(rules, list):
        rules = []
    existing = dict(ctx.state.get("flags", {}).get("br", {}))
    flags: dict[str, Any] = {}

    # BR-F1: min 2 rules (blocker, code)
    if len(rules) < 2:
        flags["BR-F1"] = flag_dict(
            1,
            "Min rules count",
            FAIL if rules else MISSING_VALUE,
            f"Cần ít nhất 2 business rules, hiện có {len(rules)}.",
        )
    else:
        flags["BR-F1"] = flag_dict(1, "Min rules count", PASS)

    # BR-F2: all have source (warning, code)
    missing_source = [r for r in rules if not str(r.get("source", "")).strip()]
    if not rules:
        flags["BR-F2"] = flag_dict(2, "All have source", WARNING, "Chưa có rule.")
    elif missing_source:
        flags["BR-F2"] = flag_dict(
            2, "All have source", WARNING, f"{len(missing_source)} rule thiếu source."
        )
    else:
        flags["BR-F2"] = flag_dict(2, "All have source", PASS)

    enough = len(rules) >= 2

    # BR-F3: statements measurable (warning, semantic)
    if not enough:
        flags["BR-F3"] = flag_dict(
            3, "Statements measurable", MISSING_VALUE, "Cần ≥2 rules trước."
        )
    elif was_passed(existing, "BR-F3"):
        flags["BR-F3"] = flag_dict(3, "Statements measurable", PASS)
    else:
        flags["BR-F3"] = flag_dict(
            3,
            "Statements measurable",
            PENDING_SEMANTIC,
            "Cần xác nhận mỗi rule có trigger + outcome đo lường được.",
        )

    # BR-F4: no contradiction (blocker, semantic)
    if not enough:
        flags["BR-F4"] = flag_dict(
            4, "No contradiction", MISSING_VALUE, "Cần ≥2 rules trước."
        )
    elif was_passed(existing, "BR-F4"):
        flags["BR-F4"] = flag_dict(4, "No contradiction", PASS)
    else:
        flags["BR-F4"] = flag_dict(
            4,
            "No contradiction",
            PENDING_SEMANTIC,
            "Cần kiểm tra mâu thuẫn ngữ nghĩa giữa các BR.",
        )

    # BR-F5: true business rules (warning, semantic)
    if not enough:
        flags["BR-F5"] = flag_dict(
            5, "True business rules", WARNING, "Chưa đủ rule để phân loại."
        )
    elif was_passed(existing, "BR-F5"):
        flags["BR-F5"] = flag_dict(5, "True business rules", PASS)
    else:
        flags["BR-F5"] = flag_dict(
            5,
            "True business rules",
            PENDING_SEMANTIC,
            "Cần phân loại: true BR vs technical constraint / assumption.",
        )

    apply_not_yet_reset(flags, existing)

    all_flags = dict(ctx.state.get("flags", {}))
    all_flags["br"] = flags
    ctx.state["flags"] = all_flags
    sync_sections_status_from_flags(ctx.state)
    return flags

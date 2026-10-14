"""Shared helpers for section flag evaluation."""

from __future__ import annotations

from typing import Any

from agents.sub_graph.shared.constants import NOT_YET_REASONABLE, PASS, PENDING_SEMANTIC


def flag_dict(
    priority: int, name: str, status: str, detail: str | None = None
) -> dict[str, Any]:
    return {"priority": priority, "name": name, "status": status, "detail": detail}


def was_passed(existing: dict, flag_id: str) -> bool:
    return existing.get(flag_id, {}).get("status") == PASS


def sticky_or_pending(
    existing: dict, flag_id: str, *, ready: bool, priority: int, name: str, detail: str
) -> dict[str, Any]:
    """PASS sticks; otherwise PENDING_SEMANTIC when data ready, else MISSING handled by caller."""
    if was_passed(existing, flag_id):
        return flag_dict(priority, name, PASS)
    if ready:
        return flag_dict(priority, name, PENDING_SEMANTIC, detail)
    return flag_dict(priority, name, PENDING_SEMANTIC, detail)


def apply_not_yet_reset(flags: dict[str, Any], existing: dict[str, Any]) -> None:
    """NOT_YET_REASONABLE → PENDING_SEMANTIC on next evaluation cycle."""
    for f_id, f_info in flags.items():
        old = existing.get(f_id, {})
        if (
            old.get("status") == NOT_YET_REASONABLE
            and f_info.get("status") == PENDING_SEMANTIC
        ):
            # Keep PENDING — already set; detail may refresh
            pass

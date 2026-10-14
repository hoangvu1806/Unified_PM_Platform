"""Feature status updates after external validation."""

from __future__ import annotations

from typing import Any


def apply_validation_result(state: dict[str, Any], result: dict[str, Any]) -> None:
    """Update feature_status from VA response. Does not mutate artifacts."""
    status = result.get("status", "")
    if status == "no_change":
        return
    if status in {"passed", "passed_with_warnings"}:
        state["feature_status"] = "VALIDATED"
    elif status in {"failed", "blocked"}:
        state["feature_status"] = "VALIDATION_FAILED"
    state["last_validation"] = {
        "status": status,
        "agent_response": result.get("agent_response", ""),
        "failed_checks": result.get("failed_checks", []),
        "warnings": result.get("warnings", []),
        "passed_checks": result.get("passed_checks", []),
        "coverage_summary": result.get("coverage_summary") or {},
        "evidence_references": result.get("evidence_references", []),
        "change_detected": result.get("change_detected"),
        "validated_at": result.get("validated_at"),
        "ruleset_version": result.get("ruleset_version"),
        "llm_commentary": result.get("llm_commentary") or "",
    }

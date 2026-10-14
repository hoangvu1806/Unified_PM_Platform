"""Common Envelope (UAPDF-AIS-001 §4.2) for control-plane artifacts."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

AGENT_BA = "ba-agent"
AGENT_VA = "validation-agent"
AGENT_DESIGNER = "designer-agent"

CONTRACT_BA_OUTPUT = "business-analysis-output"
CONTRACT_VA_REPORT = "validation-report"

ARTIFACT_BA_PACKAGE = "business_analysis_package"
ARTIFACT_VA_REPORT = "validation_report"

AGENT_VERSION = "0.1.0"
CONTRACT_VERSION = "1.0.0"
ARTIFACT_VERSION = "1.0.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def common_envelope(
    *,
    correlation_id: str,
    project_id: str,
    feature_id: str,
    agent_id: str,
    contract_name: str,
    artifact_type: str,
    artifact_status: str,
    payload: dict[str, Any],
    input_references: list[dict[str, Any]] | None = None,
    validation: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    artifact_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Wrap a specialist payload in the shared inter-agent envelope."""
    message_id = str(uuid.uuid4())
    envelope: dict[str, Any] = {
        "message_id": message_id,
        "correlation_id": correlation_id,
        "project_id": project_id,
        "feature_id": feature_id,
        "task_id": None,
        "agent": {
            "id": agent_id,
            "version": AGENT_VERSION,
            "prompt_version": AGENT_VERSION,
            "skill_versions": {},
        },
        "contract": {"name": contract_name, "version": CONTRACT_VERSION},
        "artifact": {
            "id": artifact_id or f"{artifact_type}:{feature_id}",
            "type": artifact_type,
            "version": ARTIFACT_VERSION,
            "status": artifact_status,
        },
        "input_references": list(input_references or []),
        "payload": payload,
        "validation": validation
        or {"schema_valid": True, "errors": [], "outcome": None},
        "provenance": {
            "run_id": run_id or message_id,
            "created_at": utc_now(),
        },
    }
    if extra:
        envelope.update(extra)
    return envelope

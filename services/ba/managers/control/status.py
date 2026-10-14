"""Single feature-status machine for BA, VA, Wiki evidence, and Designer handoff."""

from __future__ import annotations

from typing import Final

STATUS_DRAFT: Final = "DRAFT"
STATUS_IN_PROGRESS: Final = "IN_PROGRESS"
STATUS_PENDING_VALIDATION: Final = "PENDING_VALIDATION"
STATUS_VALIDATED: Final = "VALIDATED"
STATUS_VALIDATION_FAILED: Final = "VALIDATION_FAILED"
STATUS_EXPORTED: Final = "EXPORTED"

CONTROL_STATUSES: Final[frozenset[str]] = frozenset(
    {
        STATUS_DRAFT,
        STATUS_IN_PROGRESS,
        STATUS_PENDING_VALIDATION,
        STATUS_VALIDATED,
        STATUS_VALIDATION_FAILED,
        STATUS_EXPORTED,
    }
)

VALIDATE_ENABLED: Final[frozenset[str]] = frozenset(
    {
        STATUS_PENDING_VALIDATION,
        STATUS_VALIDATED,
        STATUS_VALIDATION_FAILED,
        STATUS_EXPORTED,
    }
)

EXPORT_OK_VA: Final[frozenset[str]] = frozenset({"passed", "passed_with_warnings"})


def normalize_feature_status(value: str | None) -> str:
    status = (value or STATUS_DRAFT).strip().upper()
    return status if status in CONTROL_STATUSES else STATUS_DRAFT


def can_validate(feature_status: str | None) -> bool:
    """Status gate only. Package readiness (Group 1 + critical OQs) is separate."""
    return normalize_feature_status(feature_status) in VALIDATE_ENABLED


def can_export(
    feature_status: str | None,
    last_validation: dict | None = None,
) -> bool:
    """Export when VALIDATED, or refresh after EXPORTED if the last VA still passed."""
    status = normalize_feature_status(feature_status)
    if status == STATUS_VALIDATED:
        return True
    if status != STATUS_EXPORTED:
        return False
    if not last_validation:
        return True
    outcome = str(last_validation.get("status") or "").strip().lower()
    return (not outcome) or outcome in EXPORT_OK_VA


def is_readonly(feature_status: str | None) -> bool:
    """True while the package stamp is EXPORTED (chat freeze / mutate lock)."""
    return normalize_feature_status(feature_status) == STATUS_EXPORTED


def is_chat_frozen(
    feature_status: str | None,
    package_exported: bool | None = None,
) -> bool:
    """Chat stays frozen after the first Export even if a later VA returns VALIDATED."""
    if package_exported:
        return True
    return is_readonly(feature_status)


def package_was_exported(state: dict | None) -> bool:
    data = state or {}
    if data.get("package_exported"):
        return True
    return normalize_feature_status(data.get("feature_status")) == STATUS_EXPORTED

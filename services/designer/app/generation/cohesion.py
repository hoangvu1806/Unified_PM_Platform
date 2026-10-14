from typing import Any

from ..models import ProjectSpecification


def normalize_project_cohesion(
    project: ProjectSpecification,
) -> tuple[ProjectSpecification, dict[str, Any]]:
    """Repair accidental shared-token drift while preserving screen composition."""
    value = project.model_copy(deep=True)
    canonical = value.design_context.style_manifest
    repairs: list[dict[str, str]] = []
    seen: set[str] = set()
    duplicate_ids: list[str] = []
    for screen in value.screens:
        if screen.screen_id in seen:
            duplicate_ids.append(screen.screen_id)
        seen.add(screen.screen_id)
        if screen.specification.style_manifest != canonical:
            screen.specification.style_manifest = canonical.model_copy(deep=True)
            repairs.append(
                {
                    "screen_id": screen.screen_id,
                    "category": "style-token-drift",
                    "action": "Applied the project style manifest.",
                }
            )
    navigation = value.design_context.navigation
    screen_names = [item.specification.screen_name for item in value.screens]
    missing_navigation = [name for name in screen_names if name not in navigation]
    return value, {
        "status": "invalid" if duplicate_ids else "valid",
        "repairs": repairs,
        "duplicate_screen_ids": duplicate_ids,
        "navigation_gaps": missing_navigation,
        "shared_style_manifest": canonical.model_dump(mode="json"),
    }

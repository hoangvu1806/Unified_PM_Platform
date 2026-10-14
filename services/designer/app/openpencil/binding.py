from typing import Any

from ..models import ComponentBinding, ComponentBindingSet


def semantic_family_matches(requirement: dict[str, Any], candidate: Any) -> bool:
    """Check control family, leaving unfamiliar library roles to the designer."""
    role = str(requirement.get("role") or "").lower()
    family = str(candidate.canonical_path).split("/", 1)[0].strip().lower()
    expected = {
        "text_input": ("input", "text field"),
        "password_input": ("input", "text field"),
        "textarea": ("textarea", "text area"),
        "select": ("select", "dropdown"),
        "button": ("button",),
        "radio": ("radio",),
        "checkbox": ("checkbox",),
        "toggle": ("toggle", "switch"),
        "tabs": ("tab",),
    }.get(role)
    return expected is None or any(value in family for value in expected)


def validate_bindings(
    requirements: list[dict[str, Any]],
    candidates: list[Any],
    bindings: ComponentBindingSet,
) -> ComponentBindingSet:
    """Canonicalize LLM choices against inspected metadata; never trust copied labels."""
    by_id = {item.component_id: item for item in candidates}
    by_path = {item.canonical_path: item for item in candidates}
    returned = {item.node_id: item for item in bindings.bindings}
    normalized: list[ComponentBinding] = []
    for requirement in requirements:
        node_id = requirement["node_id"]
        binding = returned.get(node_id)
        if binding is None or binding.status != "resolved":
            normalized.append(binding or _unresolved(node_id, "No compatible component selected"))
            continue
        preferred_name = str((requirement.get("content") or {}).get("preferred_component_name") or "").strip().casefold()
        preferred = next(
            (
                item
                for item in candidates
                if preferred_name
                and (
                    str(item.name).strip().casefold() == preferred_name
                    or str(item.canonical_path).strip().casefold().endswith("/" + preferred_name)
                )
            ),
            None,
        )
        candidate = preferred or by_id.get(binding.component_id or "")
        candidate = candidate or by_path.get(binding.canonical_path or "")
        if candidate is None:
            normalized.append(_unresolved(node_id, "Selected component was not inspected"))
            continue
        if not semantic_family_matches(requirement, candidate) and any(
            semantic_family_matches(requirement, other) for other in candidates
        ):
            normalized.append(_unresolved(node_id, "Selected component belongs to the wrong control family"))
            continue
        if _requires_icon(requirement) and _disables_icon(candidate):
            normalized.append(_unresolved(node_id, "Selected variant disables the required icon"))
            continue
        text_values = _text_values(binding.text_values, candidate.text_slots)
        # Some OpenPencil libraries do not expose text-slot metadata during the
        # catalog scan. Keep a semantically valid component in that case: the
        # page agent inspects its live subtree and edits the actual text nodes.
        # Reject a failed mapping only when the catalog positively declares slots.
        visible = _visible_content(requirement.get("content", {}))
        if visible and candidate.text_slots and not text_values:
            normalized.append(_unresolved(node_id, "Selected component cannot express the required visible content"))
            continue
        if visible and not candidate.text_slots and any(
            other.text_slots and semantic_family_matches(requirement, other) for other in candidates
        ):
            normalized.append(_unresolved(node_id, "Choose a writable variant for visible control text"))
            continue
        if len(visible) == 1 and not text_values:
            # The catalog occasionally misses a single live TEXT descendant.
            # _bind_text validates this against the mounted instance.
            text_values = {"text:Text": visible[0]}
        normalized.append(
            binding.model_copy(
                update={
                    "component_id": candidate.component_id,
                    "library_id": candidate.library_id,
                    "canonical_path": candidate.canonical_path,
                    "selected_variant": candidate.variant_name,
                    "text_values": text_values,
                }
            )
        )
    return ComponentBindingSet(bindings=normalized)


def _unresolved(node_id: str, reason: str) -> ComponentBinding:
    return ComponentBinding(node_id=node_id, status="unresolved", reason=reason)


def _text_values(values: dict[str, str], slots: list[str]) -> dict[str, str]:
    if not values or not slots:
        return {}
    result: dict[str, str] = {}
    for key, value in values.items():
        wanted = _normalized(key.removeprefix("text:"))
        matches = [slot for slot in slots if _slot_matches(wanted, slot)]
        if len(matches) == 1:
            result[matches[0]] = value
        elif len(values) == 1 and len(slots) == 1:
            result[slots[0]] = value
    return result


def _visible_content(content: dict[str, Any]) -> list[str]:
    ignored = {
        "active",
        "color",
        "description",
        "icon",
        "image_alt",
        "indicator_color",
        "query",
        "state",
        "status",
        "style",
        "style_intent",
    }
    return [
        str(value).strip()
        for key, value in content.items()
        if key.lower() not in ignored
        and not isinstance(value, bool | dict | list)
        and value is not None
        and str(value).strip()
    ]


def _requires_icon(requirement: dict[str, Any]) -> bool:
    content = requirement.get("content") or {}
    slots = requirement.get("required_slots") or []
    return bool(content.get("icon") or any("icon" in str(slot).lower() for slot in slots))


def _disables_icon(candidate: Any) -> bool:
    identity = f"{candidate.canonical_path} {candidate.variant_name or ''}".lower().replace(" ", "")
    return "icon=false" in identity


def _slot_matches(wanted: str, slot: str) -> bool:
    normalized = _normalized(slot.removeprefix("text:"))
    leaf = _normalized(slot.rsplit("/", 1)[-1].removeprefix("text:"))
    return wanted in {normalized, leaf}


def _normalized(value: str) -> str:
    return " ".join(part for part in value.lower().replace("/", " ").split() if part)

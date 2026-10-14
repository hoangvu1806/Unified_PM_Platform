import json
import re
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[3]
KNOWLEDGE_DIR = PROJECT_DIR / "docs" / "knowledge"

CATALOGS = {
    "shadcn-ui": "shadcn-components.catalog.json",
    "taptap": "taptap-components.catalog.json",
}

ROLE_HINTS = {
    "action": {"button", "link"},
    "button": {"button"},
    "input": {"input", "textarea", "select", "form"},
    "navigation": {"navigation", "menu", "tabs", "breadcrumb", "pagination"},
    "selection": {"checkbox", "radio", "select", "toggle", "switch"},
    "feedback": {"alert", "message", "result", "tooltip", "popover"},
    "dialog": {"dialog", "drawer", "popover"},
    "data": {"table", "chart", "badge", "tag"},
    "identity": {"avatar"},
    "progress": {"progress", "steps"},
    "media": {"upload", "image", "avatar"},
    "card": {"card"},
    "info_card": {"card"},
    "product_card": {"card"},
    "testimonial": {"card", "avatar"},
    "icon_button": {"button", "icon"},
}


def _tokens(value: object) -> set[str]:
    text = json.dumps(value, ensure_ascii=False).lower()
    return {part for part in re.findall(r"[a-z0-9]+", text) if len(part) > 2}


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


class KnowledgeIndex:
    """Small deterministic router over generated component catalogs."""

    def __init__(self, directory: Path = KNOWLEDGE_DIR) -> None:
        self.directory = directory
        self._catalogs: dict[str, dict[str, Any]] = {}
        self._entry_cache: dict[str, list[dict[str, Any]]] = {}

    def select(self, library_ids: list[str], source_file: str) -> list[str]:
        text = " ".join([*library_ids, source_file]).lower()
        selected = [name for name in CATALOGS if name in text]
        if "shadcn" in text and "shadcn-ui" not in selected:
            selected.append("shadcn-ui")
        if "tap tap" in text and "taptap" not in selected:
            selected.append("taptap")
        return selected

    def shortlist(
        self,
        requirements: list[dict[str, Any]],
        library_ids: list[str],
        source_file: str,
        per_requirement: int = 12,
    ) -> dict[str, Any]:
        selected = self.select(library_ids, source_file)
        matches: list[dict[str, Any]] = []
        for library in selected:
            entries = self._entries(library)
            for requirement in requirements:
                ranked = sorted(
                    ((self._score(requirement, entry), entry) for entry in entries),
                    key=lambda item: (-item[0], item[1]["canonical_path"]),
                )
                for score, entry in ranked[:per_requirement]:
                    if score <= 0:
                        continue
                    matches.append(
                        {
                            **entry,
                            "node_id": requirement["node_id"],
                            "knowledge_score": score,
                        }
                    )
        deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
        for item in matches:
            key = (item["library_id"], item["node_id"], item["component_id"])
            deduped[key] = item
        return {
            "libraries": selected,
            "matches": list(deduped.values()),
            "strategy": "page → semantic family → exact variant → writable slots",
        }

    def _catalog(self, library: str) -> dict[str, Any]:
        if library not in self._catalogs:
            path = self.directory / CATALOGS[library]
            self._catalogs[library] = json.loads(path.read_text(encoding="utf-8"))
        return self._catalogs[library]

    def _entries(self, library: str) -> list[dict[str, Any]]:
        if library in self._entry_cache:
            return self._entry_cache[library]
        catalog = self._catalog(library)
        details: dict[str, dict[str, Any]] = {}
        entries: dict[str, dict[str, Any]] = {}
        for page_name, page in catalog.get("pages", {}).items():
            for component in page.get("components", []):
                component_id = str(component.get("id", ""))
                detail = component.get("detail") or {}
                details[component_id] = detail
                entries[component_id] = self._entry(
                    library,
                    page_name,
                    component.get("name", ""),
                    component_id,
                    detail,
                    component.get("type", "COMPONENT"),
                )
        for family in catalog.get("families", []):
            family_name = str(family.get("name", ""))
            page_name = str(family.get("page", ""))
            for variant in family.get("variants", []):
                component_id = str(variant.get("id", ""))
                detail = details.get(component_id, {})
                entry = self._entry(
                    library,
                    page_name,
                    variant.get("name", family_name),
                    component_id,
                    detail,
                    variant.get("type", "COMPONENT"),
                )
                entry["family"] = family_name
                entry["variant_axes"] = family.get("variant_axes", {})
                entries[component_id] = entry
        result = [entry for entry in entries.values() if entry["type"] == "COMPONENT"]
        self._entry_cache[library] = result
        return result

    @staticmethod
    def _entry(
        library: str,
        page: str,
        name: object,
        component_id: str,
        detail: dict[str, Any],
        component_type: object,
    ) -> dict[str, Any]:
        label = str(name)
        return {
            "library_id": library,
            "component_id": component_id,
            "name": label,
            "family": label.split(",", 1)[0],
            "page": page,
            "canonical_path": f"{page.strip()}/{label}",
            "type": str(component_type),
            "text_slots": [value for value in detail.get("propCandidates", []) if str(value).startswith("text:")],
            "slot_candidates": detail.get("propCandidates", []),
        }

    @staticmethod
    def _score(requirement: dict[str, Any], entry: dict[str, Any]) -> int:
        wanted = _tokens(requirement)
        role = _normalized(str(requirement.get("role", "")))
        role_hints: set[str] = set()
        for key, hints in ROLE_HINTS.items():
            if key in role:
                wanted.update(hints)
                role_hints.update(hints)
        family_tokens = _tokens({"family": entry["family"], "page": entry["page"]})
        detail_tokens = _tokens(
            {
                "name": entry["name"],
                "slots": entry["slot_candidates"],
                "axes": entry.get("variant_axes", {}),
            }
        )
        score = len(wanted & family_tokens) * 12
        score += len(wanted & detail_tokens) * 3
        name = _normalized(entry["name"])
        family = _normalized(f"{entry['page']} {entry['family']}")
        if role and role in family:
            score += 30
        if role_hints & family_tokens:
            score += 25
        if "internal" in _normalized(str(entry["page"])):
            score -= 30
        variant = _normalized(str(requirement.get("variant_intent") or ""))
        if variant and variant in name:
            score += 12
        return score

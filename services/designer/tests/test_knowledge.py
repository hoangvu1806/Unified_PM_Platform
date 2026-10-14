import json
from pathlib import Path

from app.openpencil.knowledge import KnowledgeIndex


def test_shortlist_uses_selected_knowledge_without_dumping_catalog(tmp_path: Path) -> None:
    catalog = {
        "pages": {
            "Actions": {
                "components": [
                    {
                        "id": "button-primary",
                        "name": "Button, Variant=Primary",
                        "type": "COMPONENT",
                        "detail": {"propCandidates": ["text:Label"]},
                    },
                    {
                        "id": "avatar",
                        "name": "Avatar",
                        "type": "COMPONENT",
                        "detail": {"propCandidates": []},
                    },
                ]
            }
        },
        "families": [],
    }
    for name in ("shadcn-components.catalog.json", "taptap-components.catalog.json"):
        (tmp_path / name).write_text(json.dumps(catalog), encoding="utf-8")

    result = KnowledgeIndex(tmp_path).shortlist(
        [{"node_id": "buy", "role": "action button", "variant_intent": "primary"}],
        ["shadcn-ui"],
        "library.fig",
        per_requirement=1,
    )

    assert result["libraries"] == ["shadcn-ui"]
    assert result["matches"][0]["component_id"] == "button-primary"
    assert result["matches"][0]["node_id"] == "buy"

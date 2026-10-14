import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.models import (
    ComponentBinding,
    ComponentBindingSet,
    ComponentCandidate,
    ProjectSpecification,
)
from app.openpencil.binding import validate_bindings
from app.workflow.build import _resolver_context, resolve_component_bindings


def _project() -> ProjectSpecification:
    return ProjectSpecification.model_validate(
        {
            "schema_version": "3.0",
            "brief": {
                "product_name": "Quality App",
                "product_summary": "Review deviations",
                "platforms": ["mobile"],
                "screens": [],
            },
            "design_context": {
                "product_summary": "Review deviations",
                "visual_direction": "Operational",
            },
            "screens": [
                {
                    "screen_id": "screen-a",
                    "platforms": ["mobile"],
                    "specification": {
                        "schema_version": "2.0",
                        "screen_name": "Deviation",
                        "platform": "mobile",
                        "viewport_width": 390,
                        "viewport_height": 844,
                        "summary": "Submit a deviation",
                        "root": {
                            "id": "root-a",
                            "kind": "container",
                            "name": "Root",
                            "children": [
                                {
                                    "id": "save-a",
                                    "kind": "component",
                                    "name": "Save",
                                    "requirement": {
                                        "role": "button",
                                        "variant_intent": "primary",
                                        "required_slots": ["label"],
                                    },
                                }
                            ],
                        },
                    },
                },
                {
                    "screen_id": "screen-b",
                    "platforms": ["mobile"],
                    "specification": {
                        "schema_version": "2.0",
                        "screen_name": "Approval",
                        "platform": "mobile",
                        "viewport_width": 390,
                        "viewport_height": 844,
                        "summary": "Approve a deviation",
                        "root": {
                            "id": "root-b",
                            "kind": "container",
                            "name": "Root",
                            "children": [
                                {
                                    "id": "approve-b",
                                    "kind": "component",
                                    "name": "Approve",
                                    "requirement": {
                                        "role": "button",
                                        "variant_intent": "success",
                                    },
                                }
                            ],
                        },
                    },
                },
            ],
        }
    )


def _candidate(component_id: str, name: str) -> ComponentCandidate:
    return ComponentCandidate(
        component_id=component_id,
        library_id="library.fig",
        name=name,
        canonical_path=f"Actions/{name}",
        text_slots=["text:label"],
    )


def test_input_binding_rejects_table_cell_when_writable_input_exists() -> None:
    requirement = {"node_id": "email", "role": "text_input", "content": {"placeholder": "Email"}}
    candidates = [
        ComponentCandidate(
            component_id="table-cell", library_id="library.fig", name="Input cell",
            canonical_path="Table/Content/Single line/Input", text_slots=[],
        ),
        ComponentCandidate(
            component_id="input", library_id="library.fig", name="Input",
            canonical_path="Input/Default", text_slots=["text:Placeholder"],
        ),
    ]
    proposed = ComponentBindingSet(bindings=[
        ComponentBinding(node_id="email", status="resolved", component_id="table-cell")
    ])

    checked = validate_bindings([requirement], candidates, proposed)
    assert checked.bindings[0].status == "unresolved"
    catalog, matches = _resolver_context([requirement], candidates, {})
    assert [item["component_id"] for item in catalog] == ["input"]
    assert [item["component_id"] for item in matches["email"]] == ["input"]


def test_resolver_context_keeps_ranked_matches_and_real_alternatives() -> None:
    candidates = [_candidate("primary", "Primary"), _candidate("danger", "Danger")]
    knowledge = {
        "libraries": ["test"],
        "matches": [
            {
                "node_id": "save-a",
                "component_id": "primary",
                "knowledge_score": 80,
                "family": "Button",
                "slot_candidates": ["text:label", "icon:left"],
            },
            {
                "node_id": "other-screen",
                "component_id": "danger",
                "knowledge_score": 70,
                "family": "Button",
                "large_unused_detail": "x" * 100_000,
            },
        ],
    }

    catalog, matches = _resolver_context([{"node_id": "save-a", "role": "button"}], candidates, knowledge)

    assert {item["component_id"] for item in catalog} == {"primary", "danger"}
    assert [item["component_id"] for item in matches["save-a"]] == [
        "primary",
        "danger",
    ]
    assert matches["save-a"][0]["slot_candidates"] == ["text:label", "icon:left"]
    assert len(json.dumps({"catalog": catalog, "matches": matches})) < 2_000


def test_component_resolution_calls_llm_per_screen_with_compact_context() -> None:
    project = _project()
    candidates = [_candidate("primary", "Primary"), _candidate("success", "Success")]
    knowledge = {
        "matches": [
            {"node_id": "save-a", "component_id": "primary", "knowledge_score": 90},
            {"node_id": "approve-b", "component_id": "success", "knowledge_score": 95},
        ],
        "unused_catalog": "x" * 100_000,
    }
    prompts = SimpleNamespace(render=lambda _name, **values: "\n".join(str(value) for value in values.values()))
    llm = SimpleNamespace(
        structured=AsyncMock(
            side_effect=[
                ComponentBindingSet(
                    bindings=[
                        ComponentBinding(
                            node_id="save-a",
                            status="resolved",
                            component_id="primary",
                        )
                    ]
                ),
                ComponentBindingSet(
                    bindings=[
                        ComponentBinding(
                            node_id="approve-b",
                            status="resolved",
                            component_id="success",
                        )
                    ]
                ),
            ]
        )
    )
    owner = SimpleNamespace(llm=llm, prompts=prompts, events=SimpleNamespace(emit=AsyncMock()))
    run = SimpleNamespace(id=uuid4(), revision=1)

    result = asyncio.run(resolve_component_bindings(owner, run, project, candidates, knowledge))

    assert llm.structured.await_count == 2
    prompts_sent = [call.kwargs["prompt"] for call in llm.structured.await_args_list]
    assert all("unused_catalog" not in prompt for prompt in prompts_sent)
    assert all(len(prompt) < 2_000 for prompt in prompts_sent)
    assert [item.node_id for item in result.bindings] == ["save-a", "approve-b"]
    assert owner.events.emit.await_count == 2


def test_unknown_text_metadata_is_deferred_to_live_component_inspection() -> None:
    candidate = _candidate("button", "Primary").model_copy(update={"text_slots": []})
    result = validate_bindings(
        [
            {
                "node_id": "save",
                "role": "button",
                "content": {"label": "Save changes"},
            }
        ],
        [candidate],
        ComponentBindingSet(
            bindings=[ComponentBinding(node_id="save", status="resolved", component_id="button")]
        ),
    )

    assert result.bindings[0].status == "resolved"
    assert result.bindings[0].text_values == {"text:Text": "Save changes"}

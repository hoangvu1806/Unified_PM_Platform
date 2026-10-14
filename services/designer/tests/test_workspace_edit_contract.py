from app.workflow.workspace_agent import _edit_contract, _structure_manifest


def test_structure_manifest_keeps_parent_and_children() -> None:
    manifest = _structure_manifest(
        {
            "children": [
                {
                    "id": "root",
                    "name": "Login",
                    "type": "FRAME",
                    "children": [{"id": "button", "name": "Login button", "type": "INSTANCE"}],
                }
            ]
        },
        "root",
    )
    assert manifest["root_id"] == "root"
    assert manifest["nodes"][0]["children"] == ["button"]


def test_edit_contract_targets_named_node_and_protects_unrelated_nodes() -> None:
    manifest = _structure_manifest(
        {
            "children": [
                {"id": "root", "name": "Login", "children": [
                    {"id": "button", "name": "Login button", "children": []},
                    {"id": "email", "name": "Email input", "children": []},
                ]}
            ]
        },
        "root",
    )
    contract = _edit_contract(
        manifest,
        page_id="page-1",
        root_id="root",
        instruction="Đổi màu Login button",
        action="edit_page",
    )
    assert contract["mode"] == "local_edit"
    assert contract["target_node_ids"] == ["button"]
    assert "email" in contract["protected_node_ids"]
    assert "render_page" in contract["forbidden_operations"]

import struct
from pathlib import Path

from app.api.routes import _image_size, _standard_asset_id
from app.models import ComponentRequirement, UiNode
from app.openpencil.media import _contained_size, _raster_size
from app.workflow.build import _asset_for_node, _promote_uploaded_brand_media


def test_contained_size_preserves_portrait_aspect_ratio_without_upscaling() -> None:
    assert _contained_size((454, 648), 192, 192) == (134.52, 192.0)
    assert _contained_size((100, 50), 300, 300) == (100.0, 50.0)


def test_raster_size_reads_png_dimensions(tmp_path: Path) -> None:
    path = tmp_path / "asset.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + struct.pack(">II", 454, 648))

    assert _raster_size(path) == (454, 648)
    assert _image_size(path.read_bytes()) == (454, 648)


def test_asset_id_is_readable_unique_and_token_safe() -> None:
    first = _standard_asset_id("GĐU Mascot Final.png", ".png")
    second = _standard_asset_id("GĐU Mascot Final.png", ".png")

    assert first.startswith("gdu-mascot-final-png-")
    assert first != second
    assert "." not in first


def test_multiple_assets_are_selected_by_filename_not_list_order() -> None:
    assets = [
        {"id": "background-png-a", "name": "Background.png", "visual_role": "background"},
        {"id": "mascot-png-b", "name": "Mascot.png", "visual_role": "mascot"},
    ]
    node = UiNode(
        id="brand_mascot",
        kind="media",
        name="Brand mascot",
        content={"src": "Mascot.png", "alt": "University mascot"},
    )

    assert _asset_for_node(node, assets) == assets[1]


def test_upload_does_not_turn_unrelated_graphics_into_components() -> None:
    root = UiNode(
        id="root",
        kind="container",
        name="Splash",
        content={},
        children=[
            UiNode(
                id="mascot",
                kind="media",
                name="Mascot image",
                content={"alt": "mascot", "use_uploaded_asset": True},
            ),
            UiNode(
                id="loading_dot",
                kind="graphic",
                name="Loading dot",
                content={"shape": "circle"},
            ),
        ],
    )
    assets = [{"id": "mascot-png-a", "name": "Mascot.png", "visual_role": "mascot"}]

    _promote_uploaded_brand_media(root, assets)

    assert root.children[0].kind == "media"
    assert root.children[0].content["asset_id"] == "mascot-png-a"
    assert root.children[1].kind == "graphic"
    assert "asset_id" not in root.children[1].content


def test_uploaded_asset_is_not_added_without_explicit_screen_opt_in() -> None:
    root = UiNode(
        id="root",
        kind="container",
        name="Login",
        content={},
        children=[UiNode(id="decorative_media", kind="media", name="Decorative media", content={})],
    )

    _promote_uploaded_brand_media(
        root,
        [{"id": "mascot-png-a", "name": "Mascot.png", "visual_role": "mascot"}],
    )

    assert root.children[0].kind == "media"
    assert "asset_id" not in root.children[0].content


def test_legacy_asset_component_regression_is_repaired_on_retry() -> None:
    mascot = UiNode(
        id="mascot",
        kind="component",
        name="Mascot image",
        content={
            "asset_id": "mascot-png-a",
            "asset_binding": "design_system_component",
        },
        requirement=ComponentRequirement(role="asset_visual", capabilities=["image"]),
    )
    dot = UiNode(
        id="dot",
        kind="component",
        name="Loading dot",
        content={
            "shape": "circle",
            "asset_id": "mascot-png-a",
            "asset_binding": "design_system_component",
        },
        requirement=ComponentRequirement(role="asset_visual", capabilities=["image"]),
    )
    root = UiNode(
        id="root",
        kind="container",
        name="Splash",
        content={},
        children=[mascot, dot],
    )
    assets = [{"id": "mascot-png-a", "name": "Mascot.png", "visual_role": "mascot"}]

    _promote_uploaded_brand_media(root, assets)

    assert mascot.kind == "media"
    assert mascot.requirement is None
    assert mascot.content["asset_id"] == "mascot-png-a"
    assert "asset_binding" not in mascot.content
    assert dot.kind == "graphic"
    assert dot.requirement is None
    assert "asset_id" not in dot.content
    assert "asset_binding" not in dot.content

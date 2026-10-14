import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.errors import AppError
from app.generation.cohesion import normalize_project_cohesion
from app.models import (
    DesignBrief,
    ProjectDesignContext,
    ProjectSpecification,
    ScreenBrief,
    ScreenSpecification,
    StyleManifest,
    UiNode,
    UiSpecification,
)
from app.openpencil.media import apply_unsplash_media


def _spec(style: StyleManifest, media: bool = False) -> UiSpecification:
    children = (
        [
            UiNode(
                id="hero-photo",
                kind="media",
                name="Tea harvest",
                content={"query": "tea farmer harvesting mountain leaves", "source": "stock"},
            )
        ]
        if media
        else []
    )
    return UiSpecification(
        screen_name="Home",
        viewport_width=1440,
        viewport_height=1000,
        summary="Tea atelier",
        style_manifest=style,
        root=UiNode(id="root", kind="container", name="Root", children=children),
    )


def test_cohesion_repairs_style_drift_without_repeating_wireframes() -> None:
    shared = StyleManifest(primary_color="#14532D", font_family="Fraunces")
    project = ProjectSpecification(
        brief=DesignBrief(
            product_description="Tea atelier",
            platforms=["desktop"],
            screens=[ScreenBrief(name="Home")],
            output_filename="tea.fig",
            scope_confirmed=True,
        ),
        design_context=ProjectDesignContext(
            product_summary="Tea atelier",
            visual_direction="Botanical field notes",
            style_manifest=shared,
            navigation=["Home"],
        ),
        screens=[
            ScreenSpecification(
                screen_id="home",
                platforms=["desktop"],
                specification=_spec(StyleManifest(primary_color="#2563EB")),
            )
        ],
    )
    normalized, report = normalize_project_cohesion(project)
    assert report["status"] == "valid"
    assert report["repairs"][0]["category"] == "style-token-drift"
    assert normalized.screens[0].specification.style_manifest == shared


def test_openpencil_media_requires_unsplash_and_keeps_provenance() -> None:
    async def scenario(provider: str) -> dict:
        async def call(_session: object, tool: str, arguments: dict) -> dict:
            if tool == "find_nodes":
                return {"nodes": [{"id": "photo-node", "width": 900, "height": 600}]}
            return {
                "provider": provider,
                "applied": 1,
                "failed": 0,
                "results": [
                    {
                        "id": "photo-node",
                        "photo": {
                            "sourceId": "abc123",
                            "photographer": "A. Maker",
                            "width": 2400,
                            "height": 1600,
                        },
                    }
                ],
            }

        return await apply_unsplash_media(
            SimpleNamespace(_call=call),
            object(),
            document_id="doc",
            page_id="page",
            specification=_spec(StyleManifest(), media=True),
        )

    result = asyncio.run(scenario("unsplash"))
    assert result["assets"][0]["source_id"] == "abc123"
    assert result["assets"][0]["query"] == "tea farmer harvesting mountain leaves"
    with pytest.raises(AppError) as captured:
        asyncio.run(scenario("pexels"))
    assert captured.value.code == "OPENPENCIL_UNSPLASH_REQUIRED"


def test_legacy_media_icon_is_not_sent_to_unsplash() -> None:
    icon = UiNode.model_validate(
        {
            "id": "sec_asset_list_card_1_icon",
            "kind": "media",
            "name": "Bitcoin icon",
            "content": {"type": "icon", "query": "bitcoin logo"},
        }
    )
    assert icon.kind == "icon"

    spec = _spec(StyleManifest()).model_copy(
        update={"root": UiNode(id="root", kind="container", name="Root", children=[icon])}
    )

    async def scenario() -> dict:
        async def fail_if_called(*_args: object, **_kwargs: object) -> dict:
            raise AssertionError("stock_photo must not run for UI icons")

        return await apply_unsplash_media(
            SimpleNamespace(_call=fail_if_called),
            object(),
            document_id="doc",
            page_id="page",
            specification=spec,
        )

    result = asyncio.run(scenario())
    assert result["applied"] == 0
    assert result["assets"] == []


def test_local_asset_and_placeholder_are_not_sent_to_stock_provider() -> None:
    mascot = UiNode(
        id="gdu-mascot",
        kind="media",
        name="GDU mascot",
        content={"source": "user_asset", "asset_id": "mascot-1"},
    )
    placeholder = UiNode(
        id="avatar-placeholder",
        kind="media",
        name="Account avatar placeholder",
        content={"source": "placeholder"},
    )
    spec = _spec(StyleManifest()).model_copy(
        update={"root": UiNode(id="root", kind="container", name="Root", children=[mascot, placeholder])}
    )

    async def fail_if_called(*_args: object, **_kwargs: object) -> dict:
        raise AssertionError("stock_photo must not run for local assets or placeholders")

    result = asyncio.run(
        apply_unsplash_media(
            SimpleNamespace(_call=fail_if_called),
            object(),
            document_id="doc",
            page_id="page",
            specification=spec,
        )
    )
    assert result == {"provider": "none", "applied": 0, "failed": 0, "assets": []}


def test_legacy_untyped_icon_and_chart_are_vector_nodes() -> None:
    icon = UiNode(
        id="sec_asset_list_card_1_icon",
        kind="media",
        name="Asset Icon",
        content={"query": "bitcoin logo icon crypto currency minimalist"},
    )
    chart = UiNode(
        id="portfolio_chart",
        kind="media",
        name="Portfolio chart",
        content={"type": "image", "query": "crypto line chart data visualization"},
    )
    assert icon.kind == "icon"
    assert chart.kind == "graphic"


def test_golden_evaluation_set_covers_six_product_shapes() -> None:
    path = Path(__file__).resolve().parents[1] / "data" / "evals" / "golden-projects.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    assert {item["id"] for item in cases} == {
        "marketing",
        "dashboard",
        "commerce",
        "mobile",
        "dense-form",
        "multi-screen",
    }

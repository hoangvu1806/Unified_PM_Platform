from app.models import DesignBrief, ScreenBrief
from app.workflow.analysis import _build_scope, _merge_brief


def _brief(screens: list[ScreenBrief]) -> DesignBrief:
    return DesignBrief(
        product_name="Aurora",
        product_description="Deviation workflow",
        platforms=["mobile"],
        screens=screens,
        output_filename="aurora.fig",
        scope_confirmed=True,
    )


def test_partial_build_scope_does_not_erase_master_screen_inventory() -> None:
    current = _brief(
        [
            ScreenBrief(id="UIT-02", name="Intake"),
            ScreenBrief(id="UIT-03", name="Severity"),
            ScreenBrief(id="UIT-04", name="Inventory Hold"),
        ]
    )
    proposed = _brief(
        [
            ScreenBrief(id="UIT-02", name="Intake updated"),
            ScreenBrief(id="UIT-03", name="Severity"),
        ]
    )

    merged = _merge_brief(current, proposed)
    scope = _build_scope(merged, proposed, ["UIT-02", "UIT-03"])

    assert [screen.id for screen in merged.screens] == ["UIT-02", "UIT-03", "UIT-04"]
    assert merged.screens[0].name == "Intake updated"
    assert [screen.id for screen in scope.screens] == ["UIT-02", "UIT-03"]


def test_touchpoint_subset_selects_the_physical_screen_that_covers_it() -> None:
    brief = _brief(
        [
            ScreenBrief(
                id="deviation-intake",
                name="Deviation intake and triage",
                source_ui_ids=["UIT-02", "UIT-03", "UIT-05"],
            ),
            ScreenBrief(
                id="inventory-hold",
                name="Inventory hold",
                source_ui_ids=["UIT-04"],
            ),
        ]
    )

    scope = _build_scope(brief, brief, ["UIT-03"])

    assert [screen.id for screen in scope.screens] == ["deviation-intake"]

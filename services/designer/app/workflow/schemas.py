"""Structured outputs of the HTML designer: routing decision and UI specification."""

from __future__ import annotations

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..designsystem.scene import slug
from ..models import DesignBrief, Platform, ScreenStateReference, StyleCandidate

HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def _unique_in_order(values: list[Any]) -> list[Any]:
    """Deduplicate JSON values without requiring them to be hashable."""
    result: list[Any] = []
    for value in values:
        if not any(value == existing for existing in result):
            result.append(value)
    return result


class DesignDecision(BaseModel):
    intent: Literal["chat", "clarify_design", "propose_scope", "gather", "start_design", "edit_screens"]
    reply: str = Field(min_length=1)
    brief: DesignBrief = Field(default_factory=DesignBrief)
    target_screen_ids: list[str] = Field(default_factory=list)
    instruction: str = ""

    @field_validator("target_screen_ids")
    @classmethod
    def slugs(cls, value: list[str]) -> list[str]:
        return [slug(v, "screen") for v in value]


class PreviewContentContract(BaseModel):
    """LLM analysis of exact visible copy and actions against the approved brief."""

    default_visible_text_exact: list[str] = Field(default_factory=list, max_length=40)
    conditional_text_exact: list[str] = Field(default_factory=list, max_length=40)
    default_visible_actions: list[str] = Field(default_factory=list, max_length=20)
    conditional_actions: list[str] = Field(default_factory=list, max_length=20)


class StylePreviewPlan(BaseModel):
    """Three project-specific art directions for the style-preview gallery."""

    options: list[StyleCandidate] = Field(min_length=3, max_length=3)
    palette_exploration: Literal["explorable", "brand_limited"] = Field(
        default="explorable",
        description="Use brand_limited only when explicit fixed brand tokens leave fewer than three suitable background color families.",
    )
    content_contract: PreviewContentContract = Field(
        description="Required classification of approved screen content by first-paint visibility before generating the gallery.",
    )

    @model_validator(mode="after")
    def distinct_options(self) -> "StylePreviewPlan":
        keys = [item.key for item in self.options]
        if len(set(keys)) != 3:
            raise ValueError("Style preview option keys must be unique")
        palette_roles = {
            "primary", "primary_foreground", "background", "foreground", "surface", "muted",
            "muted_foreground", "border", "accent", "success", "warning", "destructive",
        }
        for item in self.options:
            if not palette_roles.issubset(item.palette):
                raise ValueError(f"Style option {item.key} must define every shared palette role")
            palette = Palette.model_validate(item.palette)
            if _contrast_ratio(palette.primary, palette.primary_foreground) < 4.5:
                safe_foreground = _derive_contrast_foreground(
                    palette.primary,
                    preferred=palette.primary_foreground,
                    sources=(palette.foreground, palette.muted_foreground),
                )
                if safe_foreground is None:
                    raise ValueError(
                        f"Primary color {palette.primary} cannot support 4.5:1 text contrast; "
                        "choose a darker or lighter shade within this palette."
                    )
                # The semantic on-primary role is derived deterministically so
                # a bright domain CTA uses a shade from its own palette roles.
                item.palette["primary_foreground"] = safe_foreground
        if self.palette_exploration == "explorable":
            for left in range(len(self.options)):
                for right in range(left + 1, len(self.options)):
                    left_palette = self.options[left].palette
                    right_palette = self.options[right].palette
                    background_delta = _delta_e(
                        _hex_to_lab(left_palette["background"]),
                        _hex_to_lab(right_palette["background"]),
                    )
                    primary_delta = _delta_e(
                        _hex_to_lab(left_palette["primary"]),
                        _hex_to_lab(right_palette["primary"]),
                    )
                    if max(background_delta, primary_delta) < 16:
                        raise ValueError(
                            "Explorable style options must differ clearly in either background or primary color "
                            "(CIE76 ΔE >= 16). "
                            f"Options {self.options[left].key} and {self.options[right].key} use backgrounds "
                            f"{left_palette['background']} / {right_palette['background']} (ΔE {background_delta:.1f}) "
                            f"and primaries {left_palette['primary']} / {right_palette['primary']} "
                            f"(ΔE {primary_delta:.1f}); change at least one pair to a more distinct domain palette."
                        )
        asset_ids = [item.preview_asset_id for item in self.options if item.preview_asset_id]
        if len(set(asset_ids)) != len(asset_ids):
            raise ValueError("Style preview options must use distinct illustration assets")
        if sum(item.recommended for item in self.options) != 1:
            for index, item in enumerate(self.options):
                item.recommended = index == 0
        return self


def _hex_to_lab(value: str) -> tuple[float, float, float]:
    """Convert a six-digit sRGB hex color to CIE Lab for palette comparison."""
    value = value.strip().lstrip("#")
    rgb = [int(value[index:index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
              for channel in rgb]
    x = (linear[0] * 0.4124564 + linear[1] * 0.3575761 + linear[2] * 0.1804375) / 0.95047
    y = (linear[0] * 0.2126729 + linear[1] * 0.7151522 + linear[2] * 0.0721750)
    z = (linear[0] * 0.0193339 + linear[1] * 0.1191920 + linear[2] * 0.9503041) / 1.08883

    def pivot(channel: float) -> float:
        return channel ** (1 / 3) if channel > 0.008856 else 7.787 * channel + 16 / 116

    fx, fy, fz = pivot(x), pivot(y), pivot(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _delta_e(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def _relative_luminance(value: str) -> float:
    value = value.strip().lstrip("#")
    channels = [int(value[index:index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
              for channel in channels]
    return sum(weight * channel for weight, channel in zip((0.2126, 0.7152, 0.0722), linear))


def _contrast_ratio(left: str, right: str) -> float:
    light, dark = sorted((_relative_luminance(left), _relative_luminance(right)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _derive_contrast_foreground(
    background: str,
    *,
    preferred: str,
    sources: tuple[str, ...],
) -> str | None:
    """Reuse a semantic text role, or adjust its shade while preserving its hue family."""
    source_colors = list(dict.fromkeys((preferred, *sources)))
    for color in source_colors:
        if _contrast_ratio(background, color) >= 4.5:
            return color

    background_rgb = _hex_rgb(background)
    options: list[tuple[float, str]] = []
    for source in source_colors:
        source_rgb = _hex_rgb(source)
        for step in range(1, 101):
            factor = 1 - step / 100
            for channels in (
                tuple(round(channel * factor) for channel in source_rgb),
                tuple(round(255 - (255 - channel) * factor) for channel in source_rgb),
            ):
                shade = _rgb_hex(channels)
                if _contrast_ratio(background, shade) < 4.5:
                    continue
                distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(source_rgb, channels)))
                options.append((distance, shade))
    return min(options, default=(0, ""), key=lambda item: item[0])[1] or None


def _hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def _rgb_hex(value: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{channel:02x}" for channel in value)


class Palette(BaseModel):
    """Theme colors (hex). Applied as Tailwind tokens: bg-primary, text-muted-foreground, border-border …"""

    primary: str
    primary_foreground: str = "#ffffff"
    background: str = "#ffffff"
    foreground: str = "#0f172a"
    surface: str = "#ffffff"
    muted: str = "#f1f5f9"
    muted_foreground: str = "#64748b"
    border: str = "#e2e8f0"
    accent: str = "#f59e0b"
    success: str = "#16a34a"
    warning: str = "#d97706"
    destructive: str = "#dc2626"

    @model_validator(mode="before")
    @classmethod
    def hexes(cls, value):
        if isinstance(value, dict):
            value = {k: (f"#{m.group(1).lower()}" if isinstance(v, str) and (m := HEX.match(v.strip())) else v)
                     for k, v in value.items()}
        return value

    @model_validator(mode="after")
    def require_hex_colors(self) -> "Palette":
        invalid = [name for name, value in self.model_dump().items() if not HEX.match(str(value).strip())]
        if invalid:
            raise ValueError("Palette values must be six-digit hex colors: " + ", ".join(invalid))
        return self


class DesignDirection(BaseModel):
    """Art direction shared by every screen of the product (a compact DESIGN.md)."""

    mood: str = Field("", description="2 sentences: personality, density, emphasis — specific to this domain")
    palette: Palette | None = Field(None, description="Domain-fitting colors; null when a design system is imported")
    heading_font: str = Field("Inter", description="Google Font for headings")
    body_font: str = Field("Inter", description="Google Font for body and UI text")
    radius: Literal["none", "sm", "md", "lg", "xl", "2xl"] = "lg"
    density: Literal["compact", "comfortable", "spacious"] = "comfortable"
    do: list[str] = Field(default_factory=list, max_length=6)
    dont: list[str] = Field(default_factory=list, max_length=6)


class ScenarioTargetCheck(BaseModel):
    """Explicit link from an approved trigger to the UI region it governs."""

    source_rule: str = Field(min_length=1, max_length=300)
    phase: Literal["first_paint", "after_trigger"] = "after_trigger"
    trigger_selectors: list[str] = Field(default_factory=list, max_length=12)
    target_selector: str = Field(
        min_length=1,
        max_length=100,
        pattern=r'^\[data-state-target="[a-z0-9][a-z0-9_-]{0,63}"\]$',
        description='Exact stable target selector, for example [data-state-target="medical-proof"].',
    )
    visible: bool


class StateScenario(BaseModel):
    """Deterministic browser case for a BA-approved conditional screen state."""

    name: str = Field(min_length=1, max_length=100)
    initial_values: dict[str, str] = Field(default_factory=dict, max_length=12)
    initial_checked: dict[str, bool] = Field(default_factory=dict, max_length=8)
    initial_visible: list[str] = Field(default_factory=list, max_length=12)
    initial_hidden: list[str] = Field(default_factory=list, max_length=12)
    set_values: dict[str, str] = Field(default_factory=dict, max_length=12)
    set_checked: dict[str, bool] = Field(default_factory=dict, max_length=8)
    click_selectors: list[str] = Field(
        default_factory=list, max_length=12,
        description="Ordered click triggers, repeat a selector to model repeated submissions such as lockout thresholds.",
    )
    visible: list[str] = Field(default_factory=list, max_length=12)
    hidden: list[str] = Field(default_factory=list, max_length=12)
    target_checks: list[ScenarioTargetCheck] = Field(
        default_factory=list, max_length=24,
        description=("Explicit scenario→trigger→UI target mapping. Use stable trigger selectors from "
                     "initial/set values, checked controls, or ordered clicks and exact data-state-target selectors."),
    )

    @model_validator(mode="after")
    def has_assertions(self) -> "StateScenario":
        if not any((self.visible, self.hidden, self.initial_visible, self.initial_hidden, self.target_checks)):
            raise ValueError("A state scenario must assert at least one visible or hidden target")
        trigger_selectors = set(self.set_values) | set(self.set_checked) | set(self.click_selectors)
        for check in self.target_checks:
            if check.phase == "after_trigger":
                if not check.trigger_selectors:
                    raise ValueError("An after-trigger target check must name the trigger selectors it depends on")
                unknown = set(check.trigger_selectors) - trigger_selectors
                if unknown:
                    raise ValueError("Target check references undeclared scenario trigger(s): " + ", ".join(sorted(unknown)))
            elif check.trigger_selectors:
                raise ValueError("A first-paint target check cannot depend on post-paint triggers")
        return self


class ConditionalBranch(BaseModel):
    """A browser-testable condition branch from an approved business rule."""

    name: str = Field(min_length=1, max_length=100)
    set_values: dict[str, str] = Field(default_factory=dict, max_length=12)
    set_checked: dict[str, bool] = Field(default_factory=dict, max_length=8)
    click_selectors: list[str] = Field(
        default_factory=list, max_length=12,
        description="Ordered click triggers for this branch; repeat a selector to model consecutive actions.",
    )
    visible: bool

    @model_validator(mode="after")
    def has_inputs(self) -> "ConditionalBranch":
        if not self.set_values and not self.set_checked and not self.click_selectors:
            raise ValueError("A conditional branch must set at least one control value")
        return self


class ConditionalRegion(BaseModel):
    """A conditional region with an explicit default and approved alternative cases."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    rule: str = Field(min_length=1, max_length=300)
    default_values: dict[str, str] = Field(default_factory=dict, max_length=12)
    default_checked: dict[str, bool] = Field(default_factory=dict, max_length=8)
    default_visible: bool
    branches: list[ConditionalBranch] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def has_default_inputs(self) -> "ConditionalRegion":
        if not self.default_values and not self.default_checked:
            raise ValueError("A conditional region must define the approved default control value")
        return self


class ScreenContentContract(BaseModel):
    """Classifies product content separately from conditional and test-only behavior."""

    persistent_regions: list[str] = Field(default_factory=list, max_length=20)
    test_only_states: list[str] = Field(default_factory=list, max_length=20)


class ScreenSpec(BaseModel):
    """Only first-paint fields consumed by screen UI generation."""

    id: str
    name: str = Field(min_length=1, max_length=120)
    platform: Platform = "desktop"
    purpose: str = ""
    layout: str = ""
    sections: list[str] = Field(default_factory=list)
    data: list[str] = Field(default_factory=list)
    navigation: list[str] = Field(default_factory=list)
    source_ui_ids: list[str] = Field(default_factory=list)
    must_show: list[str] = Field(
        default_factory=list, max_length=30,
        description="Verbatim first-paint copy only, sourced from the approved visible_copy list; never component descriptions.",
    )
    visual_asset_role: Literal["none", "hero", "background"] = "none"
    ux_query: str = ""

    @model_validator(mode="after")
    def normalize(self) -> "ScreenSpec":
        self.id = slug(self.id or self.name, "screen")
        if self.platform == "responsive":
            self.platform = "desktop"
        self.navigation = [slug(s, "screen") for s in self.navigation]
        self.must_show = [t.strip() for t in self.must_show if t and t.strip()]
        return self


class ScreenStateSpec(BaseModel):
    """State-only references, triggers, and future test cases, stored outside ScreenSpec."""

    states: list[str] = Field(default_factory=list)
    state_spec: list[ScreenStateReference] = Field(default_factory=list)
    conditional_content: list[str] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list, max_length=15)
    content_contract: ScreenContentContract = Field(default_factory=ScreenContentContract)
    conditional_regions: list[ConditionalRegion] = Field(default_factory=list, max_length=12)
    state_scenarios: list[StateScenario] = Field(default_factory=list, max_length=12)
    conditional_actions: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def normalize_and_expand(self) -> "ScreenStateSpec":
        self.states = [slug(state, "state") for state in self.states]
        generated: list[StateScenario] = []
        existing_names = {scenario.name for scenario in self.state_scenarios}
        for region in self.conditional_regions:
            target = f'[data-state-target="{region.id}"]'
            default_name = f"{region.id}:approved-default"
            if default_name not in existing_names:
                generated.append(StateScenario(
                    name=default_name,
                    initial_values=region.default_values,
                    initial_checked=region.default_checked,
                    initial_visible=[target] if region.default_visible else [],
                    initial_hidden=[] if region.default_visible else [target],
                    set_values=region.default_values,
                    set_checked=region.default_checked,
                    visible=[target] if region.default_visible else [],
                    hidden=[] if region.default_visible else [target],
                    target_checks=[
                        ScenarioTargetCheck(source_rule=region.rule, phase="first_paint", target_selector=target,
                                            visible=region.default_visible),
                        ScenarioTargetCheck(
                            source_rule=region.rule, phase="after_trigger",
                            trigger_selectors=list(dict.fromkeys([*region.default_values, *region.default_checked])),
                            target_selector=target, visible=region.default_visible,
                        ),
                    ],
                ))
            for branch in region.branches:
                name = f"{region.id}:{branch.name}"
                if name in existing_names:
                    continue
                generated.append(StateScenario(
                    name=name,
                    initial_values=region.default_values,
                    initial_checked=region.default_checked,
                    initial_visible=[target] if region.default_visible else [],
                    initial_hidden=[] if region.default_visible else [target],
                    set_values=branch.set_values,
                    set_checked=branch.set_checked,
                    click_selectors=branch.click_selectors,
                    visible=[target] if branch.visible else [],
                    hidden=[] if branch.visible else [target],
                    target_checks=[
                        ScenarioTargetCheck(source_rule=region.rule, phase="first_paint", target_selector=target,
                                            visible=region.default_visible),
                        ScenarioTargetCheck(
                            source_rule=region.rule, phase="after_trigger",
                            trigger_selectors=list(dict.fromkeys([
                                *branch.set_values, *branch.set_checked, *branch.click_selectors,
                            ])),
                            target_selector=target, visible=branch.visible,
                        ),
                    ],
                ))
        self.state_scenarios.extend(generated)
        return self


class UiSpec(BaseModel):
    schema_version: Literal["html-1"] = "html-1"
    style_direction: str = ""
    selected_style_key: str = ""
    style_name: str = ""
    visual_contract: dict[str, Any] = Field(default_factory=dict)
    # Approved default content and state analysis are persisted in separate maps.
    approved_default_screens: dict[str, dict[str, Any]] = Field(default_factory=dict)
    state_reference_screens: dict[str, dict[str, Any]] = Field(default_factory=dict)
    state_specs: dict[str, ScreenStateSpec] = Field(default_factory=dict)
    design: DesignDirection = Field(default_factory=DesignDirection)
    screens: list[ScreenSpec] = Field(min_length=1, max_length=20)

    @model_validator(mode="before")
    @classmethod
    def separate_legacy_state_data(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        state_specs = {key: dict(item) if isinstance(item, dict) else item
                       for key, item in (data.get("state_specs") or {}).items()}
        legacy_state_fields = ("states", "state_spec", "conditional_regions", "content_contract",
                               "state_scenarios", "rules", "conditional_content")
        for raw_screen in data.get("screens") or []:
            if not isinstance(raw_screen, dict):
                continue
            screen_id = slug(str(raw_screen.get("id") or raw_screen.get("name") or "screen"), "screen")
            legacy = {field: raw_screen.pop(field) for field in legacy_state_fields if field in raw_screen}
            if legacy:
                state = dict(state_specs.get(screen_id) or {})
                for field, item in legacy.items():
                    if isinstance(item, list):
                        state[field] = _unique_in_order([*(state.get(field) or []), *item])
                    elif field not in state:
                        state[field] = item
                state_specs[screen_id] = state

        approved_defaults = dict(data.get("approved_default_screens") or {})
        state_references = dict(data.get("state_reference_screens") or {})
        legacy_briefs = data.pop("approved_brief_screens", {})
        for screen_id, brief in (legacy_briefs or {}).items():
            if not isinstance(brief, dict):
                continue
            state_keys = {"conditional_content", "states", "state_spec", "open_questions", "rules"}
            state_ref = {key: brief[key] for key in state_keys if key in brief}
            outline = [str(item) for item in (brief.get("content_outline") or [])]
            conditional = [
                *(brief.get("conditional_content") or []),
                *(brief.get("conditional_actions") or []),
                *(brief.get("states") or []),
                *(state.get("trigger", "") for state in (brief.get("state_spec") or []) if isinstance(state, dict)),
                *(item for state in (brief.get("state_spec") or []) if isinstance(state, dict)
                  for item in (state.get("content") or [])),
            ]
            key = lambda text: "".join(char for char in str(text).casefold() if char.isalnum())
            default_outline = [item for item in outline if not any(
                key(ref) and (key(ref) in key(item) or key(item) in key(ref)) for ref in conditional
            )]
            actions = [str(item) for item in (brief.get("actions") or [])]
            default_actions = brief.get("default_actions")
            if default_actions is None:
                conditional_keys = [key(item) for item in conditional if len(key(item)) >= 8]
                default_actions = [item for item in actions if not any(
                    state_key in key(item) or key(item) in state_key
                    for state_key in conditional_keys if key(item)
                )]
            state_ref["conditional_actions"] = [item for item in actions if item not in default_actions]
            defaults = {key: item for key, item in brief.items()
                        if key not in state_keys | {"actions", "default_actions"}}
            defaults["content_outline"] = default_outline
            defaults["default_actions"] = default_actions
            approved_defaults.setdefault(screen_id, defaults)
            state_references.setdefault(screen_id, state_ref)

        data.pop("approved_brief_screens", None)
        data["approved_default_screens"] = approved_defaults
        data["state_reference_screens"] = state_references
        data["state_specs"] = state_specs
        return data

    @model_validator(mode="after")
    def unique_ids(self) -> "UiSpec":
        seen: set[str] = set()
        for screen in self.screens:
            base, i = screen.id, 2
            while screen.id in seen:
                screen.id, i = f"{base}-{i}", i + 1
            seen.add(screen.id)
        if not self.design.mood and self.style_direction:
            self.design.mood = self.style_direction
        return self

    def screen(self, screen_id: str) -> ScreenSpec | None:
        return next((s for s in self.screens if s.id == screen_id), None)

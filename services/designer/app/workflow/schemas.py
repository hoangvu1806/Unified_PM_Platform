"""Structured outputs of the HTML designer: routing decision and UI specification."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..designsystem.scene import slug
from ..models import DesignBrief, Platform

HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


class DesignDecision(BaseModel):
    intent: Literal["chat", "clarify_design", "propose_scope", "start_design", "edit_screens"]
    reply: str = Field(min_length=1)
    brief: DesignBrief = Field(default_factory=DesignBrief)
    target_screen_ids: list[str] = Field(default_factory=list)
    instruction: str = ""

    @field_validator("target_screen_ids")
    @classmethod
    def slugs(cls, value: list[str]) -> list[str]:
        return [slug(v, "screen") for v in value]


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


class ImageNeed(BaseModel):
    slot: str = Field(description="Where it goes, e.g. 'hero background', 'course card cover'")
    query: str = Field(description="2-4 English keywords for a real photo")
    orientation: Literal["landscape", "portrait", "squarish"] = "landscape"


class ScreenSpec(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=120)
    platform: Platform = "desktop"
    purpose: str = ""
    layout: str = ""
    sections: list[str] = Field(default_factory=list)
    states: list[str] = Field(default_factory=list)
    data: list[str] = Field(default_factory=list)
    navigation: list[str] = Field(default_factory=list)
    source_ui_ids: list[str] = Field(default_factory=list)
    must_show: list[str] = Field(
        default_factory=list, max_length=30,
        description="Exact visible texts the screen must contain: field labels, buttons, column headers, messages",
    )
    rules: list[str] = Field(default_factory=list, max_length=15, description="Business rules (BR-xx: …) the UI must reflect")
    imagery: list[ImageNeed] = Field(default_factory=list, max_length=4)
    ux_query: str = Field("", description="3-6 English keywords for the screen's UI concerns")

    @model_validator(mode="after")
    def normalize(self) -> "ScreenSpec":
        self.id = slug(self.id or self.name, "screen")
        if self.platform == "responsive":
            self.platform = "desktop"
        self.states = [slug(s, "state") for s in self.states]
        self.navigation = [slug(s, "screen") for s in self.navigation]
        self.must_show = [t.strip() for t in self.must_show if t and t.strip()]
        return self


class UiSpec(BaseModel):
    schema_version: Literal["html-1"] = "html-1"
    style_direction: str = ""
    design: DesignDirection = Field(default_factory=DesignDirection)
    screens: list[ScreenSpec] = Field(min_length=1, max_length=20)

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

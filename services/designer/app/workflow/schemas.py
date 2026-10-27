"""Structured outputs of the HTML designer: routing decision and UI specification."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..designsystem.scene import slug
from ..models import DesignBrief, Platform


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

    @model_validator(mode="after")
    def normalize(self) -> "ScreenSpec":
        self.id = slug(self.id or self.name, "screen")
        if self.platform == "responsive":
            self.platform = "desktop"
        self.states = [slug(s, "state") for s in self.states]
        self.navigation = [slug(s, "screen") for s in self.navigation]
        return self


class UiSpec(BaseModel):
    schema_version: Literal["html-1"] = "html-1"
    style_direction: str = ""
    screens: list[ScreenSpec] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_ids(self) -> "UiSpec":
        seen: set[str] = set()
        for screen in self.screens:
            base, i = screen.id, 2
            while screen.id in seen:
                screen.id, i = f"{base}-{i}", i + 1
            seen.add(screen.id)
        return self

    def screen(self, screen_id: str) -> ScreenSpec | None:
        return next((s for s in self.screens if s.id == screen_id), None)

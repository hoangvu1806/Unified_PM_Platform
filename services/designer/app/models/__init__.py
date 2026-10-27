from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class RunStage(StrEnum):
    # core/app/journey.py reads specification, review_spec, assembly, review_final and finished.
    REQUIREMENT = "requirement"
    SPECIFICATION = "specification"
    REVIEW_SPEC = "review_spec"
    ASSEMBLY = "assembly"
    REVIEW_FINAL = "review_final"
    FINISHED = "finished"
    BLOCKED = "blocked"
    FAILED = "failed"
    # Stages of the OpenPencil pipeline; kept so runs stored before the HTML designer stay readable.
    COMPONENTS = "components"
    BINDING = "binding"
    LAYOUT_CHECK = "layout_check"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


Platform = Literal["mobile", "tablet", "desktop", "responsive"]


class ScreenBrief(BaseModel):
    id: str = ""
    name: str = Field(min_length=1, max_length=120)
    purpose: str = Field(default="", max_length=1_000)
    platforms: list[Platform] = Field(default_factory=list)
    source_ui_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_id(self) -> "ScreenBrief":
        if not self.id:
            value = "-".join(part for part in self.name.lower().split() if part)
            self.id = "".join(char for char in value if char.isalnum() or char == "-") or "screen"
        if not self.source_ui_ids and self.id.upper().startswith("UIT-"):
            self.source_ui_ids = [self.id]
        else:
            self.source_ui_ids = list(dict.fromkeys(self.source_ui_ids))
        return self


class DesignBrief(BaseModel):
    product_name: str = ""
    product_description: str = ""
    platforms: list[Platform] = Field(default_factory=list)
    screens: list[ScreenBrief] = Field(default_factory=list)
    style_name: str | None = None
    design_system_ids: list[str] = Field(default_factory=list)
    scope_confirmed: bool = False
    # English keywords (product type, industry, audience, platform) to retrieve design knowledge.
    design_query: str = ""

    def missing_fields(self) -> list[str]:
        missing: list[str] = []
        if not self.product_description.strip():
            missing.append("product_description")
        if not self.platforms:
            missing.append("platforms")
        if not self.screens:
            missing.append("screens")
        if not self.scope_confirmed:
            missing.append("scope_confirmation")
        return missing


class ExactAsset(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=240)
    mime_type: str = Field(min_length=1, max_length=120)
    usage: Literal["exact"] = "exact"
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    aspect_ratio: float | None = Field(default=None, gt=0)
    visual_role: str = "image"
    dominant_colors: list[str] = Field(default_factory=list, max_length=8)
    background_type: str = "unknown"
    recommended_fit: Literal["contain", "cover"] = "contain"
    recommended_placement: str = "content area"
    placement_reason: str = ""
    safe_padding_percent: int = Field(default=0, ge=0, le=40)


class SessionCreate(BaseModel):
    title: str = "Untitled session"
    # Platform: the core.projects row; required when auth is on.
    project_id: str | None = Field(default=None, max_length=120)


class DesignerHandoffRequest(BaseModel):
    """BA-to-Designer handoff envelope used by the integration boundary."""

    source_agent: str = Field(default="ba-agent", max_length=80)
    correlation_id: str = Field(min_length=1, max_length=200)
    feature_id: str = Field(min_length=1, max_length=200)
    title: str = Field(default="BA handoff", min_length=1, max_length=240)
    prompt: str = Field(min_length=3, max_length=50_000)
    screen_name: str = Field(default="BA Feature", max_length=120)
    platform: Platform = "responsive"
    style_name: str | None = None
    library_ids: list[str] = Field(default_factory=list)
    assets: list[ExactAsset] = Field(default_factory=list, max_length=4)
    asset_data_urls: dict[str, str] = Field(default_factory=dict)
    # Platform: project of the BA feature and the BA user who handed off.
    project_id: str | None = Field(default=None, max_length=120)
    requested_by: str | None = Field(default=None, max_length=120)
    ba_package: dict[str, Any] | None = None


class DesignerHandoffResponse(BaseModel):
    handoff_id: str
    source_agent: str
    correlation_id: str
    feature_id: str
    session_id: UUID
    run_id: UUID
    status: str = "queued"
    designer_url: str


class SessionView(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    design_brief: DesignBrief | None = None
    # Platform scoping and provenance.
    project_id: str | None = None
    created_by: str | None = None
    source: str | None = None
    source_ref: str | None = None
    source_artifact_id: str | None = None
    design_system_id: str | None = None
    # Art direction of the spec as a theme ({"css", "fonts"}) when no design system is imported.
    visual_theme: dict[str, Any] | None = None


SCREEN_WIDTHS: dict[str, int] = {"mobile": 390, "tablet": 834, "desktop": 1440, "responsive": 1440}


class ScreenWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    platform: Platform = "desktop"
    width: int | None = Field(default=None, ge=320, le=2560)
    html: str = Field(min_length=1, max_length=400_000)
    note: str = Field(default="", max_length=400)


class ScreenView(BaseModel):
    id: str
    name: str
    platform: Platform
    width: int
    position: int
    version: int
    updated_at: datetime
    updated_by: str | None = None
    run_id: str | None = None
    html: str | None = None


DEFAULT_DESIGN_SYSTEM = "default"


class DesignSystemView(BaseModel):
    id: str
    name: str
    project_id: str | None = None
    status: Literal["importing", "ready", "failed"] = "ready"
    error: str | None = None
    source_name: str | None = None
    created_by: str | None = None
    created_at: datetime | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class DesignSystemDetail(DesignSystemView):
    theme_css: str = ""
    fonts: list[str] = Field(default_factory=list)
    components: list[dict[str, Any]] = Field(default_factory=list)


class SessionDesignSystem(BaseModel):
    design_system_id: str = Field(min_length=1, max_length=80)


class ScreenVersionView(BaseModel):
    version: int
    created_at: datetime
    updated_by: str | None = None
    run_id: str | None = None
    note: str | None = None


class RunCreate(BaseModel):
    prompt: str = Field(min_length=3, max_length=50_000)
    screen_name: str = Field(default="Screen", max_length=120)
    platform: Platform = "responsive"
    style_name: str | None = None
    library_ids: list[str] = Field(default_factory=list)
    assets: list[ExactAsset] = Field(default_factory=list, max_length=4)

    @field_validator("screen_name", mode="before")
    @classmethod
    def default_empty_screen_name(cls, v: Any) -> str:
        if isinstance(v, str):
            val = v.strip()
            return val if val else "Screen"
        return "Screen"


class RunView(BaseModel):
    id: UUID
    session_id: UUID
    revision: int
    prompt: str
    screen_name: str
    platform: str
    style_name: str | None = None
    stage: RunStage
    status: RunStatus
    intent: Literal["chat", "clarify_design", "start_design", "gather", "design"] | None = None
    assistant_message: str | None = None
    library_ids: list[str]
    specification: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class ReviewCreate(BaseModel):
    checkpoint: Literal["specification", "final"]
    decision: Literal["approved", "changes_requested", "rejected"]
    revision: int = Field(ge=1)
    feedback: str = Field(default="", max_length=4_000)


class WorkflowEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    revision: int
    sequence: int
    type: str
    time: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)


class Problem(BaseModel):
    code: str
    title: str
    detail: str
    retryable: bool = False
    action: str | None = None

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class RunStage(StrEnum):
    REQUIREMENT = "requirement"
    SPECIFICATION = "specification"
    REVIEW_SPEC = "review_spec"
    COMPONENTS = "components"
    BINDING = "binding"
    ASSEMBLY = "assembly"
    LAYOUT_CHECK = "layout_check"
    REVIEW_FINAL = "review_final"
    FINISHED = "finished"
    BLOCKED = "blocked"
    FAILED = "failed"


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
    output_filename: str = ""
    style_name: str | None = None
    design_system_ids: list[str] = Field(default_factory=list)
    scope_confirmed: bool = False

    @field_validator("output_filename", mode="after")
    @classmethod
    def normalize_filename(cls, value: str) -> str:
        clean = value.strip()
        if clean and not clean.lower().endswith(".fig"):
            clean += ".fig"
        return clean

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
        if not self.output_filename:
            missing.append("output_filename")
        return missing


class RootDecision(BaseModel):
    intent: Literal["chat", "clarify_design", "start_design", "gather", "design"]
    reply: str = Field(min_length=1)
    brief: DesignBrief = Field(default_factory=DesignBrief)
    missing_fields: list[str] = Field(default_factory=list)
    requested_screen_ids: list[str] = Field(default_factory=list)
    # Legacy fields keep old clients/tests readable during Sprint 1 migration.
    style_name: str | None = None
    screen_name: str | None = None
    platform: Platform | None = None

    @model_validator(mode="after")
    def normalize_legacy_decision(self) -> "RootDecision":
        if self.intent == "gather":
            self.intent = "clarify_design"
        elif self.intent == "design":
            self.intent = "start_design"
        if self.style_name and not self.brief.style_name:
            self.brief.style_name = self.style_name
        if self.platform and not self.brief.platforms:
            self.brief.platforms = [self.platform]
        if self.screen_name and not self.brief.screens:
            self.brief.screens = [ScreenBrief(name=self.screen_name, platforms=self.brief.platforms)]
            self.brief.scope_confirmed = True
        return self


ConversationDecision = RootDecision


class OpenPencilProfile(BaseModel):
    endpoint: str = Field(min_length=1)
    source_file: str = Field(min_length=1)
    output_file: str | None = None
    target_mode: Literal["new_file", "existing_file"] = "new_file"
    knowledge_id: Literal["auto", "shadcn-ui", "taptap"] = "auto"

    @field_validator("endpoint", "source_file", "output_file", mode="before")
    @classmethod
    def strip_profile_value(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("endpoint")
    @classmethod
    def validate_http_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("endpoint must be an absolute HTTP(S) URL")
        return value

    @model_validator(mode="after")
    def protect_component_source(self) -> "OpenPencilProfile":
        if self.output_file and self.target_mode == "new_file" and self.source_file == self.output_file:
            raise ValueError("output_file must differ from source_file in new_file mode")
        return self


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


class OpenPencilPageView(BaseModel):
    id: str
    name: str


class OpenPencilDocumentView(BaseModel):
    id: str
    name: str
    path: str | None = None
    active: bool = False
    current_page_id: str | None = None
    current_page_name: str | None = None
    pages: list[OpenPencilPageView] = Field(default_factory=list)


class LayoutRule(BaseModel):
    mode: Literal["block", "flex", "grid", "absolute"] = "flex"
    direction: Literal["row", "column"] = "column"
    gap: int = Field(default=16, ge=0, le=128)
    columns: int | None = Field(default=None, ge=1, le=12)
    padding: int = Field(default=0, ge=0, le=160)


class ComponentRequirement(BaseModel):
    role: str
    variant_intent: str | None = None
    required_slots: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)


class UiNode(BaseModel):
    id: str
    kind: Literal["container", "component", "text", "media", "icon", "graphic"]
    name: str
    content: dict[str, Any] = Field(default_factory=dict)
    layout: LayoutRule | None = None
    requirement: ComponentRequirement | None = None
    children: list["UiNode"] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_legacy_icon_media(self) -> "UiNode":
        """Old specs represented UI icons as media; photos alone belong to Unsplash."""
        semantics = " ".join(
            str(value)
            for value in (
                self.content.get("type", ""),
                self.content.get("query", ""),
                self.id,
                self.name,
            )
        ).lower()
        if self.kind == "media" and any(token in semantics for token in ("icon", "logo", "symbol", "glyph")):
            self.kind = "icon"
        elif self.kind == "media" and any(
            token in semantics
            for token in (
                "chart",
                "graph",
                "sparkline",
                "candlestick",
                "data visualization",
            )
        ):
            self.kind = "graphic"
        return self


class StyleManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    primary_color: str = "#2563EB"
    primary_dark: str = "#1D4ED8"
    accent_color: str = Field(
        default="#F59E0B",
        validation_alias=AliasChoices("accent_color", "accent_gold"),
        serialization_alias="accent_color",
    )
    neutral_dark: str = "#0F172A"
    neutral_body: str = "#475569"
    border_color: str = "#E2E8F0"
    canvas_background: str = "#F8FAFC"
    surface_card: str = "#FFFFFF"
    success_color: str = "#10B981"
    warning_color: str = "#F59E0B"
    danger_color: str = "#EF4444"
    info_color: str = "#3B82F6"
    corner_radius: int = Field(default=12, ge=0, le=40)
    font_family: str = "Inter"
    design_style: str | None = None

    @field_validator("accent_color", mode="before")
    @classmethod
    def default_null_accent(cls, value: Any) -> Any:
        return "#F59E0B" if value is None else value

    @property
    def accent_gold(self) -> str:
        return self.accent_color


class SectionPlan(BaseModel):
    id: str
    role: str = Field(
        default="content",
        description="Semantic role (e.g. navigation, hero, form, metrics, catalog, features, content, table, footer, custom)",
    )
    name: str
    intent: str
    composition: str = Field(
        default="",
        description="Chosen spatial composition and hierarchy, including how it departs from a basic stack.",
    )
    visual_anchor: str = Field(
        default="",
        description="The content or interaction that carries this section's visual focus.",
    )
    component_treatment: str = Field(
        default="",
        description="How real design-system components are arranged, sized, paired, or selectively restyled.",
    )
    layout_mode: Literal["flex", "grid", "block"] = "flex"
    direction: Literal["row", "column"] = "column"
    columns: int | None = None
    gap: int | None = Field(
        default=None, ge=0, le=128, description="Spacing gap between elements in px (e.g. 12, 16, 24, 32)"
    )
    padding: int | None = Field(
        default=None, ge=0, le=160, description="Internal section padding in px (e.g. 16, 24, 48, 64)"
    )
    target_item_count: int | None = Field(
        default=None, ge=1, le=12,
        description="Set only when the request or product content calls for a specific count.",
    )


class PageSkeleton(BaseModel):
    screen_name: str
    platform: Literal["mobile", "tablet", "desktop", "responsive"] = "responsive"
    viewport_width: int = Field(default=1440, ge=320, le=2560)
    viewport_height: int = Field(default=3800, ge=480, le=12000)
    summary: str
    style_manifest: StyleManifest = Field(default_factory=StyleManifest)
    sections: list[SectionPlan] = Field(min_length=1, description="Context-aware sections planned for this interface")
    hard_constraints: list[str] = Field(
        default_factory=list,
        description="Non-negotiable requirements extracted from the user request.",
    )


class SectionUiNode(BaseModel):
    id: str
    kind: Literal["container"] = "container"
    name: str
    layout: LayoutRule | None = None
    children: list[UiNode] = Field(default_factory=list)


class UiSpecification(BaseModel):
    schema_version: Literal["2.0"] = "2.0"
    screen_name: str
    platform: Literal["mobile", "tablet", "desktop", "responsive"] = "responsive"
    viewport_width: int = Field(ge=320, le=2560)
    viewport_height: int = Field(ge=480, le=12000)
    summary: str
    root: UiNode
    style_manifest: StyleManifest = Field(default_factory=StyleManifest)
    hard_constraints: list[str] = Field(
        default_factory=list,
        description="Non-negotiable requirements inherited from the approved PageSkeleton.",
    )

    @model_validator(mode="after")
    def assign_unique_node_ids(self) -> "UiSpecification":
        # Repeated controls may share labels, but tool mounts need distinct IDs.
        used: set[str] = set()

        def visit(node: UiNode) -> None:
            base, index = node.id, 2
            while node.id in used:
                node.id = f"{base}_{index}"
                index += 1
            used.add(node.id)
            for child in node.children:
                visit(child)

        visit(self.root)
        return self


class WorkspaceActionTarget(BaseModel):
    action: Literal["edit_page", "add_page", "refine_page"]
    screen_id: str = ""
    page_id: str = ""
    page_name: str = ""
    reference_page_id: str = ""
    new_page_name: str = ""
    instruction: str = ""
    use_selection: bool = False

    @model_validator(mode="before")
    @classmethod
    def normalize_router_action_alias(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if normalized.get("action") in {"design", "start_design"}:
            normalized["action"] = "add_page" if normalized.get("new_page_name") else "edit_page"
        return normalized


class WorkspaceActionDecision(BaseModel):
    action: Literal["chat", "clarify", "edit_page", "add_page", "refine_page"]
    reply: str = ""
    page_name: str = ""
    new_page_name: str = ""
    instruction: str = ""
    use_selection: bool = False
    requires_confirmation: bool = False
    confidence: float = Field(default=0, ge=0, le=1)
    targets: list[WorkspaceActionTarget] = Field(default_factory=list, max_length=20)

    @model_validator(mode="before")
    @classmethod
    def normalize_router_action_alias(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        action = normalized.get("action")
        if action == "gather":
            normalized["action"] = "clarify"
        elif action in {"design", "start_design"}:
            targets = normalized.get("targets")
            first_action = (
                targets[0].get("action")
                if isinstance(targets, list) and targets and isinstance(targets[0], dict)
                else None
            )
            normalized["action"] = (
                first_action
                if first_action in {"edit_page", "add_page", "refine_page"}
                else "add_page"
                if normalized.get("new_page_name")
                else "edit_page"
            )
        return normalized

    def normalized_targets(self) -> list[WorkspaceActionTarget]:
        if self.targets:
            return self.targets
        if self.action in {"edit_page", "add_page", "refine_page"}:
            return [
                WorkspaceActionTarget(
                    action=self.action,
                    page_name=self.page_name,
                    new_page_name=self.new_page_name,
                    instruction=self.instruction,
                    use_selection=self.use_selection,
                )
            ]
        return []


class WorkspacePageSectionPlan(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=600)
    content_requirements: list[str] = Field(default_factory=list, max_length=12)


class WorkspacePagePlan(BaseModel):
    screen_id: str = ""
    page_name: str = Field(min_length=1, max_length=120)
    platform: Platform = "responsive"
    purpose: str = Field(min_length=1, max_length=1_000)
    sections: list[WorkspacePageSectionPlan] = Field(min_length=1, max_length=16)
    states: list[str] = Field(default_factory=list, max_length=16)
    business_constraints: list[str] = Field(default_factory=list, max_length=20)


class ProjectDesignContext(BaseModel):
    product_summary: str
    visual_direction: str
    style_manifest: StyleManifest = Field(default_factory=StyleManifest)
    navigation: list[str] = Field(default_factory=list)
    shared_patterns: list[str] = Field(default_factory=list)
    content_tone: str = "clear and product-specific"
    responsive_strategy: str = "Adapt hierarchy and interaction density per viewport."


class ScreenSpecification(BaseModel):
    screen_id: str
    platforms: list[Platform]
    specification: UiSpecification


class ProjectSpecification(BaseModel):
    schema_version: Literal["3.0"] = "3.0"
    brief: DesignBrief
    design_context: ProjectDesignContext
    screens: list[ScreenSpecification]


class ComponentCandidate(BaseModel):
    component_id: str
    library_id: str
    name: str
    path: str = ""
    canonical_path: str
    width: float | None = None
    height: float | None = None
    text_slots: list[str] = Field(default_factory=list)
    variant_name: str | None = None
    knowledge_score: int = 0


class ComponentBinding(BaseModel):
    node_id: str
    status: Literal["resolved", "unresolved"]
    component_id: str | None = None
    library_id: str | None = None
    canonical_path: str | None = None
    selected_variant: str | None = None
    text_values: dict[str, str] = Field(default_factory=dict)
    confidence: float = Field(default=0, ge=0, le=1)
    rationale: str = ""
    reason: str | None = None


class ComponentBindingSet(BaseModel):
    bindings: list[ComponentBinding]


class OpenPencilArtifact(BaseModel):
    document_id: str
    page_id: str
    page_name: str
    output_file: str
    root_node_id: str
    created_nodes: int
    share_url: str | None = None


class RunArtifacts(BaseModel):
    project_specification: ProjectSpecification | None = None
    openpencil_capability: dict[str, Any] | None = None
    openpencil_checkpoint: dict[str, Any] | None = None
    cohesion_review: dict[str, Any] | None = None
    media_manifest: dict[str, Any] | None = None
    knowledge_snapshot: dict[str, Any] | None = None
    component_candidates: list[dict[str, Any]] = Field(default_factory=list)
    component_bindings: dict[str, Any] | None = None
    openpencil_artifact: dict[str, Any] | None = None
    layout_review: dict[str, Any] | None = None
    workspace_mutation: dict[str, Any] | None = None
    workspace_action_trace: dict[str, Any] | None = None
    live_canvas_snapshot: dict[str, Any] | None = None
    canvas_sync: dict[str, Any] | None = None
    manual_overrides: dict[str, Any] | None = None
    export_preflight: dict[str, Any] | None = None


class LayoutFinding(BaseModel):
    severity: Literal["info", "warning", "error"]
    category: str
    node_ids: list[str] = Field(default_factory=list)
    evidence: str
    correction: str

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, v: Any) -> str:
        if isinstance(v, str):
            val = v.lower().strip()
            if val in ("critical", "major", "blocker", "error", "high"):
                return "error"
            if val in ("warning", "warn", "moderate", "medium"):
                return "warning"
            if val in ("info", "minor", "low", "suggestion", "note"):
                return "info"
        return "info"


class LayoutReview(BaseModel):
    status: Literal["valid", "invalid"]
    summary: str
    findings: list[LayoutFinding] = Field(default_factory=list)

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, v: Any) -> str:
        if isinstance(v, str):
            val = v.lower().strip()
            if val in ("valid", "passed", "approved", "success", "ok"):
                return "valid"
            if val in ("invalid", "failed", "rejected", "error"):
                return "invalid"
        return "valid"


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
    mcp_profile: OpenPencilProfile | None = None
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


class SessionWorkspace(BaseModel):
    document_id: str = ""
    document_path: str = ""
    document_name: str = ""
    page_id: str = ""
    page_name: str = ""


class SessionWorkspaceUpdate(SessionWorkspace):
    pass


class WorkspaceScreenReference(BaseModel):
    screen_id: str
    page_id: str
    page_name: str
    platform: Platform = "responsive"
    root_node_id: str = ""
    root_name: str = ""
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0


class SessionView(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    design_brief: DesignBrief | None = None
    workspace: SessionWorkspace | None = None
    pending_workspace_action: WorkspaceActionDecision | None = None
    screen_registry: dict[str, WorkspaceScreenReference] = Field(default_factory=dict)
    # Platform scoping and provenance.
    project_id: str | None = None
    created_by: str | None = None
    source: str | None = None
    source_ref: str | None = None


class DesignSystemView(BaseModel):
    id: str
    name: str
    path: str
    knowledge_id: Literal["auto", "shadcn-ui", "taptap"] = "auto"


class RunCreate(BaseModel):
    prompt: str = Field(min_length=3, max_length=50_000)
    screen_name: str = Field(default="Screen", max_length=120)
    platform: Platform = "responsive"
    style_name: str | None = None
    library_ids: list[str] = Field(default_factory=list)
    mcp_profile: OpenPencilProfile | None = None
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
    mcp_profile: OpenPencilProfile | None = None
    specification: UiSpecification | None = None
    error: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class ReviewCreate(BaseModel):
    checkpoint: Literal["specification", "final"]
    decision: Literal["approved", "changes_requested", "rejected"]
    revision: int = Field(ge=1)
    feedback: str = Field(default="", max_length=4_000)
    mcp_profile: OpenPencilProfile | None = None


class RunRetry(BaseModel):
    mcp_profile: OpenPencilProfile | None = None


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

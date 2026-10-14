"""Pydantic request and response schemas for all API endpoints.

Consolidates models from both V1 chat API and Feature CRUD endpoints.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ── Enums ─────────────────────────────────────────────────────


class TicketType(str, Enum):
    """Supported BA Ticket Types."""

    NEW_FEATURE = "NEW_FEATURE"
    FEATURE_ENHANCEMENT = "FEATURE_ENHANCEMENT"
    BUG_FIX_LOG = "BUG_FIX_LOG"
    PROCESS_OPTIMIZATION = "PROCESS_OPTIMIZATION"


# ── V1 Chat Request Models ───────────────────────────────────


class ChatAction(str, Enum):
    """Optional structured chat actions."""

    VALIDATE = "validate"


class ReferenceAsset(BaseModel):
    """An external image/logo supplied as a design reference."""

    id: str = Field(..., min_length=1, max_length=120)
    type: str = Field(default="image", min_length=1, max_length=40)
    filename: str | None = Field(default=None, max_length=255)
    uri: str | None = Field(default=None, description="A URL or data URL for the reference asset.")
    usage: str = Field(default="reference", description="reference or exact")
    used_in: list[str] = Field(default_factory=list)
    instruction: str | None = Field(default=None, max_length=2000)


class AgentChatRequest(BaseModel):
    """Input payload for API V1 agent chat."""

    user_id: str = Field(..., min_length=1, description="ID của người dùng")
    ticket_type: TicketType = Field(
        default=TicketType.NEW_FEATURE, description="Loại yêu cầu ticket"
    )
    user_message: str = Field(..., min_length=1, description="Nội dung tin nhắn")
    active_section: str | None = Field(
        default=None, description="Section đang active (fd/br/wf/uc)"
    )
    action: ChatAction | None = Field(
        default=None, description="Hành động đặc biệt, vd validate"
    )
    assets: list[ReferenceAsset] = Field(
        default_factory=list,
        description="External image/logo references for the Designer handoff.",
    )


# ── V1 Chat Response Models ──────────────────────────────────


class SectionStatusInfo(BaseModel):
    """Information on section progress and validation readiness."""

    current_section: str = Field(
        default="feature_definition", description="Section đang tương tác"
    )
    can_proceed_to_validation: bool = Field(
        default=False, description="Đã đủ điều kiện chuyển sang PENDING_VALIDATION chưa"
    )
    feature_status: str = Field(default="DRAFT", description="Control-plane feature status")
    can_export: bool = Field(
        default=False,
        description="True when VALIDATED, or EXPORTED with a current passed validation",
    )
    sections: dict[str, str] = Field(
        default_factory=lambda: {
            "feature_definition": "in_progress",
            "business_rules": "not_started",
            "workflow": "not_started",
            "use_cases": "not_started",
        },
        description="Trạng thái từng section",
    )


class ExtraDataInfo(BaseModel):
    """Extra rich UI data (images, action buttons)."""

    images: list[dict[str, Any]] = Field(
        default_factory=list, description="Danh sách hình ảnh/diagrams"
    )
    buttons: list[str] = Field(
        default_factory=list, description="Danh sách nhãn nút gợi ý hành động UI"
    )


class AgentChatResponse(BaseModel):
    """Output payload for synchronous V1 agent chat."""

    session_id: str = Field(..., description="ID phiên làm việc")
    user_id: str = Field(..., description="ID người dùng")
    ticket_type: TicketType = Field(..., description="Loại ticket")
    agent_response: str = Field(
        default="", description="Nội dung câu phản hồi từ Agent"
    )
    section_status: SectionStatusInfo = Field(
        default_factory=SectionStatusInfo, description="Trạng thái các section"
    )
    extra_data: ExtraDataInfo = Field(
        default_factory=ExtraDataInfo,
        description="Dữ liệu mở rộng UI (images, buttons)",
    )


# ── Feature CRUD Models ──────────────────────────────────────


class CreateFeatureRequest(BaseModel):
    """Request body for creating a new BA feature."""

    title: str = Field(..., min_length=1, max_length=255, description="Feature title")
    description: str = Field(default="", description="Feature description / pitch")


class SectionProgress(BaseModel):
    """Progress info for a single section."""

    section_id: str
    data: dict[str, Any] = Field(default_factory=dict)
    flags: dict[str, Any] = Field(default_factory=dict)
    is_completable: bool = False


class FeatureResponse(BaseModel):
    """Response body for a feature."""

    session_id: str
    title: str
    description: str = ""
    sections: dict[str, SectionProgress] = Field(default_factory=dict)
    feature_status: str = "DRAFT"
    project_id: str = Field(
        ...,
        description=(
            "BA project scope id: PRJ- + first 12 hex chars of sha256(session_id). "
            "Assigned at create; never a shared default like PRJ-MES-01."
        ),
    )
    can_export: bool = False
    can_proceed_to_validation: bool = False
    package_exported: bool = False
    designer_enabled: bool = False
    chat_frozen: bool = False
    open_questions: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[dict[str, Any]] = Field(default_factory=list)
    last_validation: dict[str, Any] | None = None
    can_generate_bpmn: bool = False
    active_user_story_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FeatureListItem(BaseModel):
    """Lightweight feature item for list endpoint."""

    session_id: str
    title: str
    description: str = ""
    project_id: str = Field(
        ...,
        description=(
            "BA project scope id: PRJ- + first 12 hex chars of sha256(session_id). "
            "Assigned at create; never a shared default like PRJ-MES-01."
        ),
    )
    sections_completed: int = 0
    sections_total: int = 4
    feature_status: str = "DRAFT"
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── Chat History Models ───────────────────────────────────────


class ChatMessageItem(BaseModel):
    """Item representing a single chat message in history."""

    sender: str = Field(..., description="Message sender: 'user' or 'agent'")
    text: str = Field(..., description="Message content text")


class ChatHistoryResponse(BaseModel):
    """Response body for fetching chat history."""

    session_id: str
    messages: list[ChatMessageItem] = Field(default_factory=list)


class WikiDocumentHit(BaseModel):
    """Approved wiki page returned under the feature control path."""

    page_id: str
    title: str
    snippet: str = ""
    version: str | None = None
    bucket_id: str | None = None
    namespace: str | None = None
    project_id: str | None = None
    status: str = "approved"
    updated_at: str | None = None
    validation_status: str = Field(
        default="unchecked",
        description=(
            "Relative to last Validate snapshot: "
            "pass | fail | unchecked (approved after last VA / never checked)"
        ),
    )
    validation_findings: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "V-WIKI error findings citing this page_id (or V-WIKI-03 pair). "
            "Each item: check_id, name, detail, conflict_ref, conflict_page_ids."
        ),
    )


class WikiValidationSummary(BaseModel):
    """Card-level wiki validation coherence (not the same as human Approve)."""

    overall: str = Field(
        default="unchecked",
        description="pass | fail | unchecked | mixed",
    )
    counts: dict[str, int] = Field(
        default_factory=lambda: {"pass": 0, "fail": 0, "unchecked": 0},
    )
    validated_at: str | None = None
    validation_status: str | None = Field(
        default=None,
        description="Raw last_validation.status when present",
    )
    has_run: bool = False


class WikiDocumentList(BaseModel):
    session_id: str
    project_id: str = Field(
        ...,
        description="Feature hashed project_id used for scoping (company + this project)",
    )
    documents: list[WikiDocumentHit] = Field(
        default_factory=list,
        description="All visible approved pages (company + this project)",
    )
    company_documents: list[WikiDocumentHit] = Field(
        default_factory=list,
        description="Org-wide company wiki (shared across projects)",
    )
    project_documents: list[WikiDocumentHit] = Field(
        default_factory=list,
        description="Private approved pages for this feature project_id only",
    )
    wiki_validation: WikiValidationSummary = Field(
        default_factory=WikiValidationSummary,
        description="Summary of per-page validation_status vs last Validate",
    )


class TouchpointsUpdate(BaseModel):
    """Replace the session UI touchpoints list (Designer handoff fields)."""

    ui_touchpoints: list[dict[str, Any]] = Field(default_factory=list)

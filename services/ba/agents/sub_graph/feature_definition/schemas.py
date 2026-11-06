"""Pydantic Schemas for Feature Definition Node & OQ/ASM Detection."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FeatureDefinitionData(BaseModel):
    """Schema cho FD Extractor output. LLM trả về delta mỗi turn."""

    goal: str | None = Field(
        None,
        description="WHY feature này cần tồn tại — business value cụ thể. "
        "Chỉ cập nhật khi User cung cấp thông tin mới về mục tiêu.",
    )
    actors: list[str] | None = Field(
        None,
        description="Danh sách actors liên quan (format: 'ACT-NAME: mô tả vai trò'). "
        "Gộp actors mới vào danh sách hiện tại, KHÔNG xóa actors cũ.",
    )
    scope_in: list[str] | None = Field(
        None,
        description="Capabilities thuộc phạm vi feature. "
        "Thêm mới vào danh sách hiện tại.",
    )
    scope_out: list[str] | None = Field(
        None,
        description="Capabilities KHÔNG thuộc phạm vi. "
        "Thêm mới vào danh sách hiện tại.",
    )


class OpenQuestionItem(BaseModel):
    """Mô tả một câu hỏi mở (Open Question) được phát hiện."""

    id: str | None = Field(None, description="ID tự động sinh dạng OQ-XXX")
    question: str = Field(..., description="Câu hỏi kết thúc bằng dấu ?")
    severity: str = Field("warning", description="Mức độ: critical | warning | info")
    assigned_to: str = Field(
        "PO", description="Vai trò chịu trách nhiệm: PO | Tech Lead | BA | Designer"
    )
    impact: str = Field(
        ..., description="Mô tả ảnh hưởng nếu câu hỏi không được làm rõ"
    )
    affected_artifacts: list[dict[str, str]] = Field(
        default_factory=list,
        description="Existing BR/WF/US artifact IDs this question may affect, when identifiable.",
    )


class AssumptionItem(BaseModel):
    """Mô tả một giả định (Assumption) được phát hiện."""

    id: str | None = Field(None, description="ID tự động sinh dạng ASM-XX")
    statement: str = Field(
        ..., description="Giả định cụ thể, có thể verify hoặc invalidate"
    )


class OQArtifactReference(BaseModel):
    artifact_type: Literal[
        "feature_definition", "business_rules", "workflow", "use_cases", "ui_touchpoints"
    ]
    artifact_id: str
    reason: str = ""
    oq_id: str | None = None


class OpenQuestionResolution(BaseModel):
    """User answered an existing Open Question — do not invent a new OQ."""

    id: str = Field(..., description="ID OQ đã tồn tại, ví dụ OQ-001")
    answer: str = Field(..., description="Câu trả lời cụ thể của User cho OQ này")
    status: str = Field(
        "resolved",
        description="resolved khi đã trả lời đủ; open nếu vẫn chưa đủ",
    )
    affected_artifacts: list["OQArtifactReference"] = Field(
        default_factory=list,
        description="Artifact IDs cần cập nhật vì câu trả lời này, ví dụ BR-RESET-001, WF-RESET-001, US-RESET-001.",
    )


class OQArtifactUpdate(BaseModel):
    oq_id: str
    artifact_type: Literal[
        "feature_definition", "business_rules", "workflow", "use_cases", "ui_touchpoints"
    ]
    artifact_id: str
    updated_value: str = Field(
        ..., description="Updated one artifact: markdown for workflow, JSON object for business_rules/use_cases."
    )


class OQFollowThroughData(BaseModel):
    """Artifact updates made after an OQ answer, before the BA reply is composed."""

    reviewed_oq_ids: list[str] = Field(default_factory=list)
    impacted_artifacts: list[OQArtifactReference] = Field(default_factory=list)
    updates: list[OQArtifactUpdate] = Field(default_factory=list)
    no_change_reason: str | None = Field(
        None, description="Required when an answered OQ does not require artifact changes."
    )


class OQASMDetectionData(BaseModel):
    """Schema cho OQ & ASM Detector output."""

    open_questions: list[OpenQuestionItem] = Field(
        default_factory=list,
        description="Danh sách các Open Questions mới được phát hiện từ tin nhắn User.",
    )
    assumptions: list[AssumptionItem] = Field(
        default_factory=list,
        description="Danh sách các Assumptions mới được phát hiện từ tin nhắn User.",
    )
    resolved_questions: list[OpenQuestionResolution] = Field(
        default_factory=list,
        description="OQ đã có (theo id) được User trả lời trong tin nhắn này.",
    )


__all__ = [
    "AssumptionItem",
    "FeatureDefinitionData",
    "OQASMDetectionData",
    "OpenQuestionItem",
    "OpenQuestionResolution",
    "OQArtifactReference",
    "OQArtifactUpdate",
    "OQFollowThroughData",
]

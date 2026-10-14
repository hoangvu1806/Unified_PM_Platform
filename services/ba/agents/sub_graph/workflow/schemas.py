"""Workflow section schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WorkflowData(BaseModel):
    """Delta output from WF extractor — merge vào artifacts.workflow."""

    artifact_id: str | None = Field(
        None,
        description="ID artifact dạng WF-{MODULE}-001. Chỉ set khi User/PO cung cấp.",
    )
    version: str | None = Field(
        None,
        description="Version semver của workflow doc, VD 1.0.0.",
    )
    workflow_md_path: str | None = Field(
        None,
        description="Đường dẫn file markdown nếu có; thường để trống khi content inline.",
    )
    workflow_md_content: str | None = Field(
        None,
        description=(
            "Full workflow markdown. Bắt buộc có các section: "
            "## Main Flow (bảng | Step | Actor | Action | BR Ref |, ≥3 bước), "
            "## Exception Flows, ## End States, và tùy chọn ## Sequence Diagram (mermaid). "
            "Chỉ cập nhật khi User cung cấp/chỉnh sửa luồng."
        ),
    )

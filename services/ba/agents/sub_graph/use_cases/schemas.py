"""Use Cases section schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AcceptanceCriterion(BaseModel):
    id: str | None = Field(None, description="AC id dạng AC-01")
    given: str = Field(
        ...,
        description="Precondition / trạng thái ban đầu (Given)",
    )
    when: str = Field(
        ...,
        description="Hành động kích hoạt duy nhất (When)",
    )
    then: str = Field(
        ...,
        description="Kết quả quan sát được, testable (Then)",
    )


class UseCaseItem(BaseModel):
    id: str | None = Field(None, description="UC id dạng US-01")
    actor_id: str = Field(
        ...,
        description="Actor id khớp FD.actors — VD ACT-KHACH (phần trước dấu ':')",
    )
    statement: str = Field(
        ...,
        description=(
            "User story tiếng Việt dạng: 'Là [actor], tôi muốn [goal] để [value]'. "
            "Phải chứa pattern 'muốn ... để ...'."
        ),
    )
    rule_ids: list[str] = Field(
        default_factory=list,
        description="Danh sách BR-XX liên quan; ưu tiên map từ Business Rules đã có",
    )
    bpmn_node_ids: list[str] = Field(
        default_factory=list,
        description="Back-fill sau BPMN; thường để trống ở Phase 1",
    )
    acceptance_criteria: list[AcceptanceCriterion] = Field(
        default_factory=list,
        description="≥1 AC; nên có ít nhất 1 happy-path AC",
    )


class UseCasesData(BaseModel):
    """Delta output from UC extractor — merge vào artifacts.use_cases[]."""

    use_cases: list[UseCaseItem] | None = Field(
        None,
        description=(
            "User Stories mới/cập nhật trong lượt này. Mỗi lượt tối đa 1 story mới. "
            "Gộp theo id; chỉ thêm US mới khi story đang active đã đủ statement+AC. "
            "Không xóa UC cũ trừ khi User yêu cầu."
        ),
    )

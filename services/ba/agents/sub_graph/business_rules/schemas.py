"""Pydantic schemas for Business Rules section."""

from __future__ import annotations

from pydantic import BaseModel, Field


class BusinessRuleItem(BaseModel):
    id: str | None = Field(
        None,
        description="Rule id dạng BR-01. Để trống nếu rule mới — hệ thống tự cấp số.",
    )
    statement: str = Field(
        ...,
        description=(
            "Quy tắc nghiệp vụ đo lường được: điều kiện kích hoạt (trigger) + kết quả kỳ vọng (outcome). "
            "VD: 'Khi đơn COD chưa thanh toán quá 48h thì hệ thống tự hủy đơn'."
        ),
    )
    source: str | None = Field(
        None,
        description="Nguồn quy tắc: Policy | System | Security | PO | Legal",
    )


class BusinessRulesData(BaseModel):
    """Delta output from BR extractor — merge vào artifacts.business_rules[]."""

    business_rules: list[BusinessRuleItem] | None = Field(
        None,
        description=(
            "Các business rules mới hoặc cập nhật trong lượt này. "
            "Gộp theo id; không xóa rules cũ trừ khi User yêu cầu rõ."
        ),
    )

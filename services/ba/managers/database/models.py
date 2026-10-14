from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from managers.database.connection import Base

# JSONB on Postgres; generic JSON on SQLite (tests).
_PortableJSON = JSON().with_variant(JSONB(), "postgresql")
# Native enum on Postgres; VARCHAR on SQLite (tests).
_ValidationStatus = Enum(
    "pending",
    "pass",
    "error",
    "warning",
    name="validation_status_enum",
    create_type=False,
).with_variant(String(16), "sqlite")

# Enum matching the DB's validation_status_enum
import enum

class ValidationStatusEnum(str, enum.Enum):
    pending = "pending"
    pass_ = "pass"
    error = "error"
    warning = "warning"


class BaPackageModel(Base):
    """Bảng lưu trữ thông tin gói BA Package tổng thể của một session."""

    __tablename__ = "ba_packages"

    session_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, index=True)
    feature_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    feature_description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    validation_result: Mapped[dict | None] = mapped_column(_PortableJSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    is_validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    feature_status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    validation_status: Mapped[str] = mapped_column(
        _ValidationStatus,
        nullable=False,
        default="pending",
    )
    validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    sections: Mapped[list[BaPackageSectionModel]] = relationship(
        "BaPackageSectionModel", back_populates="package", cascade="all, delete-orphan"
    )


class BaPackageSectionModel(Base):
    """Bảng lưu trữ dữ liệu artifact, flags và completion state của từng section."""

    __tablename__ = "ba_package_sections"
    __table_args__ = (
        UniqueConstraint("session_id", "section_id", name="uq_session_section"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("ba_packages.session_id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    data: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    flags: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    is_completable: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    package: Mapped[BaPackageModel] = relationship(
        "BaPackageModel", back_populates="sections"
    )


class DesignerHandoffModel(Base):
    """Persistent link between one BA export and one Designer run."""

    __tablename__ = "designer_handoffs"
    __table_args__ = (
        UniqueConstraint("feature_id", "correlation_id", name="uq_designer_handoff_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feature_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    handoff_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    designer_session_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    designer_run_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    designer_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="QUEUED")
    request_payload: Mapped[dict | None] = mapped_column(_PortableJSON, nullable=True)
    response_payload: Mapped[dict | None] = mapped_column(_PortableJSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

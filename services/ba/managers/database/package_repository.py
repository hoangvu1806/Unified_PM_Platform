from __future__ import annotations

import logging
from typing import Any, Dict, Optional  # noqa: UP035

from sqlalchemy import select
from sqlalchemy.orm import Session

from managers.database.connection import SessionLocal, init_db
from managers.database.models import BaPackageModel, BaPackageSectionModel

logger = logging.getLogger(__name__)


class BaPackageRepository:
    """
    Repository layer thực hiện lưu trữ và truy vấn BA Package & Section Artifacts
    trực tiếp từ PostgreSQL Database bằng SQLAlchemy 2.0.
    """

    def __init__(self, db_session: Session | None = None) -> None:
        self._external_session = db_session
        # Giả lập in-memory fallback nếu DB hoàn toàn không khả dụng
        self._db_mock_store: Dict[str, Dict[str, Any]] = {}

    def _get_session(self) -> Session:
        """Lấy session hiện tại hoặc tạo session mới."""
        if self._external_session:
            return self._external_session
        return SessionLocal()

    def init_tables(self) -> None:
        """Tạo bảng DB nếu chưa tồn tại."""
        try:
            init_db()
        except Exception as e:
            logger.warning("Không thể tự động tạo bảng DB: %s", e)

    def get_section(self, session_id: str, section_id: str) -> Optional[Dict[str, Any]]:
        """Đọc dữ liệu thô (data dict) của 1 section dựa trên session_id và section_id từ PostgreSQL."""
        if not session_id or not section_id:
            return None

        try:
            session = self._get_session()
            close_session = self._external_session is None
            try:
                stmt = select(BaPackageSectionModel).where(
                    BaPackageSectionModel.session_id == session_id,
                    BaPackageSectionModel.section_id == section_id,
                )
                record = session.scalar(stmt)
                if record:
                    return record.data
            finally:
                if close_session:
                    session.close()
        except Exception as e:
            logger.warning("Lỗi đọc section từ DB (chuyển fallback): %s", e)

        # Fallback to mock store if DB fails
        session_pkg = self._db_mock_store.get(session_id, {})
        sections = session_pkg.get("sections", {})
        section_record = sections.get(section_id)
        if section_record:
            return section_record.get("data")
        return None

    def save_section(
        self,
        session_id: str,
        section_id: str,
        data: Dict[str, Any],
        flags: Dict[str, Any],
        is_completable: bool,
    ) -> bool:
        """Lưu hoặc cập nhật (Upsert) section artifact + flags vào PostgreSQL."""
        if not session_id or not section_id:
            return False

        try:
            session = self._get_session()
            close_session = self._external_session is None
            try:
                # 1. Kiểm tra / Tạo BaPackageModel nếu chưa tồn tại
                package = session.get(BaPackageModel, session_id)
                if not package:
                    package = BaPackageModel(session_id=session_id)
                    session.add(package)
                    session.flush()

                # 2. Upsert BaPackageSectionModel
                stmt = select(BaPackageSectionModel).where(
                    BaPackageSectionModel.session_id == session_id,
                    BaPackageSectionModel.section_id == section_id,
                )
                section_record = session.scalar(stmt)

                if section_record:
                    section_record.data = data
                    section_record.flags = flags
                    section_record.is_completable = is_completable
                else:
                    section_record = BaPackageSectionModel(
                        session_id=session_id,
                        section_id=section_id,
                        data=data,
                        flags=flags,
                        is_completable=is_completable,
                    )
                    session.add(section_record)

                session.commit()
                return True
            except Exception as ex:
                session.rollback()
                raise ex
            finally:
                if close_session:
                    session.close()
        except Exception as e:
            logger.warning("Lỗi ghi section vào DB (chuyển fallback): %s", e)

        # Fallback mock store
        if session_id not in self._db_mock_store:
            self._db_mock_store[session_id] = {"session_id": session_id, "sections": {}}

        self._db_mock_store[session_id]["sections"][section_id] = {
            "data": data,
            "flags": flags,
            "is_completable": is_completable,
        }
        return True

    def get_package(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Lấy toàn bộ thông tin BA Package (gồm tất cả các sections)."""
        try:
            session = self._get_session()
            close_session = self._external_session is None
            try:
                package = session.get(BaPackageModel, session_id)
                if package:
                    sections_dict = {}
                    for sec in package.sections:
                        sections_dict[sec.section_id] = {
                            "data": sec.data,
                            "flags": sec.flags,
                            "is_completable": sec.is_completable,
                        }
                    return {
                        "session_id": package.session_id,
                        "feature_title": package.feature_title,
                        "sections": sections_dict,
                    }
            finally:
                if close_session:
                    session.close()
        except Exception as e:
            logger.warning("Lỗi đọc package từ DB: %s", e)

        return self._db_mock_store.get(session_id)

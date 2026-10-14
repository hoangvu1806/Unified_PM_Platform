from __future__ import annotations

import re
import unicodedata
from enum import Enum
from typing import Any, Dict, List, Tuple

from agents.sub_graph.feature_definition.schemas import FeatureDefinitionData
from managers.database.package_repository import BaPackageRepository


from pydantic import BaseModel


class FlagStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    PENDING_SEMANTIC = "PENDING_SEMANTIC"


class FeatureDefinitionFlags(BaseModel):
    FD_F1: FlagStatus = FlagStatus.FAIL
    FD_F2: FlagStatus = FlagStatus.FAIL
    FD_F3: FlagStatus = FlagStatus.FAIL
    FD_F4: FlagStatus = FlagStatus.WARNING


def _slug_actor_id(text: str) -> str:
    """Build ACT-* id token from free text (ASCII alnum + hyphen)."""
    text = text.replace("Đ", "D").replace("đ", "d")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    cleaned = []
    for ch in text.upper():
        if ch.isalnum():
            cleaned.append(ch)
        elif ch in {" ", "-", "_"} and cleaned and cleaned[-1] != "-":
            cleaned.append("-")
    slug = "".join(cleaned).strip("-")
    if not slug:
        slug = f"X{abs(hash(text)) % 10000}"
    return slug


def canonicalize_actor(actor: str) -> str:
    """Normalize to `ACT-ID: description` for UC-F3 matching."""
    raw = (actor or "").strip()
    if not raw:
        return ""

    parenthesized = re.fullmatch(r"(ACT-[A-Z0-9_-]+)\s*\((.+)\)", raw, re.I)
    if parenthesized:
        return f"{parenthesized.group(1).upper()}: {parenthesized.group(2).strip()}"

    dashed = re.fullmatch(r"(ACT-[A-Z0-9_-]+)\s+-\s+(.+)", raw, re.I)
    if dashed:
        return f"{dashed.group(1).upper()}: {dashed.group(2).strip()}"

    if ":" in raw:
        id_part, desc = raw.split(":", 1)
        id_part = id_part.strip().upper()
        desc = desc.strip()
        # Repair legacy values such as "ACT-ACT-KHACH-...: ACT-KHACH (...)".
        if id_part.startswith("ACT-ACT-") and desc.upper().startswith("ACT-"):
            return canonicalize_actor(desc)
        if not id_part.startswith("ACT-"):
            id_part = f"ACT-{_slug_actor_id(id_part)}"
        return f"{id_part}: {desc}" if desc else id_part
    if re.fullmatch(r"ACT-[A-Z0-9_-]+", raw, re.I):
        return raw.upper()
    return f"ACT-{_slug_actor_id(raw)}: {raw}"


def actor_identity(actor: str) -> str:
    """Stable key for actor union (ACT-ID)."""
    canonical = canonicalize_actor(actor)
    if ":" in canonical:
        return canonical.split(":", 1)[0].strip()
    return canonical


def _union_strings(current: list[str], delta: list[str] | None) -> list[str]:
    """Append/union by normalized identity; empty delta keeps current."""
    if not delta:
        return list(current)
    result: list[str] = []
    seen: set[str] = set()
    for item in list(current) + list(delta):
        text = item.strip() if isinstance(item, str) else str(item).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _union_actors(current: list[str], delta: list[str] | None) -> list[str]:
    """Append/union actors by ACT-ID; delta description wins on same id."""
    if not delta:
        return [canonicalize_actor(a) for a in current if canonicalize_actor(a)]
    by_id: dict[str, str] = {}
    order: list[str] = []
    for item in list(current) + list(delta):
        canonical = canonicalize_actor(item if isinstance(item, str) else str(item))
        if not canonical:
            continue
        aid = actor_identity(canonical)
        if aid not in by_id:
            order.append(aid)
        by_id[aid] = canonical
    return [by_id[aid] for aid in order]


def merge_feature_definition_data(
    current: FeatureDefinitionData, delta: FeatureDefinitionData
) -> FeatureDefinitionData:
    """
    Hợp nhất FeatureDefinitionData hiện tại với delta từ LLM.

    Rules:
    - Goal: overwrite only when delta.goal is non-empty.
    - Actors / Scope In / Scope Out: append-union (never replace wholesale).
    - Actors are canonicalized to `ACT-ID: description`.
    """
    new_goal = delta.goal.strip() if delta.goal and delta.goal.strip() else current.goal
    new_actors = _union_actors(current.actors or [], delta.actors)
    new_scope_in = _union_strings(current.scope_in or [], delta.scope_in)
    new_scope_out = _union_strings(current.scope_out or [], delta.scope_out)

    return FeatureDefinitionData(
        goal=new_goal,
        actors=new_actors,
        scope_in=new_scope_in,
        scope_out=new_scope_out,
    )


def evaluate_feature_definition_flags(
    data: FeatureDefinitionData,
) -> Tuple[FeatureDefinitionFlags, bool]:
    """
    Đánh giá trạng thái 4 completion flags dựa trên dữ liệu Feature Definition mới nhất.

    Blocker Flags: FD_F1, FD_F2, FD_F3
    Warning Flag: FD_F4
    """
    f1 = (
        FlagStatus.PASS
        if data.goal and len(data.goal.strip()) >= 5
        else FlagStatus.FAIL
    )
    f2 = FlagStatus.PASS if (data.actors and len(data.actors) >= 2) else FlagStatus.FAIL
    f3 = FlagStatus.PASS if (data.scope_in and len(data.scope_in) >= 1) else FlagStatus.FAIL
    f4 = FlagStatus.PASS if (data.scope_out and len(data.scope_out) >= 1) else FlagStatus.WARNING

    flags = FeatureDefinitionFlags(
        FD_F1=f1,
        FD_F2=f2,
        FD_F3=f3,
        FD_F4=f4,
    )

    # Section completable khi tất cả Blocker Flags (F1, F2, F3) đều PASS
    is_completable = (
        f1 == FlagStatus.PASS
        and f2 == FlagStatus.PASS
        and f3 == FlagStatus.PASS
    )

    return flags, is_completable


class ArtifactManager:
    """
    Manager tập trung quản lý Artifacts & Section Data cho BA Package.
    Sử dụng BaPackageRepository kết nối PostgreSQL thông qua SQLAlchemy.
    """

    def __init__(self, db_repository: BaPackageRepository | None = None) -> None:
        self.db_repository = db_repository or BaPackageRepository()
        self.db_repository.init_tables()
        self._in_memory_store: Dict[str, Dict[str, Any]] = {}

    def get_feature_definition(self, session_id: str) -> FeatureDefinitionData:
        """Đọc dữ liệu FeatureDefinitionData hiện tại của session từ Database (hoặc fallback)."""
        raw_data = self.db_repository.get_section(session_id, "feature_definition")
        if raw_data:
            return FeatureDefinitionData(**raw_data)

        # Fallback to local memory if empty
        session_store = self._in_memory_store.get(session_id, {})
        raw_data = session_store.get("feature_definition_data")
        if raw_data:
            return FeatureDefinitionData(**raw_data)
        return FeatureDefinitionData()

    def update_feature_definition(
        self, session_id: str, delta_data: FeatureDefinitionData
    ) -> Tuple[FeatureDefinitionData, FeatureDefinitionFlags, bool]:
        """
        Thực hiện quy trình hợp nhất:
        1. Đọc current data từ DB
        2. Merge delta_data
        3. Evaluate flags & completion gate
        4. Persist data vào DB
        """
        current_data = self.get_feature_definition(session_id)
        merged_data = merge_feature_definition_data(current_data, delta_data)
        flags, is_completable = evaluate_feature_definition_flags(merged_data)

        # Persist to DB Repository
        self.db_repository.save_section(
            session_id=session_id,
            section_id="feature_definition",
            data=merged_data.model_dump(),
            flags=flags.model_dump(),
            is_completable=is_completable,
        )

        # Sync to local in-memory cache
        if session_id not in self._in_memory_store:
            self._in_memory_store[session_id] = {}

        self._in_memory_store[session_id]["feature_definition_data"] = (
            merged_data.model_dump()
        )
        self._in_memory_store[session_id]["feature_definition_flags"] = (
            flags.model_dump()
        )
        self._in_memory_store[session_id]["feature_definition_completable"] = (
            is_completable
        )

        return merged_data, flags, is_completable

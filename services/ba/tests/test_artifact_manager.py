from agents.sub_graph.feature_definition.schemas import FeatureDefinitionData
from managers.artifact.artifact_manager import (
    ArtifactManager,
    FeatureDefinitionFlags,
    FlagStatus,
    evaluate_feature_definition_flags,
    merge_feature_definition_data,
)


def test_merge_feature_definition_data() -> None:
    current = FeatureDefinitionData(
        goal="Tối ưu trải nghiệm thanh toán",
        actors=["Customer"],
        scope_in=["Thanh toán QR"],
        scope_out=["Thanh toán tiền mặt"],
    )

    delta = FeatureDefinitionData(
        goal="",  # Rỗng -> không đè goal cũ
        actors=["Customer", "Payment Gateway"],  # Customer đã có -> dedup
        scope_in=["Thanh toán QR", "Thanh toán Ví điện tử"],  # Full danh sách mới sau khi gộp
        scope_out=[],
    )

    merged = merge_feature_definition_data(current, delta)

    assert merged.goal == "Tối ưu trải nghiệm thanh toán"
    assert merged.actors == [
        "ACT-CUSTOMER: Customer",
        "ACT-PAYMENT-GATEWAY: Payment Gateway",
    ]
    assert merged.scope_in == ["Thanh toán QR", "Thanh toán Ví điện tử"]
    assert merged.scope_out == ["Thanh toán tiền mặt"]

    # Partial delta must not wipe existing actors/scopes
    partial = merge_feature_definition_data(
        merged,
        FeatureDefinitionData(goal=None, actors=["ACT-ADMIN: Admin"], scope_in=None),
    )
    assert "ACT-CUSTOMER: Customer" in partial.actors
    assert "ACT-ADMIN: Admin" in partial.actors
    assert partial.scope_in == merged.scope_in


def test_canonicalize_actor_accepts_common_act_formats() -> None:
    from managers.artifact.artifact_manager import canonicalize_actor

    assert canonicalize_actor("ACT-KHACH (Người mua)") == "ACT-KHACH: Người mua"
    assert canonicalize_actor("ACT-ADMIN - Quản trị viên") == "ACT-ADMIN: Quản trị viên"
    assert canonicalize_actor("Quản lý đơn") == "ACT-QUAN-LY-DON: Quản lý đơn"
    assert (
        canonicalize_actor("ACT-ACT-KHACH-NGUOI-MUA: ACT-KHACH (Người mua)")
        == "ACT-KHACH: Người mua"
    )


def test_legacy_actor_id_is_repaired_for_projection() -> None:
    from managers.service.state_helpers import _artifact_for_section

    state = {
        "artifacts": {
            "feature_definition": {
                "actors": ["ACT-ACT-KHACH-NGUOI-MUA: ACT-KHACH (người mua)"]
            }
        }
    }
    assert _artifact_for_section(state, "feature_definition")["actors"] == [
        "ACT-KHACH: người mua"
    ]


def test_evaluate_feature_definition_flags() -> None:
    # Kịch bản 1: Đủ thông tin -> PASS tất cả Blocker Flags
    valid_data = FeatureDefinitionData(
        goal="Tăng tỷ lệ chuyển đổi đơn hàng qua QR",
        actors=["Customer", "Payment System"],
        scope_in=["Tạo mã QR động"],
        scope_out=["Thực hiện hoàn tiền thủ công"],
    )

    flags, is_completable = evaluate_feature_definition_flags(valid_data)

    assert flags.FD_F1 == FlagStatus.PASS
    assert flags.FD_F2 == FlagStatus.PASS
    assert flags.FD_F3 == FlagStatus.PASS
    assert flags.FD_F4 == FlagStatus.PASS
    assert is_completable is True

    # Kịch bản 2: Thiếu Actors & Scope In -> FAIL
    incomplete_data = FeatureDefinitionData(
        goal="Cần tính năng mới",
        actors=["Customer"],  # Mới có 1 actor -> FD_F2 FAIL
        scope_in=[],  # Rỗng -> FD_F3 FAIL
        scope_out=[],
    )

    flags_inc, is_completable_inc = evaluate_feature_definition_flags(incomplete_data)
    assert flags_inc.FD_F2 == FlagStatus.FAIL
    assert flags_inc.FD_F3 == FlagStatus.FAIL
    assert is_completable_inc is False


def test_artifact_manager_in_memory_session_isolation() -> None:
    manager = ArtifactManager()
    session_1 = "sess_001"
    session_2 = "sess_002"

    delta_1 = FeatureDefinitionData(
        goal="Feature Session 1",
        actors=["User", "System"],
        scope_in=["Scope 1"],
    )

    delta_2 = FeatureDefinitionData(
        goal="Feature Session 2",
        actors=["Admin", "System"],
        scope_in=["Scope 2"],
    )

    merged_1, flags_1, completable_1 = manager.update_feature_definition(
        session_1, delta_1
    )
    merged_2, flags_2, completable_2 = manager.update_feature_definition(
        session_2, delta_2
    )

    assert manager.get_feature_definition(session_1).goal == "Feature Session 1"
    assert manager.get_feature_definition(session_2).goal == "Feature Session 2"

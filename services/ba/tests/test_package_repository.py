from managers.database.package_repository import BaPackageRepository


def test_repository_save_and_get_section() -> None:
    repo = BaPackageRepository()
    repo.init_tables()

    session_id = "test_db_session_1001"
    section_id = "feature_definition"
    sample_data = {
        "goal": "Tích hợp SQLAlchemy trực tiếp vào Repository",
        "actors": ["Product Manager", "Database Engine"],
        "scope_in": ["Lưu trữ Postgres", "Tự tạo bảng DB"],
        "scope_out": ["Chuyển đổi Oracle DB"],
    }
    sample_flags = {"FD_F1": "PASS", "FD_F2": "PASS", "FD_F3": "PASS", "FD_F4": "PASS"}

    # 1. Save section
    success = repo.save_section(
        session_id=session_id,
        section_id=section_id,
        data=sample_data,
        flags=sample_flags,
        is_completable=True,
    )
    assert success is True

    # 2. Get section back from DB
    retrieved_data = repo.get_section(session_id, section_id)
    assert retrieved_data is not None
    assert retrieved_data["goal"] == "Tích hợp SQLAlchemy trực tiếp vào Repository"
    assert retrieved_data["actors"] == ["Product Manager", "Database Engine"]

    # 3. Get entire package
    package = repo.get_package(session_id)
    assert package is not None
    assert session_id in package["session_id"]
    assert section_id in package["sections"]

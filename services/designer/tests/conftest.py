import pytest


@pytest.fixture(scope="session", autouse=True)
def _drop_test_schemas():
    """Drop every throwaway schema created by tests/pg.make_test_store()."""
    yield
    try:
        from psycopg import connect

        from tests.pg import TEST_SCHEMA_PREFIX, pg_test_dsn

        with connect(pg_test_dsn(), autocommit=True) as conn:
            rows = conn.execute(
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE %s",
                (TEST_SCHEMA_PREFIX + "%",),
            ).fetchall()
            for (name,) in rows:
                conn.execute(f'DROP SCHEMA "{name}" CASCADE')
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _local_storage(tmp_path, monkeypatch):
    """Every test writes files to its own local storage root, never the real bucket."""
    from platform_core.settings import get_common_settings
    from platform_core.storage import get_storage

    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("STORAGE_LOCAL_ROOT", str(tmp_path / "storage"))
    get_common_settings.cache_clear()
    get_storage.cache_clear()
    yield tmp_path / "storage"
    get_common_settings.cache_clear()
    get_storage.cache_clear()

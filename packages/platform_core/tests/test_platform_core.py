import pytest

from platform_core.db import database_url, engine_kwargs
from platform_core.settings import CommonSettings
from platform_core.storage import LocalStorage, project_key

SETTINGS = CommonSettings(
    postgres_host="pg", postgres_port=5433, postgres_db="platform",
    postgres_user="u", postgres_password="p@ss word",
)


def test_sync_url_pins_search_path_and_escapes_password():
    url = database_url("ba", "psycopg2", SETTINGS)
    assert url.startswith("postgresql+psycopg2://u:p%40ss+word@pg:5433/platform?")
    assert "options=-csearch_path%3Dba" in url


def test_async_url_uses_connect_args():
    assert "options" not in database_url("ba", "asyncpg", SETTINGS)
    assert engine_kwargs("ba") == {"connect_args": {"server_settings": {"search_path": "ba"}}}


def test_unknown_schema_rejected():
    with pytest.raises(ValueError):
        database_url("public", settings=SETTINGS)


def test_project_key_layout():
    assert project_key("PRJ-1", "wiki", "blobs", "a.pdf") == "projects/PRJ-1/wiki/blobs/a.pdf"
    assert project_key(None, "wiki", "blobs", "a.pdf") == "shared/wiki/blobs/a.pdf"


def test_local_storage_roundtrip_and_escape(tmp_path):
    store = LocalStorage(tmp_path)
    store.put("projects/P/x.bin", b"hi")
    assert store.exists("projects/P/x.bin") and store.get("projects/P/x.bin") == b"hi"
    store.delete("projects/P/x.bin")
    assert not store.exists("projects/P/x.bin")
    with pytest.raises(ValueError):
        store.put("../outside", b"x")

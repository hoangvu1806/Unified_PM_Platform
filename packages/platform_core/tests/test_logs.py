"""platform_core.logs: context fields, local JSON file, per-project storage chunks."""

import json
import logging

import pytest

from platform_core import logs
from platform_core.settings import get_common_settings
from platform_core.storage import LocalStorage, get_storage


@pytest.fixture()
def platform_logging(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("STORAGE_LOCAL_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("LOG_PROJECT_FLUSH_SECONDS", "3600")  # flush explicitly
    get_common_settings.cache_clear()
    get_storage.cache_clear()
    monkeypatch.setattr(logs, "_configured", False)
    logs.setup_logging("test-svc")
    root = logging.getLogger()
    yield tmp_path, root
    for handler in list(root.handlers):
        handler.close()
        root.removeHandler(handler)
    get_common_settings.cache_clear()
    get_storage.cache_clear()


def _project_handler(root: logging.Logger) -> logs.ProjectStorageHandler:
    return next(h for h in root.handlers if isinstance(h, logs.ProjectStorageHandler))


def test_request_context_lands_in_local_json(platform_logging):
    tmp_path, root = platform_logging
    logs.new_request_context("req-1")
    logs.bind(user="ba.an", project_id="PRJ-X")
    logging.getLogger("ba.agent").info("hello %s", "world")
    for h in root.handlers:
        h.flush()
    line = (tmp_path / "logs" / "test-svc" / "test-svc.log").read_text(encoding="utf-8").strip().splitlines()[-1]
    record = json.loads(line)
    assert record["msg"] == "hello world"
    assert record["service"] == "test-svc"
    assert record["user"] == "ba.an" and record["project_id"] == "PRJ-X" and record["request_id"] == "req-1"


def test_project_records_are_written_under_the_project_prefix(platform_logging):
    tmp_path, root = platform_logging
    logs.new_request_context()
    logs.bind(project_id="PRJ-A")
    logging.getLogger("designer_agent.workflow").info("run finished")
    logs.new_request_context()  # a request without project: must not be uploaded
    logging.getLogger("platform.access").info("GET /health 200")
    _project_handler(root).flush()

    keys = list(LocalStorage(tmp_path / "storage").keys())
    assert keys and all(k.startswith("projects/PRJ-A/logs/test-svc/") and k.endswith(".jsonl") for k in keys)
    body = (tmp_path / "storage" / keys[0]).read_text(encoding="utf-8")
    assert "run finished" in body and "/health" not in body


def test_sweep_deletes_project_log_days_past_retention(platform_logging):
    from datetime import datetime, timezone

    tmp_path, root = platform_logging
    handler = _project_handler(root)
    storage = get_storage()
    for day in ("2026-01-01", "2026-01-30", "2026-01-31"):
        storage.put(f"projects/PRJ-A/logs/test-svc/{day}/x.jsonl", b"{}\n")
    storage.put("projects/PRJ-A/logs/other-svc/2026-01-01/x.jsonl", b"{}\n")  # another service: untouched
    handler._seen.add("PRJ-A")
    handler.retention_days = 1

    assert handler.sweep(today=datetime(2026, 2, 1, tzinfo=timezone.utc)) == 2
    assert sorted(storage.keys("projects/PRJ-A/logs/")) == [
        "projects/PRJ-A/logs/other-svc/2026-01-01/x.jsonl",
        "projects/PRJ-A/logs/test-svc/2026-01-31/x.jsonl",
    ]

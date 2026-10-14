"""Platform logging: one setup for every backend.

* Console: readable one-line text (``docker compose logs``).
* Local files: JSON lines in ``LOG_DIR/<service>/<service>.log`` (daily
  rotation, 14 days). ``LOG_DIR`` is bind-mounted to ``platform/logs``.
* Per project: records that carry a ``project_id`` are buffered and written to
  platform storage (S3) under ``projects/<project_id>/logs/<service>/<YYYY-MM-DD>/``
  as ``.jsonl`` chunks, flushed every ``LOG_PROJECT_FLUSH_SECONDS``.

Every record gets ``service``, ``request_id``, ``user`` and ``project_id``
from the request context (:func:`request_context`); background tasks started
inside a request inherit it.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import socket
import threading
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

# Mutable per-request bag: dependencies fill user/project after the middleware
# created it, and the middleware still sees the values when it logs the access line.
_context: ContextVar[dict[str, Any] | None] = ContextVar("platform_log_context", default=None)

_SKIP_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}
_service_name = "platform"


def request_context() -> dict[str, Any]:
    ctx = _context.get()
    if ctx is None:
        ctx = {}
        _context.set(ctx)
    return ctx


def bind(**values: Any) -> None:
    """Attach values (user, project_id, ...) to the current request's log context."""
    request_context().update({k: v for k, v in values.items() if v is not None})


def new_request_context(request_id: str | None = None) -> dict[str, Any]:
    ctx = {"request_id": request_id or uuid.uuid4().hex[:12]}
    _context.set(ctx)
    return ctx


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _context.get() or {}
        record.service = _service_name
        for key in ("request_id", "user", "project_id"):
            if not hasattr(record, key):
                setattr(record, key, ctx.get(key))
        return True


def _record_dict(record: logging.LogRecord) -> dict[str, Any]:
    data: dict[str, Any] = {
        "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
        "level": record.levelname,
        "service": getattr(record, "service", _service_name),
        "logger": record.name,
        "msg": record.getMessage(),
    }
    for key, value in vars(record).items():
        if key in _SKIP_ATTRS or key in data or value is None:
            continue
        data[key] = value if isinstance(value, (str, int, float, bool, list, dict)) else str(value)
    if record.exc_info:
        data["exc"] = logging.Formatter().formatException(record.exc_info)
    return data


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(_record_dict(record), ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        tags = " ".join(
            f"{k}={getattr(record, k)}" for k in ("project_id", "user") if getattr(record, k, None)
        )
        line = f"{ts} {record.levelname:<7} {record.name}: {record.getMessage()}"
        if tags:
            line += f"  [{tags}]"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


class ProjectStorageHandler(logging.Handler):
    """Buffers records per project and writes .jsonl chunks to platform storage."""

    def __init__(self, service: str, flush_seconds: float = 30.0, max_lines: int = 500) -> None:
        super().__init__(level=logging.INFO)
        self.service = service
        self.flush_seconds = flush_seconds
        self.max_lines = max_lines
        self._buffers: dict[str, list[str]] = {}
        self._buf_lock = threading.Lock()
        self._host = socket.gethostname()[:12]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="project-log-flush", daemon=True)
        self._thread.start()
        atexit.register(self.flush)

    def emit(self, record: logging.LogRecord) -> None:
        project_id = getattr(record, "project_id", None)
        if not project_id or record.name.startswith(("botocore", "boto3", "urllib3", "s3transfer")):
            return
        try:
            line = json.dumps(_record_dict(record), ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            return
        with self._buf_lock:
            buf = self._buffers.setdefault(project_id, [])
            buf.append(line)
            full = len(buf) >= self.max_lines
        if full:
            threading.Thread(target=self.flush, daemon=True).start()

    def _loop(self) -> None:
        while not self._stop.wait(self.flush_seconds):
            self.flush()

    def flush(self) -> None:
        with self._buf_lock:
            pending, self._buffers = self._buffers, {}
        if not pending:
            return
        try:
            from platform_core.storage import get_storage, project_key

            storage = get_storage()
        except Exception:  # noqa: BLE001
            return
        now = datetime.now(timezone.utc)
        for project_id, lines in pending.items():
            key = project_key(
                project_id,
                "logs",
                self.service,
                now.strftime("%Y-%m-%d"),
                f"{now.strftime('%H%M%S')}-{self._host}-{uuid.uuid4().hex[:6]}.jsonl",
            )
            try:
                storage.put(key, ("\n".join(lines) + "\n").encode("utf-8"), content_type="application/x-ndjson")
            except Exception as exc:  # noqa: BLE001 — never let logging break the service
                logging.getLogger("platform.logs").warning("project log upload failed: %s", exc,
                                                           extra={"project_id": None})

    def close(self) -> None:
        self._stop.set()
        self.flush()
        super().close()


_configured = False


def setup_logging(service: str) -> None:
    """Configure root logging for ``service`` (idempotent)."""
    global _configured, _service_name
    _service_name = service
    if _configured:
        return
    _configured = True

    level = os.environ.get("PLATFORM_LOG_LEVEL", "INFO").upper()
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    context_filter = ContextFilter()

    console = logging.StreamHandler()
    console.setFormatter(ConsoleFormatter())
    console.addFilter(context_filter)
    root.addHandler(console)

    log_dir = Path(os.environ.get("LOG_DIR", "/logs")) / service
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            log_dir / f"{service}.log", when="midnight", backupCount=14, encoding="utf-8", utc=True
        )
        file_handler.setFormatter(JsonFormatter())
        file_handler.addFilter(context_filter)
        root.addHandler(file_handler)
    except OSError as exc:
        logging.getLogger("platform.logs").warning("local log dir unavailable (%s): %s", log_dir, exc)

    if os.environ.get("LOG_PROJECT_TO_STORAGE", "true").lower() in {"1", "true", "yes"}:
        project = ProjectStorageHandler(service, float(os.environ.get("LOG_PROJECT_FLUSH_SECONDS", "30")))
        project.addFilter(context_filter)
        root.addHandler(project)

    # uvicorn's own loggers go through the root handlers; its access log is
    # replaced by RequestLogMiddleware (it lacks user/project).
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    for noisy in ("httpx", "httpcore", "botocore", "boto3", "urllib3", "s3transfer", "LiteLLM", "litellm"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class RequestLogMiddleware:
    """ASGI middleware: one access line per HTTP request with user/project context."""

    def __init__(self, app, skip_paths: tuple[str, ...] = ("/health",)) -> None:
        self.app = app
        self.skip_paths = skip_paths
        self.log = logging.getLogger("platform.access")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        ctx = new_request_context(headers.get(b"x-request-id", b"").decode() or None)
        start = time.perf_counter()
        status = {"code": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", ctx["request_id"].encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            if not path.endswith(self.skip_paths):
                elapsed = round((time.perf_counter() - start) * 1000, 1)
                code = status["code"]
                self.log.log(
                    logging.WARNING if code >= 500 else logging.INFO,
                    "%s %s %s %sms",
                    scope.get("method"),
                    path,
                    code,
                    elapsed,
                    extra={"method": scope.get("method"), "path": path, "status": code, "duration_ms": elapsed},
                )

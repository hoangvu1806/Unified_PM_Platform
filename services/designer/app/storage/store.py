import asyncio
import json
import re
from collections.abc import Callable
from enum import Enum
from typing import Any, TypeVar
from uuid import UUID, uuid4

from psycopg import Connection, errors
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from pydantic import BaseModel

from ..models import (
    SCREEN_WIDTHS,
    DesignBrief,
    RunCreate,
    RunStage,
    RunStatus,
    RunView,
    ScreenVersionView,
    ScreenView,
    ScreenWrite,
    SessionView,
    WorkflowEvent,
    utc_now,
)
from .schema import initialize_schema

T = TypeVar("T")


Row = dict[str, Any]


def _json(value: BaseModel | dict[str, Any]) -> str:
    return value.model_dump_json(by_alias=True) if isinstance(value, BaseModel) else json.dumps(value, ensure_ascii=False)


def _param(value: Any) -> Any:
    # StrEnum members (RunStage/RunStatus) are stored by value, as SQLite did.
    return value.value if isinstance(value, Enum) else value


class Store:
    """Designer persistence on the shared platform Postgres (schema ``designer``).

    Public methods are unchanged from the SQLite store; only the connection
    layer differs. Every connection pins ``search_path`` to ``schema``.
    """

    def __init__(self, dsn: str, schema: str = "designer", max_size: int = 10) -> None:
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", schema):
            raise ValueError(f"invalid schema name {schema!r}")
        self.dsn = dsn
        self.schema = schema
        self._event_lock = asyncio.Lock()
        self._pool = ConnectionPool(
            dsn,
            min_size=1,
            max_size=max_size,
            kwargs={"row_factory": dict_row},
            configure=self._configure,
            open=False,
        )

    def _configure(self, conn: Connection) -> None:
        conn.execute(f'SET search_path TO "{self.schema}"')
        conn.commit()

    async def initialize(self) -> None:
        await self._call(self._initialize)

    def _initialize(self) -> None:
        with Connection.connect(self.dsn, autocommit=True) as bootstrap:
            bootstrap.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
        self._pool.open(wait=True)
        with self._pool.connection() as db:
            initialize_schema(db)

    async def close(self) -> None:
        await self._call(self._pool.close)

    async def create_session(
        self,
        title: str,
        *,
        project_id: str | None = None,
        created_by: str | None = None,
        source: str | None = None,
        source_ref: str | None = None,
        source_artifact_id: str | None = None,
    ) -> SessionView:
        now = utc_now()
        session = SessionView(
            id=uuid4(),
            title=title,
            created_at=now,
            updated_at=now,
            project_id=project_id,
            created_by=created_by,
            source=source,
            source_ref=source_ref,
            source_artifact_id=source_artifact_id,
        )
        await self._execute(
            "INSERT INTO sessions (id, title, created_at, updated_at, design_brief, "
            "project_id, created_by, source, source_ref, source_artifact_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(session.id), session.title, now.isoformat(), now.isoformat(), None,
                project_id, created_by, source, source_ref, source_artifact_id,
            ),
        )
        return session

    async def list_sessions(self, project_id: str | None = None) -> list[SessionView]:
        if project_id:
            rows = await self._fetchall(
                "SELECT * FROM sessions WHERE project_id = ? ORDER BY updated_at DESC", (project_id,)
            )
        else:
            rows = await self._fetchall("SELECT * FROM sessions ORDER BY updated_at DESC")
        return [self._session_from_row(row) for row in rows]

    # ── Platform access helpers ─────────────────────────
    async def session_project(self, session_id: UUID | str) -> tuple[bool, str | None]:
        row = await self._fetchone("SELECT project_id FROM sessions WHERE id = ?", (str(session_id),))
        return (row is not None, row["project_id"] if row else None)

    async def run_project(self, run_id: UUID | str) -> tuple[bool, str | None]:
        row = await self._fetchone(
            "SELECT s.project_id FROM runs r JOIN sessions s ON s.id = r.session_id WHERE r.id = ?",
            (str(run_id),),
        )
        return (row is not None, row["project_id"] if row else None)

    async def get_session(self, session_id: UUID) -> SessionView | None:
        row = await self._fetchone("SELECT * FROM sessions WHERE id = ?", (str(session_id),))
        return self._session_from_row(row) if row else None

    async def delete_session(self, session_id: UUID) -> bool:
        """Delete a session and its runs, events, reviews, and artifacts via FK cascades."""
        return await self._call(lambda: self._delete_session(session_id))

    def _delete_session(self, session_id: UUID) -> bool:
        with self._pool.connection() as db:
            cursor = db.execute(
                self._sql("DELETE FROM sessions WHERE id = ?"), (str(session_id),)
            )
            return cursor.rowcount > 0

    async def get_design_brief(self, session_id: UUID) -> DesignBrief:
        session = await self.get_session(session_id)
        return session.design_brief if session and session.design_brief else DesignBrief()

    async def save_design_brief(self, session_id: UUID, brief: DesignBrief) -> None:
        await self._execute(
            "UPDATE sessions SET design_brief=?, updated_at=? WHERE id=?",
            (brief.model_dump_json(), utc_now().isoformat(), str(session_id)),
        )

    async def create_run(
        self, session_id: UUID, request: RunCreate, *, triggered_by: str | None = None
    ) -> RunView:
        now = utc_now()
        run_id = uuid4()
        run = RunView(
            id=run_id,
            session_id=session_id,
            revision=1,
            prompt=request.prompt,
            screen_name=request.screen_name,
            platform=request.platform,
            style_name=request.style_name,
            stage=RunStage.REQUIREMENT,
            status=RunStatus.QUEUED,
            library_ids=request.library_ids,
            created_at=now,
            updated_at=now,
        )
        await self._execute(
            "INSERT INTO runs (id, session_id, revision, prompt, screen_name, platform, "
            "stage, status, library_ids, mcp_profile, specification, error, intent, assistant_message, style_name, created_at, updated_at, "
            "triggered_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(run.id),
                str(run.session_id),
                run.revision,
                run.prompt,
                run.screen_name,
                run.platform,
                run.stage,
                run.status,
                json.dumps(run.library_ids),
                None,
                None,
                None,
                None,
                None,
                run.style_name,
                now.isoformat(),
                now.isoformat(),
                triggered_by,
            ),
        )
        if request.assets:
            await self.set_artifact(
                run.id,
                run.revision,
                "exact_assets",
                [item.model_dump(mode="json") for item in request.assets],
            )
        return run

    async def list_runs(self, session_id: UUID) -> list[RunView]:
        rows = await self._fetchall(
            "SELECT * FROM runs WHERE session_id=? ORDER BY created_at DESC", (str(session_id),)
        )
        return [self._run_from_row(row) for row in rows]

    async def get_run(self, run_id: UUID) -> RunView | None:
        row = await self._fetchone("SELECT * FROM runs WHERE id = ?", (str(run_id),))
        return self._run_from_row(row) if row else None

    async def interrupt_unfinished_runs(self) -> int:
        """Runs live in process memory: after a restart, mark them failed (retryable) instead of "running" forever."""
        rows = await self._fetchall("SELECT id, stage FROM runs WHERE status IN ('running', 'queued')")
        for row in rows:
            await self.update_run(
                UUID(str(row["id"])),
                stage=RunStage.FAILED,
                status=RunStatus.FAILED,
                error={
                    "code": "RUN_INTERRUPTED",
                    "title": "The run was interrupted by a service restart",
                    "detail": f"It stopped during {row['stage']}.",
                    "retryable": True,
                    "action": "Retry the run.",
                    "stage": row["stage"],
                },
            )
        return len(rows)

    async def update_run(
        self,
        run_id: UUID,
        *,
        stage: RunStage | None = None,
        status: RunStatus | None = None,
        specification: BaseModel | dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        intent: str | None = None,
        assistant_message: str | None = None,
        screen_name: str | None = None,
        platform: str | None = None,
        style_name: str | None = None,
    ) -> RunView:
        now = utc_now().isoformat()
        await self._execute(
            "UPDATE runs SET stage=COALESCE(?, stage), status=COALESCE(?, status), specification=COALESCE(?, specification), "
            "error=?, intent=COALESCE(?, intent), assistant_message=COALESCE(?, assistant_message), "
            "screen_name=COALESCE(?, screen_name), platform=COALESCE(?, platform), style_name=COALESCE(?, style_name), "
            "updated_at=? WHERE id=?",
            (
                stage,
                status,
                _json(specification) if specification is not None else None,
                json.dumps(error) if error else None,
                intent,
                assistant_message,
                screen_name,
                platform,
                style_name,
                now,
                str(run_id),
            ),
        )
        run = await self.get_run(run_id)
        if run is None:
            raise LookupError(str(run_id))
        return run

    async def bump_revision(self, run_id: UUID) -> RunView:
        await self._execute(
            "UPDATE runs SET revision=revision+1, stage=?, status=?, error=NULL, updated_at=? WHERE id=?",
            (RunStage.SPECIFICATION, RunStatus.QUEUED, utc_now().isoformat(), str(run_id)),
        )
        run = await self.get_run(run_id)
        if run is None:
            raise LookupError(str(run_id))
        return run

    async def add_event(self, run_id: UUID, revision: int, event_type: str, payload: dict[str, Any]) -> WorkflowEvent:
        async with self._event_lock:
            for attempt in range(5):
                try:
                    row = await self._fetchone(
                        "SELECT COALESCE(MAX(sequence), 0) AS value FROM events WHERE run_id = ?",
                        (str(run_id),),
                    )
                    if row is None:
                        raise RuntimeError("Event sequence query returned no row")
                    event = WorkflowEvent(
                        run_id=run_id,
                        revision=revision,
                        sequence=int(row["value"]) + 1,
                        type=event_type,
                        payload=payload,
                    )
                    await self._execute(
                        "INSERT INTO events (id, run_id, revision, sequence, event_type, payload, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            str(event.id),
                            str(run_id),
                            revision,
                            event.sequence,
                            event.type,
                            json.dumps(payload),
                            event.time.isoformat(),
                        ),
                    )
                    return event
                except errors.UniqueViolation:
                    if attempt < 4:
                        await asyncio.sleep(0.05 * (attempt + 1))
                        continue
                    raise
            raise RuntimeError("Failed to allocate event sequence after retries")

    async def list_events(self, run_id: UUID, after: int = 0) -> list[WorkflowEvent]:
        rows = await self._fetchall(
            "SELECT * FROM events WHERE run_id=? AND sequence>? ORDER BY sequence",
            (str(run_id), after),
        )
        return [
            WorkflowEvent(
                id=row["id"],
                run_id=row["run_id"],
                revision=row["revision"],
                sequence=row["sequence"],
                type=row["event_type"],
                time=row["created_at"],
                payload=json.loads(row["payload"]),
            )
            for row in rows
        ]

    async def add_review(self, run_id: UUID, revision: int, checkpoint: str, decision: str, feedback: str) -> None:
        await self._execute(
            "INSERT INTO reviews (id, run_id, revision, checkpoint, decision, feedback, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid4()),
                str(run_id),
                revision,
                checkpoint,
                decision,
                feedback,
                utc_now().isoformat(),
            ),
        )

    async def set_artifact(self, run_id: UUID, revision: int, key: str, value: dict[str, Any] | list[Any]) -> None:
        await self._execute(
            "INSERT INTO artifacts (run_id, revision, artifact_key, value, created_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id, revision, artifact_key) DO UPDATE SET value=excluded.value",
            (str(run_id), revision, key, json.dumps(value), utc_now().isoformat()),
        )

    async def get_artifact(self, run_id: UUID, revision: int, key: str) -> Any | None:
        row = await self._fetchone(
            "SELECT value FROM artifacts WHERE run_id=? AND revision=? AND artifact_key=?",
            (str(run_id), revision, key),
        )
        return json.loads(row["value"]) if row else None

    async def get_latest_session_artifact(self, session_id: UUID, key: str) -> Any | None:
        """Return the newest artifact of a kind from any run in the session.

        Clarification turns create a new run, while uploaded assets belong to
        the original message. Session fallback keeps those exact bytes attached
        when the user later answers a question such as "mobile nhé".
        """
        row = await self._fetchone(
            "SELECT a.value FROM artifacts a "
            "JOIN runs r ON r.id=a.run_id "
            "WHERE r.session_id=? AND a.artifact_key=? "
            "ORDER BY a.created_at DESC LIMIT 1",
            (str(session_id), key),
        )
        return json.loads(row["value"]) if row else None

    async def list_artifacts(self, run_id: UUID, revision: int) -> dict[str, Any]:
        rows = await self._fetchall(
            "SELECT artifact_key, value FROM artifacts WHERE run_id=? AND revision=?",
            (str(run_id), revision),
        )
        return {row["artifact_key"]: json.loads(row["value"]) for row in rows}

    # ── Screens (HTML designer) ─────────────────────────
    async def list_screens(self, session_id: UUID, *, with_html: bool = False) -> list[ScreenView]:
        rows = await self._fetchall(
            "SELECT * FROM screens WHERE session_id=? ORDER BY position, created_at", (str(session_id),)
        )
        return [self._screen_from_row(row, with_html) for row in rows]

    async def get_screen(self, session_id: UUID, screen_id: str, version: int | None = None) -> ScreenView | None:
        row = await self._fetchone(
            "SELECT * FROM screens WHERE session_id=? AND screen_id=?", (str(session_id), screen_id)
        )
        if row is None:
            return None
        if version is not None and version != row["version"]:
            old = await self._fetchone(
                "SELECT html FROM screen_versions WHERE session_id=? AND screen_id=? AND version=?",
                (str(session_id), screen_id, version),
            )
            if old is None:
                return None
            row = {**row, "version": version, "html": old["html"]}
        return self._screen_from_row(row, True)

    async def save_screen(
        self,
        session_id: UUID,
        screen_id: str,
        body: ScreenWrite,
        *,
        run_id: UUID | str | None = None,
        updated_by: str | None = None,
    ) -> ScreenView:
        """Create or update a screen; every save is a new version (kept in screen_versions)."""
        return await self._call(lambda: self._save_screen(session_id, screen_id, body, run_id, updated_by))

    def _save_screen(self, session_id, screen_id: str, body: ScreenWrite, run_id, updated_by) -> ScreenView:
        now = utc_now().isoformat()
        sid, rid = str(session_id), (str(run_id) if run_id else None)
        width = body.width or SCREEN_WIDTHS[body.platform]
        with self._pool.connection() as db, db.transaction():
            current = db.execute(
                self._sql("SELECT version FROM screens WHERE session_id=? AND screen_id=? FOR UPDATE"), (sid, screen_id)
            ).fetchone()
            if current is None:
                position = db.execute(
                    self._sql("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM screens WHERE session_id=?"), (sid,)
                ).fetchone()["p"]
                version = 1
                db.execute(
                    self._sql(
                        "INSERT INTO screens (session_id, screen_id, name, platform, width, position, version, html, "
                        "run_id, updated_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    ),
                    (sid, screen_id, body.name, body.platform, width, position, version, body.html, rid, updated_by, now, now),
                )
            else:
                version = current["version"] + 1
                db.execute(
                    self._sql(
                        "UPDATE screens SET name=?, platform=?, width=?, version=?, html=?, run_id=?, updated_by=?, "
                        "updated_at=? WHERE session_id=? AND screen_id=?"
                    ),
                    (body.name, body.platform, width, version, body.html, rid, updated_by, now, sid, screen_id),
                )
            db.execute(
                self._sql(
                    "INSERT INTO screen_versions (session_id, screen_id, version, html, run_id, updated_by, note, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (sid, screen_id, version, body.html, rid, updated_by, body.note or None, now),
            )
            row = db.execute(
                self._sql("SELECT * FROM screens WHERE session_id=? AND screen_id=?"), (sid, screen_id)
            ).fetchone()
        return self._screen_from_row(row, True)

    async def list_screen_versions(self, session_id: UUID, screen_id: str) -> list[ScreenVersionView]:
        rows = await self._fetchall(
            "SELECT version, created_at, updated_by, run_id, note FROM screen_versions "
            "WHERE session_id=? AND screen_id=? ORDER BY version DESC",
            (str(session_id), screen_id),
        )
        return [ScreenVersionView.model_validate(dict(row)) for row in rows]

    async def delete_screen(self, session_id: UUID, screen_id: str) -> bool:
        def delete() -> bool:
            with self._pool.connection() as db, db.transaction():
                db.execute(
                    self._sql("DELETE FROM screen_versions WHERE session_id=? AND screen_id=?"),
                    (str(session_id), screen_id),
                )
                cursor = db.execute(
                    self._sql("DELETE FROM screens WHERE session_id=? AND screen_id=?"), (str(session_id), screen_id)
                )
                return cursor.rowcount > 0

        return await self._call(delete)

    @staticmethod
    def _screen_from_row(row: Row, with_html: bool) -> ScreenView:
        value = dict(row)
        value["id"] = value.pop("screen_id")
        if not with_html:
            value["html"] = None
        return ScreenView.model_validate(value)

    def _run_from_row(self, row: Row) -> RunView:
        value = dict(row)
        value["library_ids"] = json.loads(value["library_ids"])
        value["specification"] = json.loads(value["specification"]) if value["specification"] else None
        value["error"] = json.loads(value["error"]) if value["error"] else None
        return RunView.model_validate(value)

    @staticmethod
    def _session_from_row(row: Row) -> SessionView:
        value = dict(row)
        value["design_brief"] = json.loads(value["design_brief"]) if value.get("design_brief") else None
        return SessionView.model_validate(value)

    @staticmethod
    def _sql(sql: str) -> str:
        # Queries keep SQLite's "?" placeholders; psycopg uses "%s".
        return sql.replace("%", "%%").replace("?", "%s")

    async def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        def execute() -> None:
            with self._pool.connection() as db:
                db.execute(self._sql(sql), tuple(_param(p) for p in params))

        await self._call(execute)

    async def _fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> Row | None:
        def fetch() -> Row | None:
            with self._pool.connection() as db:
                return db.execute(self._sql(sql), tuple(_param(p) for p in params)).fetchone()

        return await self._call(fetch)

    async def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[Row]:
        def fetch() -> list[Row]:
            with self._pool.connection() as db:
                return db.execute(self._sql(sql), tuple(_param(p) for p in params)).fetchall()

        return await self._call(fetch)

    async def _call(self, function: Callable[[], T]) -> T:
        return await asyncio.to_thread(function)

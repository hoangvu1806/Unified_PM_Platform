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

from ..models import (
    DesignBrief,
    OpenPencilProfile,
    RunCreate,
    RunStage,
    RunStatus,
    RunView,
    SessionView,
    SessionWorkspace,
    UiSpecification,
    WorkflowEvent,
    utc_now,
)
from .schema import initialize_schema

T = TypeVar("T")


def output_file_for_run(screen_name: str, run_id: UUID) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", screen_name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if name.lower().endswith(".fig"):
        name = name[:-4].rstrip(" .")
    name = (name[:100].rstrip(" .") or "Untitled") + ".fig"
    return f"generated/{run_id}/{name}"


Row = dict[str, Any]


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

    async def create_session(self, title: str) -> SessionView:
        now = utc_now()
        session = SessionView(id=uuid4(), title=title, created_at=now, updated_at=now)
        await self._execute(
            "INSERT INTO sessions (id, title, created_at, updated_at, design_brief) VALUES (?, ?, ?, ?, ?)",
            (str(session.id), session.title, now.isoformat(), now.isoformat(), None),
        )
        return session

    async def list_sessions(self) -> list[SessionView]:
        rows = await self._fetchall("SELECT * FROM sessions ORDER BY updated_at DESC")
        return [self._session_from_row(row) for row in rows]

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

    async def update_session_workspace(
        self, session_id: UUID, workspace: SessionWorkspace
    ) -> SessionView:
        await self._execute(
            "UPDATE sessions SET workspace_document_id=?, workspace_document_path=?, "
            "workspace_document_name=?, workspace_page_id=?, workspace_page_name=?, "
            "updated_at=? WHERE id=?",
            (
                workspace.document_id or None,
                workspace.document_path or None,
                workspace.document_name or None,
                workspace.page_id or None,
                workspace.page_name or None,
                utc_now().isoformat(),
                str(session_id),
            ),
        )
        session = await self.get_session(session_id)
        if session is None:
            raise LookupError(str(session_id))
        return session

    async def set_pending_workspace_action(
        self, session_id: UUID, decision: Any | None
    ) -> None:
        value = decision.model_dump_json() if decision is not None else None
        await self._execute(
            "UPDATE sessions SET pending_workspace_action=?, updated_at=? WHERE id=?",
            (value, utc_now().isoformat(), str(session_id)),
        )

    async def update_session_screen_registry(
        self, session_id: UUID, entries: dict[str, Any]
    ) -> None:
        session = await self.get_session(session_id)
        registry = {
            key: value.model_dump(mode="json")
            for key, value in (session.screen_registry if session else {}).items()
        }
        for key, value in entries.items():
            registry[str(key)] = (
                value.model_dump(mode="json")
                if hasattr(value, "model_dump")
                else value
            )
        await self._execute(
            "UPDATE sessions SET workspace_screen_registry=?, updated_at=? WHERE id=?",
            (
                json.dumps(registry, ensure_ascii=False),
                utc_now().isoformat(),
                str(session_id),
            ),
        )

    async def create_run(self, session_id: UUID, request: RunCreate) -> RunView:
        now = utc_now()
        run_id = uuid4()
        profile = request.mcp_profile
        if profile:
            session = await self.get_session(session_id)
            workspace_path = (
                session.workspace.document_path
                if session and session.workspace
                else ""
            )
            if profile.target_mode == "existing_file" and profile.output_file:
                pass
            elif workspace_path:
                profile = profile.model_copy(
                    update={"output_file": workspace_path, "target_mode": "existing_file"}
                )
            else:
                profile = profile.model_copy(
                    update={
                        "output_file": output_file_for_run(request.screen_name, run_id),
                        "target_mode": "new_file",
                    }
                )
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
            mcp_profile=profile,
            created_at=now,
            updated_at=now,
        )
        await self._execute(
            "INSERT INTO runs (id, session_id, revision, prompt, screen_name, platform, "
            "stage, status, library_ids, mcp_profile, specification, error, intent, assistant_message, style_name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                profile.model_dump_json() if profile else None,
                None,
                None,
                None,
                None,
                run.style_name,
                now.isoformat(),
                now.isoformat(),
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

    async def update_run(
        self,
        run_id: UUID,
        *,
        stage: RunStage | None = None,
        status: RunStatus | None = None,
        specification: UiSpecification | None = None,
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
                specification.model_dump_json(by_alias=True) if specification else None,
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

    async def update_mcp_profile(
        self,
        run_id: UUID,
        profile: OpenPencilProfile,
    ) -> RunView:
        run = await self.get_run(run_id)
        if run is None:
            raise LookupError(str(run_id))
        brief = await self.get_design_brief(run.session_id)
        output_name = brief.output_filename or run.screen_name
        session = await self.get_session(run.session_id)
        workspace_path = (
            session.workspace.document_path if session and session.workspace else ""
        )
        if profile.target_mode == "existing_file" and profile.output_file:
            pass
        elif workspace_path:
            profile = profile.model_copy(
                update={"output_file": workspace_path, "target_mode": "existing_file"}
            )
        else:
            profile = profile.model_copy(
                update={
                    "output_file": output_file_for_run(output_name, run.id),
                    "target_mode": "new_file",
                }
            )
        await self._execute(
            "UPDATE runs SET mcp_profile=?, updated_at=? WHERE id=?",
            (profile.model_dump_json(), utc_now().isoformat(), str(run_id)),
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

    def _run_from_row(self, row: Row) -> RunView:
        value = dict(row)
        value["library_ids"] = json.loads(value["library_ids"])
        profile = json.loads(value["mcp_profile"]) if value["mcp_profile"] else None
        # Older runs could be persisted before a component source was selected.
        # Treat that incomplete profile as absent so historical runs remain
        # readable and can be retried after the current settings are configured.
        if isinstance(profile, dict) and not str(profile.get("source_file") or "").strip():
            profile = None
        value["mcp_profile"] = profile
        value["specification"] = json.loads(value["specification"]) if value["specification"] else None
        value["error"] = json.loads(value["error"]) if value["error"] else None
        return RunView.model_validate(value)

    @staticmethod
    def _session_from_row(row: Row) -> SessionView:
        value = dict(row)
        value["design_brief"] = (
            json.loads(value["design_brief"]) if value.get("design_brief") else None
        )
        value["pending_workspace_action"] = (
            json.loads(value["pending_workspace_action"])
            if value.get("pending_workspace_action")
            else None
        )
        value["screen_registry"] = (
            json.loads(value["workspace_screen_registry"])
            if value.get("workspace_screen_registry")
            else {}
        )
        document_id = str(value.get("workspace_document_id") or "")
        value["workspace"] = (
            {
                "document_id": document_id,
                "document_path": str(value.get("workspace_document_path") or ""),
                "document_name": str(value.get("workspace_document_name") or ""),
                "page_id": str(value.get("workspace_page_id") or ""),
                "page_name": str(value.get("workspace_page_name") or ""),
            }
            if document_id
            else None
        )
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

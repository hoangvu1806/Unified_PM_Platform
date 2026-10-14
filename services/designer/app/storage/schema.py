from psycopg import Connection

# Postgres port of the original SQLite schema. Column order is kept identical
# and every INSERT names its columns. JSON payloads stay TEXT (the store
# json.dumps/loads them), timestamps stay ISO-8601 TEXT.
SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, title TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  design_brief TEXT,
  workspace_document_id TEXT,
  workspace_document_path TEXT,
  workspace_document_name TEXT,
  workspace_page_id TEXT,
  workspace_page_name TEXT,
  pending_workspace_action TEXT,
  workspace_screen_registry TEXT
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  revision INTEGER NOT NULL,
  prompt TEXT NOT NULL, screen_name TEXT NOT NULL, platform TEXT NOT NULL,
  stage TEXT NOT NULL, status TEXT NOT NULL, library_ids TEXT NOT NULL,
  mcp_profile TEXT, specification TEXT, error TEXT,
  intent TEXT, assistant_message TEXT, style_name TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  revision INTEGER NOT NULL,
  sequence INTEGER NOT NULL, event_type TEXT NOT NULL, payload TEXT NOT NULL,
  created_at TEXT NOT NULL, UNIQUE(run_id, sequence)
);
CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  revision INTEGER NOT NULL,
  checkpoint TEXT NOT NULL, decision TEXT NOT NULL, feedback TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  revision INTEGER NOT NULL, artifact_key TEXT NOT NULL,
  value TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(run_id, revision, artifact_key)
);
CREATE INDEX IF NOT EXISTS idx_runs_session ON runs(session_id);
"""

# Platform columns (project scoping, provenance), added idempotently so older
# databases upgrade in place.
MIGRATIONS = (
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS project_id TEXT",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS created_by TEXT",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS source TEXT",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS source_ref TEXT",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS triggered_by TEXT",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS source_artifact_id TEXT",
    "CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id)",
    # Which OpenPencil instance each designer uses (hosted elsewhere, later
    # one per designer). No row = the default instance from .env.
    """CREATE TABLE IF NOT EXISTS openpencil_instances (
      user_id TEXT PRIMARY KEY,
      mcp_url TEXT NOT NULL,
      editor_url TEXT NOT NULL,
      auth_token TEXT,
      updated_at TEXT NOT NULL
    )""",
)


def initialize_schema(db: Connection) -> None:
    db.execute(SCHEMA)
    for statement in MIGRATIONS:
        db.execute(statement)

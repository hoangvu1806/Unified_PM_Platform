from psycopg import Connection

# Postgres port of the original SQLite schema. Column order is kept identical
# and every INSERT names its columns. JSON payloads stay TEXT (the store
# json.dumps/loads them), timestamps stay ISO-8601 TEXT.
# sessions.workspace_* / pending_workspace_action and runs.mcp_profile belong to the
# OpenPencil designer: no longer written, kept so existing databases need no migration.
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
    # HTML designer: one row per screen of a session (current HTML), every save kept as a version.
    """CREATE TABLE IF NOT EXISTS screens (
      session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
      screen_id TEXT NOT NULL,
      name TEXT NOT NULL,
      platform TEXT NOT NULL,
      width INTEGER NOT NULL,
      position INTEGER NOT NULL,
      version INTEGER NOT NULL,
      html TEXT NOT NULL,
      run_id TEXT,
      updated_by TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY (session_id, screen_id)
    )""",
    """CREATE TABLE IF NOT EXISTS screen_versions (
      session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
      screen_id TEXT NOT NULL,
      version INTEGER NOT NULL,
      html TEXT NOT NULL,
      run_id TEXT,
      updated_by TEXT,
      note TEXT,
      created_at TEXT NOT NULL,
      PRIMARY KEY (session_id, screen_id, version)
    )""",
    # Design systems imported from .fig (project_id NULL = shared by every project).
    """CREATE TABLE IF NOT EXISTS design_systems (
      id TEXT PRIMARY KEY,
      project_id TEXT,
      name TEXT NOT NULL,
      source_name TEXT,
      source_key TEXT,
      status TEXT NOT NULL,
      error TEXT,
      theme_css TEXT,
      fonts TEXT,
      index_json TEXT,
      created_by TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS design_system_snippets (
      design_system_id TEXT NOT NULL REFERENCES design_systems(id) ON DELETE CASCADE,
      variant_id TEXT NOT NULL,
      component_id TEXT NOT NULL,
      html TEXT NOT NULL,
      PRIMARY KEY (design_system_id, variant_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ds_snippets_component ON design_system_snippets(design_system_id, component_id)",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS design_system_id TEXT",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS visual_theme TEXT",
)


def initialize_schema(db: Connection) -> None:
    db.execute(SCHEMA)
    for statement in MIGRATIONS:
        db.execute(statement)

"""Designer schema (Postgres, schema ``designer``).

Postgres holds metadata and small JSON; file content (screen HTML, uploads, design-system
sources, deliverables) lives in platform storage (S3) under keys from ``storage.layout``.

``BASELINE`` is the current structure for a new database. ``BEFORE`` and ``AFTER`` upgrade
an existing one in place and are idempotent (safe on every start). HTML still stored in the
database by older versions is moved to storage by ``Store._migrate_screen_html`` before
``DROP_INLINE_HTML`` removes those columns.
"""

from psycopg import Connection

# Renames must run before BASELINE, which would otherwise create the new name empty.
BEFORE = (
    """DO $$ BEGIN
      IF to_regclass('artifacts') IS NOT NULL AND to_regclass('run_data') IS NULL THEN
        ALTER TABLE artifacts RENAME TO run_data;
      END IF;
    END $$""",
)

BASELINE = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, title TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  design_brief TEXT,
  project_id TEXT, created_by TEXT, source TEXT, source_ref TEXT, source_artifact_id TEXT,
  design_system_id TEXT, visual_theme TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  revision INTEGER NOT NULL,
  prompt TEXT NOT NULL, screen_name TEXT NOT NULL, platform TEXT NOT NULL,
  stage TEXT NOT NULL, status TEXT NOT NULL, library_ids TEXT NOT NULL,
  specification TEXT, error TEXT,
  intent TEXT, assistant_message TEXT, style_name TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, triggered_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_session ON runs(session_id);
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
-- Per-run working data (token usage, attached assets …); not the project Assets (core.artifacts).
CREATE TABLE IF NOT EXISTS run_data (
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  revision INTEGER NOT NULL, artifact_key TEXT NOT NULL,
  value TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(run_id, revision, artifact_key)
);
-- Screens: the current version of each screen; the HTML of every version is an immutable
-- object in storage (storage_key), never updated in place.
CREATE TABLE IF NOT EXISTS screens (
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  screen_id TEXT NOT NULL,
  name TEXT NOT NULL, platform TEXT NOT NULL, width INTEGER NOT NULL, position INTEGER NOT NULL,
  version INTEGER NOT NULL,
  storage_key TEXT, content_hash TEXT, size INTEGER,
  run_id TEXT, updated_by TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY (session_id, screen_id)
);
CREATE TABLE IF NOT EXISTS screen_versions (
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  screen_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  storage_key TEXT, content_hash TEXT, size INTEGER,
  run_id TEXT, updated_by TEXT, note TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (session_id, screen_id, version)
);
-- Design systems imported from .fig (project_id NULL = shared); the .fig itself is in storage.
CREATE TABLE IF NOT EXISTS design_systems (
  id TEXT PRIMARY KEY, project_id TEXT,
  name TEXT NOT NULL, source_name TEXT, source_key TEXT,
  status TEXT NOT NULL, error TEXT,
  theme_css TEXT, fonts TEXT, index_json TEXT,
  created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_design_systems_project ON design_systems(project_id);
CREATE TABLE IF NOT EXISTS design_system_snippets (
  design_system_id TEXT NOT NULL REFERENCES design_systems(id) ON DELETE CASCADE,
  variant_id TEXT NOT NULL, component_id TEXT NOT NULL, html TEXT NOT NULL,
  PRIMARY KEY (design_system_id, variant_id)
);
CREATE INDEX IF NOT EXISTS idx_ds_snippets_component ON design_system_snippets(design_system_id, component_id);
"""

AFTER = (
    # Columns added by earlier platform versions (no-ops on a new database).
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS project_id TEXT",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS created_by TEXT",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS source TEXT",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS source_ref TEXT",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS source_artifact_id TEXT",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS design_system_id TEXT",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS visual_theme TEXT",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS triggered_by TEXT",
    # Screens written before HTML moved to storage: add the storage columns, relax inline HTML.
    "ALTER TABLE screens ADD COLUMN IF NOT EXISTS storage_key TEXT",
    "ALTER TABLE screens ADD COLUMN IF NOT EXISTS content_hash TEXT",
    "ALTER TABLE screens ADD COLUMN IF NOT EXISTS size INTEGER",
    "ALTER TABLE screen_versions ADD COLUMN IF NOT EXISTS storage_key TEXT",
    "ALTER TABLE screen_versions ADD COLUMN IF NOT EXISTS content_hash TEXT",
    "ALTER TABLE screen_versions ADD COLUMN IF NOT EXISTS size INTEGER",
    """DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema()
                 AND table_name = 'screens' AND column_name = 'html') THEN
        ALTER TABLE screens ALTER COLUMN html DROP NOT NULL;
        ALTER TABLE screen_versions ALTER COLUMN html DROP NOT NULL;
      END IF;
    END $$""",
    # The OpenPencil designer is gone: its instance table and workspace/profile columns.
    "DROP TABLE IF EXISTS openpencil_instances",
    "ALTER TABLE sessions DROP COLUMN IF EXISTS workspace_document_id",
    "ALTER TABLE sessions DROP COLUMN IF EXISTS workspace_document_path",
    "ALTER TABLE sessions DROP COLUMN IF EXISTS workspace_document_name",
    "ALTER TABLE sessions DROP COLUMN IF EXISTS workspace_page_id",
    "ALTER TABLE sessions DROP COLUMN IF EXISTS workspace_page_name",
    "ALTER TABLE sessions DROP COLUMN IF EXISTS pending_workspace_action",
    "ALTER TABLE sessions DROP COLUMN IF EXISTS workspace_screen_registry",
    "ALTER TABLE runs DROP COLUMN IF EXISTS mcp_profile",
)

# After every inline HTML row is in storage (checked by the store).
DROP_INLINE_HTML = (
    "ALTER TABLE screens DROP COLUMN IF EXISTS html",
    "ALTER TABLE screen_versions DROP COLUMN IF EXISTS html",
)


def initialize_schema(db: Connection) -> None:
    for statement in BEFORE:
        db.execute(statement)
    db.execute(BASELINE)
    for statement in AFTER:
        db.execute(statement)


def has_inline_html(db: Connection) -> bool:
    row = db.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND table_name = 'screen_versions' AND column_name = 'html'"
    ).fetchone()
    return row is not None


def drop_inline_html(db: Connection) -> None:
    for statement in DROP_INLINE_HTML:
        db.execute(statement)

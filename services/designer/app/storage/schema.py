import sqlite3


def initialize_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
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
          id TEXT PRIMARY KEY, session_id TEXT NOT NULL, revision INTEGER NOT NULL,
          prompt TEXT NOT NULL, screen_name TEXT NOT NULL, platform TEXT NOT NULL,
          stage TEXT NOT NULL, status TEXT NOT NULL, library_ids TEXT NOT NULL,
          mcp_profile TEXT, specification TEXT, error TEXT,
          intent TEXT, assistant_message TEXT, style_name TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS events (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, revision INTEGER NOT NULL,
          sequence INTEGER NOT NULL, event_type TEXT NOT NULL, payload TEXT NOT NULL,
          created_at TEXT NOT NULL, UNIQUE(run_id, sequence),
          FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS reviews (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, revision INTEGER NOT NULL,
          checkpoint TEXT NOT NULL, decision TEXT NOT NULL, feedback TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS artifacts (
          run_id TEXT NOT NULL, revision INTEGER NOT NULL, artifact_key TEXT NOT NULL,
          value TEXT NOT NULL, created_at TEXT NOT NULL,
          PRIMARY KEY(run_id, revision, artifact_key),
          FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
        );
        """
    )
    columns = {row[1] for row in db.execute("PRAGMA table_info(runs)")}
    migrations = {
        "mcp_profile": "ALTER TABLE runs ADD COLUMN mcp_profile TEXT",
        "intent": "ALTER TABLE runs ADD COLUMN intent TEXT",
        "assistant_message": "ALTER TABLE runs ADD COLUMN assistant_message TEXT",
        "style_name": "ALTER TABLE runs ADD COLUMN style_name TEXT",
    }
    for column, statement in migrations.items():
        if column not in columns:
            db.execute(statement)
    session_columns = {row[1] for row in db.execute("PRAGMA table_info(sessions)")}
    if "design_brief" not in session_columns:
        db.execute("ALTER TABLE sessions ADD COLUMN design_brief TEXT")
    session_migrations = {
        "workspace_document_id": "ALTER TABLE sessions ADD COLUMN workspace_document_id TEXT",
        "workspace_document_path": "ALTER TABLE sessions ADD COLUMN workspace_document_path TEXT",
        "workspace_document_name": "ALTER TABLE sessions ADD COLUMN workspace_document_name TEXT",
        "workspace_page_id": "ALTER TABLE sessions ADD COLUMN workspace_page_id TEXT",
        "workspace_page_name": "ALTER TABLE sessions ADD COLUMN workspace_page_name TEXT",
        "pending_workspace_action": "ALTER TABLE sessions ADD COLUMN pending_workspace_action TEXT",
        "workspace_screen_registry": "ALTER TABLE sessions ADD COLUMN workspace_screen_registry TEXT",
    }
    for column, statement in session_migrations.items():
        if column not in session_columns:
            db.execute(statement)

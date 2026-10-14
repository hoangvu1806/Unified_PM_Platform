"""Schema ``core``: the single source of truth for users and projects."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id             TEXT PRIMARY KEY,          -- later: Keycloak `sub`
  username       TEXT UNIQUE NOT NULL,
  display_name   TEXT NOT NULL,
  password_hash  TEXT,                      -- AUTH_MODE=mock only
  platform_roles TEXT[] NOT NULL DEFAULT '{}',
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS projects (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  created_by  TEXT REFERENCES users(id),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  archived_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS project_members (
  project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  project_role TEXT NOT NULL CHECK (project_role IN ('BA','DESIGNER','REVIEWER','ADMIN')),
  added_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, user_id, project_role)
);
CREATE INDEX IF NOT EXISTS idx_project_members_user ON project_members(user_id);
"""

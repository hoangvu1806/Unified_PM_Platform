from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from wiki.paths import blob_dir, data_dir, db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS wiki_source (
  source_id TEXT PRIMARY KEY,
  filename TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  namespace TEXT NOT NULL,
  project_id TEXT,
  storage_uri TEXT NOT NULL,
  markdown_extract TEXT NOT NULL,
  page_map TEXT NOT NULL DEFAULT '[]',
  ingested_at TEXT NOT NULL,
  ingested_by TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_wiki_source_sha_scope
  ON wiki_source(sha256, namespace, IFNULL(project_id, ''));

CREATE TABLE IF NOT EXISTS wiki_page (
  page_id TEXT PRIMARY KEY,
  namespace TEXT NOT NULL,
  project_id TEXT,
  bucket_id TEXT NOT NULL,
  title TEXT NOT NULL,
  abbrev TEXT,
  expansion TEXT,
  disambiguation TEXT,
  status TEXT NOT NULL,
  version TEXT NOT NULL,
  body TEXT NOT NULL,
  source_ids TEXT NOT NULL DEFAULT '[]',
  owner TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wiki_revision (
  revision_id TEXT PRIMARY KEY,
  page_id TEXT NOT NULL,
  version TEXT NOT NULL,
  status TEXT NOT NULL,
  body_snapshot TEXT NOT NULL,
  diff_ref TEXT,
  actor TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (page_id) REFERENCES wiki_page(page_id)
);
"""


def connect(root: Path) -> sqlite3.Connection:
    data_dir(root).mkdir(parents=True, exist_ok=True)
    blob_dir(root).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path(root), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    # Older DBs used a global sha256 unique index, which blocked the same file
    # in two projects and made uploads look broken (HTTP 500 / drafts+=0).
    conn.execute("DROP INDEX IF EXISTS idx_wiki_source_sha256")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_wiki_source_sha_scope
          ON wiki_source(sha256, namespace, IFNULL(project_id, ''))
        """
    )
    conn.commit()
    return conn


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    data = dict(row)
    for key in ("page_map", "source_ids"):
        if key in data and isinstance(data[key], str):
            data[key] = json.loads(data[key])
    return data

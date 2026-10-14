# Changes from the source repositories

Commit `4bd69b3` imports the sources verbatim:
- BA from `git archive` at `59203e1`
- Designer from `git archive` at `42e0a4e`
- wiki-mvp copied from disk

Every later edit to imported files is listed here.

| File | Change | Why | Sprint |
|---|---|---|---|
| `services/ba/config/base_config.py` | `AliasChoices` for the unified `.env` names (`POSTGRES_*`, `LLM_*`, `BA_*`, `PLATFORM_*`, `DESIGNER_INTERNAL_URL`, `OPENPENCIL_DEFAULT_EDITOR_URL`); removed `env_file=".env"`; added `db_schema`, `async_engine_kwargs`, `platform_public_url`; `designer_ui_base_url` defaults to `PLATFORM_PUBLIC_URL/designer` | One `.env`, one Postgres with per-service schema | 1 |
| `services/ba/managers/database/connection.py` | Sync URL pins `search_path=ba`; `init_db` creates the schema | Shared database | 1 |
| `services/ba/managers/runner_context.py` | `DatabaseSessionService(..., **settings.async_engine_kwargs)` | ADK tables live in schema `ba` | 1 |
| `services/ba/factory_wiki/paths.py` | Wiki package candidates include `packages/wiki` and `/opt/platform/packages/wiki` | wiki-mvp lives in the monorepo | 1 |
| `services/ba/Dockerfile` | Build context = platform root; copies `packages/wiki` | Shared packages | 1 |
| `apps/ba-web/vite.config.js`, `src/api.js` | `base` `/ba/`; `API_BASE` from `VITE_API_BASE` | Served behind the gateway | 1 |
| `apps/ba-web/Dockerfile`, `nginx.conf` (new) | Static build + nginx instead of Vite dev server | Production-like serving behind the gateway | 1 |
| `services/designer/app/core/config.py` | `PROJECT_DIR = parents[2]`; removed `load_dotenv`/`env_file`; aliases (`DESIGNER_*`, `PLATFORM_CORS_ORIGINS`); `DESIGNER_LLM_*` falls back to shared `LLM_*` when empty | Flattened layout, one `.env` | 1 |
| `services/designer/app/core/prompts.py`, `app/openpencil/knowledge.py` | Knowledge dir `parents[2]` | Flattened layout (`backend/` → service root) | 1 |
| `services/designer/Dockerfile` | `python:3.12-slim-bookworm`; context = platform root; service root `/app` | Python 3.12 everywhere | 1 |
| `services/designer/tests/test_attachment_parser.py` | Fixture read from `tests/fixtures/` | Fixture moved | 1 |
| `apps/designer-web/vite.config.ts`, `Dockerfile` | `base` `/designer/`; API `/designer/api/v1` | Served behind the gateway | 1 |
| `apps/designer-web/nginx.conf` | Static only; API proxy removed | Gateway proxies the API | 1 |
| `apps/designer-web/src/{ChatWorkspace,SessionRail,WorkspaceHeader}.tsx` | Public images use `import.meta.env.BASE_URL` | Base path `/designer/` | 1 |
| `packages/wiki/wiki/llm_config.py` | Falls back to `LLM_BASE_URL` / `LLM_API_KEY` | Shared LLM gateway | 1 |
| `services/ba/config/base_config.py` | `async_engine_kwargs` empty for non-Postgres URLs | Tests swap the URL for SQLite in-memory | 1 |
| `services/designer/app/storage/store.py` | `sqlite3` → `psycopg_pool` (`dict_row`, `search_path` per connection); `?` kept and translated to `%s`; INSERTs name their columns; event-sequence retry catches `UniqueViolation`; `close()` | Shared Postgres, schema `designer` | 2 |
| `services/designer/app/storage/schema.py` | Postgres DDL, same column order; adds `sessions.project_id/created_by/source/source_ref`, `runs.triggered_by` | Shared Postgres; project scoping in Sprint 3 | 2 |
| `services/designer/app/core/config.py`, `app/main.py` | `postgres_dsn` (via `platform_core.db`) replaces `database_url`/`sqlite_path`; `designer_asset_dir()` | No SQLite; files in shared storage | 2 |
| `services/designer/app/api/routes.py`, `app/openpencil/media.py`, `app/workflow/analysis.py` | Asset bytes in `STORAGE_LOCAL_ROOT/shared/designer/assets` | Shared storage, S3 key layout | 2 |
| `services/designer/requirements.txt`, `Dockerfile` | `psycopg[binary,pool]`; installs `packages/platform_core` | Postgres driver, shared lib | 2 |
| `services/designer/tests/test_store.py`, `tests/pg.py`, `tests/conftest.py` (new), `pyproject.toml` | Store tests use a throwaway Postgres schema; `pythonpath = ["."]` | Postgres tests | 2 |
| `packages/wiki/wiki/db.py` | Postgres (psycopg2) behind a sqlite3-compatible wrapper: `?`→`%s`, `ifnull`→`COALESCE`, `LIKE`→`ILIKE`, PRAGMA no-op; schema `WIKI_DB_SCHEMA`; new `audit_log` table | No SQLite; keep `wiki.service`/`factory_wiki` unchanged; keep case-insensitive search | 2 |
| `packages/wiki/wiki/service.py` | `reset_store` via `information_schema` + storage keys; `CAST(? AS TEXT) IS NULL`; blobs written under storage key, `storage_uri` = key; advisory lock for `REV-` ids | Postgres semantics, S3 layout, concurrent ingest | 2 |
| `packages/wiki/wiki/paths.py`, `audit.py` | `storage_root/blob_key/blob_path`; audit rows to `wiki.audit_log` | Shared storage, no runtime files | 2 |
| `packages/wiki/tests/conftest.py`, `pyproject.toml` | Schema + storage per test; `psycopg2-binary` | Postgres tests | 2 |
| `services/ba/factory_wiki/reset.py` | Delegates to `WikiService.reset_store` (schema guard) | No SQLite | 2 |
| `services/ba/tests/conftest.py` (new), `tests/test_control_plane.py` | Wiki schema per test; clear/guard tests assert the Postgres store | Postgres wiki | 2 |

## Test results (Docker)

| Suite | Result | Original source |
|---|---|---|
| `platform_core` | 5 passed | (new) |
| `packages/wiki` | 24 passed, 1 skipped (live LLM) | — |
| `services/ba` | 162 passed, 3 skipped | — |
| `services/designer` | 107 passed, 10 failed | **same 10 failures** on the original Designer source (Python 3.11 + SQLite): missing `data/evals/golden-projects.json`, stale mocks |

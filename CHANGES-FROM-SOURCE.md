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
| `packages/platform_core/platform_core/{auth,projects,fastapi}.py` (new) | Mock JWT (Keycloak-shaped claims), project membership/role checks, FastAPI `authenticate` + `require_project` | Shared identity and authorization | 3 |
| `services/core/` (new) | core-api: users, projects, members, mock login (HttpOnly cookie), demo seed, `python -m app.legacy` (assigns pre-platform rows to `PRJ-LEGACY`, adds `project_id` foreign keys) | Project is the root of the data model | 3 |
| `apps/portal/` (new) | Portal: login (quick demo accounts), projects by user, project page (members, open BA/Designer) | Shared UI | 3 |
| `services/ba/server.py`, `managers/service/access.py` (new) | Every router depends on `ba_access`: login required; `{session_id}` routes checked against the feature's project (GET = member, other = BA/ADMIN) | Project scoping, chat visible to members only | 3 |
| `services/ba/managers/service/features.py`, `schema.py` | Create needs `project_id` (BA role); list filters by `project_id`; handoff sends `project_id`/`requested_by`; designer link carries the project | Project scoping | 3 |
| `services/ba/managers/service/wiki_pages.py` | Project membership for reads; BA role for project pages; company wiki writes and clear need ADMIN; audit actor = logged-in user | Wiki in project Assets | 3 |
| `services/ba/managers/database/models.py`, `connection.py` | `ba_packages.project_id/created_by`, `designer_handoffs.project_id` (+ in-place column upgrade) | Project scoping | 3 |
| `services/ba/managers/integrations/designer/service.py` | Optional `project_id`, `requested_by` in the handoff payload | Session lands in the same project | 3 |
| `apps/ba-web/src/platform.js` (new), entry scripts, `api.js` | Login redirect, project from `?project=`, platform bar, read-only mode for non-BA members, project-scoped list/create/clear | Project context in the BA UI | 3 |
| `services/designer/app/api/access.py` (new), `app/main.py` | `designer_access` on the UI router (health stays public); `X-Agent-Secret` checked on handoffs when configured | Project scoping; the source never verified the secret | 3 |
| `services/designer/app/api/routes.py` | Sessions need/list by `project_id`; runs record `triggered_by`; MCP endpoint resolved per user; OpenPencil instance endpoints | Project scoping; OpenPencil per designer (plan 06) | 3 |
| `services/designer/app/openpencil/instances.py` (new), `client.py` | User instance → default instance; loopback endpoints from the browser map to the default instance; per-instance MCP token | OpenPencil per designer | 3 |
| `services/designer/app/{models,storage}` | `SessionView`/`SessionCreate`/handoff carry project fields; store helpers; `openpencil_instances` table | Project scoping | 3 |
| `apps/designer-web/src/platform.ts` (new), `main.tsx`, `api.ts` | Same platform context as BA; project-scoped sessions; read-only for non-designers | Project context in the Designer UI | 3 |
| `packages/platform_core/platform_core/storage.py` | `S3Storage` (S3/MinIO/Ceph via boto3) with a write-through local cache; `make_storage`/`get_storage`; HEAD 403 falls back to LIST | Files in S3, code that reads by path keeps working | 4 |
| `packages/platform_core/platform_core/artifacts.py` (new) | `core.artifacts` registry: versions, `derived_from`, `stale` computed on read | Project Assets | 4 |
| `packages/platform_core/platform_core/sync_storage.py` (new), `settings.py` | One-off local → S3 copy; S3 settings; `startup_report` (logs config, refuses default secrets in production) | S3 switch, operability | 4 |
| `services/core/app/routes.py`, `main.py`, `compose.yml` | `GET /projects/{id}/artifacts`, `GET /artifacts/{id}/download` (members only); artifacts schema at startup; storage volume | Assets in the Portal | 4 |
| `services/ba/managers/service/assets.py` (new), `features.py` | Export / handoff publish the envelope to storage + `ba_package` artifact; version moves only when `payload` changes | Versioned BA packages | 4 |
| `services/designer/app/workflow/publish.py` (new), `service.py` | Finished run with an output file → .fig copied from OpenPencil to storage + `designer_output` artifact linked to the BA package version | Designs in Assets, stale marking | 4 |
| `services/designer/app/api/handoff_routes.py`, `app/storage/*`, `app/models` | Handoff session: `source_ref` = BA feature id, `source_artifact_id` = latest BA package | Design ↔ BA version link | 4 |
| `services/designer/app/core/config.py`, `routes.py`, `openpencil/media.py`, `workflow/analysis.py` | Assets saved via storage (`save_designer_asset`), read via `designer_asset_file` (downloads on cache miss) | Assets in S3 | 4 |
| `packages/wiki/wiki/paths.py`, `service.py` | Source blobs stored/deleted via platform storage when available (`put_blob`/`delete_blob`) | Wiki blobs in S3 | 4 |
| `apps/portal/src/{App.tsx,api.ts,styles.css}` | Project page tabs: **Assets** (artifacts, versions, "Cần xem lại", download, wiki counts) and **Data workspace** (BA and Designer sessions) | HTML structure: Project → Assets + Data workspace | 4 |
| `services/*/compose.yml`, test `conftest.py` | Test containers force `STORAGE_BACKEND=local` | Tests never write to the real bucket | 4 |
| `apps/portal/src/*`, `package.json` | Portal redesign: split login with demo account cards, home with search and per-project accent cards (quick BA/Design buttons), create-project dialog, project page with module cards and Assets / Data workspace / Members tabs; `lucide-react` 0.453.0 | Modern shared UI | 4 |
| `services/core/app/routes.py` | `GET /projects/{id}/files` (artifacts + wiki sources with creator), `GET /projects/{id}/wiki-sources/{sid}/markdown`; RFC 5987 `Content-Disposition` | Project files for agents/chats | 4 |
| `apps/designer-web/src/{projectFiles.ts,ProjectFilesPanel.tsx,MentionMenu.tsx}` (new), `ChatWorkspace.tsx`, `ReviewPanel.tsx`, `App.tsx`, `workspace.css` | Right panel "Files dự án" (creator, time, filters); drag a file into the composer, "+" button, or `@` mention picker — all reuse the existing attachment parser | Cite shared project files in Designer chats | 4 |
| `apps/designer-web/src/{platform.ts,WorkspaceHeader.tsx,styles.css}` | Project, role, user and logout moved into the Designer header (no extra top bar) | Cleaner Designer UI | 4 |
| `apps/ba-web/index.html`, `src/main.js`, `src/platform.js` | "Tạo Dự Án Mới" → "Tạo Feature mới"; page title names the project; empty project opens the new-feature dialog | Feature ≠ project on the platform | 4 |
| `packages/platform_core/platform_core/projects.py`, `services/core/app/{schema,seed,routes}.py` | Role **PM** (counts as BA + DESIGNER, like ADMIN); a new project makes its creator ADMIN + PM; demo user `pm.hoa` | One person does the whole journey | 5 |
| `services/core/app/journey.py` (new), `routes.py` | `GET /projects/{id}/features/{fid}/journey`: 9 steps (BA 1–6, Design 7–9) built from the shared DB, with locked reasons and BA package version / stale state | Guided BA → Design journey | 5 |
| `apps/portal/src/*` | Designer-style shell (project rail, breadcrumb header), journey page with the 9 steps in the single header row, embedded BA / Designer (`?embed=1`), guide dialogs on every step change, project page always shows both agents with their state ("Chờ BA"), Designer page inside the portal | Unified workspace in one app | 5 |
| `apps/ba-web/{chat.html,src/chat.js,src/design-tokens.css,src/platform-theme.css,src/platform.js}` | Designer look: Plus Jakarta Sans, borderless surfaces, pills instead of mono `[TAGS]`, Vietnamese labels, collapsible completion flags, compact action dock; embedded mode hides BA's own header; title read from the feature; journey step selects the BA section (`platform:select-section`); "Bàn giao & mở Designer" asks the portal to switch role | Same style as Designer, more room for the chat | 5 |
| `apps/designer-web/src/{BaStatusPanel.tsx,SessionRail.tsx,platform.ts,styles.css,...}` | Left rail shows the BA state of a handed-off feature (steps, package version, stale warning); embedded mode hides the brand block | Designer sees BA read-only | 5 |
| `scripts/{e2e_full_flow.sh,reset_platform_data.py,case_designer.py,e2e_ui.py}` | Full real flow (PM → BA → handoff → design → storage), data reset, UI walk-through for the new portal | Real end-to-end checks | 5 |
| `services/designer/app/workflow/{publish,review}.py`, `packages/platform_core/platform_core/artifacts.py` | Design file (.fig) and UI specification go to Assets as soon as the final design waits for review (`meta.state = review`) and are refreshed on approval (`approved`); the approval path now publishes (it spawned no task before, so approved designs never reached Assets); a refused final approval (LAYOUT_NOT_VALID) is checked before the review is recorded; `artifacts.update()` | Artifacts & versions: UI spec, design file, draft / review state | 5 |
| `services/ba/managers/service/assets.py` | Each BA package version also publishes its reference BPMN (`bpmn` artifact linked to the package) | Artifacts: BPMN | 5 |
| `services/ba/managers/control/bpmn.py`, `apps/ba-web/src/chat.js` | Aligned markdown table rules (`|:---|`) are no longer parsed as workflow steps (became a ":---" touchpoint / BPMN task); UI touchpoints shown as compact collapsible screen cards | Cleaner BA output | 5 |
| `services/core/app/journey.py` | "Duyệt thiết kế" is done only when the run is finished or the design is in Assets | Correct journey state | 5 |
| `apps/portal/src/{App.tsx,api.ts,styles.css}`, `services/core/app/routes.py`, `.env.example` | Login redesign: split screen fitted to the viewport (no scrollbar), quick sign-in lists PM accounts only, "Đăng nhập với Keycloak" button driven by `GET /api/core/auth/providers` (enabled once `KEYCLOAK_URL/REALM/CLIENT_ID` are set) | Keycloak later, modern login | 5 |

## Test results (Docker)

| Suite | Result | Original source |
|---|---|---|
| `platform_core` | 13 passed (incl. S3Storage on moto) | (new) |
| `packages/wiki` | 24 passed, 1 skipped (live LLM) | — |
| `services/ba` | 162 passed, 3 skipped | — |
| `services/designer` | 107 passed, 10 failed | **same 10 failures** on the original Designer source (Python 3.11 + SQLite): missing `data/evals/golden-projects.json`, stale mocks |
| `services/core` | 5 passed | (new) |
| `scripts/e2e_access.py` (gateway, mock users) | 36 passed | (new) |
| `scripts/e2e_assets.sh` (real S3 bucket) | PASS: BA v1 → handoff → design published → BA v2 → design stale; download ACL | (new) |

Legacy suites run with `AUTH_MODE=off`; access rules are covered by `platform_core` tests, `services/core` tests and `scripts/e2e_access.py`.

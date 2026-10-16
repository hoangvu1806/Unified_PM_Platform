# Unified Work AI Platform

One workspace for the **BA agent** (business analysis) and the **Designer agent** (UI design on OpenPencil).
A user logs in, opens a project, and takes each feature through one guided journey of 9 steps: BA analysis first,
then design, in the same screen. Both agents share one backend, one PostgreSQL database, one object storage and one `.env`.

```
Login ─► Projects ─► Project
                      ├─ Features      one journey per feature (BA steps 1–6 ─► Design steps 7–9)
                      ├─ Assets        wiki / knowledge, BA packages, designs (versioned, on S3)
                      ├─ Data workspace  BA sessions and Designer sessions (chat history)
                      └─ Members       PM · BA · DESIGNER · REVIEWER · ADMIN
```

## Repository layout

```
.
├── .env.example          the only configuration file (copy to .env)
├── docker-compose.yml    whole platform          compose.ba.yml / compose.designer.yml  one module only
├── infra/                postgres (DB "platform", schemas core / ba / designer / wiki), gateway (nginx :8080)
├── packages/
│   ├── platform_core/    settings, db, storage (S3 + local cache), auth (JWT), projects/roles, artifacts, logs
│   └── wiki/             project / company wiki (from wiki-mvp, on PostgreSQL)
├── services/
│   ├── core/             users, login, projects, members, artifacts registry, journey API
│   ├── ba/               BA agent (FastAPI + Google ADK)
│   └── designer/         Designer agent (FastAPI + Google ADK + OpenPencil MCP)
├── apps/
│   ├── portal/           React: login, projects, journey page (embeds BA and Designer)
│   ├── ba-web/           BA UI (Vite, vanilla JS)
│   └── designer-web/     Designer UI (React)
├── scripts/              end-to-end checks, real-case runners, data reset
└── docs/reference/       integration standard and product deck
```

`CHANGES-FROM-SOURCE.md` lists every change made to the imported BA and Designer sources.

## Run (Docker only)

Requirements: Docker Desktop, and the OpenPencil editor image (a separate repository, cloned next to this one as `../BA/open-pencil`).

```bash
cp .env.example .env                              # LLM keys, DB password, JWT secret, S3 keys
(cd ../BA/open-pencil && docker compose up -d)    # default OpenPencil instance: editor :1420, MCP :7600
docker compose up -d --build                      # http://localhost:8080
docker builder prune -af                          # optional: drop the build cache afterwards
```

| URL | What |
|---|---|
| http://localhost:8080/ | Portal: login, projects, journey |
| http://localhost:8080/projects/PRJ-AURORA | A project: Features, Assets, Data workspace, Members |
| http://localhost:8080/projects/&lt;id&gt;/f/&lt;feature&gt; | Journey of one feature (BA ─► Design in one screen) |
| http://localhost:8080/projects/&lt;id&gt;/designer | Designer agent of a project (also before any BA handoff) |
| http://localhost:1420 | OpenPencil editor — keep **one** tab open while the Designer builds screens |

Accounts (`AUTH_MODE=mock`, password `demo123`): `pm.hoa` and `lead.dung`, both PM (BA + Designer). No project is
seeded; create one after login. `MOCK_SEED=full` adds the single-role accounts (`ba.an`, `ba.chi`, `designer.binh`)
and the sample projects `PRJ-AURORA`, `PRJ-DEMO` — the test containers use it, and `scripts/e2e_access.py` needs it.
The login page also shows "Đăng nhập với Keycloak", enabled once `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID` are set.

## Configuration

Everything is in `.env` (see `.env.example`, grouped by section):

| Group | Keys |
|---|---|
| Database | `POSTGRES_*` — one database, one schema per service |
| Auth | `AUTH_MODE=mock` (Keycloak later), `AUTH_JWT_SECRET`, `AUTH_JWT_TTL_MINUTES` |
| LLM | `LLM_*` shared; `BA_LLM_MODEL`, `WIKI_LLM_MODEL`, `DESIGNER_LLM_*` override per agent |
| Storage | `STORAGE_BACKEND=s3\|local`, `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `STORAGE_LOCAL_ROOT` |
| OpenPencil | `OPENPENCIL_DEFAULT_MCP_URL`, `OPENPENCIL_DEFAULT_EDITOR_URL` |
| Logs | `LOG_DIR`, `LOG_PROJECT_TO_STORAGE`, `LOG_PROJECT_FLUSH_SECONDS` |

`.env` is never committed.

## How it works

**Roles.** Members of a project read everything in it, chat included. Writing in BA needs `BA`, in Designer
`DESIGNER`; `PM` and `ADMIN` count as both. A new project makes its creator `ADMIN` + `PM`. Non-members get 403.

**Journey.** `GET /api/core/projects/{id}/features/{fid}/journey` builds the 9 steps from the shared database
(BA sections, validation, BA packages, Designer sessions, runs and reviews). The portal shows them in one header
row; the BA and Designer pages are embedded below (`?embed=1`). When a step finishes, a dialog explains the next
one; after the BA package is handed off, the user is guided to switch to the Designer role. The Designer's left
rail shows the BA state of the feature, and the project page always shows both agents with their state
("Chờ BA" until a BA package exists).

**Assets.** Files use S3-style keys: `projects/<id>/ba/packages/…`, `projects/<id>/designer/outputs/…`,
`projects/<id>/wiki/blobs/…`, `projects/<id>/logs/…`, `shared/…`. S3 is the source of truth, `STORAGE_LOCAL_ROOT`
is a write-through cache. Every BA export publishes a versioned BA package and its BPMN. When a design waits
for the final review, its UI specification and the OpenPencil `.fig` are published as "Chờ duyệt"; the approval
marks them "Đã duyệt". Designs link to the BA package version they came from, so a newer BA version marks them
"cần xem lại".

**OpenPencil.** One default instance today. A designer's own instance is a row in `designer.openpencil_instances`
(`PUT /designer/api/v1/openpencil-instances/{user_id}?project_id=…`, project ADMIN only).

**Logs.** Local: `logs/<service>/<service>.log` (JSON lines, daily rotation, 14 days), each request with `user`,
`project_id`, `request_id`. Per project: `projects/<project_id>/logs/<service>/<date>/*.jsonl` in storage.

## Commands

| Task | Command |
|---|---|
| Tests | `docker compose --profile test run --rm core-test` (also `ba-test`, `designer-test`, `wiki-test`) |
| Access checks | `docker run --rm --network platform_default -v "$PWD/scripts:/s:ro" python:3.12-slim python /s/e2e_access.py http://gateway` |
| Assets flow on real storage | `sh scripts/e2e_assets.sh` |
| UI walk-through (Playwright) | `docker run --rm --network platform_default -v "$PWD/scripts:/s" mcr.microsoft.com/playwright/python:v1.48.0-jammy sh -c "pip install -q playwright==1.48.0 && python /s/e2e_ui.py http://gateway"` |
| **Full real flow** (real LLM + OpenPencil) | `sh scripts/e2e_full_flow.sh` — PM creates a project, BA scenario, handoff, design, storage check |
| Wipe run data (keeps users) | `docker compose exec -T core-api python - --yes < scripts/reset_platform_data.py` then `docker compose restart core-api` |
| BA scenario only | `docker compose exec ba-api python -m demo._runner.run_demo demo/proj_warehouse --base-url http://gateway/ba --ui-base http://localhost:8080/ba --project PRJ-DEMO --login pm.hoa` |
| Local files → S3 | `docker compose exec core-api python -m platform_core.sync_storage` |
| Legacy data → project | `docker compose exec core-api python -m app.legacy` |
| Database backup | `docker compose exec -T postgres sh -c 'pg_dump -U $POSTGRES_USER -d $POSTGRES_DB -Fc -f /tmp/platform.dump'` then `docker compose cp postgres:/tmp/platform.dump backups/` |
| One module only | `docker compose -f compose.ba.yml up -d` or `docker compose -f compose.designer.yml up -d` |

The Designer case needs exactly one OpenPencil editor tab connected; two tabs fight over the bridge
("Browser reconnected"). `scripts/openpencil_bridge.py` keeps a headless tab when no browser is open.

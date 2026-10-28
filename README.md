# Unified Work AI Platform

One workspace for the **BA agent** (business analysis) and the **Designer agent** (interactive UI screens in HTML + Tailwind, exported to Figma `.fig`, PNG and HTML).
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
│   └── designer/         Designer agent (FastAPI + Google ADK; HTML screens, `.fig` I/O in `app/figio`)
├── apps/
│   ├── portal/           React: login, projects, journey page (embeds BA and Designer)
│   ├── ba-web/           BA UI (Vite, vanilla JS)
│   └── designer-web/     Designer UI (React)
├── scripts/              end-to-end checks, real-case runners, data reset
└── docs/reference/       integration standard and product deck
```

`CHANGES-FROM-SOURCE.md` lists every change made to the imported BA and Designer sources.

## Run (Docker only)

Requirements: Docker Desktop (local) or Docker Engine + Docker Compose v2 (VPS/server).

```bash
cp .env.example .env                              # LLM keys, DB password, JWT secret, S3 keys
docker compose up -d --build                      # http://localhost:8080
docker builder prune -af                          # optional: drop the build cache afterwards
```

| URL | What |
|---|---|
| http://localhost:8080/ | Portal: login, projects, journey |
| http://localhost:8080/projects/PRJ-AURORA | A project: Features, Assets, Data workspace, Members |
| http://localhost:8080/projects/&lt;id&gt;/f/&lt;feature&gt; | Journey of one feature (BA ─► Design in one screen) |
| http://localhost:8080/projects/&lt;id&gt;/designer | Designer agent of a project (also before any BA handoff) |

Accounts (`AUTH_MODE=mock`, password `demo123`): `pm.hoa` and `lead.dung`, both PM (BA + Designer). No project is
seeded; create one after login. `MOCK_SEED=full` adds the single-role accounts (`ba.an`, `ba.chi`, `designer.binh`)
and the sample projects `PRJ-AURORA`, `PRJ-DEMO` — the test containers use it, and `scripts/e2e_access.py` needs it.
The login page also shows "Đăng nhập với Keycloak", enabled once `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID` are set.

## Deploy on a VPS

### Option A — Full stack (Postgres managed by Docker Compose)

Identical to the local dev flow above. Docker Compose starts Postgres alongside the other
services. This is the simplest option and requires no additional setup.

```bash
cp .env.example .env          # fill in all keys and secrets
docker compose up -d --build
```

Set `PLATFORM_PUBLIC_URL` to your public domain or IP before building so that the platform
generates correct links.

### Option B — VPS with an existing PostgreSQL server

Use this when the VPS already runs PostgreSQL (managed instance, system package, etc.).

**1. Prepare the database.**

Connect to your PostgreSQL server (≥ 14) as a superuser and run:

```sql
CREATE DATABASE platform;
CREATE USER platform WITH PASSWORD 'strong-password-here';
GRANT ALL PRIVILEGES ON DATABASE platform TO platform;
```

The platform creates all schemas (`core`, `ba`, `designer`, `wiki`) and tables on first start.
No manual schema migration is needed.

**2. Configure `.env`.**

```env
PLATFORM_PUBLIC_URL=https://your-domain.com

POSTGRES_HOST=127.0.0.1        # host IP as seen from inside the containers
POSTGRES_PORT=5432
POSTGRES_DB=platform
POSTGRES_USER=platform
POSTGRES_PASSWORD=strong-password-here
POSTGRES_POOL_MIN=2
POSTGRES_POOL_MAX=15
```

If PostgreSQL listens on a private LAN address (e.g. a separate DB server), use that IP.
`POSTGRES_HOST=host.docker.internal` works on Linux with `--add-host=host.docker.internal:host-gateway`
added to each service in the compose file, or just use the real IP.

**3. Disable the managed Postgres container.**

Create a compose override file next to `docker-compose.yml`:

```yaml
# compose.external-pg.yml  —  use an external PostgreSQL, skip the managed container
services:
  postgres:
    profiles: [disabled]      # never started by `docker compose up`
  core-api:
    depends_on: {}
  ba-api:
    depends_on: {}
  designer-api:
    depends_on: {}
```

Start the platform:

```bash
docker compose -f docker-compose.yml -f compose.external-pg.yml up -d --build
```

Or edit `docker-compose.yml` directly: remove the `postgres` service block and every
`depends_on: postgres` entry from the other services.

**4. Storage.**

`STORAGE_BACKEND=local` (the default) writes files under `STORAGE_LOCAL_ROOT` on the VPS host.
The compose volume bind-mounts that path into the containers.

```env
STORAGE_BACKEND=local
STORAGE_LOCAL_ROOT=/data/platform-storage    # a directory on the VPS host
```

For object storage, switch to `s3` and fill the `S3_*` variables — any S3-compatible endpoint
works (AWS S3, MinIO, Ceph, Cloudflare R2):

```env
STORAGE_BACKEND=s3
S3_ENDPOINT_URL=https://s3.amazonaws.com
S3_REGION=ap-southeast-1
S3_BUCKET=my-platform-bucket
S3_ACCESS_KEY_ID=AKIA...
S3_SECRET_ACCESS_KEY=...
```

**5. Reverse proxy (nginx on the VPS).**

The platform gateway listens on `PLATFORM_GATEWAY_PORT` (default `8080`). Put nginx in front
for TLS and the large `.fig` upload limit:

```nginx
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    client_max_body_size 110m;   # .fig upload limit (infra/gateway/nginx.conf default)

    location / {
        proxy_pass         http://127.0.0.1:8080;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;    # designer agent and BA sessions can take time
        proxy_buffering    off;     # SSE / streaming designer events
    }
}
```

Use Certbot for the TLS certificate: `certbot --nginx -d your-domain.com`.

**6. Run as a systemd service (optional).**

```ini
# /etc/systemd/system/platform.service
[Unit]
Description=BA × Designer Platform
After=docker.service network-online.target
Requires=docker.service

[Service]
WorkingDirectory=/opt/platform
ExecStart=/usr/bin/docker compose up
ExecStop=/usr/bin/docker compose down
Restart=on-failure
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable --now platform
```

## Configuration

Everything is in `.env` (see `.env.example`, grouped by section):

| Group | Keys |
|---|---|
| Database | `POSTGRES_*` — one database, one schema per service |
| Auth | `AUTH_MODE=mock` (Keycloak later), `AUTH_JWT_SECRET`, `AUTH_JWT_TTL_MINUTES` |
| LLM | `LLM_*` shared; `BA_LLM_MODEL`, `WIKI_LLM_MODEL`, `DESIGNER_LLM_*` override per agent |
| Storage | `STORAGE_BACKEND=s3\|local`, `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `STORAGE_LOCAL_ROOT` |
| Logs | `LOG_DIR`, `LOG_PROJECT_TO_STORAGE`, `LOG_PROJECT_FLUSH_SECONDS`, `LOG_PROJECT_RETENTION_DAYS` |

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

**Storage.** Postgres holds metadata and small JSON; file content lives in S3 (the source of truth;
`STORAGE_LOCAL_ROOT` is a write-through cache), one tree per project and module:

```text
projects/<project>/
  ba/packages/…                                      BA packages + BPMN (versioned Assets)
  designer/sessions/<session>/screens/<screen>/v0001.html   screen HTML, one immutable object per version
  designer/assets/<asset>                            images users upload (chat, BA handoff)
  designer/design-systems/<id>/source.fig            imported Figma file
  designer/outputs/<run>/…                           published designs (Assets)
  wiki/blobs/…
  logs/<service>/<date>/*.jsonl                      per-project logs (LOG_PROJECT_RETENTION_DAYS)
shared/…                                             the same tree without a project (auth off, tools)
```

Deleting a session, screen or design system deletes its files; published Assets stay.

**Assets.** Every BA export publishes a versioned BA package and its BPMN. When a design waits
for the final review, its UI specification and the design files are published as "Chờ duyệt"; the approval
marks them "Đã duyệt". Designs link to the BA package version they came from, so a newer BA version marks them
"cần xem lại".

**Designer.** The agent writes each screen as HTML + Tailwind (Alpine.js for interaction, lucide icons), renders
and checks it in headless Chromium inside `designer-api` (DOM lint + axe-core + screenshot), and refines it with
tools until it passes. The studio (`/designer/`) keeps chat, review and BA panels; "Trang thiết kế" opens the
design page (`/designer/canvas.html`) in a new tab. The design page has two view modes:

- **Single-screen mode** — clickable prototype, viewport picker, state switcher, element picking (reported to
  the chat via BroadcastChannel), inline code editor with version history, and the Export menu.
- **Multi-frame overview mode** — all screen × state combinations shown as side-by-side frames (Figma-style
  overview); each frame auto-sizes to its content height. Canvas zoom (Ctrl+wheel, or ±  buttons) and a
  floating zoom bar. Click any frame to jump to single-screen mode for that screen and state.

Design systems are imported from a Figma `.fig` (Settings → Design system); exports are `.fig` (opens in Figma;
one page with a row per screen, or a page per screen), PNG per screen/state and an offline HTML zip.

**Logs.** Local: `logs/<service>/<service>.log` (JSON lines, daily rotation, 14 days), each request with `user`,
`project_id`, `request_id`. Per project: `projects/<project_id>/logs/<service>/<date>/*.jsonl` in storage.

## Dependencies

Python images install with `PIP_CONSTRAINT` pointing at `services/<svc>/constraints.txt`: the exact versions of a
known-good build, so a rebuild never pulls a newer library by surprise (litellm once started needing `mcp` 2.x and
every chat turn failed). Each test suite has `tests/test_dependencies.py` (`pip check`, installed = pinned, and for
BA/Designer the litellm tool-call imports).

To upgrade on purpose: edit the version range in `pyproject.toml` / `requirements.txt`, delete the line from
`constraints.txt`, rebuild, run the tests, then refresh the pins from the new image:

```bash
docker run --rm --entrypoint pip platform-designer-api freeze --exclude-editable | grep -v " @ "   # → constraints.txt
```

## Commands

| Task | Command |
|---|---|
| Tests | `docker compose --profile test run --rm core-test` (also `ba-test`, `designer-test`, `wiki-test`) |
| Access checks | `docker run --rm --network platform_default -v "$PWD/scripts:/s:ro" python:3.12-slim python /s/e2e_access.py http://gateway` |
| Assets flow on real storage | `sh scripts/e2e_assets.sh` |
| UI walk-through (Playwright) | `docker run --rm --network platform_default -v "$PWD/scripts:/s" mcr.microsoft.com/playwright/python:v1.48.0-jammy sh -c "pip install -q playwright==1.48.0 && python /s/e2e_ui.py http://gateway"` |
| **Full real flow** (real LLM) | `sh scripts/e2e_full_flow.sh` — PM creates a project, BA scenario, handoff, design, storage check |
| Wipe run data (keeps users) | `docker compose exec -T core-api python - --yes < scripts/reset_platform_data.py` then `docker compose restart core-api` |
| BA scenario only | `docker compose exec ba-api python -m demo._runner.run_demo demo/proj_warehouse --base-url http://gateway/ba --ui-base http://localhost:8080/ba --project PRJ-DEMO --login pm.hoa` |
| Local files → S3 | `docker compose exec core-api python -m platform_core.sync_storage` |
| Legacy data → project | `docker compose exec core-api python -m app.legacy` |
| Database backup | `docker compose exec -T postgres sh -c 'pg_dump -U $POSTGRES_USER -d $POSTGRES_DB -Fc -f /tmp/platform.dump'` then `docker compose cp postgres:/tmp/platform.dump backups/` |
| One module only | `docker compose -f compose.ba.yml up -d` or `docker compose -f compose.designer.yml up -d` |

# BA × Designer Platform

One platform for the BA agent and the Designer agent. The target architecture is described in `../platform-overview.html`, and the refactor plan is in `../refactor-plan/`.

```
platform/
├── .env.example        the only configuration file (copy to .env)
├── docker-compose.yml  whole platform
├── compose.ba.yml      BA standalone        compose.designer.yml  Designer standalone
├── infra/              postgres (one DB, schemas core/ba/designer/wiki), gateway (nginx)
├── packages/           platform_core (settings, db, storage), wiki (wiki-mvp)
├── services/           core (users, projects, login), ba (FastAPI + ADK), designer (FastAPI + ADK + OpenPencil MCP)
├── apps/               portal, ba-web, designer-web
└── scripts/            bootstrap import, e2e_access.py, e2e_ui.py
```

## Run (Docker only)

```bash
cp .env.example .env        # fill LLM keys, passwords
make openpencil             # default OpenPencil instance (builds openpencil:local)
make up                     # http://localhost:8080
```

| URL | What |
|---|---|
| http://localhost:8080/ | Portal: login, projects by user |
| http://localhost:8080/ba/?project=… | BA UI for one project |
| http://localhost:8080/designer/?project=… | Designer UI for one project |
| http://localhost:1420 | OpenPencil editor (default instance) |

Demo accounts (`AUTH_MODE=mock`, password `demo123`): `ba.an`, `ba.chi` (BA), `designer.binh` (Designer), `lead.dung` (BA + Designer, project admin). Projects: `PRJ-AURORA`, `PRJ-DEMO`.

Data created before Sprint 3 (no project): `docker compose exec core-api python -m app.legacy` moves it to `PRJ-LEGACY` and adds the `project_id` foreign keys.

## Access rules

- Keycloak later; today `core-api` issues a JWT in an HttpOnly cookie (same origin via the gateway).
- Project members read everything in the project, including chat. Writing in BA needs role BA, in Designer role DESIGNER (ADMIN counts as both). Non-members get 403.
- BA → Designer handoffs authenticate with `X-Agent-Secret` (`DESIGNER_SHARED_SECRET`).

## OpenPencil

One default instance (`OPENPENCIL_DEFAULT_MCP_URL`). A designer's own instance is a row in `designer.openpencil_instances` (`PUT /designer/api/v1/openpencil-instances/{user_id}?project_id=…`, project ADMIN only); runs then use it automatically.

Run one module only: `make up-ba` or `make up-designer` (each includes postgres, gateway, core and portal). Run the tests: `make test`; access checks: `make e2e`.

Every edit to the imported sources is listed in `CHANGES-FROM-SOURCE.md`.

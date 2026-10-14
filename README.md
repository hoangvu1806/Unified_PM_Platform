# BA × Designer Platform

One platform for the BA agent and the Designer agent. The target architecture is described in `../platform-overview.html`, and the refactor plan is in `../refactor-plan/`.

```
platform/
├── .env.example        the only configuration file (copy to .env)
├── docker-compose.yml  whole platform
├── compose.ba.yml      BA standalone        compose.designer.yml  Designer standalone
├── infra/              postgres (one DB, schemas core/ba/designer/wiki), gateway (nginx)
├── packages/           platform_core (settings, db, storage), wiki (wiki-mvp)
├── services/           ba (FastAPI + ADK), designer (FastAPI + ADK + OpenPencil MCP)
└── apps/               ba-web, designer-web
```

## Run (Docker only)

```bash
cp .env.example .env        # fill LLM keys, passwords
make openpencil             # default OpenPencil instance (builds openpencil:local)
make up                     # http://localhost:8080
```

| URL | What |
|---|---|
| http://localhost:8080/ba/ | BA UI |
| http://localhost:8080/designer/ | Designer UI |
| http://localhost:1420 | OpenPencil editor (default instance) |

Run one module only: `make up-ba` or `make up-designer`. Run the tests: `make test`.

Every edit to the imported sources is listed in `CHANGES-FROM-SOURCE.md`.

# UAIP Business Analysis Agent

**Branch `one-graph`.** One control plane: one ADK graph, one runner, one V1 chat + features API, one operator UI.

Team leave / how this maps to Wiki MVP and papers: in the WikiFactoryAI workspace see **[HANDOFF.md](../../HANDOFF.md)** and **UAPDF-PIPE-001** (`Documents/Bao_cao_pipeline_BA_VA_Wiki.pdf`). Designer Agent / Penpot is a **separate report** (Đỗ Hoàng Vũ), not this repo’s runtime.

The previous `main` / `workflow-agent` / `graph-agent` lines are folded into this tree. Runtime map: [DESIGN.md](DESIGN.md). Local ops: [docs/LOCALHOST-BA.md](docs/LOCALHOST-BA.md). Demo packs: [demo/README.md](demo/README.md).

## Run (Docker)

Supported local demo. From this directory:

```bash
cp .env.example .env   # set LLM_GATE_API_KEY
# WIKI_MVP_ROOT=/absolute/path/to/WikiFactoryAI/mvp
make docker-up         # API :8000  UI :5173  Postgres :5432
make demo DEMO=proj_july4
# make demo-all
make docker-down       # stop containers; keep named volumes
```

`docker compose up -d --build` is equivalent. LiteLLM is optional
(`docker compose --profile litellm`); default API traffic uses the company
gate `https://llm-gate.imespro.ai/v1`.

UI: http://127.0.0.1:5173  
API docs: http://127.0.0.1:8000/docs  
Health: http://127.0.0.1:8000/api/health (`llm_proxy_ready` may be false; demo still 200 if Postgres + ADK are up)

**Coder VPS:** Frappe already binds host `:8000`. Use the overlay so API is **8010**:

```bash
docker compose -f docker-compose.yml -f docker-compose.coder.yml up -d --build
```

Compose 2.40 treats `ports: !reset` + a list as **no published ports**. The overlay must use `ports: !override` (commit `f422fe7`). Workspace user is `ubuntu`; persist apps under `/home/ubuntu/data/home/apps/` (symlink `~/apps`). Set `WIKI_MVP_ROOT` to the wiki-mvp checkout — not a stale `/home/coder/...` path.

**Project scope:** each feature gets `project_id = PRJ-` + first 12 hex of `sha256(session_id)` (no shared `PRJ-MES-01` default). Wiki list/upload/approve require that id; company namespace stays org-wide. `DELETE /api/features/{id}` works for any status including EXPORTED.

Ad-hoc `uvicorn` + `/tmp/ba-demo-*.db` is fallback only. Pytest stays
SQLite-isolated: `pytest tests/ -q` (no Docker).

## Control system (four capabilities, one plane)

| Capability | Role under this control plane |
| --- | --- |
| **BA** | Writes section artifacts on the feature session (FD → BR → WF → UC) |
| **VA** | Validation **step** on the same session (`[VALIDATE]` / `action=validate`) — in-process, not HTTP A2A |
| **Wiki** | **Document service** — search/fetch approved Wiki Knowledge MVP pages |
| **Designer** | **Handoff port** — exported Common Envelope; no live Designer runtime |

- **Identity:** `session_id` = `feature_id` = envelope `correlation_id`
- **Status:** `feature_status` is the only control state: `DRAFT` → `IN_PROGRESS` → `PENDING_VALIDATION` → `VALIDATED` → `EXPORTED` (or `VALIDATION_FAILED`)
- **API:** `POST /api/v1/chat/{session_id}/message|/stream` and `/api/features` (CRUD, history, documents, export)
- **UI:** Document Manager + chat. Validate, Export, and wiki evidence hang off that flow — not new apps
- **Removed:** Agyn. Do not add another orchestrator.

## Layout

```
agents/ba_agent/            # unified Workflow (router, lock, stub)
agents/sub_graph/           # NEW_FEATURE: FD, BR, WF, UC + in-process VA
managers/control/           # status machine, Common Envelope, BPMN, export
managers/service/           # V1 chat + feature CRUD + documents
managers/runner_context.py  # single ADK Runner
factory_wiki/               # Wiki MVP adapter (approved documents only)
frontend/                   # Vite operator UI
demo/                       # closed-cycle packs
docs/ba-graph-agent/        # Aug 2026 product vision (not current I/O)
```

## Status (runtime, not the product spec)

**Live on `NEW_FEATURE`:** Feature Definition → Business Rules → Workflow → Use Cases, sequentially locked. One active User Story. Validate is an **in-process** subgraph on the same runner. BPMN is a `bpmn:collaboration` (one lane per actor) with ELK layout; DIY DI if Node is missing.

**Stubbed:** `FEATURE_ENHANCEMENT`, `BUG_FIX_LOG`, `PROCESS_OPTIMIZATION` (and any section not in Tier-1) answer through `ba_not_ready`.

**Not built:** UI Touchpoints as a Designer-ready artifact, login/SSO, other ticket-type subgraphs, live Designer Agent / Penpot, Knowledge Graph.

**Wiki documents:** Validation Agent searches/fetches **approved** pages from Wiki Knowledge MVP (same 3-table SQLite store). Not a Knowledge Graph. Agents never approve wiki pages. Set `WIKI_MVP_ROOT` (or `WIKI_DATA_DIR`) so BA and `mvp/` share one data directory. UI “Clear database” wipes wiki tables only — not Postgres.

**Export:** After Validate **PASSED** or **PASSED WITH WARNINGS**, Export downloads a Common Envelope BA Package and marks the session `EXPORTED`. Chat send stays frozen after the first export. **Validate** and **Export** can run again so wiki updates refresh the package.

**Removed:** Agyn. Do not run Agyn as the BA runtime.

`docs/ba-graph-agent/` still describes an 8-section / A2A vision. This README is what the code does today.

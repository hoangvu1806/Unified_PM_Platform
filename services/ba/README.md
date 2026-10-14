# BA service (ba-api)

Business Analysis agent of the platform: one ADK graph, one runner, the V1 chat API and the features API. Runtime map: [DESIGN.md](DESIGN.md). Demo packs: [demo/README.md](demo/README.md).

Run it as part of the platform (see `../../README.md`): from `platform/`, `docker compose up -d`. The UI is served at `/ba/` and the API at `/ba/api/` behind the gateway (http://localhost:8080). Run BA alone with `docker compose -f compose.ba.yml up -d`.

## Control system

| Capability | Role |
| --- | --- |
| **BA** | Writes section artifacts on the feature session (FD → BR → WF → UC) |
| **VA** | Validation step on the same session (`[VALIDATE]` / `action=validate`), in-process |
| **Wiki** | Document service (`packages/wiki`): search/fetch approved pages, company + project scope |
| **Designer** | Handoff: the exported Common Envelope goes to designer-api (`X-Agent-Secret`), the Designer session lands in the same project |

- **Identity:** `session_id` = `feature_id` = envelope `correlation_id`. A feature belongs to one platform project (`ba_packages.project_id`).
- **Status:** `DRAFT` → `IN_PROGRESS` → `PENDING_VALIDATION` → `VALIDATED` → `EXPORTED` (or `VALIDATION_FAILED`).
- **API:** `POST /api/v1/chat/{session_id}/message|/stream`, `/api/features` (CRUD, history, documents, export, designer-handoff), `/api/wiki`, `/api/va`.
- **Access:** login required on every route; members of the project read, role BA (or ADMIN) writes.
- **Assets:** every export stores the envelope in platform storage and registers a versioned `ba_package` artifact.

## Layout

```
agents/ba_agent/            unified Workflow (router, lock, stub)
agents/sub_graph/           NEW_FEATURE: FD, BR, WF, UC + in-process VA
callbacks/                  history filter, context injection
config/                     settings (platform .env), LLM endpoint, litellm-config.yaml
managers/control/           status machine, Common Envelope, BPMN, export
managers/service/           V1 chat, features, wiki, VA routes; access control; Assets publishing
managers/runner_context.py  single ADK Runner (Postgres schema `ba`)
factory_wiki/               adapter to packages/wiki (approved documents only)
tools/bpmn_elk/             Node helper for BPMN layout
demo/                       closed-cycle scenario packs and runner
tests/                      pytest (docker compose --profile test run --rm ba-test)
```

## Status

**Live on `NEW_FEATURE`:** Feature Definition → Business Rules → Workflow → Use Cases, sequentially locked; Validate in-process; BPMN collaboration with ELK layout.

**Stubbed:** `FEATURE_ENHANCEMENT`, `BUG_FIX_LOG`, `PROCESS_OPTIMIZATION` answer through `ba_not_ready`.

**Export:** after Validate PASSED (or PASSED WITH WARNINGS) the package can be exported and handed to Designer; chat freezes after the first export, Validate/Export can run again.

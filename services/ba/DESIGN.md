# BA Agent — Unified Graph

This repo had three git lines. They are now one graph **and one control plane**.

| Branch | What it contributed | What we kept |
| --- | --- | --- |
| `main` | Scaffold, FastAPI, config | Server, settings, package layout |
| `features/workflow-agent` | Sequential Feature Definition pipeline, frontend, persistence | Frontend, artifact merge, DB package, callbacks |
| `feature/graph-agent` | ADK Workflow + Feature Definition subgraph + V1 chat | **Canonical runtime**: one Workflow graph |

## Decision

One ADK `Workflow`, one `Runner`, one feature/session identity, one `feature_status` machine. Ticket type and active section are **session state**, not extra processes. Runtime is FastAPI + Postgres + Google ADK + the company LLM gate (LiteLLM optional). Agyn is **removed** — do not re-add it or invent a fifth orchestrator. Handoff: WikiFactoryAI `HANDOFF.md` and UAPDF-PIPE-001.

Wiki, VA, and Designer are **capabilities** on this plane — not separately controlled products.

```
User turn  (Document Manager / chat)
    │
    ▼
ba_router                         session_id = feature_id = correlation_id
    ├── NEW_FEATURE + feature_definition ──► FD subgraph
    │     extractor ∥ OQ/ASM → flags → join → discussion
    ├── NEW_FEATURE + business_rules ─────► BR subgraph
    │     extractor → flags → discussion
    ├── NEW_FEATURE + workflow ───────────► WF subgraph
    │     extractor → flags → discussion
    ├── NEW_FEATURE + use_cases ──────────► UC subgraph
    │     extractor → flags → discussion
    ├── [VALIDATE] / _validate_action ────► VA subgraph (in-process step)
    │     schema → snapshot → cross-section → Wiki MVP approved docs
    ├── prior section incomplete ─────────► ba_section_locked
    └── other ticket type / unknown section ► ba_not_ready

feature_status: DRAFT → IN_PROGRESS → PENDING_VALIDATION
              → VALIDATED | VALIDATION_FAILED → EXPORTED (Designer envelope)
```

Sequential lock: FD → BR → WF → UC (`agents/ba_agent/section_gate.py`). A later section routes to `locked` until **all required blocker flags are present** and clear.

## Control plane

| Piece | Where |
| --- | --- |
| Session / feature identity | `session_id` on `/api/features` and V1 chat; envelope `correlation_id` / `feature_id` |
| Status lifecycle | `feature_status` in ADK session (+ `ba_packages.feature_status`) |
| API surface | V1 chat + `/api/features` including `/export` and `/documents` |
| Operator UI | Existing Document Manager + `chat.html` (Validate + Export) |
| Wiki | `factory_wiki` adapter → Wiki MVP 3-table SQLite + permission helpers (approved only; not `WikiService` ingest) |
| VA | In-process subgraph; report also stored as Common Envelope |
| Designer | Export envelope `handoff.to = designer-agent` — no live Designer process |

Aligned with `Documents/Tieu_chuan_tich_hop_BA_Designer_Validation_Agent_v1.md` (Common Envelope, session, gates). We did **not** add Design Session Manager / Artifact Registry / Integration Gateway as separate products.

## What is implemented vs not

| Area | Runtime today |
| --- | --- |
| Ticket `NEW_FEATURE` | Live: FD, BR, WF, UC + in-process Validate |
| Other ticket types | Stub (`ba_not_ready`). Enum is accepted; graph is not. |
| OQ / ASM | Detector node on **FD only**. BR/WF/UC discussion can *display* existing items. Product spec wants per-turn detection on every Tier-1 section — not implemented (P1). Critical `open` OQs still gate `can_proceed_to_validation`. User answers resolve via `resolved_questions` or `OQ-00N: …` in chat (`apply_oq_resolutions`); we do not waive unanswered critical OQs. |
| Validate | Same runner, nested workflow (**not** HTTP A2A). Schema / snapshot / cross-section checks plus V-WIKI-01..05. Wiki pull reads **approved Wiki MVP documents** (adapter). VA must not mutate artifacts. PASS/FAIL is Python; LLM only explains. |
| BPMN | Live: `managers/control/bpmn.py` emits `bpmn:collaboration` (one lane per FD actor); Node `bpmn-elk-layout` places DI; DIY fallback if Node is missing. |
| UI Touchpoints | Not a Designer-ready artifact. Export may include a hook; Penpot is out of this repo. |
| Export | When `feature_status` is `VALIDATED` (or `EXPORTED` with a current passed VA). First export freezes chat; Validate/Export can still refresh against wiki. Envelope `handoff.to = designer-agent`. |
| Login / identity | Platform login (core-api, mock JWT now, Keycloak later). Routes check project membership/role; ADK sessions still use `USER_ID = "ba-user"` internally. |
| Knowledge Graph / Agyn | Out of scope. Wiki is documents, not a graph. Designer is a separate platform service reached by handoff. |

This DESIGN.md is the runtime map. Validate is in-process, not HTTP A2A.

## State contract

| Key | Role |
| --- | --- |
| `session_id` / `feature_id` | One control key |
| `ticket_type` | `NEW_FEATURE` \| `FEATURE_ENHANCEMENT` \| `BUG_FIX_LOG` \| `PROCESS_OPTIMIZATION` |
| `active_section` | `feature_definition` \| `business_rules` \| `workflow` \| `use_cases` |
| `artifacts` | Section payloads |
| `flags` | Completion flags |
| `open_questions` / `assumptions` | Tier-2 detections (written on FD today) |
| `sections_status` / `feature_status` | Gate + **control** lifecycle |

## API

- `POST /api/v1/chat/{session_id}/message` — sync JSON
- `POST /api/v1/chat/{session_id}/stream` — SSE
- `/api/features` — feature CRUD + history
- `GET /api/features/{session_id}/documents` — approved wiki pages for this feature's `project_id`
- `POST /api/features/{session_id}/export` — Common Envelope; only when `VALIDATED`
- Uninitialized runner → **503**. Empty `session_id` / `user_message` → **400**. Exported session mutations → **409**.

`get_runner(ticket_type)` still validates the enum. Every valid type shares the same runner.

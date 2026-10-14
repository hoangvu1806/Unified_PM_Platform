# Demo packs — closed-cycle BA automation

Folder-driven demos under `demo/proj_*/`. Each pack has:

- `feature.json` — create feature title/description
- `wiki/project/*.pdf` (+ optional `wiki/company/`) — Document Manager uploads
- `demo/_shared/wiki/company/*.pdf` — shared Nimbus Factory ground rules
- `chat/*.jsonl` — BA section turns (FD → BR → WF → UC)
- `expect.json` — closed-cycle assertions

Last closed-cycle run: **15/09/2026** on Coder Docker (API :8010, UI :5173). Six packs: five `EXPORTED`, Aurora `VALIDATED` (`skip_export`). Write-up: UAPDF-PIPE-001.

## Prerequisites

1. API healthy (`make docker-up`, or Coder overlay on :8010) with `LLM_GATE_API_KEY` set. Chat needs the gate; wiki approve does not.
2. Python venv with BA deps (`.venv`) for the runner on the machine that calls the API.
3. Wiki MVP checkout for PDF build (`WikiFactoryAI/mvp` next to BA, or `WIKI_MVP_ROOT`).

## Commands

```bash
# Rebuild PDFs from wiki/**/src/*.md
make demo-pdfs

# One pack
make demo DEMO=proj_july4

# All packs including aurora (stop on first failure)
make demo-all

# Continue after failures
.venv/bin/python -m demo._runner.run_demo --all --continue --base-url http://127.0.0.1:8000
```

Against VPS API:

```bash
.venv/bin/python -m demo._runner.run_demo --all --continue \
  --base-url https://8010--main--aquamarine-leopon-37--vupham.coder.imespro.ai \
  --ui-base https://5173--main--aquamarine-leopon-37--vupham.coder.imespro.ai
```

## Packs

| Folder | Theme |
|--------|--------|
| `proj_july4` | July 4 flag ops / XOR weather |
| `proj_hestia` | Cooking assistant / food safety |
| `proj_warehouse` | Material request pick-pack |
| `proj_spend` | Spend approval thresholds |
| `proj_onboarding` | HR onboarding |
| `proj_aurora` | Multi-plant deviation CAPA + recall (large; often `skip_export`) |

## Add pack #6

1. Copy any `proj_*` folder.
2. Edit `feature.json`, `wiki/**/src/*.md`, `chat/*.jsonl`, `expect.json`.
3. `make demo-pdfs` then `make demo DEMO=proj_yourname`.

Set `"skip_export": true` in `expect.json` to stop after Validate (chat stays unlocked for manual Export).

## Notes

- Runner uploads **PDFs** with `sort_mode=heuristic`, then the runner (not the agent) approves drafts.
- Chat needs a live LLM; agents never call wiki approve/ingest/propose.
- Export freezes further BA chat (`package_exported`); that is expected success.
- If `--all` fails immediately on glossary IDs already approved as `namespace=project` / `PRJ-MES-01`, `POST /api/wiki/clear` with confirm `CLEAR`, delete the failed features, and re-run. That clears wiki tables only.
- Coder: `docker compose -f docker-compose.yml -f docker-compose.coder.yml up -d --build` (API 8010). Pass `--base-url` / `--ui-base` to the public 8010/5173 URLs.

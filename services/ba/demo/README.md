# Demo packs — closed-cycle BA automation

Folder-driven demos under `demo/proj_*/`. Each pack has:

- `feature.json` — create feature title/description
- `wiki/project/*.pdf` (+ optional `wiki/company/`) — Document Manager uploads
- `demo/_shared/wiki/company/*.pdf` — shared Nimbus Factory ground rules
- `chat/*.jsonl` — BA section turns (FD → BR → WF → UC)
- `expect.json` — closed-cycle assertions

## Run on the platform

Inside the running `ba-api` container, through the gateway (login + project):

```bash
docker compose exec ba-api python -m demo._runner.run_demo demo/proj_warehouse \
  --base-url http://gateway/ba --ui-base http://localhost:8080/ba \
  --project PRJ-DEMO --login lead.dung
```

`--login` needs role BA in the project and ADMIN to seed the company wiki. `--all --continue` runs every pack.

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
3. Rebuild PDFs (`python -m demo._runner.md_to_pdf`) then run the pack as above.

Set `"skip_export": true` in `expect.json` to stop after Validate (chat stays unlocked for manual Export).

## Notes

- Runner uploads **PDFs** with `sort_mode=heuristic`, then the runner (not the agent) approves drafts.
- Chat needs a live LLM; agents never call wiki approve/ingest/propose.
- Export freezes further BA chat (`package_exported`); that is expected success.
- If `--all` fails immediately on glossary IDs already approved as `namespace=project` / `PRJ-MES-01`, `POST /api/wiki/clear` with confirm `CLEAR`, delete the failed features, and re-run. That clears wiki tables only.
- Coder: `docker compose -f docker-compose.yml -f docker-compose.coder.yml up -d --build` (API 8010). Pass `--base-url` / `--ui-base` to the public 8010/5173 URLs.

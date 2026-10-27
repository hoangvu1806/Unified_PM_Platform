# Designer service (designer-api)

UI design agent of the platform, being rebuilt: the OpenPencil/JSX pipeline is removed
and the agent will write each screen as **HTML + Tailwind** (Alpine.js for interaction).
UI at `/designer/`, API at `/designer/api/v1/` behind the gateway; data in Postgres schema
`designer`, files in platform storage (S3). Everything runs in this one container.

## Today

- Sessions, runs, events (SSE), reviews, BA handoffs and project access work as before.
- Accepted runs stop with `DESIGNER_REBUILDING` (retryable) until the new agent lands.
- `app/figio/`: pure-Python reader/writer for Figma `.fig` files (Kiwi codec, zip container,
  `FigBuilder`). Reads real Figma exports byte-exactly; files it writes open in Figma.

## Planned

```text
message / BA handoff
  -> planner: brief + UiSpec (screens, regions, data)   -> human spec review
  -> screen builder: write_screen / edit_screen / check_screen / finish_screen
       check = headless Chromium render + DOM lint + screenshot
  -> human final review
  -> Assets: HTML bundle, PNG per screen/state, .fig (DOM -> Figma nodes via figio)
design systems: imported from a Figma .fig (or file link) -> theme tokens + HTML snippets
```

## Test

```powershell
docker compose --profile test run --rm designer-test
# figio only, on the host:
.venv\Scripts\python -m pytest -q --noconftest services/designer/tests/test_figio.py
```

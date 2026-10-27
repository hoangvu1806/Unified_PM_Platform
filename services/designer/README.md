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
- `app/render/`: a screen is an HTML body fragment. `build_document` wraps it with theme tokens
  (Tailwind v4 `@theme`), the vendored Tailwind browser build, Alpine.js, `runtime.js` and a CSP;
  `Renderer` (Playwright, one headless Chromium per process) screenshots it, switches
  `data-state`, returns the compiled CSS and runs `lint.js` (page overflow, clipped text,
  child overflow, empty regions, broken images, tap targets, type scale + axe-core contrast
  and names). Vendor files and versions: `app/render/vendor/README.md`.
- Screens are stored per session (`screens`, every save in `screen_versions`) and served by
  `app/api/screens.py`: list/read/save/delete, versions, `/document` (iframe `srcdoc`) and
  `/screenshot`.

Screen conventions for the agent and the design page:

| Markup | Meaning |
|---|---|
| `data-state="error"` / `data-state-hide="error"` | Shown only / hidden in state `error` (screenshots per state) |
| `data-goto="screen-id"` | Prototype link to another screen of the session |
| Alpine (`x-data`, `@click`, `x-show`, …) | Real interaction inside a screen |
| `data-d` | Element id added by the runtime at render time (never stored) |

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
# figio + render on the host (uses the Chromium Playwright already installed there):
.venv\Scripts\python -m pytest -q --noconftest services/designer/tests/test_figio.py services/designer/tests/test_render.py
```

# Designer service (designer-api)

UI design agent of the platform: it writes each screen as **HTML + Tailwind** (Alpine.js for
interaction, lucide icons) and checks it in headless Chromium.
UI at `/designer/`, API at `/designer/api/v1/` behind the gateway; data in Postgres schema
`designer`, files in platform storage (S3). Everything runs in this one container.

## Today

- Sessions, runs, events (SSE), reviews, BA handoffs and project access work as before.
- The agent (`app/workflow/designer.py`): router → UI spec with art direction (human review) → per screen
  one draft call + at most `DESIGNER_REVIEW_ROUNDS` (2) review calls with the screenshot, DOM lint and the
  spec's required texts (`must_show`); a review replies `OK`, SEARCH/REPLACE blocks or a rework, and an edit
  is kept only if it does not make the checks worse. The first screen sets the shell, the others are built in
  parallel (`DESIGNER_PARALLEL_SCREENS`). Chat edits go straight to a review call with the user's instruction.
- Context per call is small and specific: the art direction (palette, fonts, radius, do/don't) applied as the
  session theme, the design system's relevant components, the screen's spec, business rules, photos found by
  `find_images` (Unsplash with a key, else Openverse + Wikimedia), and design knowledge retrieved for this
  product and screen from `knowledge/` (vendored skills: ui-ux-pro-max data + Anthropic's frontend-design;
  see `knowledge/README.md`). Nothing domain- or platform-specific is hard-coded in the prompts.
- `app/designsystem/`: `.fig` → tokens (Tailwind `@theme`) + component HTML snippets; gallery.
- `app/export/`: DOM → Figma nodes (`extract.js` + `figma.py`), bundle zip (HTML prototype, PNG, `design.fig`),
  published to Assets as `designer_output`.
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

## Flow

```text
message / BA handoff
  -> router (intent, brief, design_query)
  -> spec: art direction + screens (sections, states, must_show, rules, imagery, ux_query)
       knowledge: product profile (style, palette, fonts, anti-patterns) + frontend-design skill
  -> human spec review
  -> per screen: draft -> render + lint + must_show check -> review (OK / edits), ≤ 2 rounds
       knowledge: UX guidelines for the screen and platform, pre-delivery checklist
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

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
  published to Assets as `designer_output`. In the `.fig` each screen is a row (the screen, then its states);
  `/export?layout=rows` puts every row on one page, `layout=pages` gives each screen its own page (chosen in
  the design page's "Xuất" menu).
- `app/figio/`: pure-Python reader/writer for Figma `.fig` files (Kiwi codec, zip container,
  `FigBuilder`). Reads real Figma exports byte-exactly; files it writes open in Figma.
- `app/render/`: a screen is an HTML body fragment. `build_document` wraps it with theme tokens
  (Tailwind v4 `@theme`), the vendored Tailwind browser build, Alpine.js, `runtime.js` and a CSP;
  `Renderer` (Playwright, one headless Chromium per process) screenshots it, switches
  `data-state`, returns the compiled CSS and runs `lint.js` (page overflow, clipped text,
  child overflow, empty regions, broken images, tap targets, type scale + axe-core contrast
  and names). Vendor files and versions: `app/render/vendor/README.md`.
- `app/render/runtime.js`: injected into every screen document. Assigns `data-d` element ids,
  installs CSS rules for `data-state` / `data-state-hide` visibility, handles `data-goto` prototype
  navigation, replaces `<i data-lucide>` with SVGs, and manages selection mode (hover outline + click
  report). On `designer:state` messages, sets `data-active-state` on `<html>` then posts a `resize`
  message with `scrollHeight` after 60 ms so the caller can read the accurate post-render height.
- Screens are stored per session (`screens`, every save in `screen_versions`) and served by
  `app/api/screens.py`: list/read/save/delete, versions, `/document` (iframe `srcdoc`) and
  `/screenshot`.
- Storage (`app/storage/`): Postgres keeps metadata only; every file key comes from `layout.py`
  (`projects/<project>/designer/sessions/<session>/screens/<screen>/v0001.html`, `assets/<id>`,
  `design-systems/<id>/source.fig`, `outputs/<run>/…`). Each screen save writes a new immutable object
  (sha256 + size in the row). Uploaded images are per project (`storage/assets.py`; screens reference
  `asset:<id>`, inlined when rendered). On start the store moves HTML still stored inline by older versions
  to storage, then drops those columns. Deleting a session/screen/design system deletes its files.

## Design page (`/designer/canvas.html`)

The design page (`apps/designer-web/src/canvas/`) has two view modes toggled by the button in
the left rail:

**Single-screen mode** (default)
- Clickable prototype rendered in an `<iframe>` at selected viewport width
- Viewport picker and state switcher (custom `CanvasPicker` dropdown, styled with design tokens)
- Element picking: hover → outline; click → selected element sent to the chat via `BroadcastChannel`
- Inline code editor with version history; save triggers a new `screen_version`
- "Xuất" (Export) menu: `.fig`, PNG per screen/state, offline HTML zip; layout choice (rows/pages)

**Multi-frame overview mode**
- All screen × state combinations rendered as side-by-side frames — same concept as Figma frames
- Each `StateFrame` posts `designer:state` into its iframe and listens for `ready` + `resize`
  messages from `runtime.js` to grow the card to the full content height (no cropping)
- Canvas zoom: Ctrl+wheel on the overview area, or the ± buttons in the floating zoom bar
  (range 30 % – 200 %, step 15 %)
- Click any frame to switch back to single-screen mode focused on that screen and state

Both modes share:
- Back (←) button in the rail header to return to the chat studio
- Theme toggle (Sun/Moon) in the toolbar, propagated into every iframe via `data-theme`

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

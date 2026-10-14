# Agentic Designer — 3-sprint rebuild plan

Updated: 2026-09-08  
Status: completed

> Historical implementation plan. The current runtime is documented in
> [ARCHITECTURE.md](ARCHITECTURE.md) and [DESIGN_AGENT_REFACTOR.md](DESIGN_AGENT_REFACTOR.md).

## Outcome

Build a conversation-first designer that collects a complete project brief before
starting, generates a consistent but creative specification for every requested screen,
then designs and repairs those screens in one OpenPencil file using real components,
style skills, targeted knowledge, and Unsplash photography.

The rebuild keeps the existing top-level folders. It simplifies code inside them and
removes legacy files only after their replacements pass tests.

## Target runtime

```text
User message
  -> RootAgent: answer | collect brief | start design
  -> ProjectAnalyzer
  -> for each screen: CreativeScreenSpecGenerator
  -> project specification review
  -> create one output .fig
  -> for each platform and screen: OpenPencilDesigner observe/correct loop
  -> cross-screen review
  -> final human review
```

The root agent is conversational. It does not start the design graph until the brief
contains product intent, platforms, confirmed screen scope, and output filename. Style
and design system may use explicit defaults.

## Sprint 1 — Conversation and creative multi-screen specifications

### Goal

Replace one-message/one-screen routing with durable brief collection and project-wide,
hierarchical specification generation without reducing LLM creativity.

### Work

- Add a compact root decision contract:
  `chat | clarify_design | start_design`, natural reply, accumulated brief, and missing
  fields.
- Persist messages and `DesignBriefDraft` in SQLite so a design request can be completed
  over multiple turns.
- Introduce `ProjectBrief`, `ProjectDesignContext`, `ScreenBrief`, and a collection of
  `ScreenSpecification` artifacts.
- Accept an arbitrary confirmed screen list. “All screens” produces a proposed inventory
  and waits for confirmation instead of assuming three screens.
- Replace fixed `screen_name/platform` composer requirements with a natural message
  endpoint. Keep compatibility routes temporarily while the frontend migrates.
- Run project analysis once, then loop screens. Each screen retains the existing creative
  hierarchy: architect -> section plan -> nested JSON expansion -> cohesion pass.
- Generate the project style manifest once from product context plus style skill. Presets
  become fallback only; they no longer overwrite model output.
- Pass a short `DesignMemory` between screens for navigation, tokens, component language,
  content terminology, and deliberate exceptions.
- Update semantic review UI to show screen inventory, platforms, flows, and each spec.
- Add unit/contract tests for chat, multi-turn brief collection, arbitrary screen counts,
  all-screen confirmation, and cross-screen consistency.

### Acceptance criteria

- Normal questions produce a direct answer and no design run/timeline.
- Incomplete design messages persist known fields and ask only for missing material
  information.
- No design graph begins without confirmed screen scope and output filename.
- A test brief with 6 screens and 2 platforms creates 6 screen specs, not a fixed set.
- Every spec validates and shares one project design context while preserving distinct
  screen composition.
- Backend tests pass without relying on unrelated globally installed pytest plugins.

### Cleanup in this sprint

- Remove root-package compatibility aliases and redundant re-exports after imports are
  migrated.
- Consolidate duplicate router/analyzer contracts.
- Remove unused prompt files only after a prompt-usage test proves they are unreachable.
- Repair existing duplicate model fields and stale tests.

## Sprint 2 — OpenPencil-native design and overflow repair

### Goal

Replace one-shot page rendering with a measurable screen-by-screen design loop that
cannot reach final review with objective overflow or unresolved placeholders.

### Work

- Discover MCP capabilities at connection time and record the OpenPencil version/tools
  used by the run.
- Create one output `.fig`; create pages/frames only for requested screen/platform pairs.
  Do not always create desktop and mobile pages.
- Adopt skeleton-first execution:
  1. render screen skeleton;
  2. fill section placeholders with `render(replace_id=...)`;
  3. inject verified component instances and media;
  4. polish with granular MCP tools.
- Preserve hierarchical creative JSX generation per section, but expand beyond the
  artificial three-element vocabulary when supported: frames, text, shapes, SVG/icons,
  effects, grids, and intentional absolute decoration.
- Inspect selected component dimensions/slots before placement. Fit each instance using
  `set_layout_child`, constraints, min/max sizing, or choose a safe primitive fallback.
- Validate each screen separately with `page_bounds`, `describe`, `node_bounds`, and
  `analyze_overlaps`.
- Add a bounded repair loop (maximum two correction passes): findings -> targeted MCP
  updates/re-render -> remeasure. Never blindly regenerate the whole project.
- Export each screen image. When the configured model supports images, add screenshot
  aesthetic review; otherwise perform deterministic checks and retain previews for human
  review.
- Track expected component count per screen/platform. Never compare a desktop+mobile sum
  with a single-screen expected value.
- Save a checkpoint after each completed screen so retry resumes from the failing screen.

### Acceptance criteria

- Zero critical/major unintended overflow at final review.
- Zero unresolved slot/photo placeholders.
- Root bounds match the target viewport for each screen/platform.
- Component count is evaluated per screen/platform and reports no false double count.
- Mobile touch targets are at least 44x44 unless explicitly classified non-interactive.
- Failure in screen 5 resumes screen 5 without duplicating screens 1–4.
- A saved `.fig` contains only requested screen/platform pages plus deliberate support
  pages such as tokens/components.

### Cleanup in this sprint

- Split the oversized gateway into focused modules already inside `openpencil/`:
  connection/capabilities, document/page execution, component placement, media, and QA.
- Replace the duplicated JSX prompts with one screen architect prompt and one section
  designer prompt.
- Remove deprecated one-shot JSX compiler/linter paths once integration tests use the
  new execution loop.

## Sprint 3 — Skills, knowledge, Unsplash, and quality gate

### Goal

Raise visual quality and consistency through selectively loaded expertise and real media,
then remove the remaining legacy implementation.

### Work

- Turn style Markdown into retrievable skills: philosophy, composition, typography,
  tokens, signature treatments, responsive guidance, and negative constraints.
- Retrieve only relevant skill sections for the project/screen/section. Do not inject
  every style document into every prompt.
- Extend knowledge into two clear channels:
  design/UX knowledge and real component knowledge. Knowledge advises; it does not force
  a template or an incorrect component.
- Query/inspect only shortlisted real components and keep evidence keyed by source
  fingerprint.
- Make OpenPencil MCP `stock_photo` the primary photo path. Generate specific English
  queries from media intent, choose orientation from the target frame, and vary `index`
  to avoid repeated images.
- Require the active MCP provider to be Unsplash when requested; fail with an actionable
  setup message rather than silently switching providers.
- Persist provider, source ID, photographer, dimensions, query, and target node for every
  applied image. Perform Unsplash download tracking and retain attribution/profile links
  through the official API where required.
- Add media QA: correct subject, crop, contrast behind text, no repeated hero/catalog
  photo, no empty image frame.
- Run whole-project cohesion review after individual screens: navigation, typography,
  spacing rhythm, tokens, components, imagery, and intentional exceptions.
- Build a small golden evaluation set covering landing, dashboard, commerce, mobile app,
  dense form, and multi-screen product flows.
- Rewrite authoritative documentation and delete superseded V2/V3 plans, dead prompts,
  stale generators, and obsolete tests.

### Acceptance criteria

- The same style skill yields related design language without repeated wireframes.
- Component selection can deliberately fall back to primitives with a recorded reason.
- Every requested media node receives an image or an explicit actionable failure.
- Unsplash runs report Unsplash as provider and retain attribution/download evidence.
- No duplicate stock image is used within a screen unless explicitly intended.
- Cross-screen review detects and repairs accidental token/navigation drift.
- Golden runs pass objective layout gates and human review shows a material visual
  improvement over the stored baseline previews.
- `pytest`, Ruff, type checking, and frontend build pass; no dead prompt/runtime path
  remains.

## Non-goals

- No agent per style, screen, section, or component.
- No fixed screen count or fixed section template.
- No unbounded self-reflection loop.
- No vector database in the first rebuild.
- No full design-system tree or raw `.fig` in the LLM context.
- No large frontend redesign until backend contracts and workflow state are stable.

## Implementation order and migration safety

1. Add new contracts/tables beside the old read path.
2. Move frontend message submission to the new root endpoint.
3. Switch specification artifacts to project + screens.
4. Switch OpenPencil execution to per-screen pages and repair loop.
5. Enable MCP media and enriched skills/knowledge.
6. Run migration/evaluation suite.
7. Delete old paths based on import/prompt coverage, then rewrite README.

The runtime prompt inventory is covered by a test. Superseded prompts and planning
documents were removed after the replacement pipeline passed its test suite.

## Sources

- [OpenPencil MCP server](https://openpencil.dev/programmable/mcp-server)
- [OpenPencil changelog](https://github.com/open-pencil/open-pencil/blob/master/CHANGELOG.md)
- [OpenPencil stock-photo tool](https://github.com/open-pencil/open-pencil/blob/master/packages/core/src/tools/stock-photo.ts)
- [OpenPencil stock-photo providers](https://github.com/open-pencil/open-pencil/blob/master/packages/core/src/tools/stock-photo/providers.ts)
- [Unsplash API documentation](https://unsplash.com/documentation)
- [Unsplash API guidelines](https://help.unsplash.com/en/articles/2511245-unsplash-api-guidelines)
- [Google ADK sequential and graph workflow guidance](https://adk.dev/agents/workflow-agents/sequential-agents/)

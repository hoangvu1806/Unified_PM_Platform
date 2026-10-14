# Design agent refactor

## Active flow

Conversation / workspace routing → creative skeleton JSON → one coherent
whole-screen semantic JSON →
design-system retrieval and binding → one page designer with tools → inspection
and refinement → save / checkpoint / review.

Project generation keeps its skeleton and section progress events. Workspace
creation keeps its page plan and produces the same `UiSpecification` before
retrieval. Workspace edits inspect the existing page and preserve that context.
Both rendering paths call `openpencil/page_agent.py`.

The page designer uses one ADK conversation with focused functions:

- `inspect_design_system`: inspected alternatives, component definitions and bindings.
- `search_design_system`: query focused alternatives from the already retrieved real catalog.
- `plan_design`: record the chosen direction and visible completion checks.
- `bind_component`: change an inspected component or repair its text mappings;
  import missing dependencies before using an alternative.
- `fetch_icons`: retrieve exact icons; return search alternatives for missing names.
- `render_page`: replace the current root, mount real instances and apply photos.
- `inspect_nodes`: reread exact properties and nested IDs from live nodes.
- `inspect_canvas_tools`: read the current MCP schema for native edits when needed.
- `edit_node`: change a live node's common color, text, size and type properties.
- `edit_canvas`: apply a batch of native edits; return each result/error and
  automatically capture the changed canvas.
- `inspect_page`: actual JSX, geometry and a raster when OpenPencil can export it.
- `reflect_page`: assess the latest code, telemetry and raster against the creative
  plan, required content and project navigation; either continue refining or complete
  when the latest inspection has a raster, complete content and no critical
  page/container overflow.

Tool failures return their actual messages to the same conversation. ADK argument
errors are also returned through its tool-error callback. Three identical failed
actions start one fresh model context on the existing canvas; another stall stops
with a retryable error instead of running for hundreds of calls.
The page conversation has no artificial call ceiling or wall-clock timeout; it
ends on an accepted final reflection, cancellation, or a retryable failure.
There are no nested generation, parser-healing and
aesthetic-repair loops. Cancellation still propagates.
If the provider emits final prose before `reflect_page` passes, the harness resumes
the same ADK session with the existing tool history instead of raising
`DESIGN_INCOMPLETE` or treating pseudo-code as an action.
The loop is Plan → Reason → Act → Observe → Reflect; only tool actions and the final concise
summary are externalized. Skeleton expansion is a plain async function rather than
an agent/generator class.
The final layout artifact is derived from measured telemetry; it no longer starts
a second semantic-review LLM call after the page agent has already inspected it.

## Problems found and changes

| Previous behavior | Effect | Change |
| --- | --- | --- |
| Imported design-system components but skipped bindings during page assembly | Screens only resembled a design system | Required mounts become real instances; inserted count is checked |
| Re-ran JSX generation after parser errors without passing the error | Repeated failures with no learning | Tool response includes the error in the ongoing conversation |
| Emergency fallback drew only a title and description | A broken design could look like success | No synthetic fallback screen or section |
| Independent fragment generation plus heuristic tree splitting | Lost whole-page hierarchy and context | One designer sees the entire screen |
| Regex healing imposed bold type, colored CTAs, padding, shadows and replacements | Style intent changed after generation | Active page renderer sends authored JSX to the engine unchanged |
| Component text handling recolored buttons using words such as “save” | Library identity changed silently | Text binding only edits declared slots; errors remain visible |
| Custom styles defaulted to minimal | Original direction disappeared | Unknown styles follow the brief without a preset |
| JSX contract mixed engine syntax and one aesthetic recipe | LLM received conflicting instructions | Compact renderer contract; separate sourced design knowledge |
| Partial catalog hints prevented broad source discovery | The model saw too few real variants | Every requirement receives its knowledge matches plus up to 12 relevant components verified from the real source |
| Reparsed the whole `.fig` for each candidate | Component discovery took tens of minutes | One catalog scan, source-aware disk cache; reused validated bindings on retry |
| Proxy Gemini endpoint returned empty STOP with zero tokens | No tool call reached the agent | Configure the verified OpenAI-compatible `/v1` transport with `openai/` model prefix; keep the same model |
| ADK expanded literal `{...}` in JSX instructions | `Context variable not found: number` before any tool call | Supply the fully rendered prompt through a callable instruction |
| Retry reopened an already-open output and deleted its active page | RPC timeout followed by stale page IDs | Reuse the live document, explicitly scope the initial page, resume the screen in place |
| A project-wide 40-component dependency limit | Larger screens failed even with valid components | Deduplicated dependency traversal without that arbitrary cap |
| Schema retries repeated the same prompt / repaired truncated JSON silently | Content could disappear | Previous response and validation error are sent back for correction |
| Duplicate skeleton control IDs | Two bindings consumed the same mount and reported 16/17 instances | Assign distinct node IDs before component resolution |
| Reopened .fig files remapped node IDs | Cached component references pointed at missing nodes | Check actual component masters and reimport missing definitions; retain the existing document |
| Workspace used separate mutation/refinement planners and property aliases | Duplicate logic and different capabilities | Same tool-driven page designer as project assembly |
| Seven long style presets plus legacy UX snippets were injected as rules | Generic recipes constrained visual direction and inflated context | The brief and one sourced design-craft document guide the LLM; style names remain user intent, not hardcoded recipes |
| A second LLM reviewed layout after the page agent | Repeated model latency and conflicting severity rules | Final review uses objective telemetry only; aesthetic judgment stays in the page agent's inspect/refine loop |
| Skeleton sections only carried role/name/layout | Creative direction disappeared before rendering | Each section now preserves its composition, visual anchor and component treatment through `UiSpecification` |
| Sections were expanded in separate model calls | Repeated card stacks and inconsistent hierarchy because no section saw the whole page | One whole-screen composer designs all section relationships in one call after the mandatory skeleton |
| Catalog entries without precomputed text-slot metadata were rejected | Valid real components stayed unused even though their live text nodes could be edited | Keep semantically valid bindings, inspect their mounted subtrees and let the designer edit actual text nodes |
| A second full render followed native refinement | New instances silently restored default colors, labels and sizes | Protect live refinements; structural resets must be explicit and are followed by another complete component audit |
| `inspect_page` exposed only the outer JSX | The designer often missed stale colors and clipped labels nested inside real instances | Return exact mounted instance IDs and let `inspect_nodes` read suspicious subtrees on demand |
| The provider returned prose while refinement was still pending | A changed canvas failed as `DESIGN_INCOMPLETE` before the model executed its own next steps | Resume the same ADK session; report a semantic stall only after another final response at the identical canvas state |
| The batch editor described MCP arguments by hand | The model used JSX aliases such as `justify`, `textAutoResize` and `overflow`, causing partial batches | Request compact live schemas for the next edit tools and return the expected schema beside each failed operation |
| Every component subtree and edit schema was copied into one observation | The next model turn became slow and unfocused | Keep current JSX and screenshot, then inspect only the component nodes and tool schemas needed for the next action |
| Mounted instances kept their 98-190px library width | Inputs and buttons occupied only part of their declared 358px slots | Resize instances to their mount; inspect the painted inner surface too, because instance resize may not stretch library descendants |
| `responsive` had no static reference viewport | Enterprise screens could become inconsistent 390px mobile canvases | Represent responsive designs on a 1440×1024 reference frame and reserve 390×844 for explicit mobile requests |
| A whole radio group or labeled field became one component requirement | Resolver selected a single switch/input that could not express the group or label | Compose groups and form-field labels as containers around separate design-system primitives |
| A table-cell sample input was selected as a standalone form input | Text slots were empty, so the user's placeholder disappeared; wrong dimensions and sample colors survived | Prefer the matching control family and a writable text variant; revalidate cached bindings |
| `tool_choice=required` compelled a tool call even when the model needed to finish or recover | The model emitted invalid empty operations repeatedly | Let the model choose its next action and stop after three identical failed calls |
| Reflection only returned the outer JSX and broad geometry | Narrow painted surfaces and stale library colors were invisible to the agent | Return compact live instance, surface and text IDs, sizes and colors; edit those nodes and reinspect |
| A failure after successful canvas edits lost unsaved work | Retry reopened the last saved defaults | Save the current OpenPencil document on page failure and resume existing mounted instances |
| Exact generated copy and non-text container overflow blocked completion | Creative wording and legitimate nested layouts could be rejected | Treat generated copy as advisory; block only concrete missing mounts, component underfill and clipped visible text |

## Knowledge

[`knowledge/design-craft.md`](knowledge/design-craft.md) contains attributed
research from W3C, Nielsen Norman Group and Google Design, plus clearly identified
editorial design suggestions. `PromptLibrary` injects it into project direction,
workspace page planning and the page designer.

Accessibility criteria are separated from aesthetic suggestions. A static design
cannot prove keyboard, semantics, motion or responsive implementation conformance.
The obsolete style recipes, fragment generator, regex linter, separate
visual-refinement runner and their unused prompts have been removed. The user's
style choice remains part of the brief and is interpreted against the product and
actual design system.

## Ownership and recovery

Server code owns source/output separation, page identity, component IDs, instance
insertion, photo provenance and checkpoints. The LLM owns composition and visual
decisions. A successful render records its root before component insertion: if
insertion fails, the next render replaces that root instead of appending another.
Workspace page identity is persisted before the tool loop so retries reuse empty
pages. Project retries retain completed screens and reopen the saved document.

Structured planning retains schemas because the frontend and storage depend on
them. Human scope/final review, SSE and session routing remain in place. The old
standalone single-screen gateway renderer and workspace mutation executor were
removed from the active API implementation.

## Verification and limits

Regression tests exercise the actual ADK runner with a scripted model, error
feedback, malformed JSON correction, component mounts, icon retrieval, image
context, partial insertion recovery, cancellation, project checkpoints, and
workspace edit/add/multiple-page/empty-page retry paths. External model and MCP
calls are mocked in these tests.

Live investigation on 2026-09-22 confirmed the repeated catalog parsing and
ADK instruction interpolation failures. The source catalog scan took 22.79 seconds;
subsequent discovery returned 52 verified candidates in under 0.2 seconds.
Actual rendering and visual review use the configured provider and OpenPencil bridge;
these are separate from mocked regression checks.

Targeted checks can run from `backend` with `PYTHONPATH` set to that directory and
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`; external model and OpenPencil calls are not
required for those checks.

## Live endpoint findings

The configured proxy returned Gemini-native `STOP` responses with empty text and
zero tokens for the page-tool request. The same model and prompt returned a real
`inspect_design_system` call through `/v1/chat/completions`. Configuration now uses
that OpenAI-compatible protocol; this does not change the selected model.

OpenPencil's browser file opener waits for `requestAnimationFrame`. In the live
session, bringing its tab to the foreground released a stalled open, confirming
why the previous run appeared frozen. The agent also reports MCP timeouts instead
of silently waiting. No change to the separate OpenPencil repository or Docker
image was made.

The provider, skeleton generator, page renderer, gateway and project executor now
share one page-design loop instead of independent generators and repair agents.
Legacy generator/linter/refinement tests were removed with the obsolete
implementation; focused tool-loop and checkpoint coverage remains.

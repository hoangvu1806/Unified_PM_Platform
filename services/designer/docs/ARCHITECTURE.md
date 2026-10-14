# Architecture

React chat/workbench → FastAPI → conversation/workspace routing → JSON planning
→ design-system retrieval → shared tool-driven page designer → saved output and review.

## Planning

A confirmed `DesignBrief` defines scope. The project analyzer defines shared style
and content direction. The plain `generate_ui_specification` function requests a
`PageSkeleton`, then composes the complete `UiSpecification` in one whole-screen
model call. It emits the existing skeleton/section events without a graph runner
or synthetic fallback sections.
Each section carries its selected composition, visual anchor and component
treatment into the final semantic JSON, so component retrieval and rendering do
not lose the creative plan.
Workspace additions retain `WorkspacePagePlan`; edits inspect the live page.
Both produce semantic JSON before retrieving components.

## Retrieval

`KnowledgeIndex` suggests relevant catalog entries, then `ComponentSource` scans
the real source file once and adds up to 12 verified alternatives for every
component requirement. Bindings retain real IDs, variants and text slots.
Dependencies are imported before page design. An empty library cannot silently
substitute for required design-system controls.

## Design execution

`AdkProvider.run_tools` runs one ADK conversation. `openpencil/page_agent.py` exposes
component inspection/binding, icon retrieval, rendering, inspection and completion.
Errors become tool results in the same model context. The model corrects its
arguments and preserves the plan; the runtime does not rewrite aesthetics.
The design-system inspection reports selected components and catalog coverage.
Focused catalog search keeps the full retrieved library available without placing
every candidate in context. The designer requests compact live MCP schemas only
for its next edit tools, and a failed operation returns that tool's expected schema.
A premature final-text response resumes in the same session. Repeated invalid
tool calls get one fresh model context on the existing canvas; a second stall
ends with a retryable error rather than waiting indefinitely. Repeated final
responses at the same canvas state also end with a retryable error.

The conversation follows Plan → Reason → Act → Observe → Reflect. Planning comes from the
approved creative JSON and inspected library; action is always a tool call;
observation is the real tool result, syntax error, telemetry or screenshot; and
reflection happens in the same model context before the next action. Private model
reasoning is not stored as another schema or workflow object.

`inspect_page` fetches current live JSX, mounted instance IDs and geometry and requests a fresh raster
through MCP. Export retries transient failures, and completion is blocked until a
raster is available. If MCP still cannot provide one, the conversation ends with a
retryable OpenPencil error instead of repeating inspect/reflect. The raster is
attached to the next model turn. Text-node copy and resolved component labels are
compared with live JSX; design metadata is never mistaken for visible copy.
`reflect_page` records
whether the inspected result still needs work and completes the page when it does
not; it rejects stale inspection evidence and blocking geometry. The trace records
inspection ID, raster availability, live JSX
length and the reflection outcome for debugging.

After mounting real components, `inspect_page` reports each instance's actual
size, visible surface colors and sizes, text, and exact node IDs. `inspect_nodes`
remains available for a focused reread of a nested subtree. This exposes controls
that remain narrow or retain library colors even when their outer mount is correct.
`edit_canvas` applies a related group of native node operations and automatically
captures the resulting JSX, telemetry and raster. Each operation returns its own
result or MCP error, so the model can repair one failed edit without losing the
successful edits or entering an inspect/reflect loop.

`render_page` owns the target document/page and tracks the current root. It mounts
real component instances at declared slots and applies only explicitly requested
stock media. User-provided assets and placeholders stay local to the canvas and
must not invoke a provider lookup.
After native node edits begin, a different full-page render is rejected unless the
designer explicitly requests a structural reset, because replacement creates new
instances with library-default properties.
`inspect_page` returns actual geometry and JSX, and attaches a raster to model
context when available. Completion requires inspection of the latest successful
render and rejects wrong viewport width, empty mounts, visually underfilled
components, and clipped text. These are integration checks; the runtime does not
score aesthetics or require exact generated copy.
The page conversation has no artificial call ceiling or wall-clock timeout. It
ends when the final reflection accepts the inspected result or the run is cancelled.

## Persistence and boundaries

SQLite stores sessions, briefs, runs, specifications, events, reviews and artifacts.
SSE replay uses event sequence numbers. Project checkpoints preserve completed
screens. The output file is saved when a page fails after material edits, so retry
can refine the existing canvas. Workspace traces preserve page identity and tool
errors for retry.
Source design-system files are read-only inputs; output pages are separate.
Server code owns IDs and persistence, while the LLM owns composition and polish.
Scope and final reviews remain unchanged. Photo provenance retains the existing
OpenPencil Unsplash contract.

`PromptLibrary` adds [design craft knowledge](knowledge/design-craft.md) only where
visual direction or execution is decided: project direction, workspace page
planning and page design.

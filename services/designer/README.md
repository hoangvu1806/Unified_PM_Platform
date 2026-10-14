# Designer service (designer-api)

Conversation-first UI design agent built with FastAPI, Google ADK and OpenPencil MCP.
It runs inside the platform (`../../README.md`): UI at `/designer/`, API at
`/designer/api/v1/` behind the gateway; data in Postgres schema `designer`, files in
platform storage (S3).

## How it works

```text
message
  -> root: answer | clarify design | start design
  -> project analyzer
  -> screen specification loop
  -> human scope review
  -> design-system component retrieval
  -> one OpenPencil file, one page per screen/platform
  -> one tool-driven page designer: render, inspect, correct, refine
  -> final human review
```

Normal questions are answered without starting the design graph. A design starts only
after product intent, platforms, screen scope, output filename, and scope confirmation
are available. Screen count is dynamic; there is no fixed three-screen template.

## Quality model

- Skeleton JSON records a chosen composition, visual anchor and component
  treatment for every section before semantic component requirements are expanded.
- Every required control retrieves inspected design-system options. Real component
  instances and fetched icons are used to build the interface.
- One ADK tool conversation designs and refines each page. Tool and syntax errors
  go back to the model with their context; there is no synthetic fallback screen.
- Mounted design-system instances can be selectively adjusted through the same
  tool loop, then visually inspected again before completion.
- `inspect_page` retrieves live JSX, geometry and a current MCP raster. Completion
  requires that raster and rejects approved content missing from the live JSX;
  a clean `reflect_page` assessment then completes the page directly.
- Project creation and workspace editing share the same page designer.
- The designer inspects JSX, measurements and a screenshot when available, then
  refines the layout and decoration before completing the page. Completion rejects
  wrong viewport width, empty component mounts and critical container overflow.
- Source libraries, output files, checkpoints and human reviews remain separate.
- Sourced design guidance lives in [design-craft.md](docs/knowledge/design-craft.md).

## Run and test

From `platform/` (everything runs in Docker):

```powershell
cd ..\..\BA\open-pencil; docker compose up -d     # default OpenPencil instance (editor :1420, MCP :7600)
cd <platform>; docker compose up -d                # whole platform, http://localhost:8080
docker compose --profile test run --rm designer-test
```

The editor tab (http://localhost:1420) must be open for MCP write automation. Each
designer's runs use their OpenPencil instance (`designer.openpencil_instances`) or the
default one; the endpoint typed in Settings is only used in `PLATFORM_ENV=dev`.

Project files (BA packages, wiki documents, finished designs) are listed in the right
panel ("Files dự án") and can be dragged into the chat or cited with `@`.

Architecture details are in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

### Model endpoint protocol

For an OpenAI-compatible proxy, use `DESIGNER_LLM_MODEL=openai/<model-name>` and
`DESIGNER_LLM_BASE_URL=<proxy>/v1`. The prefix selects the wire protocol, not the model vendor.
Use `gemini/` only for a working Gemini-native endpoint. This project’s proxy
returned empty Gemini responses (`STOP`, zero tokens) for the page tools; its
OpenAI-compatible route returned valid tool calls for the same model and prompt.

# Agentic Designer

Conversation-first UI design agent built with FastAPI, Google ADK, React, SQLite, and
OpenPencil MCP.

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
  The [refactor notes](docs/DESIGN_AGENT_REFACTOR.md) explain decisions and limits.

## Local setup

Requirements: Python 3.11+, Node.js 20+, and OpenPencil with HTTP MCP enabled.

```powershell
Copy-Item .env.example .env
cd backend
pip install -r requirements.txt
python run.py
```

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Default endpoints:

- Frontend: `http://127.0.0.1:3232`
- Backend API: `http://127.0.0.1:8282/api/v1`
- OpenAPI: `http://127.0.0.1:8282/api/docs`
- OpenPencil MCP: `http://127.0.0.1:7600/mcp`

Configure the OpenPencil source file in frontend Settings. For screens containing
photography, add an Unsplash key in OpenPencil AI settings and select Unsplash as the
active stock-photo provider.

## Verification

```powershell
cd backend
$env:PYTHONPATH=(Get-Location).Path
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
pytest -q
ruff check app tests

cd ..\frontend
npm run build
```

The golden project shapes are stored in
[`backend/data/evals/golden-projects.json`](backend/data/evals/golden-projects.json).
Architecture details are in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

### Model endpoint protocol

For an OpenAI-compatible proxy, use `LLM_MODEL=openai/<model-name>` and
`BASE_URL=<proxy>/v1`. The prefix selects the wire protocol, not the model vendor.
Use `gemini/` only for a working Gemini-native endpoint. This project’s proxy
returned empty Gemini responses (`STOP`, zero tokens) for the page tools; its
OpenAI-compatible route returned valid tool calls for the same model and prompt.

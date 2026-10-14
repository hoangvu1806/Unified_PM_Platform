# OpenPencil runtime

This project does not start Docker or install OpenPencil packages. The only external
design process is OpenPencil plus its HTTP MCP bridge.

Example manual startup from the directory that should contain design files:

```powershell
$env:OPENPENCIL_MCP_ROOT = "E:\working\BA\design-files"
$env:OPENPENCIL_MCP_AUTH_TOKEN = "replace-with-a-local-secret"
openpencil-mcp-http
```

Then copy the same token into the backend `.env`. Enter the endpoint printed by the
running MCP process in frontend Settings. Source and output paths are also supplied
by that panel and may be relative to `OPENPENCIL_MCP_ROOT`; the MCP server rejects
paths escaping that root.

OpenPencil itself must be running for MCP write automation. The selected file does
not need to be manually focused: the workflow calls `open_file`, `create_page`, and
`save_file` with explicit document/page IDs.

For read-only CI without the editor UI, use the OpenPencil CLI directly:

```powershell
openpencil info design-system.fig --json
openpencil lint generated\new-screen.fig --json
openpencil analyze overlaps generated\new-screen.fig --json
```

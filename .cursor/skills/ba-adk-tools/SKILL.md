---
name: ba-adk-tools
description: >-
  Wires BA discussion ADK FunctionTools (wiki search/fetch, optional web_search,
  preview_bpmn). Use when adding tools to FD/UC/WF discussion agents, checking
  the deny list, or debugging BA tool registration. Extractors/flags stay tool-less.
---

# BA ADK discussion tools

## Where

Module: `agents/sub_graph/shared/discussion_tools.py`  
Wired on **FD + User Story (UC) + WF discussion** only. Extractors / flags / VA discussion stay tool-less.

## Allowed tools

| Tool | Rule |
|------|------|
| `wiki.search_pages` | Always try wiki first; approved only |
| `wiki.fetch_page` | Fetch approved page body after search |
| `web_search` | After wiki miss for **in-package** BA clarification only. **Refuse** FD `scope_out` / non-goals / unrelated browsing. Brave/Tavily if env key; else “not configured” — **do not hallucinate**. Cite URLs. Never treat as approved wiki. |
| `preview_bpmn` | After WF has actor-step rows; calls `build_bpmn_xml`; does not bypass flags |

## Never register

`approve` / `ingest` / `propose` / `wiki.approve_page` / `wiki.ingest_source` / `wiki.propose_page`

## Prompts

“You have tools. Search wiki before inventing. Never web_search scope_out/non-goals; web only after wiki miss for in-package clarification. BPMN preview is a sketch.”

No Google ADK `google_search` (BA uses the company Qwen gate).

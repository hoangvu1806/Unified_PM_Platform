---
name: ba-bpmn-collaboration
description: >-
  Build BA BPMN as a collaboration swimlane diagram from the WF actor table.
  Use when editing managers/control/bpmn.py, BPMN preview, lanes, XOR/AND
  gateways, BPMNDI, bpmn_by_story, or fixing flattened flowchart layouts.
---

# BA BPMN collaboration

## Deterministic Python owns XML

No LLM PASS/FAIL for the diagram. Source: `managers/control/bpmn.py` (+
`managers/control/bpmn_elk.py` for layout only).

## Emit

- `bpmn:collaboration` + `participant` + **one lane per WF Actor**
- Never invent Management/Supplier unless those actors are in the story/FD
- Gateways: `exclusiveGateway` (XOR, `isMarkerVisible`) and `parallelGateway` (AND)
- Human work = `userTask`; start/end events
- Parse optional **Gateway** column from the WF table (`XOR` / `AND` / blank)

## BPMNDI

- **Prefer ELK** when Node + `tools/bpmn_elk` (`bpmn-elk-layout`) are available:
  Python emits ELK-BPMN JSON; Node lays out; XML+DI returned
- **Fallback DIY** swimlane DI in Python: **Y = lane**, **X = sequence**
  (no Node, timeout, bad JSON, or `BA_BPMN_ELK_DISABLE=1`)
- Lane shapes: `isHorizontal="true"` (DIY path); ELK positions lanes via elkjs
- Client `ensureBpmnDi` is **fallback only** when DI is missing
- Agents never invent lanes; ELK only positions what Python already decided

## One BPMN per active story

- Store `artifacts.bpmn_by_story[US-xx]` and set `bpmn_reference` to the active story
- Prefer `active_user_story_id`; else US-01 / first story

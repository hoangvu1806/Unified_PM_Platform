---
name: ba-one-story-flow
description: >-
  Runs BA as one concrete User Story at a time under a Feature parent session.
  Use when working on BA User Stories, active_user_story_id, Sec 04, use_cases,
  one-story lock, or when tempted to dump multiple US-xx in one turn.
---

# BA one-story flow

## Rules

- **Feature** = parent package (`session_id`). Inside it: N flows, each = one User Story.
- Finish the **active** story (statement + AC + required UC flags for that row) before starting `US-02`.
- Section display title is **User Stories**; JSON key stays `use_cases`.
- Do **not** invent a second story until the PO says the current one is done.
- Completeness: `UC-F1` min 1 story; do **not** require N stories to Validate.
- WF for the active story: table `Step | Actor | Action | BR | Gateway` (`XOR` / `AND` / blank). Actors must match FD (they become BPMN lanes).

## Anti-patterns

- Dumping four User Stories in one turn
- Rewriting finished stories while building the next
- Inventing actors not in Feature Definition

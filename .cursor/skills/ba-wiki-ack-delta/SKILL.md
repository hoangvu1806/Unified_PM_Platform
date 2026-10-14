---
name: ba-wiki-ack-delta
description: >-
  Acknowledge approved wiki as agreed text, then only delta the new idea in the
  same topic. Use when BA touches wiki, ack-then-delta, approved pages, V-WIKI-*
  Validate findings, or agents are tempted to overwrite stories from wiki.
---

# BA wiki acknowledge-then-delta

## Rules

- Inject **approved** wiki into FD / User Story context. Drafts stay hidden.
- List existing wiki titles/ids first (“already agreed”), then only develop the **new** idea if it is the **same topic** as the feature.
- If the idea is a different product → `scope_out` / OQ; do not rewrite agreed stories.
- BA **does not** auto-overwrite `artifacts.use_cases` from wiki. Human pastes/confirms; extractor merges by `US-xx`.
- Agents **never** approve, ingest, or propose wiki pages (search/fetch only).

## Validate wiki violations are errors

`V-WIKI-*` findings are **errors** (same class as V-02): they set `VALIDATION_FAILED` and **block Export**.

| Check | Meaning |
|-------|---------|
| V-WIKI-01 | Wiki policy numbers/thresholds disagree with BR |
| V-WIKI-02 | Wiki contradicts an agreed User Story / AC |
| V-WIKI-03 | Two approved pages contradict each other |
| V-WIKI-04 | Wiki asserts FD `scope_out` or unknown actor as in-scope |
| V-WIKI-05 | Warning only — coverage gap |

Human fixes **wiki or package**, then re-Validate. Chat may ACK a finding; it must not pretend the story overwrote wiki.

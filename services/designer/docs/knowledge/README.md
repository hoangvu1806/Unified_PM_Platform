# Design-system knowledge

This directory contains the compact, reviewed guidance used by Designer Agent V3. Knowledge is
the agent's primary design-system context; raw `.fig` files and complete component indexes are
never inserted into LLM prompts.

## Registry

| Design-system ID | Knowledge | Status |
|---|---|---|
| `taptap` | [taptap.md](taptap.md) | Existing; must be reconciled with the headless index |
| `shadcn-ui` | [shadcn-ui.md](shadcn-ui.md) | Existing; must be reconciled with the headless index |
| `material-ui` | `material-ui.md` | To be generated and reviewed in V3 Phase 1 |
| `design-v0-3` | `design-system-v0.3.md` | To be generated and reviewed in V3 Phase 1 |

Cross-cutting runtime guidance is also injected into design prompts. The current
export contract is [OpenPencil → Figma export readiness](fig-export-asset-and-layout-quality.md);
it covers embedded user assets and post-import text/layout validation.

The existing `*-components.catalog.json` files are legacy MCP snapshots. They remain reference
evidence during migration but are not the V3 runtime index and must not be treated as current
component truth. V3 indexes are generated headlessly from the immutable sources under
`E:/working/BA/designer-data/design-systems` and stored under `designer-data/indexes`.

## Progressive disclosure

The backend selects context; an LLM does not read files or catalogs directly:

1. Load only the selected design system's identity, foundations, layout, responsive, and
   composition guidance when producing a specification.
2. Search the local machine index deterministically for each approved component requirement.
3. Load only the relevant component-family knowledge and at most eight candidate summaries.
4. Read exact metadata for at most three finalists and verify the chosen ID, variant, and slots.
5. Give binding and review agents only the chosen component details or measured layout rules they
   need for the current stage.

Normal conversation loads no design-system knowledge unless the user explicitly asks about it.

## Knowledge contract

Each reviewed document should use stable headings for:

```text
Identity
Foundations
Tokens
Layout and responsive behavior
Component families
Variant and slot guidance
Composition recipes
Accessibility
Constraints and anti-patterns
Source fingerprint
```

Lightweight tags may be added to headings for deterministic section selection. A vector database
is not required for the baseline.

## Correctness and token rules

- Knowledge explains intended usage; the current headless index proves exact availability.
- Never inject a complete knowledge document, raw `.fig`, document tree, or full index into a
  prompt.
- Deduplicate repeated sections and candidates before estimating the context budget.
- Record knowledge hash, selected headings, source fingerprint, and candidate IDs with each run.
- When source fingerprint changes, regenerate the index and create a drift report. Do not silently
  overwrite reviewed knowledge.

This follows progressive disclosure: compact routing guidance first, relevant family guidance
second, and exact component evidence only for finalists.

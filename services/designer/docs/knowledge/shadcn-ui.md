# shadcn/ui component knowledge

## Source and scope

- Source: `@shadcn_ui - Design System (Community)` (`tab-3` at snapshot time).
- Snapshot: 999 entries across 5 pages: 18 component sets and 981 components.
- Breakdown: 20 composed components, 100 primitives, and 877 icons.
- Full evidence: [shadcn-components.catalog.json](shadcn-components.catalog.json).
- No OpenPencil variables were exposed. Preserve the real components rather than
  rebuilding an assumed Tailwind theme.

This is a community design file, not the canonical shadcn code registry. Use its
exact component names for OpenPencil and shadcn's semantic composition model when
planning the interface.

## Selection algorithm

1. Choose a composed component from `Components` when it already models the whole
   interaction.
2. Use `Primitives` to assemble a missing pattern or control a specific state.
3. Add icons from `Icons` only after the semantic component is selected.
4. Choose exact source variant values; capitalization and typos are significant.
5. Bind text and content from `detail.propCandidates`, then compose the output in a
   separate document.

Prefer the smallest semantic component that owns the interaction. For example,
choose `dialog` for a modal task and the primitive `button` only for its actions;
do not recreate the dialog from unrelated rectangles and text.

## Composed components

The `Components` page contains these 20 reusable patterns:

| Category | Components |
| --- | --- |
| Navigation and disclosure | accordion, tabs and content, navigation menu and content, menubar and content |
| Menus and command | command, context menu, dropdown menu |
| Selection and input | radio group, select, select options, slider |
| Feedback and progress | progress, tooltip, hover card, popover |
| Containers and viewport | dialog, `alter dialog`, scroll-area, separator |
| Supporting | label |

The source calls the alert-dialog component `alter dialog`. Preserve that exact
name when looking it up. A composed `table` is stored on `Typography`, and
`input/small` is stored on `Internal Only Canvas`; these are source-file quirks.

## Primitive families

| Family | Variant axes | Use |
| --- | --- | --- |
| button | type; Default/hover state | actions and icon buttons |
| input | type, Size, State | text fields and left-label fields |
| textarea | type, state | long text and text-with-action |
| checkbox | default/with text | multi-select boolean choice |
| radio button | default/selected | single choice |
| switch | off/on | immediate setting toggle |
| tab item | selected/unselected | tab trigger |
| accordion Item | closed/open | disclosure row |
| collapsible | closed/open | custom disclosure region |
| menubar item | default/selected | menu trigger |
| menu item | type and state | command/menu row |
| menu section title | default/padded | menu grouping label |
| navigation menu item | default/dropdown/link; state | top-level navigation |
| navigation menu content item | Default/selected | navigation panel item |
| navigation menu content | two columns/with picture | navigation panel body |
| section items | top/middle/bottom/title/divider | grouped menu composition |
| avatar | image/initials | user identity |
| table item | head/item and state | table rows/cells |

Standalone primitives are `menubar`, `tab card`, `tabs`, `poster`, `navigation
menu`, `scroll list item`, `inline code`, and `palette`.

### Button semantics

Button set `0:826` contains these exact types:

```text
default, primary button, destructive, outline, subtle, ghost, link,
with icon, just icon, just icon circle, loading
```

Use `primary button` for the main CTA, `default` for a normal action,
`destructive` for irreversible/dangerous actions, `outline` or `subtle` for lower
emphasis, `ghost` in compact chrome, and `link` only for navigation-like actions.
`loading` owns progress feedback; do not combine it with a separate spinner.

### Form semantics

- Input set `0:1062` supports default/small size and default, focused, completed,
  disabled states. `label to the left` is a structural type, not just text.
- Textarea set `0:1033` has default and `with button` types.
- Checkbox is for zero-to-many choices; radio is for exactly one; switch changes a
  persistent setting immediately.
- Use composed `select` plus `select options` rather than drawing an input and loose
  menu independently.

## Icons

The `Icons` page contains 877 standalone components named `icon/<lucide-name>`.
Do not load the icon catalog into the LLM context. Derive a short semantic keyword
from the requirement, then search `pages.Icons.components` locally.

Icon rules:

- Prefer a text label for important or unfamiliar actions.
- Use one icon family consistently; do not mix arbitrary custom SVGs.
- Match the icon to meaning (`search`, `trash`, `settings`), not decoration.
- Icon-only actions require an accessible name in the UI specification.

## Composition patterns

- Navigation shell: navigation menu + menu content/item + button/avatar actions.
- Form: label + input/textarea/select + local validation copy + action buttons.
- Settings row: label/description + switch, checkbox, select, or radio group.
- Data view: table primitives + dropdown/context menu for row actions + dialog for
  destructive confirmation.
- Command surface: command or dropdown menu; use menu sections and items rather
  than manual rows.
- Overlay: tooltip for a short hint, hover card for preview, popover for compact
  interaction, dialog for a focused task.

## Binding rules

Use the catalog's real component detail:

- `text:<node name>` identifies replaceable copy.
- `slot:<node name>` identifies replaceable nested content.
- `usedOnScreens` shows demonstrated composition, not a hard usage restriction.

Apply data after the component and state are resolved. Preserve internal spacing,
radius, and colors. If content does not fit, choose a different component/state or
change the surrounding layout before editing component internals.

Source values have inconsistent casing and typos such as `diabled`, `defaukt`,
`Default`, and `default`. Treat values as opaque enum strings in matching code.

## OpenPencil workflow

OpenPencil cannot directly instantiate a component ID from one document inside
another. Use the same safe import flow for every shadcn component:

1. `get_jsx` from the source document.
2. Render a local definition on the output document's `Components` page.
3. Create instances from the local definition.
4. Bind content, compose layout, validate geometry, and save the independent file.

When reparenting into a non-auto-layout slot, reset the child's local coordinates.
If an export omits instance text overrides, use a positioned text overlay only as
the documented renderer workaround; keep the component instance itself intact.

## Visual character

The snapshot uses Inter throughout. Common colors are slate neutrals:
`#0F172A`, `#334155`, `#475569`, `#64748B`, `#94A3B8`, `#CBD5E1`, `#E2E8F0`,
`#F1F5F9`, white, and black. Frequent spacing values include 4, 6, 8, 10, 12,
16, 24 and 32. These are observations, not bound tokens.

## Offline lookup recipes

```text
catalog.pages.Components.components
catalog.families where page == "Primitives" and name == "button"
family.variants where name contains "type=destructive"
catalog.pages.Icons.components where name == "icon/search"
component.detail.propCandidates
```

Call MCP discovery again only if the component is absent, the source file changed,
or the stored ID no longer resolves.


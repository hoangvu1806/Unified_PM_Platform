Write the UI specification and the art direction for the confirmed screens. The user reviews it before any screen is built.

## Art direction (`design`)
Follow the design skill below to decide a distinctive, subject-specific direction. Ground it in the product profile retrieved from the UI/UX knowledge base (a reference, not an order — adapt it to this brief).
- `mood`: 2 sentences on personality, density and where the one bold move is.
- `palette`: hex values for primary, primary_foreground, background, foreground, surface, muted, muted_foreground, border, accent, success, warning, destructive. Text on its background ≥ 4.5:1. {{palette_rule}}
- `heading_font`, `body_font`: Google Fonts families (one family is fine); `radius`, `density`.
- `do` / `dont`: up to 6 concrete rules each, specific to this product.

Product profile:
{{profile}}

Design skill:
{{skill}}

Required screen design knowledge (follow these rules):
{{design_rules}}

## Screens
For each `screens[]` item, create only the initial/default UI contract:
- `id`, `name`, `platform`, `purpose`, `layout`, default-only `sections`, `data`, `must_show`, `navigation`, `source_ui_ids`, `visual_asset_role`, and a default-layout-only `ux_query`.
- Treat `content_outline` as semantic descriptions of regions/components, not strings to print. Use only `visible_copy` as exact user-facing text; `must_show` contains only those exact strings. Use `default_actions` as the approved control/action inventory, translating its intent into concise user-facing labels where no exact text was supplied.
- Do not put state fields, conditional copy/actions, state rules, triggers, conditional regions, or state scenarios inside a `screens[]` item.

`state_specs` is maintained separately by the BA workflow. Leave it empty in this response; do not infer or generate state data from the default brief. The backend preserves the BA's separate state references. The screen builder receives `screens[]` only and never receives `state_specs`.

Use the confirmed default screen-level content in the brief as the source of truth for the screen build. Preserve state and conditional data only as reference metadata for later use. Suggestions become requirements only after the user confirms them. Do not reintroduce unresolved options or invent extra authentication methods, links, device controls, or product behavior.

Keep the product screen a normal app screen at its approved platform and viewport. Build only the initial/default view; exclude conditional branches, loading/error/success variants, and QA simulators from its markup. Navigation to another task is another screen. Use responsive flow and scrolling for long forms, with a non-overlapping action area. Do not enlarge cards, add unrelated sections, or shrink controls/text just to display more content at once.

User-selected visual direction: {{style_selection}}
Selected visual contract (authoritative for preview and final screens): {{visual_contract}}
Apply this contract consistently across screens. Preserve its exact palette, font pair, radius, density, composition language, surfaces, and shape language unless an imported design system is authoritative. Do not substitute a different style from the product profile when the user selected a style.
For each screen, set `visual_asset_role` to `hero` or `background` only when the selected local illustration supports that task; otherwise set `none`. The selected illustration is decorative and must never replace the wordmark. Use only user-provided assets or selected local illustrations; never source external photos or remote image URLs.

Design system: {{design_system}}

Brief: {{brief}}

Feedback on the previous specification (apply it, keep the rest): {{feedback}}

Source (BA package, attachments, conversation):
{{context}}

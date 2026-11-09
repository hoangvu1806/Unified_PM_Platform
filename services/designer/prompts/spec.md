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
For each screen:
- `id`, `name`, `platform` as in the brief; `purpose` (who, to do what);
- `layout`: the composition in 1-2 sentences;
- `sections`: ordered regions with their real content (fields + types, columns, figures, actions);
- `states`: non-default states worth designing, as short ids (`error`, `empty`, `loading` …);
- `data`: realistic sample data in the product's language and domain;
- `must_show`: the exact visible texts the screen must contain (labels, buttons, column headers, key messages) — taken from the source requirements, in the user's language;
- `rules`: business rules from the source (keep their ids, e.g. `BR-02: …`) that the UI must reflect;
- `navigation`: ids of screens it links to; `source_ui_ids`: source touchpoints covered;
- `ux_query`: 3-6 English keywords describing the screen's UI concerns (e.g. "login form password validation"), used to retrieve UX guidelines.

Use the confirmed screen-level content in the brief as the source of truth for each screen's regions, content, actions and states. Preserve BA and user-confirmed requirements. Suggestions become requirements only after the user confirms them. Do not reintroduce unresolved options or invent extra authentication methods, links, device controls, or product behavior.

User-selected visual direction: {{style_selection}}
Selected visual contract (authoritative for preview and final screens): {{visual_contract}}
Apply this contract consistently across screens. Preserve its exact palette, font pair, radius, density, composition language, surfaces, and shape language unless an imported design system is authoritative. Do not substitute a different style from the product profile when the user selected a style.
For each screen, set `visual_asset_role` to `hero` or `background` only when the selected local illustration supports that task; otherwise set `none`. The selected illustration is decorative and must never replace the wordmark. Use only user-provided assets or selected local illustrations; never source external photos or remote image URLs.

Design system: {{design_system}}

Brief: {{brief}}

Feedback on the previous specification (apply it, keep the rest): {{feedback}}

Source (BA package, attachments, conversation):
{{context}}

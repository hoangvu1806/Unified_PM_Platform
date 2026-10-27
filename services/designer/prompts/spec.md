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

## Screens
For each screen:
- `id`, `name`, `platform` as in the brief; `purpose` (who, to do what);
- `layout`: the composition in 1-2 sentences;
- `sections`: ordered regions with their real content (fields + types, columns, figures, actions);
- `states`: non-default states worth designing, as short ids (`error`, `empty`, `loading` …);
- `data`: realistic sample data in the product's language and domain;
- `must_show`: the exact visible texts the screen must contain (labels, buttons, column headers, key messages) — taken from the source requirements, in the user's language;
- `rules`: business rules from the source (keep their ids, e.g. `BR-02: …`) that the UI must reflect;
- `imagery`: 1-4 real photos for the screen (slot + 2-4 English keywords about the subject + orientation) — every screen carries real imagery (background, hero, covers, avatars or empty-state art) unless the brief explicitly rules it out;
- `navigation`: ids of screens it links to; `source_ui_ids`: source touchpoints covered;
- `ux_query`: 3-6 English keywords describing the screen's UI concerns (e.g. "login form password validation"), used to retrieve UX guidelines.

Design system: {{design_system}}

Brief: {{brief}}

Feedback on the previous specification (apply it, keep the rest): {{feedback}}

Source (BA package, attachments, conversation):
{{context}}

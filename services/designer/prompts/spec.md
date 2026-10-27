Write the UI specification for the confirmed screens. It is reviewed by the user before any screen is built, so it must be concrete and short.

For each screen:
- `id`, `name`, `platform` as in the brief;
- `purpose`: who uses it and to do what (one sentence);
- `layout`: the overall composition in one or two sentences (e.g. "left sidebar navigation, header with breadcrumb and primary action, two-column body: form left, summary card right");
- `sections`: ordered regions with their real content (fields with labels and types, table columns, KPIs, actions);
- `states`: important non-default states to design (empty, loading, validation error, success, permission denied …), each as a short id like `error`;
- `data`: realistic sample data to show (Vietnamese names, codes, amounts, dates in the product's domain);
- `navigation`: ids of screens this one links to;
- `source_ui_ids`: BA touchpoints covered.

Also give `style_direction`: 2–3 sentences of visual direction fitting the product and audience (density, mood, emphasis), consistent with the design system below. Do not restate generic best practices.

Design system: {{design_system}}

Brief: {{brief}}

Feedback on the previous specification (apply it, keep the rest): {{feedback}}

Source context (BA package, attachments, conversation):
{{context}}

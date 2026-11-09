# Screen Sequence Identity and Content Rules

**Document type:** Required supporting rules for screens that belong to the same product flow. Use with `material-ui-ux-knowledge-reference.md` and `multi-screen-design-rules.md`; do not replace either file.

These rules guide visual and content consistency, not a fixed template. The approved BA scope, user decisions, imported brand assets, and product design system remain authoritative. Apply the rules to previews, specs, generated screens, and visual review.

## UI contract and enforcement

- For a confirmed screen, treat its approved visible regions and actions as a content contract. Preserve all approved fields, links, checkboxes, alternate methods, and user-confirmed additions; do not infer optionality from the chosen layout.
- Keep literal labels quoted in the confirmed brief verbatim. Mark BA/user-approved content as binding and suggestions as non-visible until accepted. Never invent a new functional action to fill space.
- Apply the same confirmed content and control set to each style-preview option. Let composition and palette vary, not the agreed product behavior.
- Enforce measurable properties after rendering in the browser: exact required visible copy, accessible contrast, minimum touch-target proxy, peer-field alignment, control overlap, clipping/overflow, and asset loading. Repair and rerender before offering the gallery.
- Use image review for visual hierarchy, rhythm, illustration/background placement, palette harmony, and genuine differences between options. Feedback must identify a visible issue and a concrete fix; perform at most one focused polish pass after measurable checks pass. Subjective preference alone must not keep the user from proceeding.
- The screen background should reach its bottom edge. Include a footer only if confirmed or if it is restrained decoration with no new factual claim; avoid unexplained white bands or detached footer strips.

## 1. Keep one recognizable product identity

- Establish the product identity once from the supplied logo, wordmark, product name, or approved brand guidance. Reuse that same identity across sibling screens and all style-preview options.
- Do not invent a different logo for each screen or style. Do not turn a decorative icon, education illustration, photo, badge, or avatar into a second logo.
- If no logo asset is supplied, use a consistent text wordmark or product name. If the brand name is uncertain, use a restrained placeholder and record the assumption instead of fabricating an official mark.
- A logo/wordmark and an illustration have different jobs: the identity identifies the product; the illustration or photo sets the scene or supports the task. Keep them in separate layout regions and never substitute one for the other.
- A style may vary color, scale, placement, and surrounding surface treatment of the same identity, within the approved brand. It must not change the identity itself.

## 2. Compose each screen by role, not by a copied template

First identify the roles that the particular task needs: safe-area/header, brand, hero or background scene, title and supporting copy, primary content/form, actions, and optional footer. Use only relevant roles; not every screen needs every role or a card.

- Give the screen one clear focal point and an intentional reading order. Related brand and welcome copy may form a group; keep form fields and actions in a separate, scannable group when that improves clarity.
- Choose centered or editorial alignment deliberately. For a centered welcome composition, center the title and supporting line together. For a left-aligned form, align its labels, fields, and helper text to one content edge. Do not mix alignments accidentally.
- Use normal responsive layout flow for text, forms, and actions. Avoid absolute positioning for essential content. Keep decorative cropping on a separate image/background layer so it cannot cover or clip readable content or controls.
- Balance vertical rhythm from the top safe area through the footer. Avoid both cramped headers and oversized empty gaps between the hero, greeting, and task. Let the content determine height; do not force the same vertical layout on login, OTP, success, settings, or other different tasks.
- Add a card only when it groups related content. Avoid a card wrapping the greeting and then another card wrapping the form without a clear visual reason. Keep approved footers within the safe area and visible; do not invent footer claims or remove required footer content to make a composition fit.
- Treat persistent bottom actions/footers as layout regions, not overlays. Prefer a normal-flow footer after the content. Never use `position: fixed` to pin a footer over a scrollable list, card stack, form, or terminal actions. If a pinned action bar is essential, make the screen a constrained flex column, put scrolling content in a `min-height: 0; overflow-y: auto` region, and keep the footer as a separate non-overlapping sibling; if overlay positioning is unavoidable, reserve bottom padding at least equal to the full footer height plus safe-area inset and spacing. Verify the last content item and all footer actions remain visible together while scrolling.
- Use the same spacing scale and alignment logic for related controls. For authentication alternatives, keep the primary action, centered “Hoặc” divider, and alternate action visually grouped, with symmetric divider lines and the spacing specified by the core mobile rules.

## 3. Keep typography and copy coherent

- Define a small set of type roles and use them consistently: brand, screen title, body/supporting text, field label, input/helper, action, and footer. A display face may be used for headings only when the direction intentionally calls for it; do not mix type families or weights arbitrarily within one screen.
- Keep a title and its supporting line aligned as a pair. Use readable line height and wrapping; do not shrink text until it becomes illegible in the phone preview.
- Give each line of copy one purpose. Remove repeated explanations (for example, stating twice that an OTP was sent), duplicate field instructions, and decorative copy that adds no meaning.
- Preserve approved terminology and actions. Do not invent security promises, support contacts, institutional details, product features, or policy text to fill blank space.
- Example values are placeholders, not entered data. Keep inputs empty in their default state unless the approved screen explicitly requires a prefilled value. Use clearly fictional, non-sensitive examples; do not show realistic personal data as if it belonged to a real user.

## 4. Keep control language and states predictable

- Across screens in one flow, reuse the same semantic colors and component language for primary actions, secondary actions, links, fields, focus, success, warning, and errors. A distinct style direction may map those roles to its own palette, but do not introduce an unrelated one-off color.
- Keep actions visually distinct and comfortably separated. Apply the core knowledge's platform-specific target guidance and its preview measurement proxy; the checkbox or small icon's label should provide the usable hit area.
- Do not show success checks, completed password criteria, active states, or other positive feedback before the corresponding input or action has actually reached that state.
- Show only the approved default state on first render. Keep loading, error, success, and test variants distinct and do not add a test/simulator control to the product screen.
- State changes must not silently alter the product identity, typography system, action labels, or unrelated screen content.

## 5. Make style alternatives meaningfully different

- For a preview gallery, keep the same approved screen content, actions, brand identity, component sizing, and interaction meaning in each option.
- Create visual difference through multiple deliberate choices such as dominant palette, large-scale composition, hero/background treatment, typography character, and surface/shape language. A color swap on an otherwise identical layout is not a distinct direction.
- Do not reuse one illustration as the logo or repeat the same focal composition in every option. Select only assets that fit the product and place them at a meaningful scene scale when the art direction calls for a hero/background.
- Before showing the gallery, compare the three options side by side. Confirm their dominant color families and screen silhouettes differ, while shared controls and identity remain recognizable.

## 6. Sequence review before delivery

Review each rendered screen at the target phone width, then compare sibling screens as a set. Inspect both the full preview and a reduced thumbnail. At minimum confirm:

- one consistent brand identity; no duplicate or substituted logo;
- a clear distinction between brand, hero/background, greeting, content/form, actions, and optional footer;
- no overlap, clipping, accidental dead space, misaligned peer fields, or inconsistent title/supporting-copy alignment;
- persistent footer/action bars do not cover content at the top, middle, or end of any scrollable region; the final card and terminal actions can both be reached and read;
- readable and consistent typography, semantic link color, palette-aligned primary action, balanced spacing, and usable touch targets;
- no duplicate microcopy, invented claims, misleading prefilled data, or state feedback shown prematurely;
- distinct preview directions where a gallery is requested, with shared content and interaction language;
- all required approved content remains present and no unapproved feature or control was introduced.

Fix visible issues before presenting the screen or gallery. Automated checks can help find problems but do not replace visual inspection.

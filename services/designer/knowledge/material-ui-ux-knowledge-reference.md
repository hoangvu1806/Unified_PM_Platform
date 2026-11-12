# Core Screen Design Rules for Designer Agents

**Document type:** Required screen-level design instructions. Apply to every screen during specification, implementation, and review.

This file is the single source of truth for shared rules that apply to an individual screen. The companion `multi-screen-design-rules.md` contains only cross-screen consistency procedures and quantitative density/text heuristics. Follow the user's brief, approved scope, product design system, brand, and platform before applying general guidance here. These rules do not impose Material Design or any particular visual theme. Platform-specific numbers below are sourced from official guidance; CSS preview measurements are explicitly implementation proxies, not conversions between pt, dp, and CSS px.

## 1. Authority, source material, and scope

Apply requirements in this order:

1. The user's explicit request and approved BA scope determine purpose, content, actions, states, and exclusions.
2. If the user identifies an imported Figma file or design system as authoritative, preserve its visual language, tokens, components, and assets. Use only its assets in strict-source mode.
3. Follow the product's existing brand and platform conventions.
4. Apply these rules where higher-priority sources leave a decision open.

Do not turn assumptions, examples, sample data, reference imagery, or adjacent workflows into product requirements. Do not add screens or features beyond the approved scope. If an essential decision is missing, choose a neutral fallback where safe and record the assumption; ask for clarification when the decision changes scope or user behavior.

Use realistic synthetic prototype data. Never include real credentials, secrets, or personal data. Keep internal actor IDs, rule IDs, and implementation details out of user-facing UI.

## 2. Purpose and content

- Give each screen one clear user purpose and make its main task apparent.
- Include only content and controls needed for that task or required by approved business rules.
- Put the essential information and action first.
- Remove duplicate explanations, filler, decorative labels, and content added only to fill space.
- Let content density follow the task. A simple form should be compact when practical; a content-heavy task may need scrolling. Never clip or hide required content to force a one-screen fit.
- Use a card only when a separate surface meaningfully groups content or actions. Prefer a list for repeated, similar items. Avoid wrapping every field or section in a card and avoid nested cards.
- Use imagery only when it supports the task, is requested, or belongs to the authoritative design system. Do not add imagery merely because an image source is available.
- For style previews that assign an illustration, decide whether it is a standalone hero or a screen background as part of the art direction. A background treatment is valid: use the scene as a large image layer behind/under the interface (often in the lower region for a compact sign-in screen), preserve its aspect ratio/crop intentionally, and add a surface or gradient so text and controls remain readable. Do not render a requested background as a small logo-side illustration or a detached block inserted between brand, greeting, and form.

## 3. Visual system and consistency

- Reuse the active design system's color, typography, spacing, shape, surface, elevation, and component tokens.
- When no system exists, establish a small, coherent set of visual roles and reuse them within the feature.
- Use semantic color roles where available. Pair foreground and background choices for readable contrast; do not communicate meaning by color alone.
- Derive preview palettes from the project's brand, domain, audience, and chosen art direction. Assign explicit roles for page/background, surface, text, primary action, and accent before rendering. Keep primary actions within that palette; do not introduce an unrelated high-saturation color (for example, an isolated orange CTA in a teal/navy direction) unless the project brand or a deliberate palette relationship supports it. Keep shared actions visually coherent within one option.
- Treat color as one coordinated system, not independent color picks for the background, cards, text, and buttons. Before rendering, map the available design-system/brand tokens to semantic roles: `background`, `surface`, `surface-variant/card`, `text`, `muted-text`, `border`, `primary-action`, `on-primary`, `link`, `accent`, and semantic status colors when needed. Every visible color must serve one of these roles or be an explicitly justified decorative color in the chosen direction; do not introduce unrelated one-off colors.
- Source priority for color is: user-approved design-system tokens, then supplied brand tokens, then a project-derived palette only where the system leaves a role unspecified. Never replace an imported primary or invent a competing brand palette. If a role is missing, derive a compatible tint/shade from an existing token or use a neutral surface/text role; preserve contrast and explain no new brand meaning through color.
- Keep foreground/background pairs intentional at the actual component surface: body and control text on their surface, button label on its fill, links on the containing surface, and borders against adjacent surfaces. Cards should use a restrained tonal step, border, or elevation from the same palette, not a separate theme. Primary, secondary, and alternate buttons must share the product's component language; their fills and outlines come from the same role map. Check text contrast against the exact rendered surface, not just the page background.
- Domain and audience inform the palette mood, but do not impose fixed industry color formulas. Do not assume every bank must be navy or every education app mint. Select a harmonious palette from the actual brand/design system and project context; an accent such as gold for rewards is allowed only when intentionally assigned a semantic role and used consistently.
- For a mobile screen preview, the viewport represents the app content canvas, not a device mockup. Do not draw a fake notch, Dynamic Island, black camera pill, sensor cutout, or other device hardware/system-chrome decoration inside the screen. Render a status/navigation bar only when approved screen content or the requested native-system treatment calls for it; reserve the safe area without painting a fake hardware shape over the header or title.
- Use hierarchy, borders, and elevation to clarify real relationships. Avoid giving every element equal emphasis or applying the same heavy shadow/card treatment everywhere.
- Keep a clear typography hierarchy for title, section heading, body, field label, supporting text, and status.
- Keep typography internally consistent on each screen: use one primary font family for body copy, labels, inputs, helper text, and buttons; a second family may be used for display headings only when the art direction deliberately calls for it. Define the type roles, weights, sizes, and line heights as a small scale and reuse them. Do not mix serif/sans styles, weights, letter spacing, or casing arbitrarily within one screen; preserve readable alignment and hierarchy at thumbnail size.
- On welcome, sign-in, and other identity-led entry screens, treat the brand and greeting as a deliberate visual group. Center-align the greeting by default when the art direction calls for a friendly/welcoming composition; if using editorial or institutional left alignment, align the subtitle with it and make that choice consistent rather than accidental. Do not place the greeting inside a form card by default; choose a shared surface only when it strengthens grouping and keeps the hierarchy clear.
- Use a limited set of text styles and the product's font. Do not impose Material tokens, Roboto, or another library's styling unless required by the product.

## 4. Copy and controls

- When the approved default actions contain separate groups, use a consistent spacing rhythm in every style direction. Keep any separator centered between equal divider rules, and align related actions consistently. These are preview implementation values, not native dp/pt conversions.
- Keep links that are explicitly present in the approved default action list within the option's semantic link/text color role. Do not introduce a link or an unrelated link color to satisfy a style convention.
- Define explicit foreground roles for the text and controls that exist in the approved default screen. Keep them legible against their actual surfaces and apply related roles consistently; do not invent optional controls or content to use a role.
- Across three style options for one project, preserve a shared interaction component language: identical approved action labels, button sizing, shape, typography, and alternate-action treatment only when alternate actions are approved. Let each option's primary-action fill follow that option's palette; it must harmonize with its screen and remain consistent within that option. Create visual variety through distinct background/hero palettes, composition, typography character, imagery, and surface treatment. The three dominant background/color families must be visibly different, not minor hue shifts.

- Write concise, specific, user-facing text in sentence case and use the product's terminology consistently.
- Button labels should state the action with a clear verb phrase. Keep them short where practical without clipping, truncating, or making the action ambiguous.
- When the approved default actions call for a separator, center it between the related actions, align its divider lines symmetrically, and give it enough vertical space that it reads as a separator rather than a button label.
- Give every input a persistent visible label. Placeholder text is a hint or example, never the only label.
- Error messages should explain the problem and the next step while respecting security and privacy rules.
- Use the simplest control that supports the user's decision. Do not add tabs, chips, dialogs, carousels, menus, or navigation unless the task needs them.
- Provide one visually dominant primary action. Make secondary actions quieter; use the companion multi-screen density guidance for numerical review targets.
- Keep icon style consistent. Give icon-only controls an accessible name.

## 5. Layout and responsive behavior

- Design for the actual available viewport width and height. Use content-driven sizing; avoid fixed heights that clip text or controls.
- Reflow the layout as space changes. Do not stretch a phone layout across desktop or shrink a desktop layout mechanically onto a phone.
- Prevent unintended horizontal overflow. Keep forms and reading content at a comfortable width on large screens.
- Reuse the product's spacing scale. If none exists, define a modest, consistent scale; multiples of 4 or 8 CSS pixels are a starting point, not a mandate.
- For Android-native layout, use the Android 4dp/8dp grid guidance and `dp` for layout dimensions; use `sp` for text so user font scaling works. For web previews, use a coherent CSS-pixel scale as a visual approximation; do not label CSS px as dp or pt.
- Respect device insets/safe areas and keep content within them. Use consistent page margins, align related content, and group elements by meaning. Platform guidance does not prescribe one universal composition such as placing a greeting inside or outside a form card; choose that from the project art direction and preserve clear grouping.
- Align related elements and use whitespace to clarify grouping. Keep independent controls sufficiently separated and usable.
- Support text wrapping, localization, zoom, and text scaling without overlap or loss of essential information.
- Keep the primary action associated with the task and reachable on compact screens.

## 6. Interaction and accessibility

- Design only the interaction states relevant to the approved workflow, such as enabled, focus, pressed, disabled, loading, success, empty, and error.
- Make each interactive control's appearance and accessible semantics agree with its current state and the result of activating it. Distinguish a control that reports a state from one that names the next action; use the product/platform convention consistently.
- For binary controls, make both states recognizable through an appropriate icon, label, selected treatment, or combination. Do not rely on color alone, and do not imply that every toggle must use a specific icon or slash treatment.
- For an icon toggle that is explicitly included in the approved screen, update its icon and accessible name/state when the value changes. For example, a password field that is revealed commonly uses an open-eye icon and a masked field an eye-off icon; activating the control must actually switch masking. Choose a clear accessible label such as “Show password” or “Hide password” that matches the action/state model used by the implementation.
- Apply the same state consistency to other controls: selected/unselected, expanded/collapsed, favorite/saved, checked/unchecked, and enabled/disabled. Use standard platform components and familiar conventions when available; do not invent a new icon meaning without a clear reason.
- When an approved action changes data or starts asynchronous work, show only the feedback states included in the approved state specification. Do not add loading, success, or failure UI to the default screen. Preserve entered data when an approved validation state occurs.
- When field validation is part of an approved triggered state, connect the message to its field, provide an appropriate next step, and expose the error state to assistive technology. Do not communicate validation only through border color or an icon.
- Do not expose sensitive values unnecessarily. If password visibility is explicitly approved as a default action, the control must toggle masking without changing the value; use the platform's secure-input behavior and make the current visibility/action understandable. Do not add this optional control by convention.
- On web, support keyboard navigation, semantic controls, accessible names, visible focus, and a logical reading/focus order. Never make hover the only way to access an action.
- Aim for WCAG AA contrast: at least 4.5:1 for normal text and 3:1 for large text and meaningful UI graphics. Check actual colors rather than assuming token pairs always pass.
- Keep touch targets usable and separated. Official guidance: Apple recommends at least 44×44 pt for iOS button hit regions; Android recommends at least 48×48 dp for touch targets. These are platform-specific logical units and are not interchangeable with CSS px. In this HTML preview renderer, enforce 48×48 CSS px as a conservative visual proxy when a mobile platform is unspecified; for an explicit native platform, follow its native units at implementation time. Keep neighboring actions visually distinct with comfortable separation; Android accessibility guidance recommends at least 8dp between focusable elements where practical, while Apple advises sufficient spacing. The preview may use 8 CSS px as a review proxy, not a platform conversion. When a checkbox/radio glyph is small, make its wrapping label the full hit area.
- Typography should use a clear hierarchy and remain usable with user text scaling. On Android use `sp` and appropriate Material type roles where Material is the chosen system; Material roles are guidance, not a mandate to adopt Material styling. On Apple platforms support Dynamic Type and avoid clipping at larger text sizes. In web previews, allow wrapping and content-driven heights rather than treating a fixed px font size as a native platform rule.
- Align related form fields to one consistent content column. Keep the left and right edges of peer fields aligned; align labels and supporting text to their field. Center a button label unless the design system defines a clear leading-icon pattern. Do not let text, controls, or focus rings overlap, clip, or escape their containers.
- Keep readable content and controls inside the visible content column and safe area. Do not put them inside an overflow-clipping container. Intentional image cropping is allowed only on a dedicated decorative background/illustration layer, separate from interactive content; mark decorative imagery appropriately (`alt=""` for decorative `<img>`, or `aria-hidden="true"` for decorative SVG) and never crop functional controls.
- Use content-driven component heights and allow localized text to wrap. Never force a fixed height that truncates a title, label, helper, or button action.
- Respect reduced-motion preferences. Motion should communicate feedback or a state change and must not delay interaction.
- Provide useful alternative text for informative images; mark decorative imagery so assistive technology can ignore it.

## 7. Per-screen review

Before presenting a screen as complete, review it at the target size and relevant responsive sizes. Confirm:

- Purpose, content, controls, and states match the approved scope.
- Required business rules and user-facing text are represented correctly.
- The main task and primary action are easy to find.
- Interactive controls behave as shown; icons, labels, accessible names, and feedback stay consistent across their relevant states.
- No unnecessary card, section, copy, image, or decoration remains.
- Text, controls, focus, contrast, and touch interaction are usable; nothing clips or overlaps.
- There is no unintended horizontal scrolling and larger text remains usable.
- Authoritative Figma/design-system assets and styles are preserved.

If a check fails, revise the screen before calling it complete. A visual review is required; automated checks alone are insufficient.

## 8. Official platform references

Use the current platform documentation when selecting native dimensions or behavior; do not present these as universal web/CSS pixel rules:

- Apple Human Interface Guidelines — [Layout](https://developer.apple.com/design/human-interface-guidelines/layout), [Buttons](https://developer.apple.com/design/human-interface-guidelines/buttons), and [Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility).
- Android Developers — [Layout basics](https://developer.android.com/design/ui/mobile/guides/layout-and-content/layout-basics), [Grids and units](https://developer.android.com/design/ui/mobile/guides/layout-and-content/grids-and-units), [Content structure](https://developer.android.com/design/ui/mobile/guides/layout-and-content/content-structure), and [Accessibility for views](https://developer.android.com/guide/topics/ui/accessibility/views/apps-views).
- Material 3 — [Typography in Compose](https://developer.android.com/develop/ui/compose/designsystems/material3).
- Contrast criterion — [WCAG 2.2, Contrast Minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).

Art direction decisions (palette, hero/background placement, illustration, title alignment, and whether greeting and form share a surface) are project-specific choices, not requirements imposed by Apple, Android, or Material. Preserve approved content while arranging those regions clearly and avoiding overlap.

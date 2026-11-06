# Project-Aware Screen Style Preview

Use this skill when preparing visual directions for a user to compare before the full UI specification is written.

## Understand the design brief

- Treat the approved screen scope and each screen's confirmed visible regions and actions as the only source of product content.
- Understand the product, audience, domain, platform, and screen purpose before choosing a visual language.
- Choose the representative screen from its confirmed content and interaction richness. Never assume a particular screen type or industry.
- Keep behavioral states as design constraints. Show the normal/default state in a style preview; do not turn state names into controls or test cases.

## Plan three art directions for this project

- Keep the same screen, information, controls, and meaning in all three options.
- Derive the three names and art directions from this product, its audience, domain, and approved screen; do not reuse the same generic style trio for every project.
- Give each option a memorable, project-relevant visual concept. Distinguish them through composition, visual hierarchy, typography, palette, surface treatment, shape language, and imagery—not by color alone.
- Select the appropriate design vocabulary for the product and audience. A learning product may use learning-related visual motifs; healthcare, commerce, finance, and other products need their own relevant vocabulary. These are visual cues, never new product features.
- Make a small design plan for each option: focal point, layout/composition, type character, color roles, and one signature visual detail. Check that the three plans are recognizably different before writing markup. Use the assigned composition and motif in the rendered UI, not only in the card's descriptive text.
- Name explicit background, surface, text, primary-action, link, and accent roles, grounded in the project's brand/domain. Keep all three directions visibly different in dominant color family and composition. Reuse one shared button component language across the gallery: same confirmed labels, size, shape, typography, and alternate-action treatment, while each primary fill follows its own palette. Keep secondary links such as “Quên mật khẩu” in a consistent readable link role, not an isolated orange. Center brand, greeting, and supporting copy across a friendly welcome/sign-in gallery unless the user asks for editorial alignment; center “Or/Hoặc” symmetrically with at least 12 CSS px above and below the divider.
- Give each option one coherent type system: primary family across body, labels, inputs, helper text, and buttons; an optional display family only when planned for headings. Set a small hierarchy of sizes, weights, line heights, and letter spacing, then reuse it. Visual styles may differ between options, but typography must not vary arbitrarily within one screen.
- When the product and screen archetype support it, include one original inline SVG or CSS illustration that reflects the product's industry and audience. Keep it subordinate to the task and do not use it to invent content or capabilities.
- If an art direction assigns a visual, make it visibly large enough to define the composition. It can be a hero or a large background scene behind/beneath the UI; for a compact sign-in screen, a lower-screen backdrop can add warmth without pushing the form out of reach. Do not place a requested backdrop as a detached illustration block between logo, greeting, and form.
- Keep assigned illustrations separate from the brand wordmark. Use the complete image as a background/scene layer in a hero or screen region; never turn it into a logo, app icon, badge, avatar, or header ornament. Preserve readability with a surface or gradient behind foreground text and controls.
- Treat confirmed screen content/actions as a whitelist for factual claims and functional copy. Remove invented branding, slogans, fake identifiers, security/legal claims, and unsupported informational labels. Restrained decorative footer styling may remain when it adds no facts and does not crowd the screen.
- Avoid default centered forms, identical nested cards, sterile blank space, generic SaaS chrome, decorative labels, fabricated statistics, and unearned luxury/editorial styling. Do not let all options collapse to the same white form with a different accent.

## Render and critique

- Render each HTML preview at the target platform dimensions before showing it. Apply official platform guidance accurately: iOS hit regions 44×44 pt, Android targets 48×48 dp, Android layout uses dp and text uses sp. The browser preview's 48×48 CSS px threshold is a conservative QA proxy, not a unit conversion. Respect safe areas/insets, text scaling, consistent spacing, and clear separation between brand, greeting, hero, form, and actions; the grouping is project-specific rather than mandated by a platform.
- Run DOM layout and accessibility checks on every rendered preview. For cross-platform mobile previews, enforce 48×48 CSS px minimum hit areas; align peer form fields to a shared column and reject clipped text, overflow, or overlapping controls. A failed check requires a repair and a fresh render.
- On mobile, preserve safe-area space and deliberate separation between brand, title, form, and actions. Review vertical balance at full screen and thumbnail scale; reject controls or headings crammed against the top with unintended empty space below.
- Inspect the screenshots, not only the source markup. Check visual hierarchy, readable text at thumbnail size, spacing, clipping, contrast, source-faithful labels, and whether the three styles look different.
- Treat critique findings as blocking and actionable: enlarge an assigned scene if it reads as an avatar; remove unsupported factual labels/claims, but do not reject decorative footer treatment solely for being outside BA copy; remove stray bottom fragments such as isolated dots/squares, clipped image scraps, or broken rules; rebalance excess whitespace through layout and image scale, never by inventing copy. Re-render and review targeted candidates again after each repair.
- Remove invented copy, test/demo/debug UI, fake version numbers, fake contact details, and any control not supported by the approved screen.
- If the screenshot looks generic, cramped, sparse, illegible, lacks a relevant focal graphic where appropriate, or shares the same composition as another option, revise the HTML using specific visual-review notes and render it again.
- Do not show the gallery when a required visual review fails, cannot be parsed, or still reports issues after the repair pass. Explain that the preview was withheld and invite a retry; never silently accept an unchecked or failed render.
- Prefer a small, purposeful inline SVG illustration or CSS composition over random emoji or external placeholder imagery. Keep illustrations relevant and subordinate to the screen's job.

## Output discipline

- Return one self-contained HTML body fragment per style, using the project's supported Tailwind/runtime constraints.
- Preserve the approved screen's identity, confirmed fields/actions, and product language.
- Do not add behavior or visible content to make the preview look fuller. Use composition, typography, color, and relevant illustration to create visual richness.

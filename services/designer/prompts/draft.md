Build the default screen `{{screen_id}}` now.

Screen:
{{screen}}

Build only the initial state shown immediately when the user opens the screen. State notes and conditional branches are stored separately and are not part of this render input.

Selected local illustration for this screen (if applicable):
{{style_asset}}

Must show (exact texts): {{must_show}}
Images: use only the supplied local illustration or user-provided assets. Do not fetch, search for, or add external images.
Other screens (for `data-goto`): {{others}}

UX guidelines for this screen (UI/UX knowledge base):
{{ux}}

The approved screen payload is the boundary. Render only its default fields, content, and actions. `sections` and `actions` describe required components and behavior; they are not necessarily literal copy. Use concise, natural user-facing labels for controls, and print text verbatim only when it appears in `must_show` (which comes from explicit `visible_copy`). Treat `default_actions` as the exhaustive allowlist for interactive controls: do not add convenience actions, QR scanners, icon buttons, or clickable affordances unless that action is explicitly approved. Never expose specification prose as a label, button, or paragraph. Do not add conditional errors, warnings, success/loading variants, state panels, state controls, or messages from behavioral notes. Do not add unsupported controls, policy/support/security claims, identifiers, or factual copy. For inputs, render one visible label and one placeholder source; never place an absolutely positioned overlay/span that repeats the input's placeholder. If the approved visible copy includes a placeholder, keep it as the native `placeholder` attribute and use a distinct approved field label. Keep the default UI visible in plain HTML on first paint; do not hide default content behind `x-show`, `x-cloak`, collapsed content, or a state-dependent Alpine expression. Do not hardcode a state that occurs only after an interaction. On short mobile screens, keep the brand/title, task fields, and primary action in a compact, balanced vertical group. Do not use `min-h-screen` with `justify-between` or a `flex-1` spacer to pin the CTA to the bottom when that leaves a large empty region between related content. Use consistent 16–24px section gaps, keep related labels/fields/actions on a shared alignment axis, and center the overall content column with `mx-auto`/`max-w` while choosing left- or center-aligned text intentionally for the screen archetype. Preserve at least 48px hit areas for interactive controls. Keep the screen at its normal app viewport: use responsive flow and scrolling for long content, with a non-overlapping action area. A fixed/sticky action bar must not cover selectable cards (including radio/option cards), form controls, or the last content item; prefer normal flow, or reserve enough scrollable bottom space for the full covered item and safe area. Do not enlarge cards or shrink controls/text to force everything above the fold. For a selected illustration, use the supplied asset token as a separate hero/background layer only when the screen's `visual_asset_role` is `hero` or `background`; never use it as a logo, avatar, badge, or header mark. Use only the option's color and typography tokens.

Global screen-title alignment rule: center the primary screen title and any directly associated subtitle or introductory copy within the screen content column across all screen archetypes. Keep navigation actions in their established positions; keep body copy, form labels, inputs, table/list data, and other task content aligned for scanning (normally left-aligned). Only an explicit user instruction may override the centered primary-title rule. Apply this consistently without hardcoding specific screen names or title text.


{{reference}}

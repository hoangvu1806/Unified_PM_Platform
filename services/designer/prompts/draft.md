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

The approved screen payload is the boundary. Render only its default fields, content, and actions. `sections` and `actions` describe required components and behavior; they are not necessarily literal copy. Use concise, natural user-facing labels for controls, and print text verbatim only when it appears in `must_show` (which comes from explicit `visible_copy`). Never expose specification prose as a label, button, or paragraph. Do not add conditional errors, warnings, success/loading variants, state panels, state controls, or messages from behavioral notes. Do not add unsupported controls, policy/support/security claims, identifiers, or factual copy. Keep the default UI visible in plain HTML on first paint; do not hide default content behind `x-show`, `x-cloak`, collapsed content, or a state-dependent Alpine expression. Do not hardcode a state that occurs only after an interaction. Keep the screen at its normal app viewport: use responsive flow and scrolling for long content, with a non-overlapping action area. Do not enlarge cards or shrink controls/text to force everything above the fold. For a selected illustration, use the supplied asset token as a separate hero/background layer only when the screen's `visual_asset_role` is `hero` or `background`; never use it as a logo, avatar, badge, or header mark. Use only the option's color and typography tokens.

{{reference}}

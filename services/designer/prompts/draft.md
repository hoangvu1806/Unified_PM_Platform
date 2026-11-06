Build the screen `{{screen_id}}` now.

Screen:
{{screen}}

Behavioral state variants available only in the external Canvas Test menu (do not render these as controls):
{{states}}

Selected local illustration for this screen (if applicable):
{{style_asset}}

Must show (exact texts): {{must_show}}
Business rules to reflect: {{rules}}
Photos to use (slot → URL): {{images}}
Other screens (for `data-goto`): {{others}}

UX guidelines for this screen (UI/UX knowledge base):
{{ux}}

The screen specification is the approved boundary. Do not add any controls, actions, scenarios, policy/support/security claims, identifiers, or other factual copy that is not supported by it. Behavioral states are Test-only metadata: never render a state picker, simulator or test button in the product screen. Keep the default UI visible in plain HTML on first paint; do not gate default content behind `x-show`, `x-cloak`, collapsed content, or state-dependent Alpine. Use `data-state` only for non-default variants. For a selected illustration, use the supplied asset token as a separate hero/background layer only when the screen's `visual_asset_role` is `hero` or `background`; never use it as a logo, avatar, badge, or header mark. Use only the option's color and typography tokens.

{{reference}}

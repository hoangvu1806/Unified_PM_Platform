{{task}}

Approved screen specification (source of truth):
{{approved_screen}}

Generated UI spec for this screen:
{{screen_spec}}

Selected visual contract (preserve it):
{{visual_contract}}

The attached image is the screen rendered at {{width}}px (default state). Automated checks:
{{checks}}

Review it as a design lead against the art direction, the skill and this checklist (UI/UX knowledge base):
{{checklist}}

Also audit the screen-sequence identity and content rules: the brand mark must be consistent and distinct from decorative imagery; title and supporting copy must have deliberate alignment; composition must separate hero/background, content, actions, and any approved footer without overlap or large accidental gaps; copy must not repeat itself; and demo values or success feedback must not appear as real/default state. Preserve the screen's own task layout rather than forcing a shared template.

Treat additions outside the approved screen as defects. Remove invented links/buttons, state simulators, test/demo controls, sample account values, security/support/policy claims, identifiers, and navigation. A state named in the spec is not a control to switch states. Match the selected palette, typography, composition and illustration role. Do not add content to fill empty space.

The initial/default view must render visibly on first paint. Keep default content as ordinary visible HTML; do not hide it behind Alpine `x-show`, `x-cloak`, collapsed containers, or `data-state`. For Splash, preserve the approved loading indicator and initialization/session-check copy as the visible default; error variants stay hidden until selected from the Canvas Test menu. Never put Test controls in the app screen.

Reply in ONE of these forms:
- `OK` — only when the checks list no errors and the design needs no change;
- one or more edit blocks, each copying an exact, unique snippet of the current HTML:
<<<<<<< SEARCH
exact snippet from the current HTML
=======
replacement
>>>>>>> REPLACE
- or, for a rework, the complete new HTML fragment.

Fix every error and missing text first; then improve hierarchy, spacing, alignment and polish. Nothing else in the reply.

Current HTML:
{{html}}

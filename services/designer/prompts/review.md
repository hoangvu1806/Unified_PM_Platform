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

Global screen-title alignment rule: center the primary screen title and any directly associated subtitle or introductory copy within the screen content column across all screen archetypes. Keep navigation actions in their established positions; keep body copy, form labels, inputs, table/list data, and other task content aligned for scanning (normally left-aligned). Only an explicit user instruction may override the centered primary-title rule. Apply this consistently without hardcoding specific screen names or title text.

Review this build as the initial/default screen only. Conditional error, warning, loading, success, and branch content are stored as reference metadata and are intentionally omitted from this build. Report it as a defect if such state-only copy or panels appear in the initial screen. Do not require or suggest implementing after-trigger behavior during this build.

Treat screen sections/actions as semantic descriptions unless exact text is listed under `visible_copy`. Accept concise natural user-facing labels that satisfy the described component; do not require or preserve explanatory phrases like "field with..." or "button to..." as visible labels. Only `must_show` is verbatim copy.

Treat additions outside the approved screen as defects. Remove invented links/buttons, state simulators, test/demo controls, sample account values, security/support/policy claims, identifiers, and navigation. A state named in the spec is not a control to switch states. Match the selected palette, typography, composition and illustration role. Do not add content to fill empty space.

Keep default content visible on first paint. Keep bottom action bars outside scrollable content and fix any rendered overlap, including content covered in the initial viewport.

The initial/default view must render visibly on first paint. Keep default content as ordinary visible HTML; do not hide it behind Alpine `x-show`, `x-cloak`, collapsed containers, or state-dependent visibility. For Splash, preserve only the approved initial/default content. Omit error variants from this build. Never put Test controls in the app screen.

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

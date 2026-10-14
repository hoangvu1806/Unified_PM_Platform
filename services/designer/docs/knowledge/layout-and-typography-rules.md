# Layout and typography rules

This file converts general design-system guidance into executable rules for the
screen composer and OpenPencil page designer. It is product-neutral. The active
product brief and selected design system still take precedence when they define
an explicit value.

## Source references

- Primer Stack: https://primer.github.io/brand/layout/Stack/
- Primer typography source: https://github.com/primer/design/blob/main/content/foundations/typography.mdx
- GOV.UK layout: https://design-system.service.gov.uk/styles/layout/
- GOV.UK type scale: https://design-system.service.gov.uk/styles/type-scale/
- GOV.UK buttons: https://design-system.service.gov.uk/components/button/
- USWDS spacing tokens: https://designsystem.digital.gov/design-tokens/spacing-units/
- USWDS layout grid: https://designsystem.digital.gov/utilities/layout-grid/
- Material 3 foundations: https://m3.material.io/foundations/

## Core layout model

- Build each screen from one root frame with explicit width and height.
- Use a parent layout container for every related group of elements.
- Use a vertical stack for mobile forms and sequential content.
- Use a horizontal stack only for items that belong on the same row.
- Use a grid for two-dimensional repeated content; do not fake a grid with
  arbitrary absolute positions.
- Keep the screen's primary content inside a consistent horizontal content rail.
- Use equal leading and trailing insets for related content unless the brief
  explicitly calls for an asymmetric composition.
- Prefer `fill` sizing for form fields, primary actions and content regions.
- Use `hug` sizing for labels, icons and short links.
- Do not let a child frame silently exceed its parent frame.
- Keep layout direction and alignment explicit; never rely on renderer defaults.

## Mobile defaults

These are starting values, not immutable brand tokens:

- Viewport reference: 390 x 844 for mobile screens when no other viewport is
  specified.
- Screen side padding: 16px; use 24px when the visual direction needs more air.
- Form and action controls normally use the same available width.
- Stack field groups vertically rather than putting unrelated fields side by side.
- Keep the primary action visible in the initial viewport when possible.
- Respect safe-area-like top and bottom space and do not place important content
  against the frame edge.

## Mobile root frame and screen boundary

- Every mobile screen must have exactly one top-level root frame. The semantic
  specification may use `root_canvas` as an internal ID, but the live frame
  name must be unique and preserve the screen identity, for example
  `SCR-01 · Login`, `SCR-02 · Authenticating`, `SCR-03 · Dashboard`.
- The root frame must be an explicit 390 x 844 frame unless the brief specifies
  another mobile viewport.
- Give the root frame an opaque background fill; do not rely on the page canvas
  color to represent the screen background.
- Enable clipping on the root frame so no child layer renders outside the screen
  bounds.
- Keep every visible child, text node and control fully inside the root frame.
- When a persistent screen boundary is required in the editor, add a subtle 1px
  neutral stroke to the root frame. The Figma selection outline alone is not a
  permanent border and disappears when the frame is deselected.
- Do not create a second outer canvas that is larger than the root frame unless
  it is explicitly requested as a device mockup.

## Multi-screen flow canvas

- A multi-screen flow must use one shared Figma page for the flow, not one page
  per screen.
- Each requested screen must be a separate top-level frame on that shared page.
- Keep a consistent grid for screen frames: equal horizontal and vertical gaps,
  aligned columns and no accidental overlap.
- For mobile screens, use the 390 x 844 frame size and a minimum 96px gap between
  adjacent frames unless the brief explicitly specifies another arrangement.
- Place screens in reading/order sequence and preserve their screen IDs in frame
  names so prototype connections remain understandable.
- Before completion, inspect the page-level bounding boxes and verify that no two
  root frames overlap or are positioned on top of one another.

## Layer naming and section contract

- Use stable semantic section names rather than generic `Frame`, `Text` or
  `Icon` names. A mobile screen should normally expose named sections such as
  `status_bar_section`, `header_section`, `main_content`, `form_section` and
  `support_footer` only when those sections exist.
- `status_bar_section` is a frame/container, never a text node or a loose icon.
  Its children must be a time text node and a named `status_icons_cluster`.
- `status_icons_cluster` is a horizontal frame containing named icon nodes such
  as `wifi_icon` and `battery_icon`; keep the same component family, size,
  baseline and right inset across all screens in the same flow.
- Do not place direct text/icon children beside an unnamed wrapper when they
  belong to the same semantic section. Use the same hierarchy contract on every
  screen so editing one section can resolve its exact node path.
- A screen edit must resolve `screen_id -> page_id -> root_node_id -> section
  node_id`. Never select a node by `root_canvas`, duplicate name or first root.

## Spacing scale

- Use a small, repeatable spacing scale: 4, 8, 12, 16, 24, 32, 40 and 48px.
- Use 4px or 8px increments for internal component spacing unless the selected
  design system provides another token.
- Label-to-input gap: 4-8px.
- Field-to-field gap: 12-16px.
- Related control group gap: 16-24px.
- Section gap: 24-32px.
- Screen-level top and bottom breathing room: 24-48px.
- Do not invent a new spacing value to repair one local alignment problem.

## Alignment and distribution

- Align labels, inputs, helper text and buttons to the same leading and trailing
  edges within a form.
- Use `items="stretch"` for form controls that should share a width.
- Use `items="center"` for icon-and-label rows when their visual centers should
  align.
- Use `justify="start"` for normal reading and form flow.
- Use `justify="center"` only for splash, empty, success or status content.
- Use `justify="between"` only when the first and last items intentionally
  anchor opposite edges of a row.
- Do not use `justify="between"` to disguise missing spacing tokens.
- Keep repeated controls equal in width and height when they have equivalent
  priority.
- Use one obvious primary action per screen. Secondary actions should not look
  like competing primary actions.
- Center button labels vertically and horizontally inside the button surface.
- Place a form's main action on the same alignment rail as the fields unless the
  product pattern explicitly calls for another placement.

## Text wrapping and overflow

- User-facing text must wrap when it exceeds the available width.
- Give every text node a real parent width; never pair `fill` text with an
  unresolved parent size.
- Give text beside an icon or control flexible space so it can wrap instead of
  pushing the control outside the frame.
- Use explicit width constraints and line height for Vietnamese copy with
  diacritics.
- Prefer wrapping over truncation for headings, labels, instructions and errors.
- Use `maxLines` only when truncation is an intentional product decision.
- Do not clip visible copy. Increase the parent height or allow the text node to
  grow when it wraps.
- Keep body text readable by limiting unusually long lines; use a narrower text
  container instead of shrinking the font excessively.
- Do not justify ordinary UI copy. Prefer the reading direction's leading edge
  alignment; center only short, isolated status or brand copy.
- Centered headings or status messages must set both an explicit text width and
  `align="center"`; when they wrap, the parent must grow vertically and keep
  the same center rail. Do not leave wrapped text at the renderer's default
  leading alignment.

## User-provided image and logo placement

- Identify the image's role and the screen where the request calls for it. A
  logo, mascot, illustration, photograph and background serve different purposes;
  an upload does not automatically belong on every screen.
- Choose a semantic parent section and reserve a bounded image area before
  composing nearby text. A centered login mascot may sit above the title; a
  supporting mascot may sit beside a header only when the text column remains
  wide enough for longer copy.
- Preserve the source aspect ratio. Prefer contain for logos and mascots; crop
  only when the image's role permits it. Judge the visible subject, including
  transparent margins, when sizing and aligning the image. Do not cut off
  meaningful details to make a box fit.
- Define spacing from the visible subject to the status bar, heading,
  description and next section using the screen's spacing scale. The subject
  must not touch or overlap text, controls, status icons or the screen edge.
- Give nearby text a real width and allow it to wrap and grow. If longer copy
  crowds a side-by-side header, reduce the image within its intended bounds or
  use a vertical composition. Do not shrink text below the type scale or hide
  it behind the image.
- After the original image is applied, inspect the rendered screen. Source
  dimensions and transparency can make the final image differ from its marker.

## Status bar and small-detail consistency

- Keep time and signal, Wi-Fi and battery icons inside one status-bar section
  with stable left/right insets across the flow. Align the icons visually on
  one row, using consistent size, weight and spacing.
- Check status-bar contrast against the header and clearance from screen edges.
  A longer time string must not push the icon cluster or collide with content.
- Inspect icon-to-label baselines, button-label centering, checkbox alignment,
  input padding and trailing icon insets at the rendered viewport. Repeated
  controls should share dimensions and alignment rails.

## Typography

- Define a type scale before composing a screen: display, heading, title, body,
  label and caption roles.
- Use one font family and a small set of approved weights.
- Use semantic roles instead of arbitrary font sizes for each node.
- Use line-height tokens that create a consistent vertical rhythm.
- Keep labels visibly distinct from placeholder text; a placeholder is not a
  replacement for a persistent field label.
- Use weight and size to establish hierarchy before adding color or decoration.
- Do not alter letter spacing casually; use the selected type scale's values.
- Verify that the chosen font renders Vietnamese diacritics correctly.
- Keep headings concise and allow them to wrap when the screen is narrow.

## Forms and controls

- Use one vertical form column on mobile unless the brief explicitly requires a
  different composition.
- Keep each label visually close to its field and aligned to the same rail.
- Keep helper and error text close to the field that it describes.
- Use one primary button and make it easy to find after the final required field.
- Keep secondary links visually subordinate and do not place them where they can
  be mistaken for the primary action.
- Keep visibility toggles and trailing field controls inside the field bounds.
- Use consistent control heights within a form.
- Never render a disabled state unless the specification explicitly says that the
  control is disabled.
- Maintain logical order: heading, explanation, fields, recovery/alternative
  actions, primary action, then support or legal content when applicable.

## Quality gate before completion

- No visible child is clipped, overflowed or accidentally outside its parent.
- All text is readable and wraps without overlapping another node.
- Verify long Vietnamese strings at the actual 390px viewport; no text may
  expand horizontally beyond its content rail or root frame.
- Verify the root frame background, clipping behavior and optional boundary
  stroke in the rendered screenshot, not only in the layer tree.
- Related elements share alignment rails and spacing tokens.
- Primary and secondary actions are visually distinguishable.
- Repeated controls have consistent dimensions.
- The screen is balanced within its viewport; large empty regions or crowded
  corners require an intentional explanation in the design plan.
- Inspect the actual screenshot and live node geometry before declaring the page
  complete.
- When an uploaded image is used, verify its final visible bounds and distance
  from text, status icons and the next section. Correct crowded spacing on the
  canvas and inspect the result again.

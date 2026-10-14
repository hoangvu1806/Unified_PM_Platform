# Design System v0.3 knowledge

## Foundations
Small starter library centered on Open Sans, bright blue action color, 24px icon geometry, and simple media primitives. Use its limited component inventory honestly; compose custom primitives when a suitable component is absent.

## Button
Aliases: cta, action, submit
Roles: primary-action, secondary-action
Source patterns: set=button
Slots: label=text, leading-icon=instance-swap, trailing-icon=instance-swap
Use: Simple immediate actions.
Avoid: Fabricating unsupported semantic variants.

## Media
Aliases: image, thumbnail, photo
Roles: media, product-media, illustration
Source patterns: set=media
Slots: image=image
Use: Rectangular visual content with a known aspect ratio.

## Checkbox
Aliases: check, multiple choice
Roles: multi-select, selection-control
Source patterns: name=checkbox
Slots: label=text
Use: Independent selections.

## Radio
Aliases: option, single choice
Roles: single-select, selection-control
Source patterns: name=radio
Slots: label=text
Use: One choice from a short visible set.

## Section Label
Aliases: heading, eyebrow, section title
Roles: section-heading, content-label
Source patterns: name=section label
Slots: label=text
Use: Compact section context.

## Steps
Aliases: progress steps, sequence
Roles: progress, ordered-process
Source patterns: name=steps
Slots: label=text, content=repeated
Use: A genuinely ordered multi-step process.

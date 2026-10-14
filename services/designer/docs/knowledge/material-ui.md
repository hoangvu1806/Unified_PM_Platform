# Material UI knowledge

## Foundations
Material hierarchy uses tonal surfaces, elevation only when spatial separation is real, an 8px layout rhythm, readable state layers, and explicit responsive breakpoints. Components should retain their semantic variants and accessibility states.

## Button
Aliases: cta, action, submit, purchase
Roles: primary-action, secondary-action, destructive-action
Source patterns: set=Button
Slots: label=text, start-icon=instance-swap, end-icon=instance-swap
Use: Immediate actions; contained for primary, outlined or text for lower emphasis.

## Icon Button
Aliases: icon action, compact action
Roles: icon-action, toolbar-action
Source patterns: set=Icon Button
Slots: icon=instance-swap
Use: Familiar actions with an accessible label supplied by the product.

## Text Field
Aliases: input, field, search
Roles: text-input, search-input, form-input
Source patterns: set=Text Field
Slots: label=text, value=text, helper=text, leading-icon=instance-swap
Use: Typed input with persistent context and validation space.

## Select
Aliases: dropdown, picker, choice
Roles: single-select, form-select
Source patterns: set=Select
Slots: label=text, value=text
Use: One choice from a longer option list.

## Checkbox
Aliases: check, multiple choice
Roles: multi-select, selection-control
Source patterns: set=Checkbox
Slots: label=text
Use: Independent or multiple selections.

## Switch
Aliases: toggle, on off
Roles: binary-control, settings-control
Source patterns: set=Switch
Slots: label=text
Use: Immediate binary settings.

## Tabs
Aliases: tabs, view switcher
Roles: local-navigation, view-switcher
Source patterns: set=Tabs
Slots: label=text, icon=instance-swap
Use: Peer destinations within one context.

## Dialog
Aliases: modal, confirmation
Roles: dialog, confirmation-dialog
Source patterns: set=Dialog
Slots: title=text, message=text, content=content-zone
Use: Focused decisions or short interrupting tasks.

## Alert
Aliases: warning, error, success, notice
Roles: feedback, status-message
Source patterns: set=Alert
Slots: title=text, message=text, icon=instance-swap
Use: Important contextual status.

## Card
Aliases: content surface, summary
Roles: content-group, summary-card, product-card
Source patterns: set=Card
Slots: title=text, body=text, media=image, actions=content-zone
Use: One coherent object or action group.

## Data Grid
Aliases: table, rows, columns
Roles: data-display, tabular-data
Source patterns: set=Data Grid
Slots: content=repeated
Use: Large comparable datasets on wide viewports.

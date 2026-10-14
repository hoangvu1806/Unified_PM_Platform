# Design craft: evidence, direction, execution

Researched 2026-09-22. This is an editorial synthesis for the designer's context,
not a style validator. The user's brief and chosen design system take precedence.
Accessibility requirements are distinct from aesthetic suggestions; attractive
screens alone cannot establish WCAG conformance.

## Start with a point of view

Identify the audience, their immediate task and the information that changes their
decision. Choose a short visual thesis: precise and instrument-like, calm and
human, kinetic and playful, or another direction grounded in this product.
Record palette roles, type roles, density, composition and one signature gesture
in the skeleton. Compare a couple of plausible directions briefly; commit and
build. Avoid endless ideation and generic style adjectives without decisions.

## Hierarchy and composition

Scale, contrast, balance and perceptual grouping help readers recognize priority
and relationships. Make the first focal point useful. Use proximity and alignment
to associate content before adding boxes. Balance visual weight rather than
requiring symmetry. Similar controls should look related; unrelated information
need not become identical cards. Repetition can establish rhythm while a
meaningful exception creates emphasis. This interpretation follows
[Nielsen Norman Group's five visual principles](https://www.nngroup.com/articles/principles-visual-design/).

## Expressive, usable identity

Expressive interfaces can guide attention through deliberate shape, size, color
and motion. Google's research describes tested expressive directions, not a
universal aesthetic prescription. Adapt the idea to the audience and task; do not
copy a trend's surface everywhere. See
[Google Design's account of Material expressive research](https://design.google/library/expressive-material-design-google-research).

Possible explorations: editorial type with a precise data grid; product-specific
diagrams as a focal point; warm materials with technical labels; a restrained
canvas with one vivid interaction; asymmetric composition around real imagery.
These are starting points authored for this knowledge file, not mandatory recipes.
An operational dashboard may earn its identity through excellent data hierarchy
and density. A luxury direction may use thin display type. Flat white headers,
quiet buttons, square corners and dense layouts are all legitimate when intended.

## Components are the vocabulary

After skeleton JSON, retrieve options for every control family and variant,
including navigation, inputs, actions, feedback, overlays and repeated data.
Inspect actual dimensions, editable text slots and available icons before drawing.
Reuse real instances; do not merely copy their names into a prompt. Compose the
page around the components' behavior. Extend only an actual library gap and record
it. Keep a coherent icon family, optical weight and alignment. Never silently
replace an unavailable semantic icon with an unrelated sparkle.

## Type, color, content

Use type scale, line length, weight and whitespace as complementary tools. Choose
fonts that support the language, especially Vietnamese diacritics. Check long
labels and realistic data rather than optimizing only short sample text. Choose
color by semantic role; status needs text or shape as well as hue. Derive visual
character from the brief rather than imposing blue CTAs or dark heroes. Use
meaningful domain copy and an obvious action vocabulary; never invent testimonials
or present fabricated business metrics as verified facts.

## Accessibility baseline

WCAG 2.2 AA text contrast is generally at least 4.5:1, or 3:1 for large text
(18pt regular / 14pt bold), with specified exceptions such as logos and inactive
controls. Test actual foreground/background combinations, including text over
images; a palette alone is not evidence of compliance.
[W3C contrast guidance](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).

WCAG 2.2 AA pointer targets generally require 24 by 24 CSS pixels or sufficient
spacing under the criterion, with exceptions including inline and equivalent
targets. Larger touch areas can improve comfort; 44px is not the universal AA
minimum. Plan visible focus and readable states. A static mockup cannot verify
keyboard access, semantics, reflow or reduced motion in an implementation.
[W3C target-size guidance](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html).

## Build, observe, refine

Build usable structure with the retrieved components first. Then inspect the
actual screen, not just source code: clipped labels, spacing rhythm, density,
alignment, image crop, component fit and the intended focal point. Repair real
errors through tools. Add decoration only where it reinforces the visual thesis.
Keep intentional overlap distinct from content collisions. A failed tool call
does not invalidate the design direction. Reinspect after changes; stop when the
screen meets the brief. Report missing visual evidence honestly.

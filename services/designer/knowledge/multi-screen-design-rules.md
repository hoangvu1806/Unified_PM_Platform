# Multi-Screen Design Rules for Designer Agents

**Document type:** Required cross-screen design instructions, plus review heuristics for screen density and text length.

Use this file when a feature has multiple screens. It does not replace the companion `material-ui-ux-knowledge-reference.md`: that file owns source authority, scope, per-screen components, accessibility, responsive behavior, imagery, and general review rules. Follow its priority order when rules appear to conflict. This file does not require Material Design.

The cross-screen rules below apply only when there are sibling screens. Density and text-length targets are review heuristics that can help with any screen, including a single-screen feature.

## 1. Create a shared design contract for sibling screens

Before building multiple screens, define a concise contract from the product's existing design system or brand:

- semantic colors and their meanings;
- font and type styles for titles, body, labels, and supporting content;
- spacing scale and common grouping gaps;
- shape, border, surface, and elevation patterns;
- icon family and component variants;
- primary/secondary action hierarchy;
- shared navigation shell only when the approved flow calls for one.

Reuse the contract across sibling screens. Update it deliberately when a real requirement needs a new role, then check which screens need the update. Different tasks may use different layouts; consistency does not mean copying the same layout everywhere.

## 2. Cross-screen consistency audit

For the same meaning, use the same visual treatment across screens: primary action, error/success state, field label, screen title, list row, card, and navigation. Keep action wording, typography, spacing rhythm, component variants, icon style, and surface hierarchy consistent.

Allow content and task-specific layout to vary. Do not introduce a one-off color, font, radius, icon style, or button variant on one screen without a product reason. Reuse a shared shell only for screens that belong to the same top-level navigation structure.

## 3. Density heuristics

These are starting targets for **one compact phone viewport**, not hard limits and not official values from any design system. Adapt them for viewport, task complexity, accessibility, and required content.

| Visible at once | Starting target | Review when above target |
|---|---:|---:|
| Dominant primary actions | 1 | More than 1 competes for attention |
| Secondary buttons | 0–2 | 3 or more |
| Cards | 0–4 | 5 or more, or cards used only as decoration |
| Major sections | 3–5 | 6 or more |
| Tappable controls | About 5–9 | About 10 or more |
| Bottom navigation destinations | 3–5, only when bottom navigation fits the product | More than 5 |
| Actions in a card | 0–2 | 3 or more |

Exceeding a target means **review**, not automatic deletion. Preserve all approved requirements, readable type, and usable touch targets. Reduce overload in this order:

1. Remove duplicate or out-of-scope content.
2. Merge related sections or repeated cards into a clear list/group.
3. Reduce the emphasis of secondary actions.
4. Use progressive disclosure for secondary actions only when they remain discoverable and accessible.
5. Propose a separate screen only for a genuinely separate task and only when the approved scope permits it; otherwise ask before expanding scope.

Do not force desktop/tablet layouts to meet phone counts. Reassess density at the actual viewport.

## 4. Text-fit heuristics

Use realistic, localized content. The following are practical defaults, not character-count requirements. Adapt for Vietnamese wording, accessibility, and actual viewport width.

| Element | Starting guidance |
|---|---|
| Screen/app-bar title | One line when practical; shorten or deliberately wrap before truncating |
| Section heading | Brief phrase, typically 1–4 words |
| Button | One line; specific verb phrase, often 1–3 words |
| Chip/tab | Short and scannable |
| List headline | Usually one line; supporting detail can wrap |
| Card title | Usually 1–2 lines |
| Card supporting text | A few concise lines; move long detail to the appropriate view |
| Dialog | One clear title and a brief consequence/action explanation |
| Helper/error text | State the format, problem, or next step clearly |
| Body text on wide screens | Constrain the reading column instead of stretching long lines |

Never truncate critical values, statuses, dates, errors, or instructions. Test realistic shortest/longest strings and localized content. Do not pad sparse content; reduce the surface or combine it with a related group.

## 5. Multi-screen workflow and final audit

1. Inventory the approved screens, each screen's purpose, primary action, key content, and navigation links.
2. Define the shared design contract.
3. Design each screen from its own task and business rules, applying the density and text heuristics without changing scope.
4. Compare sibling screens for visual and wording drift; update the contract or affected screens deliberately.
5. Review each screen at relevant viewport sizes using the core file's per-screen checklist.
6. Report assumptions and unresolved design/scope decisions. Fix visible drift and overload before delivery.

Cross-screen audit:

- [ ] Screen inventory and links match approved scope; no adjacent flow was inferred.
- [ ] Shared visual meanings and component patterns are consistent.
- [ ] Task-specific layouts remain appropriate; no irrelevant shell was copied.
- [ ] Density/text targets were reviewed and justified exceptions preserve requirements and usability.
- [ ] Same actions use consistent wording; responsive behavior works at actual target sizes.

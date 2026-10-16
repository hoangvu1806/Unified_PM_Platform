# OpenPencil static JSX contract

Use vector JSX, not HTML/CSS: Frame, Text, Rectangle, Ellipse, Line, Star,
Polygon, Icon. Props are literals; do not use JS variables, map(), functions,
style or className. The render tool returns the engine's actual syntax errors.
Return one root Frame sized for the specified viewport.

- Sizing: w/h={number}, w/h="fill" or "hug", grow={number}, minW, maxW.
- Auto-layout: flex="row" or "col", gap, wrap, rowGap, justify="start" /
  "center" / "end" / "between", items="start" / "center" / "end" / "stretch".
- Padding: p, px, py, pt, pr, pb, pl. Numeric literal props use braces.
- Appearance: bg and stroke as hex colors, strokeWidth, rounded, opacity,
  shadow="offsetX offsetY blur #color", overflow="hidden".
  The static JSX contract does not accept CSS gradients. Use a solid hex fill
  for the first pass, or layer a small number of vector rectangles when a
  gradient effect is essential.
- Text: size, weight, color, font, textAlign, maxLines. Give text an explicit
  color and enough width for wrapping. Choose weight from the design direction.
- Icons: <Icon name="lucide:search" size={20} color="#123456" />.
  Fetch names before rendering; use the returned alternatives for missing names.
- Components: an empty <Frame name="slot::<node_id>" ... /> for each resolved
  binding. Size using the actual component dimensions. The tool mounts the real
  instance and edits its declared text slots. Do not draw a substitute control.
- Exact uploaded assets: uploads are opt-in per screen. Use an uploaded asset
  only when the approved specification explicitly marks that screen/node with
  an asset ID or the user's request explicitly scopes the asset to that screen
  or to all screens. Never add an uploaded asset just because it is available.
  Preserve the original asset and identify it with the
  exact uploaded ID supplied in the prompt, using `asset::<asset-id>` in the
  media node content. Never use the filename (for example
  `asset::Untitled.png`), never invent an ID, and never create an empty image
  placeholder. Do not redraw, recolor, or replace the asset; only resize,
  reposition, crop, or apply explicitly requested display styling. The page is
  not complete until the uploaded asset is visible in the rendered preview.
- Photos: use <Rectangle name="photo::<media-node-id>" w="fill" h={180} /> only
  when the specification explicitly marks the node as stock media
  (source="stock" or use_stock=true). User-provided assets must use their
  asset reference; placeholders must remain vector/CSS-like primitives and
  must never be sent to a stock-photo provider.

Use auto-layout for flow and fill sizing; absolute/vector composition is valid
when coordinates are deliberate. A fill child needs a resolved parent size;
flexible text next to a fixed control needs space to wrap. Escape literal text
where needed. All palette, typography, spacing, radii and decorative decisions
belong to the brief and design system, not this renderer contract.

Common mistakes the engine rejects (avoid them in the first call):
- Expressions in props: write `w={390}`, never `w={390 - 32}`, `{...props}` or template strings.
- Text without content or width: `<Text w="fill" size={14} color="#111827">Hôm nay</Text>`.
- Children of a component slot: a `slot::<node_id>` Frame stays empty; size it, nothing inside.
- Every resolved binding needs its slot in the render; a missing slot fails the page.
- Native edit operations take the exact argument names from `inspect_canvas_tools`
  (e.g. `node_resize` needs the live node ID and numeric width/height); read the
  schema once, then batch several operations in one `edit_canvas` call.

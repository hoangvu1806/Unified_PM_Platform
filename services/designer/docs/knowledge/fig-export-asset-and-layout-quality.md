# OpenPencil → Figma export readiness

This is a product-level contract for designs that are exported from OpenPencil to
Figma as `.fig`. It covers two common export regressions: missing uploaded images
and text that overflows or changes geometry after import.

## Scope and source of truth

- OpenPencil is the authoring canvas and owns the live node tree.
- The exported `.fig` must be self-contained: it must not need OpenPencil,
  the original upload directory, a local path, or a temporary URL to render.
- The screenshot, live node geometry and post-export verification are the source
  of truth. JSX or metadata alone cannot prove that an image or text will survive
  the export.
- This document complements `layout-and-typography-rules.md`; it does not replace
  the approved product brief, hard constraints or selected design-system tokens.

## Uploaded image asset contract

When a user uploads an image, preserve the original bytes and MIME type in the
backend asset store. An asset reference may be used for selection and traceability,
but it is not sufficient for export.

```json
{
  "id": "logo-123",
  "mimeType": "image/png",
  "width": 512,
  "height": 512,
  "bytes": "<original binary data>"
}
```

When applying an asset to an OpenPencil image node:

- pass the original bytes to the image-fill operation;
- use Base64 only as a transport encoding, with the MIME type retained in the
  image metadata or data URI;
- do not use `http://`, `https://`, `file://`, `blob:`, a local path, a temporary
  upload URL, CSS-only `background-image`, or an OpenPencil-only asset ID as the
  image source;
- keep the asset ID as provenance metadata, never as the only image data;
- preserve aspect ratio and use `FIT`/contain for logos and mascots unless the
  brief explicitly requests cropping;
- prefer inline SVG or native vector geometry for logos when the source is vector.

Base64 in a prompt, JSX string or CSS declaration does not prove that the image
is embedded in the exported file. It must reach the actual image node and survive
the exporter.

## Asset preflight before `.fig` export

Before export, inspect every visible image node and produce a blocking finding for
any node that fails one of these checks:

1. The node has an image fill and non-empty image data.
2. The image bytes can be resolved without reading an external URL or local path.
3. The MIME type is supported and matches the bytes.
4. The rendered image is visible in the latest OpenPencil screenshot.
5. The image is inside its intended parent and does not overlap text, controls or
   the screen edge.
6. The exported `.fig` is reopened in an isolated Figma session and the image is
   still visible.

If the OpenPencil exporter cannot preserve embedded image bytes, do not claim the
`.fig` is complete. Use a post-import Figma plugin/API step to upload the original
bytes into the corresponding image fills, or export a self-contained SVG/PNG
fallback. Never silently ship a blank image node.

## Text geometry contract

Figma can recalculate text geometry when fonts, line height, width constraints or
auto-layout settings differ from OpenPencil. Design for the imported result:

- give every text node an explicit usable width inside its parent;
- use a real parent width; never leave a `fill` text node inside an unresolved or
  auto-sized parent;
- allow headings, descriptions, labels, errors and Vietnamese copy to wrap;
- allow the text node and its parent section to grow vertically when wrapping;
- set an explicit line height and text alignment, especially for centered copy;
- keep icon-and-text rows flexible so text wraps instead of pushing the icon or
  control outside the frame;
- use truncation only when it is an explicit product requirement;
- never use clipping to hide a layout defect;
- avoid shrinking type below the selected type scale to force a single line;
- verify the actual font supports Vietnamese diacritics, and use a deliberate
  fallback when it does not;
- keep button labels vertically and horizontally centered after wrapping rules
  are applied; labels that can wrap need a button height that can grow.

For fixed mobile screens, verify long strings at the actual viewport width (normally
390px). For desktop screens, verify the smallest supported content column, not only
the widest reference canvas.

## Figma import text preflight

Before accepting an exported file, check each visible text node for:

- right and bottom bounds inside its parent;
- no overlap with another visible text node, icon or control;
- no clipping caused by the parent frame or instance;
- no unexpected one-line expansion beyond the content rail;
- correct line count, readable line height and visible diacritics;
- stable button, input and card heights after text substitution.

Check realistic long Vietnamese examples, not only short placeholder text. Typical
stress cases include long names, validation errors, helper text, multi-word buttons,
and headings with diacritics.

## Agent behavior

The agent must:

1. Treat user uploads as exact local product assets, not as stock-media requests.
2. Apply the original image bytes to the live image node after mounting a component.
3. Inspect the final image, not only an empty marker or asset ID.
4. Inspect live node bounds after text substitution.
5. Repair width, wrapping, line height, parent height, spacing or composition when
   telemetry or the screenshot shows overflow.
6. Reinspect after every repair.
7. Block completion when a visible image is blank or visible text is clipped,
   overflowed, overlapped or outside the root frame.

## Export acceptance criteria

An export is complete only when all of the following are true:

- every uploaded image remains visible without access to OpenPencil's asset store;
- no image depends on a URL, local path, blob URL or internal asset reference;
- all required text is present, readable and inside its parent/root frame;
- no visible text, control or image is clipped or overlaps another required element;
- the imported `.fig` preserves the intended visual hierarchy, spacing and assets;
- any exporter limitation is reported as an unverified export, never hidden.

## Debug checklist

If an image is missing, inspect the image node's actual fill after `set_image_fill`,
then inspect the exported file. If the fill exists in OpenPencil but not in Figma,
the defect is in the exporter or import path, not in the agent's visual layout.

If text overflows only in Figma, compare font family, font availability, width,
line height, auto-height and parent clipping before changing the copy. Prefer fixing
the text constraints and parent geometry over reducing the type size.

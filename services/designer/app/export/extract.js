// DOM → layer tree for the .fig export. Evaluated by Playwright on a rendered screen:
//   await page.evaluate(EXTRACT_JS)  ->  root layer
// Geometry is absolute (page coordinates); Python makes it parent-relative.
// Raster layers (svg, img, canvas, video) carry a "shot" id: Python screenshots that element.
() => {
  let shots = 0;
  const px = (v) => parseFloat(v) || 0;
  // Any CSS color (oklch, color-mix, …) -> sRGB [r, g, b, a] by painting one canvas pixel.
  const ctx = Object.assign(document.createElement("canvas"), { width: 1, height: 1 }).getContext("2d", { willReadFrequently: true });
  const cache = new Map();
  const rgba = (value) => {
    if (!value || value === "transparent" || value === "rgba(0, 0, 0, 0)") return null;
    if (cache.has(value)) return cache.get(value);
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = "#000";
    ctx.fillStyle = value;
    ctx.fillRect(0, 0, 1, 1);
    const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
    const out = a === 0 ? null : [r, g, b, +(a / 255).toFixed(3)];
    cache.set(value, out);
    return out;
  };
  const COLOR = /(?:rgba?|hsla?|oklch|oklab|lab|lch|color)\([^()]*(?:\([^()]*\)[^()]*)*\)|#[0-9a-fA-F]{3,8}/;
  const splitTop = (value) => {
    const out = [];
    let depth = 0, start = 0;
    for (let i = 0; i < value.length; i++) {
      if (value[i] === "(") depth++;
      else if (value[i] === ")") depth--;
      else if (value[i] === "," && depth === 0) { out.push(value.slice(start, i)); start = i + 1; }
    }
    out.push(value.slice(start));
    return out.map((v) => v.trim()).filter(Boolean);
  };
  const shadows = (value) => {
    if (!value || value === "none") return [];
    return splitTop(value).map((part) => {
      const color = (part.match(COLOR) || ["rgba(0,0,0,0.25)"])[0];
      const nums = part.replace(color, "").replace("inset", "").trim().split(/\s+/).map(px);
      return { inset: part.includes("inset"), color: rgba(color), x: nums[0] || 0, y: nums[1] || 0, blur: nums[2] || 0, spread: nums[3] || 0 };
    }).filter((s) => s.color);
  };
  const visible = (s) => s.display !== "none" && s.visibility !== "hidden" && parseFloat(s.opacity) > 0;
  const rectOf = (r) => ({ x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height });

  function box(el, s) {
    const b = {
      bg: rgba(s.backgroundColor) || (s.backgroundImage.includes("gradient") ? rgba((s.backgroundImage.match(COLOR) || [])[0]) : null),
      radius: [s.borderTopLeftRadius, s.borderTopRightRadius, s.borderBottomRightRadius, s.borderBottomLeftRadius].map(px),
      border: ["Top", "Right", "Bottom", "Left"].map((side) => ({
        w: s[`border${side}Style`] === "none" ? 0 : px(s[`border${side}Width`]),
        c: rgba(s[`border${side}Color`]),
      })),
      shadows: shadows(s.boxShadow),
      opacity: parseFloat(s.opacity),
      clip: s.overflowX !== "visible" || s.overflowY !== "visible",
    };
    if (s.display.includes("flex")) {
      b.flex = {
        dir: s.flexDirection.startsWith("column") ? "VERTICAL" : "HORIZONTAL",
        wrap: s.flexWrap === "wrap",
        gap: px(s.columnGap) || px(s.gap),
        rowGap: px(s.rowGap),
        pad: [s.paddingTop, s.paddingRight, s.paddingBottom, s.paddingLeft].map(px),
        justify: s.justifyContent,
        align: s.alignItems,
      };
    }
    return b;
  }

  function textStyle(s) {
    return {
      family: s.fontFamily.split(",")[0].replace(/["']/g, "").trim(),
      size: px(s.fontSize),
      weight: parseInt(s.fontWeight, 10) || 400,
      italic: s.fontStyle === "italic",
      lineHeight: s.lineHeight === "normal" ? null : px(s.lineHeight),
      letterSpacing: s.letterSpacing === "normal" ? 0 : px(s.letterSpacing),
      color: rgba(s.color) || [0, 0, 0, 1],
      align: s.textAlign,
      transform: s.textTransform,
      decoration: s.textDecorationLine,
    };
  }

  // A text node as laid out by the browser: trimmed, split into its rendered lines (Figma must not
  // re-wrap it with slightly different metrics), with the rect of the visible characters only.
  function textLayer(node, s) {
    const raw = node.textContent;
    const words = [...raw.matchAll(/\S+/g)];
    if (!words.length) return null;
    const range = document.createRange();
    const lines = [];
    for (const m of words) {
      range.setStart(node, m.index);
      range.setEnd(node, m.index + m[0].length);
      const rects = [...range.getClientRects()].filter((r) => r.width > 0 && r.height > 0);
      if (!rects.length) continue;
      const first = rects[0];
      const last = lines[lines.length - 1];
      if (last && Math.abs(first.top - last.top) < first.height / 2) {
        last.words.push(m[0]);
        last.right = Math.max(last.right, ...rects.map((r) => r.right));
        last.bottom = Math.max(last.bottom, ...rects.map((r) => r.bottom));
      } else {
        lines.push({ words: [m[0]], top: first.top, left: first.left, right: first.right, bottom: first.bottom });
      }
    }
    if (!lines.length) return null;
    const left = Math.min(...lines.map((l) => l.left));
    const right = Math.max(...lines.map((l) => l.right));
    const top = lines[0].top;
    const bottom = Math.max(...lines.map((l) => l.bottom));
    return {
      kind: "text", text: lines.map((l) => l.words.join(" ")).join("\n"), lines: lines.length,
      x: left + scrollX, y: top + scrollY, w: right - left, h: bottom - top, style: textStyle(s),
    };
  }

  const RASTER_INPUTS = new Set(["checkbox", "radio", "range", "color", "date", "datetime-local", "time", "month", "week", "file"]);

  function walk(el) {
    const s = getComputedStyle(el);
    if (!visible(s)) return null;
    const r = el.getBoundingClientRect();
    const tag = el.tagName.toLowerCase();
    const layer = {
      kind: "frame",
      name: el.getAttribute("data-component") || el.getAttribute("aria-label") || el.id || tag,
      ...rectOf(r),
      box: box(el, s),
      absolute: s.position === "absolute" || s.position === "fixed",
      // CSS paint order: in-flow boxes, then positioned ones (relative too) by z-index, in DOM order.
      positioned: s.position !== "static",
      z: parseInt(s.zIndex, 10) || 0,
      // Photos, gradients and patterns: Python captures the background alone as an image fill.
      bgShot: s.backgroundImage !== "none" && r.width > 0 && r.height > 0 ? `b${shots++}` : null,
      grow: parseFloat(s.flexGrow) > 0,
      stretch: s.alignSelf === "stretch",
      children: [],
    };
    if (layer.bgShot) el.setAttribute("data-bgshot", layer.bgShot);
    if (["svg", "img", "canvas", "video", "picture"].includes(tag) || (tag === "input" && RASTER_INPUTS.has(el.type))) {
      layer.bgShot = null;
      layer.kind = "raster";
      layer.shot = `s${shots++}`;
      el.setAttribute("data-shot", layer.shot);
      return r.width > 0 && r.height > 0 ? layer : null;
    }
    if (["input", "textarea", "select"].includes(tag)) {
      const value = tag === "select" ? el.options[el.selectedIndex]?.text || "" : el.value || el.placeholder || "";
      if (value) {
        const pad = [s.paddingLeft, s.paddingTop].map(px);
        // Inputs and selects center their single line vertically; textareas start at the top padding.
        const lineH = s.lineHeight === "normal" ? px(s.fontSize) * 1.25 : px(s.lineHeight);
        const top = tag === "textarea" ? pad[1] + px(s.borderTopWidth) : (r.height - lineH) / 2;
        layer.children.push({
          kind: "text", text: value, lines: 1, x: layer.x + pad[0] + px(s.borderLeftWidth), y: layer.y + top,
          w: Math.max(1, r.width - pad[0] - px(s.paddingRight)), h: lineH,
          style: { ...textStyle(s), color: el.value ? rgba(s.color) || [0, 0, 0, 1] : [113, 113, 122, 1] },
        });
      }
      return layer;
    }
    for (const node of el.childNodes) {
      if (node.nodeType === 3) {
        const text = textLayer(node, s);
        if (text) layer.children.push(text);
      } else if (node.nodeType === 1) {
        const child = walk(node);
        if (child) layer.children.push(child);
      }
    }
    return layer;
  }

  const root = walk(document.body);
  root.name = document.title || "Screen";
  root.w = Math.max(root.w, document.documentElement.scrollWidth);
  root.h = Math.max(root.h, document.documentElement.scrollHeight);
  return root;
};

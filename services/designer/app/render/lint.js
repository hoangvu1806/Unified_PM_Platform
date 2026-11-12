// Layout lint on the rendered DOM. Evaluated by Playwright after runtime.js:
//   await page.evaluate(LINT_JS, {mobile, axe})  ->  {findings, text, height}
// Accessibility and contrast come from axe-core; the geometry rules are ours.
async ({ mobile, axe, strictTouchTargets = false, strictVisualQuality = false, requiredTexts = [], forbiddenTexts = [] }) => {
  const findings = [];
  const MAX = 5;
  const visibleBounds = (el) => {
    const rect = el.getBoundingClientRect();
    const box = { left: Math.max(0, rect.left), right: Math.min(window.innerWidth, rect.right),
      top: Math.max(0, rect.top), bottom: Math.min(window.innerHeight, rect.bottom) };
    for (let parent = el.parentElement; parent; parent = parent.parentElement) {
      const style = getComputedStyle(parent);
      const clipX = /(hidden|clip|auto|scroll)/.test(style.overflowX);
      const clipY = /(hidden|clip|auto|scroll)/.test(style.overflowY);
      if (!clipX && !clipY) continue;
      const clip = parent.getBoundingClientRect();
      if (clipX) { box.left = Math.max(box.left, clip.left); box.right = Math.min(box.right, clip.right); }
      if (clipY) { box.top = Math.max(box.top, clip.top); box.bottom = Math.min(box.bottom, clip.bottom); }
    }
    return box.right - box.left > 0 && box.bottom - box.top > 0 ? box : null;
  };
  const short = (el) => {
    const html = el.outerHTML.replace(/\sdata-d="[^"]*"/g, "");
    const foreground = getComputedStyle(el).color;
    const surfaces = [];
    let parent = el;
    while (parent && surfaces.length < 6) {
      const style = getComputedStyle(parent);
      const background = style.backgroundColor;
      if (background && background !== "rgba(0, 0, 0, 0)" && background !== "transparent") {
        surfaces.push({
          tag: parent.tagName.toLowerCase(),
          className: String(parent.className || "").slice(0, 180),
          background,
        });
      }
      parent = parent.parentElement;
    }
    return {
      id: el.getAttribute("data-d"),
      text: (el.innerText || el.getAttribute("aria-label") || "").trim().slice(0, 80),
      html: html.length > 200 ? html.slice(0, 200) + "…" : html,
      bounds: (() => {
        const rect = visibleBounds(el) || el.getBoundingClientRect();
        return { x: Math.round(rect.x ?? rect.left), y: Math.round(rect.y ?? rect.top),
          width: Math.round(rect.width ?? rect.right - rect.left), height: Math.round(rect.height ?? rect.bottom - rect.top) };
      })(),
      foreground,
      surfaces,
    };
  };
  const add = (severity, rule, message, els) => {
    if (!els.length) return;
    findings.push({ severity, rule, message, count: els.length, elements: els.slice(0, MAX).map(short) });
  };
  const visible = (el) => {
    const s = getComputedStyle(el);
    return el.getClientRects().length > 0 && s.visibility !== "hidden" && Number(s.opacity) > 0;
  };
  const all = [...document.body.querySelectorAll("*")].filter(
    (el) => !["SCRIPT", "STYLE", "TEMPLATE"].includes(el.tagName) && visible(el),
  );
  const vw = window.innerWidth;

  // Preview content contract: explicit quoted UI copy from the approved screen
  // must survive every visual direction unchanged.
  const normalizeCopy = (value) => (value || "").replace(/\s+/g, " ").trim().toLocaleLowerCase();
  const containsCopyPhrase = (haystack, value) => {
    const phrase = normalizeCopy(value);
    if (!phrase) return false;
    const escaped = phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+");
    const startsWithWord = /^[\p{L}\p{N}]/u.test(phrase);
    const endsWithWord = /[\p{L}\p{N}]$/u.test(phrase);
    return new RegExp(`${startsWithWord ? "(?:^|[^\\p{L}\\p{N}])" : ""}${escaped}${endsWithWord ? "(?![\\p{L}\\p{N}])" : ""}`, "iu").test(haystack);
  };
  // Placeholder/accessible-name copy is visible UI text too, even though the
  // browser does not include input placeholders in document.body.innerText.
  const controlCopy = all
    .filter((el) => el.matches("input,textarea,select,[role=combobox]"))
    .flatMap((el) => [
      el.getAttribute("placeholder"),
      el.getAttribute("aria-label"),
      el.matches("select") ? el.selectedOptions?.[0]?.textContent : "",
    ])
    .filter(Boolean);
  const visibleText = [document.body.innerText, ...controlCopy].filter(Boolean).join("\n");
  const visibleCopy = normalizeCopy(visibleText);
  const missingCopy = requiredTexts.filter((value) => value && !visibleCopy.includes(normalizeCopy(value)));
  if (missingCopy.length) {
    findings.push({
      severity: "error", rule: "required-content", count: missingCopy.length, elements: [],
      message: `Approved UI text is missing: ${missingCopy.join("; ")}. Preserve all confirmed labels and actions.`,
    });
  }
  // Match whole text tokens/phrases. A plain substring check incorrectly
  // treats the reward label "+100 Xu" as the unavailable-balance state "0 Xu".
  const prematureConditionalCopy = forbiddenTexts.filter((value) => value && containsCopyPhrase(visibleCopy, value));
  if (prematureConditionalCopy.length) {
    findings.push({
      severity: "error", rule: "conditional-content-on-first-paint", count: prematureConditionalCopy.length, elements: [],
      message: `Conditional-state UI is visible before its trigger: ${prematureConditionalCopy.join("; ")}. Keep conditional regions closed/hidden in the initial preview.`,
    });
  }

  // Page wider than the viewport: horizontal scroll on the real device.
  if (document.documentElement.scrollWidth > vw + 1) {
    const wide = all.filter((el) => el.getBoundingClientRect().right > vw + 1);
    const outermost = wide.filter((el) => !wide.includes(el.parentElement));
    add("error", "page-overflow", `Page is ${document.documentElement.scrollWidth}px wide; the viewport is ${vw}px.`, outermost);
  }

  // Text cut off by a clipping box without an intended ellipsis/line clamp.
  const clipped = all.filter((el) => {
    if (!el.childNodes.length || ![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) return false;
    const s = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    // Detect visually hidden accessibility text from its CSS geometry rather
    // than relying on an application-specific class name.
    const accessibilityOnly = s.position === "absolute" && (
      s.clip !== "auto" || s.clipPath !== "none" ||
      (rect.width <= 1 && rect.height <= 1 && /(hidden|clip)/.test(s.overflowX + s.overflowY) && s.whiteSpace === "nowrap")
    );
    if (accessibilityOnly) return false;
    const clips = /(hidden|clip)/.test(s.overflowX + s.overflowY);
    if (!clips || s.textOverflow === "ellipsis" || s.webkitLineClamp !== "none") return false;
    return el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1;
  });
  add("error", "clipped-text", "Text is cut off by its box.", clipped);

  // Content cut off by an ancestor that clips (overflow hidden/clip), or pushed into a horizontal
  // scroll inside a box: the user cannot see or reach it without scrolling.
  const clipper = (el) => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (s.overflowX !== "visible" || s.overflowY !== "visible") return { el: p, s };
    }
    return null;
  };
  const intentionalDecoration = (el) =>
    (el.matches("img") && !(el.getAttribute("alt") || "").trim()) ||
    (el.matches("svg") && (el.getAttribute("aria-hidden") === "true" || el.getAttribute("role") === "presentation"));
  const leaves = all.filter((el) => !intentionalDecoration(el) && (el.matches("button,a,input,select,textarea,img,svg") ||
    [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())));
  const cut = [], scrolled = [];
  for (const el of leaves) {
    const c = clipper(el);
    if (!c) continue;
    const a = el.getBoundingClientRect(), b = c.el.getBoundingClientRect();
    if (a.right > b.right + 2 || a.left < b.left - 2) {
      (/(hidden|clip)/.test(c.s.overflowX) ? cut : scrolled).push(el);
    }
  }
  add("error", "clipped-content", "Content is cut off by a container that hides overflow.", cut.filter((el) => !cut.includes(el.parentElement)));
  add("warning", "horizontal-scroll", "Content only fits by scrolling horizontally inside its box.", scrolled.filter((el) => !scrolled.includes(el.parentElement)));

  // A child sticking out of a visible box (background or border) it belongs to.
  const boxed = (el) => {
    const s = getComputedStyle(el);
    return s.backgroundColor !== "rgba(0, 0, 0, 0)" || parseFloat(s.borderTopWidth) > 0 || s.boxShadow !== "none";
  };
  const sticking = all.filter((el) => {
    const parent = el.parentElement;
    if (!parent || parent === document.body || !boxed(parent)) return false;
    if (getComputedStyle(el).position === "absolute" || getComputedStyle(el).position === "fixed") return false;
    const a = el.getBoundingClientRect();
    const b = parent.getBoundingClientRect();
    return a.right > b.right + 4 || a.left < b.left - 4 || a.bottom > b.bottom + 4;
  });
  add("warning", "child-overflow", "Element sticks out of its container.", sticking);

  // Large boxes with nothing inside: unfinished regions or placeholder blocks.
  const media = "img,svg,canvas,video,picture,input,textarea,select,iframe";
  const empty = all.filter((el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 120 || r.height < 120 || !boxed(el)) return false;
    if ((el.innerText || "").trim() || el.querySelector(media) || el.matches(media)) return false;
    return getComputedStyle(el).backgroundImage === "none";
  });
  add("warning", "empty-region", "Large empty box: fill it with content or remove it.", empty);

  const broken = [...document.images].filter((img) => img.complete && img.naturalWidth === 0);
  add("error", "broken-image", "Image failed to load.", broken);

  // Two independent controls must not occupy the same tap area. Ignore nested
  // descendants such as an icon or label inside its owning button.
  const semanticInteractiveRoles = new Set(["button", "link", "radio", "checkbox", "switch", "tab", "option", "menuitem"]);
  const isInteractive = (el) => el.matches("a,button,input:not([type=hidden]),select,textarea") ||
    semanticInteractiveRoles.has((el.getAttribute("role") || "").toLowerCase()) ||
    el.hasAttribute("onclick") || [...el.attributes].some((attr) =>
      attr.name === "@click" || attr.name.startsWith("x-on:") || attr.name.startsWith("@"));
  // Inspect attributes in JS instead of putting Alpine's @click spelling in a
  // CSS selector; CSS selectors cannot parse [@click] as a valid attribute name.
  const controls = all.filter(isInteractive).filter((el) => {
    for (let parent = el.parentElement; parent; parent = parent.parentElement) {
      if (isInteractive(parent)) return false;
    }
    return true;
  });
  const overlapping = [];
  for (let i = 0; i < controls.length; i++) {
      const a = visibleBounds(controls[i]);
      if (!a) continue;
    for (let j = i + 1; j < controls.length; j++) {
      const b = visibleBounds(controls[j]);
      if (!b) continue;
      const overlapX = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const overlapY = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (overlapX > 2 && overlapY > 2) overlapping.push(controls[i], controls[j]);
    }
  }
  add("error", "interactive-overlap", "Interactive controls overlap and may block one another.", [...new Set(overlapping)]);

  // A bottom-pinned action bar must not cover the initial viewport's scrollable
  // form/list content. Detect the actual rendered geometry, rather than relying
  // on prompts to remember a bottom padding workaround.
  const bottomPinned = all.filter((el) => {
    const style = getComputedStyle(el);
    if (!(style.position === "fixed" || style.position === "sticky")) return false;
    const rect = el.getBoundingClientRect();
    return rect.height >= 32 && rect.bottom >= window.innerHeight - 4 && rect.top < window.innerHeight;
  });
  const footerOverlaps = new Set();
  for (const footer of bottomPinned) {
    const footerRect = footer.getBoundingClientRect();
    const documentScrolls = document.documentElement.scrollHeight > document.documentElement.clientHeight + 8;
    const scrollRoots = [
      ...(documentScrolls ? [document.documentElement] : []),
      ...[...document.querySelectorAll("*")].filter((el) => {
      if (el === footer || el.contains(footer)) return false;
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return /(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 8 &&
        rect.top < footerRect.bottom && rect.bottom > footerRect.top;
      }),
    ];
    for (const scrollRoot of scrollRoots) {
      for (const content of all) {
        if (footer.contains(content) || content.contains(footer) || !scrollRoot.contains(content)) continue;
        if (!(content.matches("a,button,input,select,textarea,img,svg,canvas,video,[role=button],[data-state-target]") ||
        [...content.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()))) continue;
        const rect = content.getBoundingClientRect();
        const overlapX = Math.min(rect.right, footerRect.right) - Math.max(rect.left, footerRect.left);
        const overlapY = Math.min(rect.bottom, footerRect.bottom) - Math.max(rect.top, footerRect.top);
        if (overlapX > 12 && overlapY > 8) footerOverlaps.add(content);
      }
    }
  }
  add("error", "sticky-footer-overlap",
    "A fixed/sticky bottom action bar covers content in the initial scroll viewport. Put the footer in normal flow or in a non-overlapping flex layout with a separately scrollable content region.",
    [...footerOverlaps]);

  // The screen canvas represents app content, not a device frame. Catch the
  // common fake Dynamic Island/notch rendered as a tiny dark pill at top-center.
  // This is a blocking defect because it can cover the page title and is never
  // needed to reserve safe-area space in a web preview.
  const isNotchShape = (rect, style, hasPaint = true) => {
    if (!hasPaint || rect.top < -1 || rect.top > Math.min(96, window.innerHeight * 0.12)) return false;
    if (rect.width < 18 || rect.width > Math.min(180, vw * 0.48) || rect.height < 5 || rect.height > 34) return false;
    if (rect.width / rect.height < 2 || Math.abs((rect.left + rect.right) / 2 - vw / 2) > vw * 0.12) return false;
    const color = style.backgroundColor.match(/rgba?\(([^)]+)\)/);
    const gradient = /gradient/i.test(style.backgroundImage);
    const channels = color ? color[1].split(/[,/ ]+/).filter(Boolean).map(Number) : [];
    const alpha = channels.length > 3 ? channels[3] : 1;
    const luminance = channels.length >= 3
      ? (channels[0] * 299 + channels[1] * 587 + channels[2] * 114) / 1000
      : 0;
    const radius = parseFloat(style.borderTopLeftRadius);
    const rounded = radius >= rect.height * 0.3 || /999|full|round/i.test(style.borderRadius);
    return rounded && (gradient || (color && alpha > 0.05 && luminance < 72));
  };
  const pseudoRect = (el, pseudo, style) => {
    const host = el.getBoundingClientRect();
    const number = (value, base) => value?.endsWith("%")
      ? parseFloat(value) * base / 100
      : Number.parseFloat(value) || 0;
    const width = number(style.width, host.width);
    const height = number(style.height, host.height);
    if (!width || !height) return null;
    const leftValue = style.left !== "auto" ? number(style.left, host.width)
      : style.right !== "auto" ? host.width - number(style.right, host.width) - width : 0;
    const topValue = style.top !== "auto" ? number(style.top, host.height)
      : style.bottom !== "auto" ? host.height - number(style.bottom, host.height) - height : 0;
    let dx = 0, dy = 0;
    try {
      const matrix = new DOMMatrixReadOnly(style.transform);
      dx = matrix.m41;
      dy = matrix.m42;
    } catch (_) { /* no transform */ }
    const left = host.left + leftValue + dx;
    const top = host.top + topValue + dy;
    return { left, top, right: left + width, bottom: top + height, width, height };
  };
  const fakeNotches = new Set();
  for (const el of all) {
    if (el.matches("input,button,a,select,textarea,img,[role=button]")) continue;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    if (isNotchShape(rect, style)) fakeNotches.add(el);
    for (const pseudo of ["::before", "::after"]) {
      const layer = getComputedStyle(el, pseudo);
      if (layer.content === "none" || layer.content === "normal") continue;
      const shape = pseudoRect(el, pseudo, layer);
      if (shape && isNotchShape(shape, layer)) fakeNotches.add(el);
    }
    // Also catch an explicitly drawn rounded SVG bar without flagging the
    // complete SVG illustration/logo as a notch.
    if (el.tagName.toLowerCase() === "rect") {
      const fill = style.fill || el.getAttribute("fill") || "";
      const rx = Number.parseFloat(style.rx || el.getAttribute("rx") || "0");
      const fillMatch = fill.match(/#([0-9a-f]{6})/i);
      const darkFill = fillMatch ? Number.parseInt(fillMatch[1], 16) < 0x484848 : /black|rgb\(0,\s*0,\s*0\)/i.test(fill);
      if (rx > 0 && darkFill && isNotchShape(rect, { backgroundColor: "rgb(0, 0, 0)", backgroundImage: "none", borderTopLeftRadius: `${rx}px`, borderRadius: `${rx}px` })) {
        fakeNotches.add(el);
      }
    }
  }
  add("error", "fake-device-notch",
    "A fake notch/Dynamic Island/camera pill is visible inside the app canvas and may cover the screen title. Remove it; represent safe area as spacing only, then rerender.",
    [...fakeNotches]);

  if (mobile) {
    const small = all.filter((el) => {
      if (!el.matches("a,button,input,select,textarea,[role=button],[onclick],[x-on\\:click],[\\@click]")) return false;
      const target = el.matches("input[type=checkbox],input[type=radio]") ? (el.closest("label") || el) : el;
      const box = target.getBoundingClientRect();
      return box.width < 48 || box.height < 48;
    });
    const measuredSmall = small.slice(0, MAX).map((el) => {
      const target = el.matches("input[type=checkbox],input[type=radio]") ? (el.closest("label") || el) : el;
      const box = target.getBoundingClientRect();
      return `${el.tagName.toLowerCase()} ${Math.round(box.width)}×${Math.round(box.height)} CSS px`;
    });
    add(strictTouchTargets ? "error" : "warning", "tap-target",
      `Mobile touch target is smaller than 48×48 CSS px (cross-platform preview baseline). Measured: ${measuredSmall.join(", ")}. Enlarge the interactive element itself, not only its decorative wrapper.`, small);

    if (strictTouchTargets) {
      const misaligned = [];
      const fieldSelector = "input:not([type=hidden]):not([type=checkbox]):not([type=radio]),select,textarea";
      // Compare the visible field shell, not a borderless input child. Password
      // inputs commonly share a row with a visibility button, making the input
      // narrower even though the actual bordered field aligns with its peers.
      const fieldBox = (field) => {
        const isFieldSurface = (node) => {
          const style = getComputedStyle(node);
          const rect = node.getBoundingClientRect();
          const hasBorder = ["Top", "Right", "Bottom", "Left"].some((side) =>
            parseFloat(style[`border${side}Width`]) > 0,
          );
          const hasSurface = style.backgroundColor !== "rgba(0, 0, 0, 0)" || style.boxShadow !== "none";
          return hasBorder || hasSurface
            ? rect.width >= Math.min(window.innerWidth * 0.5, 240) && rect.height >= 32 && rect.height <= 96
            : false;
        };
        for (let parent = field.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
          if (isFieldSurface(parent)) return parent;
        }
        return field;
      };
      const forms = [...document.querySelectorAll("form")].filter(visible);
      const groups = forms.map((form) => [...form.querySelectorAll(fieldSelector)].filter(visible));
      if (!forms.length) {
        // Generated previews sometimes use semantic divs rather than <form>. Group peer fields
        // under their nearest shared ancestor that contains at least two text-entry controls.
        const byAncestor = new Map();
        for (const field of all.filter((el) => el.matches(fieldSelector))) {
          for (let parent = field.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
            const peers = [...parent.querySelectorAll(fieldSelector)].filter(visible);
            if (peers.length >= 2) {
              byAncestor.set(parent, peers);
              break;
            }
          }
        }
        groups.push(...byAncestor.values());
      }
      for (const fields of groups) {
        if (fields.length < 2) continue;
        const boxes = fields.map((el) => fieldBox(el).getBoundingClientRect());
        const left = Math.min(...boxes.map((r) => r.left));
        const right = Math.max(...boxes.map((r) => r.right));
        fields.forEach((field, i) => {
          if (Math.abs(boxes[i].left - left) > 8 || Math.abs(boxes[i].right - right) > 8) misaligned.push(field);
        });
      }
      add("error", "form-field-alignment",
        "Visible field shells for related form fields do not share consistent left and right edges (8px tolerance).", misaligned);
    }
  }

  const sizes = new Set(
    all
      .filter((el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()))
      .map((el) => getComputedStyle(el).fontSize),
  );
  if (sizes.size > 7) {
    findings.push({
      severity: "info", rule: "type-scale", count: sizes.size, elements: [],
      message: `${sizes.size} font sizes in use (${[...sizes].join(", ")}); keep a tighter type scale.`,
    });
  }

  if (axe && window.axe) {
    const result = await window.axe.run(document.body, {
      runOnly: { type: "rule", values: ["color-contrast", "image-alt", "button-name", "link-name", "label"] },
      resultTypes: ["violations"],
    });
    for (const v of result.violations) {
      const els = v.nodes.map((n) => document.querySelector(n.target[0])).filter(Boolean);
      add(v.id === "color-contrast" ? (strictVisualQuality ? "error" : "warning") : "info", v.id, v.help, els);
    }
  }

  // Inputs render placeholders visually, but innerText omits them. Return the
  // same visible-copy surface used by required-content QA so later build gates
  // do not reject a correct repair for preserving an approved placeholder.
  return { findings, text: visibleText, height: document.documentElement.scrollHeight };
};

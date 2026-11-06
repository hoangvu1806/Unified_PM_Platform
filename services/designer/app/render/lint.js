// Layout lint on the rendered DOM. Evaluated by Playwright after runtime.js:
//   await page.evaluate(LINT_JS, {mobile, axe})  ->  {findings, text, height}
// Accessibility and contrast come from axe-core; the geometry rules are ours.
async ({ mobile, axe, strictTouchTargets = false }) => {
  const findings = [];
  const MAX = 5;
  const short = (el) => {
    const html = el.outerHTML.replace(/\sdata-d="[^"]*"/g, "");
    return {
      id: el.getAttribute("data-d"),
      text: (el.innerText || el.getAttribute("aria-label") || "").trim().slice(0, 80),
      html: html.length > 200 ? html.slice(0, 200) + "…" : html,
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

  const photos = [...document.images].filter((img) => img.naturalWidth > 0).length +
    all.filter((el) => /url\(/.test(getComputedStyle(el).backgroundImage)).length;
  if (!photos) {
    findings.push({ severity: "warning", rule: "no-imagery", count: 0, elements: [],
      message: "The screen has no photo or illustration: add one with find_images (background, hero, cards)." });
  }

  const broken = [...document.images].filter((img) => img.complete && img.naturalWidth === 0);
  add("error", "broken-image", "Image failed to load.", broken);

  if (mobile) {
    const small = all.filter((el) => {
      if (!el.matches("a,button,input,select,textarea,[role=button],[onclick],[x-on\\:click],[\\@click]")) return false;
      const r = el.getBoundingClientRect();
      const target = el.matches("input[type=checkbox],input[type=radio]") ? (el.closest("label") || el) : el;
      const box = target.getBoundingClientRect();
      return box.width < 48 || box.height < 48;
    });
    add(strictTouchTargets ? "error" : "warning", "tap-target",
      "Mobile touch target is smaller than 48×48 CSS px (cross-platform preview baseline).", small);

    if (strictTouchTargets) {
      const misaligned = [];
      const fieldSelector = "input:not([type=hidden]):not([type=checkbox]):not([type=radio]),select,textarea";
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
        const boxes = fields.map((el) => el.getBoundingClientRect());
        const left = Math.min(...boxes.map((r) => r.left));
        const right = Math.max(...boxes.map((r) => r.right));
        fields.forEach((field, i) => {
          if (Math.abs(boxes[i].left - left) > 8 || Math.abs(boxes[i].right - right) > 8) misaligned.push(field);
        });
      }
      add("error", "form-field-alignment",
        "Related form fields do not share consistent left and right edges (8px tolerance).", misaligned);
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
      add(v.id === "color-contrast" ? "warning" : "info", v.id, v.help, els);
    }
  }

  return { findings, text: document.body.innerText, height: document.documentElement.scrollHeight };
};

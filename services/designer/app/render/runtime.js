// Designer runtime, loaded in every screen document (design iframe and headless render).
// - data-d ids on elements, so the canvas and lint can point at an element;
// - data-state / data-state-hide: elements shown only in (or hidden in) a named state;
// - data-goto="screen-id": prototype navigation, reported to the parent page;
// - <i data-lucide="name"> icons replaced by lucide SVGs (also after Alpine re-renders);
// - selection mode: hover outline, click reports the element to the parent page.
(() => {
  const SKIP = new Set(["SCRIPT", "STYLE", "TEMPLATE", "HEAD", "META", "LINK", "TITLE"]);

  function assignIds(root) {
    let n = 0;
    const walk = (el) => {
      if (SKIP.has(el.tagName)) return;
      if (!el.hasAttribute("data-d")) el.setAttribute("data-d", "e" + n);
      n += 1;
      for (const child of el.children) walk(child);
    };
    walk(root);
  }

  function installStates() {
    const names = new Set();
    for (const el of document.querySelectorAll("[data-state],[data-state-hide]")) {
      for (const attr of ["data-state", "data-state-hide"]) {
        for (const name of (el.getAttribute(attr) || "").split(/\s+/)) if (name) names.add(name);
      }
    }
    const css = [...names]
      .map((name) => {
        const q = JSON.stringify(name);
        return `html:not([data-active-state~=${q}]) [data-state~=${q}]{display:none!important}` +
          `html[data-active-state~=${q}] [data-state-hide~=${q}]{display:none!important}`;
      })
      .join("\n");
    const style = document.createElement("style");
    style.id = "designer-states";
    style.textContent = css;
    document.head.appendChild(style);
    return [...names];
  }

  function describe(el) {
    const html = el.outerHTML.replace(/\sdata-d="[^"]*"/g, "");
    return {
      id: el.getAttribute("data-d"),
      tag: el.tagName.toLowerCase(),
      text: (el.innerText || "").trim().slice(0, 200),
      html: html.length > 600 ? html.slice(0, 600) + "…" : html,
    };
  }

  const post = (message) => {
    if (window.parent !== window) window.parent.postMessage({ source: "designer-screen", ...message }, "*");
  };

  let selecting = false;
  let hovered = null;
  const outline = (el, on) => {
    if (!el) return;
    el.style.outline = on ? "2px solid #6366f1" : "";
    el.style.outlineOffset = on ? "-2px" : "";
  };

  document.addEventListener("mouseover", (event) => {
    if (!selecting) return;
    outline(hovered, false);
    hovered = event.target.closest("[data-d]");
    outline(hovered, true);
  });
  document.addEventListener(
    "click",
    (event) => {
      if (selecting) {
        event.preventDefault();
        event.stopPropagation();
        const el = event.target.closest("[data-d]");
        if (el) post({ type: "select", element: describe(el) });
        return;
      }
      const link = event.target.closest("[data-goto]");
      if (link) {
        event.preventDefault();
        post({ type: "goto", screen: link.getAttribute("data-goto") });
      }
    },
    true,
  );

  window.addEventListener("message", (event) => {
    const data = event.data || {};
    if (data.type === "designer:state") {
      if (data.state) document.documentElement.setAttribute("data-active-state", data.state);
      else document.documentElement.removeAttribute("data-active-state");
      // Report updated height after the DOM re-renders for this state.
      setTimeout(() => post({ type: "resize", height: document.documentElement.scrollHeight }), 60);
    } else if (data.type === "designer:select") {
      selecting = !!data.on;
      if (!selecting) outline(hovered, false);
    }
  });

  const icons = () => {
    if (window.lucide && document.querySelector("i[data-lucide]")) window.lucide.createIcons();
  };

  window.__designer = { assignIds, describe, states: [] };
  const start = () => {
    icons();
    new MutationObserver(icons).observe(document.body, { childList: true, subtree: true });
    assignIds(document.body);
    window.__designer.states = installStates();
    post({ type: "ready", states: window.__designer.states, height: document.documentElement.scrollHeight });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();

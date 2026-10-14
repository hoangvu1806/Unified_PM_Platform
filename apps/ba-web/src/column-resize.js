/**
 * Drag-to-resize the three-column BA/VA chrome (nav | chat | workspace).
 * Widths persist in localStorage for this browser/page.
 */

const DEFAULTS = { nav: 310, workspace: 430 };
const MIN_NAV = 180;
const MIN_WORKSPACE = 200;
const MIN_CHAT = 280;
const SPLITTER = 6;

export function initColumnResize(container, storageKey) {
  if (!container || !storageKey) return;

  const nav = container.querySelector('.section-nav');
  const chat = container.querySelector('.chat-panel');
  const workspace = container.querySelector('.workspace-panel');
  const splitLeft = container.querySelector('[data-splitter="nav-chat"]');
  const splitRight = container.querySelector('[data-splitter="chat-ws"]');
  if (!nav || !chat || !workspace || !splitLeft || !splitRight) return;

  let widths = loadWidths(storageKey);
  applyWidths(nav, workspace, widths);

  const onResize = () => {
    widths = clampToViewport(widths, container.clientWidth);
    applyWidths(nav, workspace, widths);
    saveWidths(storageKey, widths);
  };
  window.addEventListener('resize', onResize);

  bindSplitter(splitLeft, (dx) => {
    widths = clampToViewport(
      { nav: widths.nav + dx, workspace: widths.workspace },
      container.clientWidth,
    );
    applyWidths(nav, workspace, widths);
  }, () => saveWidths(storageKey, widths));

  bindSplitter(splitRight, (dx) => {
    widths = clampToViewport(
      { nav: widths.nav, workspace: widths.workspace - dx },
      container.clientWidth,
    );
    applyWidths(nav, workspace, widths);
  }, () => saveWidths(storageKey, widths));
}

function loadWidths(key) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return { ...DEFAULTS };
    const parsed = JSON.parse(raw);
    const nav = Number(parsed.nav);
    const workspace = Number(parsed.workspace);
    if (!Number.isFinite(nav) || !Number.isFinite(workspace)) return { ...DEFAULTS };
    return { nav, workspace };
  } catch {
    return { ...DEFAULTS };
  }
}

function saveWidths(key, widths) {
  try {
    localStorage.setItem(key, JSON.stringify({
      nav: Math.round(widths.nav),
      workspace: Math.round(widths.workspace),
    }));
  } catch {
    // private mode / quota — ignore
  }
}

function applyWidths(nav, workspace, widths) {
  nav.style.width = `${Math.round(widths.nav)}px`;
  nav.style.flex = `0 0 ${Math.round(widths.nav)}px`;
  workspace.style.width = `${Math.round(widths.workspace)}px`;
  workspace.style.flex = `0 0 ${Math.round(widths.workspace)}px`;
}

function clampToViewport(widths, viewportWidth) {
  const available = Math.max(
    viewportWidth - MIN_CHAT - SPLITTER * 2,
    MIN_NAV + MIN_WORKSPACE,
  );
  let nav = widths.nav;
  let workspace = widths.workspace;
  nav = Math.max(MIN_NAV, nav);
  workspace = Math.max(MIN_WORKSPACE, workspace);
  if (nav + workspace > available) {
    const overflow = nav + workspace - available;
    const navShare = nav / (nav + workspace);
    nav = Math.max(MIN_NAV, nav - overflow * navShare);
    workspace = Math.max(MIN_WORKSPACE, available - nav);
  }
  return { nav, workspace };
}

function bindSplitter(el, onDelta, onEnd) {
  el.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    el.classList.add('dragging');
    document.body.classList.add('col-resizing');
    el.setPointerCapture(event.pointerId);
    let lastX = event.clientX;

    const onMove = (moveEvent) => {
      const dx = moveEvent.clientX - lastX;
      lastX = moveEvent.clientX;
      if (dx) onDelta(dx);
    };
    const onUp = () => {
      el.classList.remove('dragging');
      document.body.classList.remove('col-resizing');
      el.removeEventListener('pointermove', onMove);
      el.removeEventListener('pointerup', onUp);
      el.removeEventListener('pointercancel', onUp);
      onEnd();
    };
    el.addEventListener('pointermove', onMove);
    el.addEventListener('pointerup', onUp);
    el.addEventListener('pointercancel', onUp);
  });
}

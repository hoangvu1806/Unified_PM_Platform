/**
 * Platform context for the BA UI (Sprint 3).
 *
 * - Project: `?project=` (from the Portal) or `?project_id=` (BA's own links),
 *   remembered per tab. Pages that read `project_id` from the URL get it
 *   filled in before their own module code runs (this module is imported first).
 * - Login: no session → /login?next=<this page>; any 401 from the BA API does the same.
 * - Read-only: members without the BA role see chat and documents but no inputs.
 * - A thin bar links back to the Portal and shows project, user, role.
 */

import './platform-theme.css';

const STORAGE_KEY = 'platform.projectId';
const API_BASE = import.meta.env.VITE_API_BASE || '/api';

function toLogin() {
  const next = window.location.pathname + window.location.search;
  window.location.assign(`/login?next=${encodeURIComponent(next)}`);
}

function readProjectId() {
  const params = new URLSearchParams(window.location.search);
  const fromUrl = (params.get('project') || params.get('project_id') || '').trim();
  if (fromUrl) {
    try { sessionStorage.setItem(STORAGE_KEY, fromUrl); } catch { /* private mode */ }
    return fromUrl;
  }
  try { return sessionStorage.getItem(STORAGE_KEY) || ''; } catch { return ''; }
}

export const projectId = readProjectId();

// Embedded in the platform journey page (?embed=1): no own platform bar.
export const isEmbedded = (() => {
  const fromUrl = new URLSearchParams(window.location.search).get('embed') === '1';
  try {
    if (fromUrl) sessionStorage.setItem('platform.embed', '1');
    return fromUrl || (window.self !== window.top && sessionStorage.getItem('platform.embed') === '1');
  } catch {
    return fromUrl;
  }
})();
if (isEmbedded) document.documentElement.classList.add('platform-embed-root');

// Shared theme with Portal and Designer (same storage key), dark by default.
(function applyTheme() {
  let mode = 'dark';
  try {
    const saved = localStorage.getItem('designer.theme');
    if (saved === 'light' || saved === 'dark') mode = saved;
    else if (saved === 'system') mode = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  } catch { /* private mode */ }
  document.documentElement.setAttribute('data-theme', mode);
  window.addEventListener('storage', (e) => {
    if (e.key === 'designer.theme' && (e.newValue === 'light' || e.newValue === 'dark')) {
      document.documentElement.setAttribute('data-theme', e.newValue);
    }
  });
})();

// Existing BA pages read ?project_id= at import time: make sure it is there.
(function syncUrl() {
  if (!projectId) return;
  const url = new URL(window.location.href);
  if (url.searchParams.get('project_id') === projectId && !url.searchParams.has('project')) return;
  url.searchParams.delete('project');
  url.searchParams.set('project_id', projectId);
  window.history.replaceState(window.history.state, '', url);
})();

// Any 401 from the BA API means the platform session expired.
const nativeFetch = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const res = await nativeFetch(input, init);
  const url = typeof input === 'string' ? input : input?.url || '';
  if (res.status === 401 && url.includes(`${API_BASE}/`)) toLogin();
  return res;
};

const BAR_CSS = `
#platformBar{position:sticky;top:0;z-index:1000;display:flex;align-items:center;gap:14px;height:40px;padding:0 18px;
  background:var(--bg-surface);box-shadow:0 1px 0 var(--border-subtle);font:600 12.5px 'Plus Jakarta Sans',system-ui,sans-serif;color:var(--text-dim)}
#platformBar a{color:var(--text-dim);text-decoration:none}
#platformBar a:hover{color:var(--text-main)}
#platformBar .pb-project{color:var(--text-main);font-weight:700}
#platformBar .pb-id{font-weight:500;opacity:.8}
#platformBar .pb-spacer{flex:1}
#platformBar .pb-role{padding:2px 9px;border-radius:999px;background:var(--accent-cyan-subtle);color:var(--accent-cyan);font-size:11px;font-weight:700}
#platformBar .pb-ro{color:#f59e0b;background:rgba(245,158,11,.14)}
#platformBar button{background:none;border:0;color:var(--text-dim);cursor:pointer;font:inherit}
#platformBar button:hover{color:var(--text-main)}
body.platform-readonly #btnCreateFeature, body.platform-readonly #btnCreateFeature2, body.platform-readonly #btnStartChat,
body.platform-readonly #btnValidate, body.platform-readonly #btnExport, body.platform-readonly #btnExportBpmn,
body.platform-readonly #btnRegenBpmn, body.platform-readonly #btnExportDesigner,
body.platform-readonly #chatInput, body.platform-readonly #btnSend, body.platform-readonly #btnAttachReference,
body.platform-readonly #wikiUploadForm, body.platform-readonly #btnWikiClear,
body.platform-readonly .btn-delete-feature { display:none !important; }
`;

function renderBar(user, project, roles, readOnly) {
  const style = document.createElement('style');
  style.textContent = BAR_CSS;
  document.head.appendChild(style);
  const bar = document.createElement('div');
  bar.id = 'platformBar';
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  bar.innerHTML = `
    <a href="/">← Dự án</a>
    <span class="pb-project">${esc(project?.name || projectId)}</span>
    <span class="pb-id">${esc(projectId)}</span>
    <a href="index.html?project_id=${encodeURIComponent(projectId)}">Features</a>
    <a href="wiki.html?project_id=${encodeURIComponent(projectId)}">Wiki</a>
    <span class="pb-spacer"></span>
    ${readOnly ? '<span class="pb-role pb-ro">CHỈ ĐỌC</span>' : ''}
    ${roles.map((r) => `<span class="pb-role">${esc(r)}</span>`).join('')}
    <span>${esc(user.name)}</span>
    <button type="button" id="pbLogout">Đăng xuất</button>`;
  document.body.prepend(bar);
  bar.querySelector('#pbLogout').addEventListener('click', async () => {
    await nativeFetch('/api/core/auth/logout', { method: 'POST' }).catch(() => {});
    window.location.assign('/login');
  });
}

/** Resolves once the user and project are known (or redirects away). */
export const platformReady = (async () => {
  const meRes = await nativeFetch('/api/core/me', { credentials: 'same-origin' });
  if (meRes.status === 401) { toLogin(); return new Promise(() => {}); }
  if (!meRes.ok) return { user: null, project: null, roles: [], readOnly: false };
  const user = await meRes.json();
  if (!projectId) { window.location.assign('/'); return new Promise(() => {}); }
  const pRes = await nativeFetch(`/api/core/projects/${encodeURIComponent(projectId)}`);
  if (!pRes.ok) { window.location.assign('/'); return new Promise(() => {}); }
  const project = await pRes.json();
  const roles = project.my_roles || [];
  const readOnly = !roles.includes('BA') && !roles.includes('ADMIN') && !roles.includes('PM');
  if (readOnly) document.body.classList.add('platform-readonly');
  if (isEmbedded) document.body.classList.add('platform-embed');
  else renderBar(user, project, roles, readOnly);
  return { user, project, roles, readOnly };
})();

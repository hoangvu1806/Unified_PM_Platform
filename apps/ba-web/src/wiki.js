/**
 * BA-styled Wiki Knowledge page.
 * Same MVP SQLite as factory_wiki / WIKI_MVP_ROOT. Humans approve; agents never do.
 *
 * When opened from BA/VA with ?project_id=, this page is scoped to that project:
 * lists show company (shared) + this project only — never another project's private pages.
 *
 * With ?session=, approved rows also show last-Validate fail detail (V-WIKI pairs)
 * so you can demote/delete the violator, then re-Validate.
 */

// Platform: login, project context and read-only mode (must load first).
import './platform.js';
import {
  listWikiPages,
  uploadWikiSource,
  approveWikiPage,
  demoteWikiPage,
  deleteWikiPage,
  clearWikiStore,
  getFeatureDocuments,
} from './api.js';
import { escapeHtml } from './markdown.js';

const params = new URLSearchParams(window.location.search);
const sessionId = params.get('session') || '';
const featureTitle = params.get('title') || '';
const scopedFromBa = Boolean(params.get('project_id'));
let projectId = (params.get('project_id') || '').trim();

/** @type {Record<string, { validation_status?: string, validation_findings?: object[] }>} */
let validationByPageId = {};

const noticeEl = document.getElementById('wikiNotice');
const draftsEl = document.getElementById('wikiDrafts');
const approvedEl = document.getElementById('wikiApproved');
const projectInput = document.getElementById('wikiProject');
const scopeBanner = document.getElementById('wikiScopeBanner');

function withProject(hrefBase) {
  const q = new URLSearchParams();
  if (sessionId) q.set('session', sessionId);
  if (featureTitle) q.set('title', featureTitle);
  if (projectId) q.set('project_id', projectId);
  const qs = q.toString();
  return qs ? `${hrefBase}?${qs}` : hrefBase;
}

function chatHref() {
  if (!sessionId) return 'index.html';
  return withProject('chat.html');
}

function vaHref() {
  if (!sessionId) return withProject('va.html');
  return withProject('va.html');
}

function setNotice(text, kind = '') {
  if (!noticeEl) return;
  noticeEl.textContent = text;
  noticeEl.classList.remove('ok', 'err');
  if (kind) noticeEl.classList.add(kind);
}

function actorValue() {
  return document.getElementById('wikiActor')?.value || 'ba.lead';
}

function findingLine(findings, escape) {
  const list = Array.isArray(findings) ? findings : [];
  if (!list.length) return '';
  return list
    .map((f) => {
      const code = escape(f.check_id || 'V-WIKI');
      const detail = escape((f.detail || f.name || '').slice(0, 160));
      const others = (f.conflict_page_ids || []).map((id) => escape(id)).join(', ');
      const ref =
        others
          ? ` · vs ${others}`
          : f.conflict_ref
            ? ` · ref ${escape(String(f.conflict_ref).slice(0, 80))}`
            : '';
      return `<div class="wiki-va-finding"><span class="mono">${code}</span>${ref}<br>${detail}</div>`;
    })
    .join('');
}

function renderTable(rows, { approve = false, manageApproved = false } = {}) {
  if (!rows.length) {
    return `<p class="empty-row">${approve ? 'Chưa có draft.' : 'Chưa có trang approved.'}</p>`;
  }
  const hasActions = approve || manageApproved;
  const metaLabel = manageApproved ? 'VA' : approve ? 'status' : 'version';
  const colgroup = `<colgroup>
      <col class="col-page-id">
      <col class="col-ns">
      <col class="col-bucket">
      <col class="col-title">
      <col class="col-meta">
      ${hasActions ? '<col class="col-actions">' : ''}
    </colgroup>`;
  const head = `<tr>
      <th scope="col">page_id</th>
      <th scope="col">ns</th>
      <th scope="col">bucket</th>
      <th scope="col">title</th>
      <th scope="col">${metaLabel}</th>
      ${hasActions ? '<th scope="col">Actions</th>' : ''}
    </tr>`;
  const body = rows
    .map((p) => {
      const ns = escapeHtml(p.namespace || 'project');
      const pid = p.page_id || '';
      const va = validationByPageId[pid] || {};
      const status = String(va.validation_status || p.validation_status || '').toLowerCase();
      const findings = va.validation_findings || p.validation_findings || [];
      const stamp =
        status === 'fail'
          ? '<span class="stamp stamp-error">fail</span>'
          : status === 'pass'
            ? '<span class="stamp stamp-approved">pass</span>'
            : sessionId
              ? '<span class="stamp stamp-pending">unchecked</span>'
              : `<span class="mono">${escapeHtml(p.version || '')}</span>`;
      const failDetail =
        status === 'fail' ? findingLine(findings, escapeHtml) : '';
      const approveBtn = approve
        ? `<td class="wiki-actions-cell"><div class="wiki-row-actions"><button class="btn btn-cyan" type="button" data-approve="${escapeHtml(pid)}">Approve</button></div></td>`
        : '';
      const manageBtns = manageApproved
        ? `<td class="wiki-actions-cell">
            <div class="wiki-row-actions">
              <button class="btn wiki-btn-demote" type="button" data-demote="${escapeHtml(pid)}" title="approved → draft">Demote</button>
              <button class="btn wiki-btn-delete" type="button" data-delete="${escapeHtml(pid)}" title="Hard delete">Delete</button>
            </div>
          </td>`
        : '';
      const midCol = manageApproved
        ? `<td>${stamp}${failDetail}</td>`
        : approve
          ? `<td>${escapeHtml(p.status || '')}</td>`
          : `<td>${escapeHtml(p.version || '')}</td>`;
      return `<tr data-validation-status="${escapeHtml(status || '')}">
      <td class="mono" title="${escapeHtml(pid)}">${escapeHtml(pid)}</td>
      <td><span class="tag">${ns}</span></td>
      <td><span class="tag">${escapeHtml(p.bucket_id || '')}</span></td>
      <td class="wiki-title-cell">${escapeHtml(p.title || '')}${
        p.snippet
          ? `<div style="color:var(--text-dim);font-size:12px;margin-top:2px;">${escapeHtml(p.snippet)}</div>`
          : ''
      }</td>
      ${midCol}
      ${approveBtn}
      ${manageBtns}
    </tr>`;
    })
    .join('');
  return `<table class="wiki-table">${colgroup}<thead>${head}</thead><tbody>${body}</tbody></table>`;
}

function renderSplitSections(companyRows, projectRows, opts = {}) {
  return `
    <div class="wiki-split">
      <div class="wiki-split-block">
        <h3 class="wiki-split-title">Company <span class="tag tag-cyan">shared</span></h3>
        <p class="wiki-split-sub">Visible to every BA project.</p>
        ${renderTable(companyRows, opts)}
      </div>
      <div class="wiki-split-block">
        <h3 class="wiki-split-title">This project only <span class="tag tag-violet mono">${escapeHtml(projectId)}</span></h3>
        <p class="wiki-split-sub">Private to this project_id — other projects cannot see these pages.</p>
        ${renderTable(projectRows, opts)}
      </div>
    </div>`;
}

function bindApproveButtons(root) {
  root.querySelectorAll('[data-approve]').forEach((btn) => {
    btn.addEventListener('click', () => handleApprove(btn.getAttribute('data-approve')));
  });
}

function bindManageButtons(root) {
  root.querySelectorAll('[data-demote]').forEach((btn) => {
    btn.addEventListener('click', () => handleDemote(btn.getAttribute('data-demote')));
  });
  root.querySelectorAll('[data-delete]').forEach((btn) => {
    btn.addEventListener('click', () => handleDelete(btn.getAttribute('data-delete')));
  });
}

async function loadValidationOverlay() {
  validationByPageId = {};
  if (!sessionId) return null;
  try {
    const docs = await getFeatureDocuments(sessionId);
    for (const d of docs.documents || []) {
      if (!d?.page_id) continue;
      validationByPageId[d.page_id] = {
        validation_status: d.validation_status,
        validation_findings: d.validation_findings || [],
      };
    }
    return docs.wiki_validation || null;
  } catch {
    return null;
  }
}

async function refresh() {
  if (!projectId) {
    draftsEl.innerHTML =
      '<p class="empty-row">Mở Wiki từ BA chat (có <code class="mono">project_id</code>) hoặc nhập project id ở form upload.</p>';
    approvedEl.innerHTML = draftsEl.innerHTML;
    return;
  }
  const [payload, wikiVa] = await Promise.all([
    listWikiPages(projectId),
    loadValidationOverlay(),
  ]);
  const companyDrafts = payload.company_drafts || [];
  const projectDrafts = payload.project_drafts || [];
  const companyApproved = payload.company_approved || [];
  const projectApproved = payload.project_approved || [];

  // Fallback if older API without split fields
  if (
    !payload.company_approved &&
    !payload.project_approved &&
    Array.isArray(payload.approved)
  ) {
    for (const p of payload.approved) {
      if (p.namespace === 'company') companyApproved.push(p);
      else projectApproved.push(p);
    }
  }
  if (
    !payload.company_drafts &&
    !payload.project_drafts &&
    Array.isArray(payload.drafts)
  ) {
    for (const p of payload.drafts) {
      if (p.namespace === 'company') companyDrafts.push(p);
      else projectDrafts.push(p);
    }
  }

  draftsEl.innerHTML = renderSplitSections(companyDrafts, projectDrafts, { approve: true });
  approvedEl.innerHTML = renderSplitSections(companyApproved, projectApproved, {
    manageApproved: true,
  });
  bindApproveButtons(draftsEl);
  bindManageButtons(approvedEl);

  const hint = document.getElementById('wikiApprovedHint');
  if (hint) {
    if (wikiVa && wikiVa.overall === 'fail') {
      hint.textContent =
        'Last Validate: wiki FAIL — demote or delete one page in each conflict pair, then re-Validate.';
    } else if (sessionId) {
      hint.textContent =
        'VA stamps come from last Validate on this session. After demote/delete, re-Validate.';
    } else {
      hint.textContent =
        'Open from BA/VA with ?session= to see fail stamps. Prefer Demote (→ draft) over Delete.';
    }
  }
}

async function handleApprove(pageId) {
  if (!pageId) return;
  if (!window.confirm(`Approve ${pageId}? Agents cannot do this.`)) return;
  try {
    await approveWikiPage(pageId, { actor: actorValue(), projectId });
    setNotice(
      `Approved ${pageId}. Run Validate again — VA reads this approved page, not drafts and not the previous report.`,
      'ok',
    );
    await refresh();
  } catch (err) {
    setNotice(err.message || String(err), 'err');
  }
}

async function handleDemote(pageId) {
  if (!pageId) return;
  if (
    !window.confirm(
      `Demote ${pageId} to draft?\n\nIt becomes invisible to BA/VA (clears V-WIKI if this was the violator). Re-Validate after.`,
    )
  ) {
    return;
  }
  try {
    await demoteWikiPage(pageId, { actor: actorValue(), projectId });
    setNotice(
      `Demoted ${pageId} → draft. Re-Validate in BA/VA to clear the last fail snapshot.`,
      'ok',
    );
    await refresh();
  } catch (err) {
    setNotice(err.message || String(err), 'err');
  }
}

async function handleDelete(pageId) {
  if (!pageId) return;
  if (
    !window.confirm(
      `Hard delete ${pageId}?\n\nPrefer Demote when unsure. This cannot be undone. Re-Validate after.`,
    )
  ) {
    return;
  }
  try {
    await deleteWikiPage(pageId, { actor: actorValue(), projectId });
    setNotice(`Deleted ${pageId}. Re-Validate in BA/VA.`, 'ok');
    await refresh();
  } catch (err) {
    setNotice(err.message || String(err), 'err');
  }
}

function setClearPanelOpen(open) {
  const panel = document.getElementById('wikiClearPanel');
  const input = document.getElementById('wikiClearConfirm');
  if (!panel) return;
  panel.hidden = !open;
  if (input) {
    input.value = '';
    if (open) input.focus();
  }
}

async function handleClear() {
  const typed = (document.getElementById('wikiClearConfirm')?.value || '').trim();
  if (typed.toUpperCase() !== 'CLEAR') {
    setNotice('Type CLEAR to confirm. This deletes all wiki pages, drafts, sources, blobs.', 'err');
    return;
  }
  if (!window.confirm('This deletes all wiki pages, drafts, sources, blobs. Continue?')) {
    return;
  }
  const btn = document.getElementById('btnWikiClearConfirm');
  if (btn) btn.disabled = true;
  setNotice('Clearing wiki database…');
  try {
    const result = await clearWikiStore({
      confirm: 'CLEAR',
      actor: actorValue(),
    });
    setNotice(
      `Wiki cleared (${result.removed_blobs ?? 0} blobs). Drafts and approved lists are empty. Upload still works.`,
      'ok',
    );
    setClearPanelOpen(false);
    await refresh();
  } catch (err) {
    setNotice(err.message || String(err), 'err');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function handleUpload(event) {
  event.preventDefault();
  const file = document.getElementById('wikiFile').files[0];
  if (!file) {
    setNotice('Choose a file to upload.', 'err');
    return;
  }
  const namespace = document.getElementById('wikiNamespace').value;
  if (!scopedFromBa) {
    projectId = projectInput.value.trim();
    if (!projectId && namespace === 'project') {
      setNotice('Nhập project_id (mở từ BA chat để khóa đúng dự án).', 'err');
      return;
    }
  } else {
    projectId = (params.get('project_id') || projectId || '').trim();
    if (projectInput) projectInput.value = projectId;
  }
  const btn = document.getElementById('btnWikiUpload');
  btn.disabled = true;
  setNotice(
    namespace === 'company'
      ? `Uploading ${file.name} → company draft (shared)… LLM sort can take up to ~60s.`
      : `Uploading ${file.name} → draft for ${projectId} only… LLM sort can take up to ~60s.`,
  );
  try {
    const result = await uploadWikiSource(file, {
      namespace,
      projectId,
      actor: actorValue(),
      sortMode: document.getElementById('wikiSort').value,
    });
    const n = (result.proposed_page_ids || []).length;
    if (result.sort_status === 'unchanged_existing_source') {
      setNotice(
        `Same file already ingested for this project — source=${result.source_id || '—'}, linked drafts=${n}. Upload a changed file or Approve existing drafts.`,
        n ? 'ok' : 'err',
      );
    } else {
      setNotice(
        `Ingest OK — drafts+=${n}, source=${result.source_id || '—'}, sort=${result.sort_backend || result.sort_status || '—'}. VA still cannot see these drafts until you Approve.`,
        'ok',
      );
    }
    document.getElementById('wikiFile').value = '';
    await refresh();
  } catch (err) {
    setNotice(err.message || String(err), 'err');
  } finally {
    btn.disabled = false;
  }
}

function syncNamespaceHint() {
  const ns = document.getElementById('wikiNamespace')?.value;
  const hint = document.getElementById('wikiProjectHint');
  if (!hint) return;
  if (ns === 'company') {
    hint.textContent = 'Company upload ignores project binding — page is shared org-wide.';
  } else if (projectId) {
    hint.textContent = `Project upload is private to ${projectId}. Other projects will not see it.`;
  } else {
    hint.textContent = 'Required for project uploads — open Wiki from BA chat or paste the hashed PRJ-… id.';
  }
}

function initChrome() {
  if (!projectId && !scopedFromBa) {
    projectId = '';
  }
  if (projectInput) {
    projectInput.value = projectId;
    projectInput.placeholder = 'PRJ-… (from BA link)';
    if (scopedFromBa) {
      projectInput.readOnly = true;
      projectInput.title = 'Locked to the BA feature project_id';
      projectInput.classList.add('is-locked');
    }
  }
  if (scopeBanner) {
    if (scopedFromBa) {
      scopeBanner.hidden = false;
      scopeBanner.innerHTML = `Scoped to BA project <code class="mono">${escapeHtml(projectId)}</code>${
        sessionId ? ` · session <code class="mono">${escapeHtml(sessionId.slice(0, 12))}…</code>` : ''
      }. Lists show <strong>company (shared)</strong> + <strong>this project only</strong>.`;
    } else if (!projectId) {
      scopeBanner.hidden = false;
      scopeBanner.innerHTML =
        'No <code class="mono">project_id</code> in the URL. Open Wiki from a BA feature (dock link) so lists use that hashed <code class="mono">PRJ-…</code>, or enter it in the Project field below. Never defaults to a shared MES id.';
    } else {
      scopeBanner.hidden = true;
    }
  }
  const ba = document.getElementById('linkOpenBa');
  const va = document.getElementById('linkOpenVa');
  if (ba) ba.href = chatHref();
  if (va) va.href = vaHref();
  const tag = document.getElementById('sessionTag');
  if (tag) {
    if (sessionId && projectId) {
      tag.textContent = `[SESSION] ${sessionId.slice(0, 12)}… · ${projectId}`;
    } else if (sessionId) {
      tag.textContent = `[SESSION] ${sessionId.slice(0, 12)}…`;
    } else if (projectId) {
      tag.textContent = `project · ${projectId}`;
    } else {
      tag.textContent = 'documents · pick project_id';
    }
  }
  document.getElementById('wikiNamespace')?.addEventListener('change', syncNamespaceHint);
  syncNamespaceHint();
}

async function init() {
  initChrome();
  document.getElementById('wikiUploadForm').addEventListener('submit', handleUpload);
  document.getElementById('btnWikiClear')?.addEventListener('click', () => setClearPanelOpen(true));
  document.getElementById('btnWikiClearCancel')?.addEventListener('click', () => setClearPanelOpen(false));
  document.getElementById('btnWikiClearConfirm')?.addEventListener('click', handleClear);
  document.getElementById('wikiClearConfirm')?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      handleClear();
    }
  });
  try {
    await refresh();
  } catch (err) {
    setNotice(err.message || String(err), 'err');
    draftsEl.innerHTML = '<p class="empty-row">Không tải được wiki store. Kiểm tra WIKI_MVP_ROOT / API :8000.</p>';
  }
}

init();

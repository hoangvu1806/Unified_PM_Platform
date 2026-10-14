/**
 * Validate Agent page — same session_id / feature_status as BA chat.
 * Reuses the in-process VA subgraph (action=validate + discuss turns).
 * Does not fork a second validator and does not mutate BA artifacts.
 */

import { sendChatMessage, getFeature, getChatHistory, getFeatureDocuments } from './api.js';
import { initColumnResize } from './column-resize.js';
import { escapeHtml, formatChatMarkdown } from './markdown.js';
import { renderApprovedWikiDocs } from './wiki-docs-list.js';

const TIER1 = [
  { id: 'feature_definition', num: 'SEC-01', title: 'Feature Definition' },
  { id: 'business_rules', num: 'SEC-02', title: 'Business Rules' },
  { id: 'workflow', num: 'SEC-03', title: 'Workflow' },
  { id: 'use_cases', num: 'SEC-04', title: 'User Stories' },
];

let sessionId = '';
let featureTitle = '';
let featureStatus = 'DRAFT';
let canValidate = false;
let isSending = false;
let messages = [];
let wikiDocuments = [];
let wikiCompanyDocuments = null;
let wikiProjectDocuments = null;
let wikiValidationSummary = null;
let wikiDocsExpanded = false;
let lastValidation = null;
let sections = {};
let packageHint = '';
let projectId = '';

const chatStream = document.getElementById('chatStream');
const chatInput = document.getElementById('chatInput');
const btnSend = document.getElementById('btnSend');

function factoryPageHref(page) {
  const q = new URLSearchParams();
  if (sessionId) q.set('session', sessionId);
  if (featureTitle) q.set('title', featureTitle);
  if (projectId) q.set('project_id', projectId);
  return `${page}?${q.toString()}`;
}

async function init() {
  const params = new URLSearchParams(window.location.search);
  sessionId = params.get('session') || '';
  featureTitle = params.get('title') || 'Untitled Feature';
  if (params.get('project_id')) projectId = params.get('project_id');
  if (!sessionId) {
    alert('Thiếu session ID. Mở Validate Agent từ Document Manager hoặc BA chat.');
    window.location.href = 'index.html';
    return;
  }

  document.getElementById('headerFeatureTitle').textContent = featureTitle;
  document.getElementById('sessionTag').textContent = `[SESSION] ${sessionId.slice(0, 12)}... · ${projectId}`;
  const baLink = document.getElementById('linkOpenBa');
  if (baLink) {
    baLink.href = factoryPageHref('chat.html');
  }
  const wikiLink = document.getElementById('linkOpenWiki');
  if (wikiLink) {
    wikiLink.href = factoryPageHref('wiki.html');
  }

  initColumnResize(document.querySelector('.app-container'), 'va-page-column-widths');
  bindEvents();
  await refreshAll();
  await loadHistory();
  if (!messages.length) {
    messages.push({
      sender: 'agent',
      text: canValidate
        ? 'Đây là **Validate Agent** trên cùng session với BA chat. Bấm **Run Validate** để chạy rules (PASS/FAIL do Python). Sau đó hỏi tự do về findings / wiki — VA giải thích, không sửa artifact, không đảo kết quả. Muốn đổi gói hãy mở BA chat.'
        : packageHint || validationNotReadyFallback(),
    });
  }
  renderAll();
}

function bindEvents() {
  btnSend.addEventListener('click', () => handleSend(null));
  const btnValidate = document.getElementById('btnValidate');
  if (btnValidate) {
    btnValidate.addEventListener('click', handleValidate);
  }
  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend(null);
    }
  });
}

async function refreshAll() {
  const feature = await getFeature(sessionId);
  featureStatus = feature.feature_status || 'DRAFT';
  if (feature.package_exported != null) packageExported = Boolean(feature.package_exported);
  if (feature.chat_frozen) packageExported = true;
  canValidate = Boolean(feature.can_proceed_to_validation);
  lastValidation = feature.last_validation || lastValidation;
  sections = feature.sections || {};
  if (feature.title) {
    featureTitle = feature.title;
    document.getElementById('headerFeatureTitle').textContent = featureTitle;
  }
  if (feature.project_id) {
    projectId = feature.project_id;
    document.getElementById('sessionTag').textContent =
      `[SESSION] ${sessionId.slice(0, 12)}... · ${projectId}`;
    const baLink = document.getElementById('linkOpenBa');
    if (baLink) baLink.href = factoryPageHref('chat.html');
    const wikiLink = document.getElementById('linkOpenWiki');
    if (wikiLink) wikiLink.href = factoryPageHref('wiki.html');
  }
  try {
    const docs = await getFeatureDocuments(sessionId);
    wikiDocuments = docs.documents || [];
    wikiCompanyDocuments = docs.company_documents || null;
    wikiProjectDocuments = docs.project_documents || null;
    wikiValidationSummary = docs.wiki_validation || null;
  } catch (err) {
    console.warn('wiki documents', err);
  }
  packageHint = buildReadinessHint(feature);
  syncButtons();
}

function buildReadinessHint(feature) {
  if (feature.can_proceed_to_validation) {
    return `Sẵn sàng validate. feature_status = **${feature.feature_status}**.`;
  }
  const lines = [
    '📋 **Validate Agent chưa chạy được.**',
    '',
    'Cổng tuần tự **FD → BR → WF → UC** vẫn giữ. Không validate draft trống.',
    '',
    `feature_status hiện tại: **${feature.feature_status || 'DRAFT'}**`,
  ];
  for (const sec of TIER1) {
    const row = (feature.sections || {})[sec.id];
    const done = row && row.is_completable ? 'completed' : 'incomplete';
    lines.push(`- \`${sec.id}\`: ${done}`);
  }
  const critical = (feature.open_questions || []).filter(
    (oq) => oq.severity === 'critical' && (oq.status || 'open') === 'open',
  );
  if (critical.length) {
    lines.push('');
    lines.push('Open questions **critical** còn mở (trả lời trong BA chat bằng `OQ-00N:`):');
    for (const oq of critical) {
      lines.push(`- \`${oq.id || 'OQ'}\`: ${oq.question || ''}`);
    }
  }
  lines.push('');
  lines.push('Hãy hoàn tất BA chat, rồi mở lại trang này.');
  return lines.join('\n');
}

function validationNotReadyFallback() {
  return 'Package chưa đủ điều kiện validate. Hoàn tất FD → BR → WF → UC trên BA chat trước.';
}

const VALIDATE_STATUSES = ['PENDING_VALIDATION', 'VALIDATED', 'VALIDATION_FAILED', 'EXPORTED'];
const CHAT_FROZEN_REASON = 'Chat is frozen after Export';
const INFLIGHT_REASON = 'Đang xử lý — chờ lượt hiện tại kết thúc';
const CHAT_FROZEN_HINT = 'Chat is frozen after Export. Validate can still refresh against current approved wiki.';

let packageExported = false;

function isBaChatFrozen() {
  return packageExported || featureStatus === 'EXPORTED';
}

function setControlEnabled(el, enabled, reason) {
  if (!el) return;
  el.disabled = !enabled;
  if (enabled || !reason) {
    el.removeAttribute('title');
    el.removeAttribute('aria-description');
  } else {
    el.title = reason;
    el.setAttribute('aria-description', reason);
  }
}

function setSendBusy(busy) {
  if (!btnSend) return;
  btnSend.classList.toggle('is-sending', busy);
  btnSend.setAttribute('aria-busy', busy ? 'true' : 'false');
  btnSend.setAttribute('aria-label', busy ? 'Đang xử lý...' : 'Gửi cho VA');
}

function syncButtons() {
  const baFrozen = isBaChatFrozen();
  const canRunValidate = !isSending && (canValidate || VALIDATE_STATUSES.includes(featureStatus));
  const lockReason = isSending ? INFLIGHT_REASON : '';
  setControlEnabled(
    document.getElementById('btnValidate'),
    canRunValidate,
    canRunValidate ? '' : (lockReason || 'Validate when the BA package is ready'),
  );
  if (chatInput) {
    chatInput.disabled = isSending;
    chatInput.title = baFrozen
      ? 'BA chat is frozen; VA can still discuss findings and re-validate'
      : '';
  }
  setControlEnabled(btnSend, !isSending, lockReason);
  const hint = document.getElementById('composerLockHint');
  if (hint) {
    if (isSending) {
      hint.hidden = false;
      hint.textContent = INFLIGHT_REASON;
    } else if (baFrozen) {
      hint.hidden = false;
      hint.textContent = 'BA chat is frozen after Export. VA can still discuss and re-validate against wiki.';
    } else {
      hint.hidden = true;
      hint.textContent = '';
    }
  }
  const stampEl = document.getElementById('featureStatusBadge');
  if (stampEl) {
    stampEl.textContent = featureStatus;
    stampEl.dataset.status = featureStatus;
  }
}

async function loadHistory() {
  try {
    const historyRes = await getChatHistory(sessionId, 'validation');
    if (historyRes && historyRes.messages && historyRes.messages.length) {
      messages = historyRes.messages.map((m) => ({ sender: m.sender, text: m.text }));
    }
  } catch (err) {
    console.warn('VA history', err);
  }
  if (lastValidation && lastValidation.agent_response) {
    const report = lastValidation.agent_response;
    if (!messages.some((m) => m.text && m.text.includes(report.slice(0, 40)))) {
      messages.push({ sender: 'agent', text: report });
    }
  }
}

function renderAll() {
  renderNav();
  renderReadiness();
  renderWiki();
  renderChat();
  renderWorkspace();
  updateProgress();
}

function renderNav() {
  const g1 = document.getElementById('group1List');
  const g2 = document.getElementById('group2List');
  g1.innerHTML = TIER1.map((sec) => {
    const row = sections[sec.id];
    const done = row && row.is_completable;
    const stamp = done
      ? '<span class="stamp stamp-approved">[COMPLETED]</span>'
      : '<span class="stamp stamp-pending">[INCOMPLETE]</span>';
    return `<div class="section-item">
      <div class="section-item-head">
        <span class="mono section-item-id">${sec.num}</span>
        <span class="section-item-title">${sec.title}</span>
        ${stamp}
      </div>
    </div>`;
  }).join('');
  const vaStamp = lastValidation
    ? `<span class="stamp ${lastValidation.status === 'failed' || lastValidation.status === 'blocked' ? 'stamp-error' : 'stamp-approved'}">[${escapeHtml(String(lastValidation.status || 'none').toUpperCase())}]</span>`
    : '<span class="stamp stamp-pending">[NO RUN]</span>';
  g2.innerHTML = `
    <div class="section-item active">
      <div class="section-item-head">
        <span class="mono section-item-id">VA</span>
        <span class="section-item-title">Validation report</span>
        ${vaStamp}
      </div>
      <div class="section-item-body">
        <span class="section-item-sub">In-process subgraph · same session</span>
      </div>
    </div>
  `;
}

function renderReadiness() {
  const grid = document.getElementById('checklistGrid');
  const items = [
    { ok: canValidate, label: 'FD → BR → WF → UC complete + no critical OQ' },
    { ok: true, label: 'VA chat can discuss findings even after BA Export' },
    { ok: Boolean(lastValidation && lastValidation.agent_response), label: 'Last validation report available' },
  ];
  grid.innerHTML = items.map((item) => `
    <div class="check-item ${item.ok ? 'done' : ''}">
      <div class="check-icon">${item.ok ? '✓' : '•'}</div>
      <span>${escapeHtml(item.label)}</span>
    </div>
  `).join('');
  document.getElementById('checkProgressRatio').textContent = canValidate ? 'READY' : 'Not ready';
}

function renderWiki() {
  renderApprovedWikiDocs(wikiDocuments, {
    escapeHtml,
    expanded: wikiDocsExpanded,
    projectId,
    companyDocuments: wikiCompanyDocuments || undefined,
    projectDocuments: wikiProjectDocuments || undefined,
    wikiValidation: wikiValidationSummary || undefined,
    onToggle: (next) => {
      wikiDocsExpanded = next;
      renderWiki();
    },
  });
}

function renderChat() {
  chatStream.innerHTML = '';
  messages.forEach((msg) => {
    const row = document.createElement('div');
    row.className = `message-row ${msg.sender === 'user' ? 'user' : ''} animate-fadeIn`;
    const body = msg.sender === 'agent'
      ? `<div class="bubble bubble-md">${formatChatMarkdown(msg.text)}</div>`
      : `<div class="bubble">${escapeHtml(msg.text)}</div>`;
    row.innerHTML = `
      <div class="avatar ${msg.sender === 'user' ? 'user-avatar' : 'agent'}">
        ${msg.sender === 'user' ? 'YOU' : 'VA'}
      </div>
      ${body}
    `;
    chatStream.appendChild(row);
  });
  chatStream.scrollTop = chatStream.scrollHeight;
}

function renderWorkspace() {
  const wsEl = document.getElementById('workspaceBody');
  const failed = (lastValidation && lastValidation.failed_checks) || [];
  const warnings = (lastValidation && lastValidation.warnings) || [];
  const passed = (lastValidation && lastValidation.passed_checks) || [];
  const coverage = (lastValidation && lastValidation.coverage_summary) || {};
  const report = lastValidation && lastValidation.agent_response;
  const evidence = (lastValidation && lastValidation.evidence_references) || [];
  const findings = failed.length
    ? failed.map((f) => `
        <div class="ws-item-card">
          <div class="ws-item-header">
            <span class="ws-item-id">${escapeHtml(f.check_id || 'V')}</span>
            <span class="ws-item-meta">${escapeHtml(f.severity || 'error')}</span>
          </div>
          <div class="ws-item-body"><strong>${escapeHtml(f.name || '')}</strong><br>${escapeHtml(f.detail || '')}${
            f.evidence_page_id || f.page_id
              ? `<br><span class="ws-item-meta">wiki ${escapeHtml(f.evidence_page_id || f.page_id)}${
                  f.evidence_page_title ? ` · ${escapeHtml(f.evidence_page_title)}` : ''
                }${
                  f.conflict_ref
                    ? ` · conflict ${escapeHtml(String(f.conflict_ref))}`
                    : ''
                }</span>`
              : f.conflict_ref
                ? `<br><span class="ws-item-meta">conflict ${escapeHtml(String(f.conflict_ref))}</span>`
                : ''
          }${
            f.suggestion ? `<br><em>${escapeHtml(f.suggestion)}</em>` : ''
          }</div>
        </div>
      `).join('')
    : emptyHint('Không có failed_checks.');
  const covLine = lastValidation
    ? `${coverage.use_cases ?? '—'} UC · ${coverage.business_rules ?? '—'} BR · ${coverage.exception_flows ?? '—'} exception · ${coverage.wiki_pages ?? '—'} wiki · ${escapeHtml(String(lastValidation.ruleset_version || ''))}`
    : '';
  wsEl.innerHTML = `
    <div class="field-group">
      <label class="field-label">Last report</label>
      ${report
        ? `<div class="bubble bubble-md" style="max-width:100%;">${formatChatMarkdown(report)}</div>`
        : emptyHint('Chưa có report. Bấm Run Validate khi package READY.')}
    </div>
    <div class="field-group">
      <label class="field-label">Coverage</label>
      ${covLine ? `<div class="ws-item-body">${escapeHtml(covLine)}</div>` : emptyHint('Chưa có coverage.')}
      ${passed.length
        ? `<div class="ws-item-body">Passed: ${escapeHtml(passed.map((p) => p.check_id || p.name).join(', '))}</div>`
        : ''}
    </div>
    <div class="field-group">
      <label class="field-label">Findings</label>
      ${findings}
    </div>
    <div class="field-group">
      <label class="field-label">Warnings</label>
      ${warnings.length
        ? warnings.map((w) => `<div class="ws-item-body">• ${escapeHtml(w.name || '')}: ${escapeHtml(w.detail || '')}</div>`).join('')
        : emptyHint('Không có warning.')}
    </div>
    <div class="field-group">
      <label class="field-label">Wiki evidence (approved)</label>
      ${evidence.length
        ? evidence.slice(0, 12).map((e) => `<div class="ws-item-body">• ${escapeHtml(e.page_id || '')}: ${escapeHtml(e.title || '')}</div>`).join('')
        : emptyHint('Không có trang approved.')}
    </div>
  `;
}

function emptyHint(text) {
  return `<div style="font-size:11.5px;color:var(--text-dim);padding:8px 0;">${escapeHtml(text)}</div>`;
}

function updateProgress() {
  const completed = TIER1.filter((s) => sections[s.id] && sections[s.id].is_completable).length;
  const pct = Math.round((completed / TIER1.length) * 100);
  document.getElementById('globalProgressFill').style.width = `${pct}%`;
  document.getElementById('progressLabel').textContent = `${completed} / ${TIER1.length} Required`;
  document.getElementById('globalProgressStamp').textContent = `[${completed}/4 GROUP 1]`;
}

async function handleValidate() {
  if (isSending) return;
  if (!canValidate && !VALIDATE_STATUSES.includes(featureStatus)) {
    messages.push({ sender: 'agent', text: packageHint || validationNotReadyFallback() });
    renderChat();
    return;
  }
  chatInput.value = '[VALIDATE] Validate BA package';
  await handleSend('validate');
}

async function handleSend(action) {
  const text = chatInput.value.trim();
  if (!text || isSending) return;

  messages.push({ sender: 'user', text });
  chatInput.value = '';
  renderChat();

  isSending = true;
  setSendBusy(true);
  syncButtons();
  showTyping();

  let current = null;
  try {
    await sendChatMessage(sessionId, text, 'validation', { action }, {
      onMessage: (data) => {
        removeTyping();
        if (!current) {
          current = { sender: 'agent', text: data.text || '' };
          messages.push(current);
        } else {
          current.text += data.text || '';
        }
        renderChat();
      },
      onStateUpdate: (stateData) => {
        if (stateData.feature_status) featureStatus = stateData.feature_status;
        if (stateData.can_proceed_to_validation != null) {
          canValidate = Boolean(stateData.can_proceed_to_validation);
        }
        if (stateData.package_exported != null) packageExported = Boolean(stateData.package_exported);
        if (stateData.chat_frozen) packageExported = true;
        if (stateData.last_validation && Object.keys(stateData.last_validation).length) {
          lastValidation = stateData.last_validation;
        }
        syncButtons();
        renderNav();
        renderReadiness();
        renderWiki();
        renderWorkspace();
      },
      onDone: async () => {
        removeTyping();
        try {
          await refreshAll();
        } catch (err) {
          console.warn('VA refresh', err);
        }
        const report = lastValidation && lastValidation.agent_response;
        if (action === 'validate' && report) {
          if (!current || !current.text || !String(current.text).trim()) {
            if (!current) {
              current = { sender: 'agent', text: report };
              messages.push(current);
            } else {
              current.text = report;
            }
          }
        }
        renderAll();
      },
      onError: async (err) => {
        removeTyping();
        const preserved = messages.map((m) => ({ ...m }));
        const errText = String((err && err.message) || 'Unknown error')
          .split(/\r?\n/)
          .find((line) => line.trim()) || 'Unknown error';
        const compact = errText.replace(/\s+/g, ' ').trim().slice(0, 480);
        messages = [...preserved, { sender: 'agent', text: `⚠️ Lỗi: ${compact}` }];
        renderAll();
        try {
          await refreshAll();
        } catch (refreshErr) {
          console.warn(refreshErr);
        }
        if (messages.length < preserved.length + 1) {
          messages = [...preserved, { sender: 'agent', text: `⚠️ Lỗi: ${compact}` }];
        }
        renderAll();
      },
    });
  } finally {
    isSending = false;
    setSendBusy(false);
    syncButtons();
  }
}

function showTyping() {
  if (chatStream.querySelector('.typing-row')) return;
  const row = document.createElement('div');
  row.className = 'message-row typing-row animate-fadeIn';
  row.innerHTML = `
    <div class="avatar agent">VA</div>
    <div class="bubble typing-indicator">
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
    </div>
  `;
  chatStream.appendChild(row);
  chatStream.scrollTop = chatStream.scrollHeight;
}

function removeTyping() {
  const el = chatStream.querySelector('.typing-row');
  if (el) el.remove();
}

init();

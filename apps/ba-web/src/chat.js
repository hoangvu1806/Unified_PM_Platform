/**
 * BA Agent — Chat Workspace Script
 *
 * Handles:
 * - 8 sections navigation (2 groups)
 * - Chat messaging with SSE streaming
 * - Real-time flags/data updates
 * - Workspace form rendering
 */

// Platform: login, project context and read-only mode (must load first).
import { isEmbedded } from './platform.js';
import { sendChatMessage, getFeature, getChatHistory, exportFeature, exportAndOpenDesigner, getFeatureDocuments, downloadBpmn, saveTouchpoints } from './api.js';
import { initColumnResize } from './column-resize.js';
import { escapeHtml, formatChatMarkdown } from './markdown.js';
import { destroyBpmnPreview, renderBpmnDiagram, resizeBpmnPreview } from './bpmn-viewer.js';
import { renderApprovedWikiDocs } from './wiki-docs-list.js';

// ── Section Definitions ──────────────────────────────────────

const TIER1_IDS = ['feature_definition', 'business_rules', 'workflow', 'use_cases'];

const SECTIONS = [
  {
    id: 'feature_definition', group: 1, num: 'SEC-01',
    title: 'Feature Definition', sub: 'Định nghĩa tính năng',
    flags: [
      { id: 'FD-F1', label: 'Goal (Mục tiêu & Giá trị nghiệp vụ)', severity: 'blocker' },
      { id: 'FD-F2', label: 'Actors (Tác nhân ≥ 2)', severity: 'blocker' },
      { id: 'FD-F3', label: 'Scope In (Phạm vi bao gồm ≥ 1)', severity: 'blocker' },
      { id: 'FD-F5', label: 'No scope conflict (Scope In vs Out)', severity: 'blocker' },
      { id: 'FD-F4', label: 'Scope Out (Phạm vi ngoại trừ ≥ 1)', severity: 'warning' },
    ],
  },
  {
    id: 'business_rules', group: 1, num: 'SEC-02',
    title: 'Business Rules', sub: 'Quy tắc nghiệp vụ',
    flags: [
      { id: 'BR-F1', label: 'Min rules count >= 2', severity: 'blocker' },
      { id: 'BR-F2', label: 'All have source', severity: 'warning' },
      { id: 'BR-F3', label: 'Statements measurable', severity: 'warning' },
      { id: 'BR-F4', label: 'No contradiction', severity: 'blocker' },
      { id: 'BR-F5', label: 'True business rules', severity: 'warning' },
    ],
  },
  {
    id: 'workflow', group: 1, num: 'SEC-03',
    title: 'Workflow', sub: 'Quy trình luồng',
    flags: [
      { id: 'WF-F1', label: 'Main flow defined', severity: 'blocker' },
      { id: 'WF-F2', label: 'End-to-end coverage', severity: 'blocker' },
      { id: 'WF-F3', label: 'Exception flows exist', severity: 'warning' },
      { id: 'WF-F4', label: 'Actor consistency', severity: 'blocker' },
      { id: 'WF-F5', label: 'BR references', severity: 'warning' },
      { id: 'WF-F6', label: 'End states defined', severity: 'warning' },
    ],
  },
  {
    id: 'use_cases', group: 1, num: 'SEC-04',
    title: 'User Stories', sub: 'User stories + AC',
    flags: [
      { id: 'UC-F1', label: 'Min use cases >= 1', severity: 'blocker' },
      { id: 'UC-F2', label: 'Statement format', severity: 'blocker' },
      { id: 'UC-F3', label: 'Actor validity', severity: 'blocker' },
      { id: 'UC-F4', label: 'Rule linkage', severity: 'warning' },
      { id: 'UC-F5', label: 'No duplicate scope', severity: 'blocker' },
      { id: 'UC-F6', label: 'Actor coverage', severity: 'warning' },
      { id: 'UC-F7', label: 'AC exists', severity: 'blocker' },
      { id: 'UC-F8', label: 'Happy path AC', severity: 'blocker' },
    ],
  },
  {
    id: 'bpmn_reference', group: 2, num: 'SEC-05',
    title: 'BPMN Reference', sub: 'Sơ đồ BPMN (Auto)',
    flags: [],
  },
  {
    id: 'ui_touchpoints', group: 2, num: 'SEC-06',
    title: 'UI Touchpoints', sub: 'Điểm chạm UI (Auto)',
    flags: [],
  },
  {
    id: 'open_questions', group: 2, num: 'SEC-07',
    title: 'Open Questions', sub: 'Câu hỏi tồn đọng',
    flags: [],
  },
  {
    id: 'assumptions', group: 2, num: 'SEC-08',
    title: 'Assumptions', sub: 'Giả định thiết kế',
    flags: [],
  },
];

// ── State ────────────────────────────────────────────────────

let activeSectionIndex = 0;
let sessionId = '';
let featureTitle = '';
let chatHistories = {};    // { sectionId: [{ sender, text }] }
let sectionStates = {};    // { sectionId: { status, flagValues, data, is_completable } }
let isSending = false;
let pendingEdits = [];     // [{ id, type: 'REMOVE'|'ADD', field: string, value: string, timestamp: number }]
let dbStateBackup = {};    // Backup data for canceling pending edits
let receivedStateUpdate = false;
let featureStatus = 'DRAFT';
let packageExported = false;
let designerEnabled = false;
let projectId = '';
let bpmnExpanded = false;
let openQuestions = [];
let assumptions = [];
let wikiDocuments = [];
let wikiCompanyDocuments = null;
let wikiProjectDocuments = null;
let wikiValidationSummary = null;
let wikiDocsExpanded = false;
let wikiDocsDismissed = false;
/** Catalog UI only — hide until Validate is unlocked (not during FD/BR/WF/US drafting). */
let canProceedToValidation = false;
let lastValidation = null;
let canGenerateBpmn = false;
let activeUserStoryId = null;
/** Per-section workspace pane: form | spec | diagram | xml */
const workspaceViewBySection = {};

/** Normalize flag map values to status strings (PASS / WARNING / …). */
function flagStatusOf(value) {
  if (value == null) return 'PENDING';
  if (typeof value === 'string') return value.toUpperCase();
  if (typeof value === 'object' && value.status) return String(value.status).toUpperCase();
  return 'PENDING';
}

function normalizeFlagMap(rawFlags) {
  if (!rawFlags || typeof rawFlags !== 'object') return {};
  const out = {};
  for (const [key, val] of Object.entries(rawFlags)) {
    // Accept both FD-F1 and legacy FD_F1
    const id = key.replace(/_/g, '-');
    out[id] = flagStatusOf(val);
  }
  return out;
}

const FLAG_TONE_CLASS = { pass: 'done', warning: 'warning', fail: 'fail' };
const FLAG_TONE_ICON = { pass: '✓', warning: '!', fail: '✕' };

/**
 * Visual tone from evaluation status, not flag role.
 * PASS → green; optional-role open/pending → yellow; required incomplete or FAIL → red.
 */
function flagVisualTone(flag, rawStatus) {
  const status = flagStatusOf(rawStatus);
  if (status === 'PASS') return 'pass';
  if (status === 'FAIL') return 'fail';
  if (flag.severity === 'blocker') return 'fail';
  return 'warning';
}

/** Count flags by visual status so header/sidebar match the grid colors. */
function flagProgress(sec, flagValues) {
  let pass = 0;
  let warning = 0;
  let fail = 0;
  sec.flags.forEach((f) => {
    const tone = flagVisualTone(f, flagValues[f.id]);
    if (tone === 'pass') pass += 1;
    else if (tone === 'warning') warning += 1;
    else fail += 1;
  });
  return { pass, warning, fail };
}

function formatFlagProgressParts(sec, flagValues) {
  if (!sec.flags.length) return null;
  const p = flagProgress(sec, flagValues);
  return {
    pass: `${p.pass} đạt`,
    warnings: `${p.warning} cảnh báo`,
    fails: p.fail ? `${p.fail} chưa đạt` : '',
  };
}

function formatFlagProgressCompact(sec, flagValues) {
  const parts = formatFlagProgressParts(sec, flagValues);
  if (!parts) return '';
  const bits = [parts.pass, parts.warnings];
  if (parts.fails) bits.push(parts.fails);
  return bits.join(' · ');
}

function unlockNextTier1(completedSectionId) {
  const curIdx = TIER1_IDS.indexOf(completedSectionId);
  if (curIdx < 0 || curIdx + 1 >= TIER1_IDS.length) return;
  const nextId = TIER1_IDS[curIdx + 1];
  const next = sectionStates[nextId];
  if (next && next.status === 'locked') {
    next.status = 'active';
  }
}

function applyCompletable(secId, completable) {
  const state = sectionStates[secId];
  if (!state) return;
  state.is_completable = Boolean(completable);
  if (completable) {
    state.status = 'completed';
    unlockNextTier1(secId);
    return;
  }
  if (state.status === 'completed') {
    state.status = 'in_progress';
  }
}

function applyStateUpdate(stateData, fallbackSectionId) {
  if (!stateData) return;
  receivedStateUpdate = true;

  const targetSecId = stateData.select_section || fallbackSectionId;
  const targetState = sectionStates[targetSecId] || sectionStates[fallbackSectionId];
  if (!targetState) return;

  if (stateData.flags && typeof stateData.flags === 'object') {
    for (const sid of TIER1_IDS) {
      const key = flagKeyForSection(sid);
      if (key && stateData.flags[key] && sectionStates[sid]) {
        sectionStates[sid].flagValues = normalizeFlagMap(stateData.flags[key]);
      }
    }
  }

  const nested = stateData.flags && stateData.flags[flagKeyForSection(targetSecId)];
  const secFlags =
    stateData.flags_for_section
    || nested
    || stateData[`${targetSecId}_flags`]
    || stateData.feature_definition_flags;
  const secData =
    stateData.data
    || stateData[`${targetSecId}_data`]
    || stateData.feature_definition_data
    || artifactDataForSection(stateData.artifacts, targetSecId);

  if (secFlags) targetState.flagValues = normalizeFlagMap(secFlags);
  if (secData) targetState.data = unwrapSectionData(secData, targetSecId);

  const statusMap = stateData.sections_status || {};
  const focusId = stateData.select_section || targetSecId;
  if (statusMap[targetSecId] === 'completed') {
    applyCompletable(targetSecId, true);
  } else if (statusMap[targetSecId]) {
    applyCompletable(targetSecId, false);
  } else if (focusId === targetSecId) {
    applyCompletable(targetSecId, Boolean(stateData.section_completable));
  }

  if (stateData.sections_status) {
    for (const sid of TIER1_IDS) {
      const st = stateData.sections_status[sid];
      if (!sectionStates[sid] || st == null) continue;
      if (st === 'completed') {
        applyCompletable(sid, true);
      } else {
        applyCompletable(sid, false);
        if (st === 'in_progress' && sectionStates[sid].status === 'locked') {
          sectionStates[sid].status = 'in_progress';
        }
      }
    }
  }

  if (stateData.feature_status) {
    featureStatus = stateData.feature_status;
  }
  if (stateData.package_exported != null) {
    packageExported = Boolean(stateData.package_exported);
  }
  if (stateData.designer_enabled != null) {
    designerEnabled = Boolean(stateData.designer_enabled);
  }
  if (stateData.chat_frozen) {
    packageExported = true;
  }
  if (Array.isArray(stateData.open_questions)) {
    openQuestions = stateData.open_questions;
  }
  if (Array.isArray(stateData.assumptions)) {
    assumptions = stateData.assumptions;
  }
  if (stateData.last_validation && Object.keys(stateData.last_validation).length) {
    lastValidation = stateData.last_validation;
  }
  if (stateData.active_user_story_id !== undefined) {
    activeUserStoryId = stateData.active_user_story_id || null;
  }
  if (stateData.can_proceed_to_validation != null) {
    const newlyUnlocked =
      Boolean(stateData.can_proceed_to_validation) && !canProceedToValidation;
    canProceedToValidation = Boolean(stateData.can_proceed_to_validation);
    if (newlyUnlocked) {
      void loadWikiDocuments().then(() => renderWikiDocuments());
    }
  }
  unlockGroup2IfReady();
  syncControlButtons(stateData);

  renderChatHeader();
  renderChecklist();
  renderWikiDocuments();
  renderWorkspace();
  renderSectionList();
  updateGlobalProgress();
}

const VALIDATE_STATUSES = ['PENDING_VALIDATION', 'VALIDATED', 'VALIDATION_FAILED', 'EXPORTED'];
const CHAT_FROZEN_REASON = 'Chat đã khoá sau khi Export';
const INFLIGHT_REASON = 'Đang xử lý — chờ lượt hiện tại kết thúc';
const CHAT_FROZEN_HINT = 'Chat đã khoá sau khi Export. Vẫn có thể Validate và Export lại theo wiki đã duyệt mới nhất.';

function isChatFrozen() {
  return packageExported || featureStatus === 'EXPORTED';
}

/** Mutate lock for regenerate — API uses EXPORTED status only (not package_exported). */
function isReadonlyFeature() {
  return featureStatus === 'EXPORTED';
}

function lastValidationPassed() {
  const outcome = lastValidation && lastValidation.status;
  return !outcome || outcome === 'passed' || outcome === 'passed_with_warnings';
}

function factoryPageHref(page) {
  const q = new URLSearchParams();
  if (sessionId) q.set('session', sessionId);
  if (featureTitle) q.set('title', featureTitle);
  if (projectId) q.set('project_id', projectId);
  return `${page}?${q.toString()}`;
}

function syncFactoryDockLinks() {
  const wiki = document.getElementById('linkDockWiki');
  const va = document.getElementById('linkDockVa');
  if (wiki) wiki.href = factoryPageHref('wiki.html');
  if (va) va.href = factoryPageHref('va.html');
}

function unlockGroup2IfReady() {
  const allDone = TIER1_IDS.every((id) => sectionStates[id] && sectionStates[id].status === 'completed');
  if (!allDone) return;
  canGenerateBpmn = true;
  for (const id of ['bpmn_reference', 'ui_touchpoints']) {
    if (sectionStates[id] && sectionStates[id].status === 'locked') {
      sectionStates[id].status = 'active';
    }
  }
}

function hasBpmnXml() {
  return Boolean(sectionStates.bpmn_reference?.data?.bpmn_xml_content);
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
  const sendBtn = document.getElementById('btnSend');
  if (!sendBtn) return;
  sendBtn.classList.toggle('is-sending', busy);
  sendBtn.setAttribute('aria-busy', busy ? 'true' : 'false');
  sendBtn.setAttribute('aria-label', busy ? 'Đang xử lý...' : 'Gửi cho Agent');
}

function syncControlButtons(stateData = {}) {
  if (stateData.package_exported != null) {
    packageExported = Boolean(stateData.package_exported);
  }
  if (stateData.chat_frozen) {
    packageExported = true;
  }
  const chatFrozen = isChatFrozen();
  if (stateData.can_generate_bpmn != null) {
    canGenerateBpmn = Boolean(stateData.can_generate_bpmn) || hasBpmnXml();
  }
  const hasBpmn = hasBpmnXml();
  const canValidateBtn = !isSending && VALIDATE_STATUSES.includes(featureStatus);
  const canExportPkg = !isSending && (
    featureStatus === 'VALIDATED'
    || (featureStatus === 'EXPORTED' && lastValidationPassed())
  );
  const canBpmn = hasBpmn || canGenerateBpmn;
  const canSend = !chatFrozen && !isSending;

  const lockReason = chatFrozen ? CHAT_FROZEN_REASON : (isSending ? INFLIGHT_REASON : '');
  setControlEnabled(
    document.getElementById('btnValidate'),
    canValidateBtn,
    canValidateBtn ? '' : (isSending ? INFLIGHT_REASON : 'Validate when Group 1 is complete and critical OQs are clear'),
  );
  setControlEnabled(
    document.getElementById('btnExport'),
    canExportPkg,
    canExportPkg ? '' : (featureStatus !== 'VALIDATED' && featureStatus !== 'EXPORTED' ? 'Export requires VALIDATED' : INFLIGHT_REASON),
  );
  setControlEnabled(
    document.getElementById('btnExportDesigner'),
    canExportPkg && designerEnabled,
    canExportPkg ? (designerEnabled ? '' : 'Designer handoff is disabled in BA configuration') : 'Designer handoff requires VALIDATED',
  );
  setControlEnabled(
    document.getElementById('btnExportBpmn'),
    canBpmn,
    canBpmn ? '' : 'BPMN unlocks after FD → BR → WF → UC',
  );
  const canRegen = canBpmn && !isReadonlyFeature() && !isSending;
  setControlEnabled(
    document.getElementById('btnRegenBpmn'),
    canRegen,
    canRegen
      ? ''
      : (isReadonlyFeature()
        ? 'BPMN regenerate locked after EXPORTED'
        : (canBpmn ? INFLIGHT_REASON : 'BPMN unlocks after FD → BR → WF → UC')),
  );
  setControlEnabled(document.getElementById('btnSend'), canSend, lockReason);
  const inputEl = document.getElementById('chatInput');
  if (inputEl) {
    inputEl.disabled = chatFrozen;
    inputEl.title = chatFrozen ? CHAT_FROZEN_REASON : '';
  }

  const hint = document.getElementById('composerLockHint');
  if (hint) {
    if (chatFrozen) {
      hint.hidden = false;
      hint.textContent = CHAT_FROZEN_HINT;
    } else if (isSending) {
      hint.hidden = false;
      hint.textContent = INFLIGHT_REASON;
    } else {
      hint.hidden = true;
      hint.textContent = '';
    }
  }

  syncFactoryDockLinks();

  const stampEl = document.getElementById('featureStatusBadge');
  if (stampEl) {
    stampEl.textContent = featureStatus;
    stampEl.dataset.status = featureStatus;
  }
}

function triggerBlobDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function flagKeyForSection(sectionId) {
  return ({
    feature_definition: 'fd',
    business_rules: 'br',
    workflow: 'wf',
    use_cases: 'uc',
  })[sectionId] || '';
}

function artifactDataForSection(artifacts, sectionId) {
  if (!artifacts) return null;
  if (sectionId === 'feature_definition') return artifacts.feature_definition || {};
  if (sectionId === 'business_rules') return { business_rules: artifacts.business_rules || [] };
  if (sectionId === 'workflow') return artifacts.workflow || {};
  if (sectionId === 'use_cases') return { use_cases: artifacts.use_cases || [] };
  if (sectionId === 'ui_touchpoints') {
    const items = artifacts.ui_touchpoints;
    if (Array.isArray(items)) return { ui_touchpoints: items };
    return items || null;
  }
  return artifacts[sectionId] || null;
}

function unwrapSectionData(data, sectionId) {
  if (!data || typeof data !== 'object') return {};
  if (sectionId === 'feature_definition') return data;
  if (sectionId === 'business_rules') {
    return Array.isArray(data.business_rules) ? data : { business_rules: data.business_rules || [] };
  }
  if (sectionId === 'use_cases') {
    return Array.isArray(data.use_cases) ? data : { use_cases: data.use_cases || [] };
  }
  if (sectionId === 'ui_touchpoints') {
    return Array.isArray(data.ui_touchpoints) ? data : { ui_touchpoints: data.ui_touchpoints || data.items || [] };
  }
  return data;
}

// ── DOM References ───────────────────────────────────────────

const chatStream = document.getElementById('chatStream');
const chatInput = document.getElementById('chatInput');
const btnSend = document.getElementById('btnSend');
const checklistGrid = document.getElementById('checklistGrid');
const pendingEditsBanner = document.getElementById('pendingEditsBanner');
const referenceAssetInput = document.getElementById('referenceAssetInput');
const btnAttachReference = document.getElementById('btnAttachReference');
function setAttachLabel(text) {
  const label = btnAttachReference?.querySelector('.attach-label');
  if (label) label.textContent = text;
}
let referenceAssets = [];

function readReferenceAsset(file) {
  return new Promise((resolve, reject) => {
    if (!file.type.startsWith('image/')) {
      reject(new Error(`${file.name}: chỉ hỗ trợ file hình ảnh`));
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      reject(new Error(`${file.name}: kích thước tối đa là 5MB`));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => resolve({
      id: `reference-${crypto.randomUUID()}`,
      type: 'image',
      filename: file.name,
      uri: reader.result,
      usage: 'reference',
      instruction: 'Dùng làm hình ảnh tham khảo; được phép điều chỉnh theo layout UI.',
    });
    reader.onerror = () => reject(new Error(`Không đọc được ${file.name}`));
    reader.readAsDataURL(file);
  });
}

async function handleReferenceAssetChange() {
  const files = Array.from(referenceAssetInput?.files || []);
  try {
    const added = await Promise.all(files.slice(0, 3).map(readReferenceAsset));
    referenceAssets.push(...added);
    setAttachLabel(`Ảnh tham chiếu (${referenceAssets.length})`);
  } catch (err) {
    window.alert(err.message);
  } finally {
    if (referenceAssetInput) referenceAssetInput.value = '';
  }
}

// ── Pending Edits Banner Handler ──────────────────────────────

function renderPendingEditsBanner() {
  if (!pendingEditsBanner) return;

  if (pendingEdits.length === 0) {
    pendingEditsBanner.style.display = 'none';
    pendingEditsBanner.innerHTML = '';
    return;
  }

  const itemsHtml = pendingEdits.map(edit => {
    const verb = edit.type === 'REMOVE' ? 'Xóa' : 'Thêm';
    const prep = edit.type === 'REMOVE' ? 'khỏi' : 'vào';
    return `<div>• ${verb} "${escapeHtml(edit.value)}" ${prep} ${edit.field}</div>`;
  }).join('');

  pendingEditsBanner.style.display = 'flex';
  pendingEditsBanner.innerHTML = `
    <div>
      <div class="pending-edits-title">
        <span>⚡ Thay đổi thủ công chờ gửi (${pendingEdits.length}):</span>
      </div>
      <div class="pending-edits-list">
        ${itemsHtml}
      </div>
    </div>
    <button class="btn-clear-edits" id="btnClearEdits">✕ Hủy tất cả</button>
  `;

  const btnClear = document.getElementById('btnClearEdits');
  if (btnClear) {
    btnClear.onclick = handleClearPendingEdits;
  }
}

function handleClearPendingEdits() {
  pendingEdits = [];
  // Restore section data from backup if available
  const sec = SECTIONS[activeSectionIndex];
  if (dbStateBackup[sec.id]) {
    sectionStates[sec.id].data = JSON.parse(JSON.stringify(dbStateBackup[sec.id]));
  }
  renderPendingEditsBanner();
  renderWorkspace();
}

function handleRemoveTag(field, index) {
  const sec = SECTIONS[activeSectionIndex];
  const stateData = sectionStates[sec.id].data || {};
  const currentList = stateData[field] || [];

  if (index < 0 || index >= currentList.length) return;

  const itemToRemove = currentList[index];
  const tagValue = typeof itemToRemove === 'string'
    ? itemToRemove
    : (itemToRemove.name || itemToRemove.item || itemToRemove.id || itemToRemove.statement || '');

  // Save backup if not already saved
  if (!dbStateBackup[sec.id]) {
    dbStateBackup[sec.id] = JSON.parse(JSON.stringify(stateData));
  }

  // Remove locally
  currentList.splice(index, 1);
  stateData[field] = currentList;

  // Track pending edit
  pendingEdits.push({
    id: 'edit_' + Date.now(),
    type: 'REMOVE',
    field: field,
    value: tagValue,
    timestamp: Date.now(),
  });

  renderPendingEditsBanner();
  renderWorkspace();
}

function bindWorkspaceRemovals(wsEl, field) {
  wsEl.querySelectorAll(`.tag-chip-remove[data-field="${field}"], .ws-item-remove[data-field="${field}"]`).forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const index = parseInt(btn.getAttribute('data-index'), 10);
      handleRemoveTag(field, index);
    });
  });
}

function emptyWorkspaceHint(text) {
  return `<div style="font-size: 11.5px; color: var(--text-dim); padding: 8px 0;">${escapeHtml(text)}</div>`;
}

function workspaceTabsFor(sec) {
  if (sec.id === 'bpmn_reference') {
    return [
      { id: 'diagram', label: 'Diagram' },
      { id: 'xml', label: 'XML' },
    ];
  }
  if (sec.id === 'ui_touchpoints') {
    return [
      { id: 'form', label: 'List' },
      { id: 'spec', label: 'Spec' },
    ];
  }
  if (sec.group === 1) {
    return [
      { id: 'form', label: 'Form Editor' },
      { id: 'spec', label: 'Spec Output' },
    ];
  }
  return [];
}

function defaultWorkspaceView(sec) {
  const tabs = workspaceTabsFor(sec);
  if (!tabs.length) return null;
  if (sec.id === 'bpmn_reference') return 'diagram';
  return tabs[0].id;
}

function getWorkspaceView(sec) {
  const tabs = workspaceTabsFor(sec);
  const stored = workspaceViewBySection[sec.id];
  if (stored && tabs.some((t) => t.id === stored)) return stored;
  return defaultWorkspaceView(sec);
}

function setWorkspaceView(viewId) {
  const sec = SECTIONS[activeSectionIndex];
  workspaceViewBySection[sec.id] = viewId;
  renderWorkspace();
  const tab = document.querySelector(`.ws-seg-tab[data-ws-view="${CSS.escape(viewId)}"]`);
  if (tab) tab.focus();
}

function specPayloadFor(sec, data) {
  if (sec.id === 'ui_touchpoints') return { ui_touchpoints: data.ui_touchpoints || [] };
  if (sec.id === 'open_questions') return openQuestions;
  if (sec.id === 'assumptions') return assumptions;
  return data;
}

function renderSpecOutput(wsEl, payload, emptyHint) {
  const has = Array.isArray(payload)
    ? payload.length > 0
    : payload && typeof payload === 'object'
      ? Object.keys(payload).length > 0
      : Boolean(payload && String(payload).trim());
  if (!has) {
    wsEl.innerHTML = emptyWorkspaceHint(emptyHint || 'Chưa có spec.');
    return;
  }
  const text = typeof payload === 'string' ? payload : JSON.stringify(payload, null, 2);
  wsEl.innerHTML = `
    <div class="field-group">
      <label class="field-label">Spec</label>
      <pre class="ws-json-fallback">${escapeHtml(text)}</pre>
    </div>
  `;
}

function renderBpmnXmlWorkspace(wsEl, data, state) {
  if (state.status === 'locked') {
    wsEl.innerHTML = emptyWorkspaceHint('BPMN mở sau khi hoàn tất tuần tự FD → BR → WF → UC.');
    return;
  }
  const xml = data.bpmn_xml_content || '';
  wsEl.innerHTML = `
    <div class="field-group">
      <label class="field-label">BPMN XML</label>
      ${xml
        ? `<pre class="ws-json-fallback">${escapeHtml(xml)}</pre>`
        : emptyWorkspaceHint('Chưa sinh BPMN. Hoàn tất UC rồi bấm Export BPMN.')}
    </div>
    <div class="ws-bpmn-actions">
      <button class="btn btn-cyan" type="button" id="btnWsExportBpmn" ${xml || canGenerateBpmn ? '' : 'disabled'}>Tải file .bpmn</button>
      <button class="btn" type="button" id="btnWsRegenBpmn" ${canGenerateBpmn && !isReadonlyFeature() ? '' : 'disabled'} title="${isReadonlyFeature() ? 'Feature is EXPORTED — BPMN regenerate is locked' : 'Rebuild diagram (ELK if available) and refresh preview'}">Regenerate diagram</button>
    </div>
  `;
  const btn = document.getElementById('btnWsExportBpmn');
  if (btn) btn.addEventListener('click', handleExportBpmn);
  const regen = document.getElementById('btnWsRegenBpmn');
  if (regen) regen.addEventListener('click', handleRegenerateBpmn);
}

function renderWorkspaceHeader(sec, view) {
  const tablist = document.getElementById('workspaceTablist');
  const tag = document.getElementById('workspaceTypeTag');
  const chrome = tablist && tablist.closest('.ws-chrome');
  if (tag) tag.textContent = sec.title || 'Workspace';
  if (!tablist) return;

  const tabs = workspaceTabsFor(sec);
  if (chrome) chrome.classList.toggle('is-plain', tabs.length === 0);
  if (!tabs.length) {
    tablist.hidden = true;
    tablist.innerHTML = '';
    return;
  }

  tablist.hidden = false;
  tablist.innerHTML = tabs.map((t) => {
    const selected = t.id === view;
    return `
      <button
        type="button"
        class="ws-seg-tab"
        role="tab"
        id="ws-tab-${t.id}"
        data-ws-view="${t.id}"
        aria-selected="${selected ? 'true' : 'false'}"
        tabindex="${selected ? '0' : '-1'}"
        aria-controls="workspaceBody"
      >${escapeHtml(t.label)}</button>
    `;
  }).join('');

  const body = document.getElementById('workspaceBody');
  const activeTab = tablist.querySelector(`[data-ws-view="${CSS.escape(view || '')}"]`);
  if (body) {
    if (activeTab) body.setAttribute('aria-labelledby', activeTab.id);
    else body.removeAttribute('aria-labelledby');
  }
}

function bindWorkspaceHeader() {
  const tablist = document.getElementById('workspaceTablist');
  if (!tablist || tablist.dataset.bound) return;
  tablist.dataset.bound = '1';

  tablist.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-ws-view]');
    if (!btn || !tablist.contains(btn)) return;
    setWorkspaceView(btn.getAttribute('data-ws-view'));
  });

  tablist.addEventListener('keydown', (e) => {
    const tabs = [...tablist.querySelectorAll('[role="tab"]')];
    if (!tabs.length) return;
    const current = document.activeElement;
    const idx = tabs.indexOf(current);
    let next = idx;
    if (e.key === 'ArrowRight') next = idx < 0 ? 0 : (idx + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') next = idx < 0 ? tabs.length - 1 : (idx - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = tabs.length - 1;
    else return;
    e.preventDefault();
    setWorkspaceView(tabs[next].getAttribute('data-ws-view'));
  });
}

function renderBpmnWorkspace(wsEl, data, state) {
  if (state.status === 'locked') {
    wsEl.innerHTML = emptyWorkspaceHint('BPMN mở sau khi hoàn tất tuần tự FD → BR → WF → UC.');
    return;
  }
  const xml = data.bpmn_xml_content || '';
  wsEl.innerHTML = `
    <div class="field-group">
      <label class="field-label">BPMN Reference</label>
      <div class="ws-meta-row">
        <span class="ws-meta-pill">${escapeHtml(data.artifact_id || 'BPMN-…')}</span>
        <span class="ws-meta-pill">v${escapeHtml(data.version || '—')}</span>
        <span class="ws-meta-pill">${escapeHtml(data.source || 'deterministic')}</span>
        <span class="ws-meta-pill">${escapeHtml(data.layout_engine || (String(xml).includes('exporterVersion') ? 'elk' : 'diy'))}</span>
      </div>
    </div>
    <div class="field-group">
      <label class="field-label">BPMN diagram</label>
      ${xml
        ? `<div class="bpmn-preview-wrap${bpmnExpanded ? ' is-expanded' : ''}" id="bpmnPreviewWrap">
             <div class="bpmn-preview-toolbar">
               <button type="button" class="bpmn-expand-btn" id="btnBpmnExpand" aria-label="${bpmnExpanded ? 'Collapse BPMN' : 'Expand BPMN'}">${bpmnExpanded ? 'Collapse' : 'Expand'}</button>
             </div>
             <div class="bpmn-preview" id="bpmnPreviewCanvas" role="img" aria-label="BPMN diagram preview"></div>
           </div>
           <p class="bpmn-preview-hint">Read-only preview (pan / zoom). Use Regenerate diagram to rebuild layout into session state; Export only downloads the current XML.</p>`
        : emptyWorkspaceHint('Chưa sinh BPMN. Hoàn tất UC rồi bấm Regenerate diagram hoặc Export BPMN.')}
    </div>
    <div class="ws-bpmn-actions">
      <button class="btn btn-cyan" type="button" id="btnWsExportBpmn" ${xml || canGenerateBpmn ? '' : 'disabled'}>Tải file .bpmn</button>
      <button class="btn" type="button" id="btnWsRegenBpmn" ${canGenerateBpmn && !isReadonlyFeature() ? '' : 'disabled'} title="${isReadonlyFeature() ? 'Feature is EXPORTED — BPMN regenerate is locked' : 'Rebuild diagram (ELK if available) and refresh preview'}">Regenerate diagram</button>
    </div>
  `;
  const btn = document.getElementById('btnWsExportBpmn');
  if (btn) btn.addEventListener('click', handleExportBpmn);
  const regen = document.getElementById('btnWsRegenBpmn');
  if (regen) regen.addEventListener('click', handleRegenerateBpmn);
  const expandBtn = document.getElementById('btnBpmnExpand');
  if (expandBtn) expandBtn.addEventListener('click', toggleBpmnExpand);
  document.body.classList.toggle('bpmn-expanded', Boolean(xml && bpmnExpanded));
  if (xml) {
    const canvas = document.getElementById('bpmnPreviewCanvas');
    renderBpmnDiagram(canvas, xml).then(() => {
      if (bpmnExpanded) resizeBpmnPreview();
    });
  }
}

function toggleBpmnExpand() {
  bpmnExpanded = !bpmnExpanded;
  const wrap = document.getElementById('bpmnPreviewWrap');
  const btn = document.getElementById('btnBpmnExpand');
  if (wrap) wrap.classList.toggle('is-expanded', bpmnExpanded);
  document.body.classList.toggle('bpmn-expanded', bpmnExpanded);
  if (btn) {
    btn.textContent = bpmnExpanded ? 'Collapse' : 'Expand';
    btn.setAttribute('aria-label', bpmnExpanded ? 'Collapse BPMN' : 'Expand BPMN');
  }
  requestAnimationFrame(() => resizeBpmnPreview());
}

function collapseBpmnExpand() {
  if (!bpmnExpanded) return;
  toggleBpmnExpand();
}

function renderTouchpointsWorkspace(wsEl, data, state) {
  if (state.status === 'locked') {
    wsEl.innerHTML = emptyWorkspaceHint('UI Touchpoints mở sau khi hoàn tất FD → BR → WF → UC (sau BPMN).');
    return;
  }
  const items = Array.isArray(data.ui_touchpoints) ? data.ui_touchpoints : [];
  const readonly = featureStatus === 'EXPORTED';
  const cards = items.length === 0
    ? emptyWorkspaceHint('Chưa có touchpoint. Hoàn tất UC để Agent sinh danh sách màn hình.')
    : items.map((tp, idx) => `
        <div class="ws-item-card" data-tp-index="${idx}">
          <div class="ws-item-header">
            <span class="ws-item-id">${escapeHtml(tp.id || `UIT-${idx + 1}`)}</span>
            <span class="ws-item-meta">${escapeHtml(tp.interaction || 'form')} · ${escapeHtml(tp.bpmn_node_id || '')}</span>
          </div>
          <div class="field-group" style="margin-top:8px;">
            <label class="field-label">Name / Screen</label>
            <input class="field-input tp-field" data-field="name" data-index="${idx}" value="${escapeHtml(tp.name || tp.screen || '')}" ${readonly ? 'readonly' : ''} />
          </div>
          <div class="field-group">
            <label class="field-label">Actor</label>
            <input class="field-input tp-field" data-field="actor" data-index="${idx}" value="${escapeHtml(tp.actor || '')}" ${readonly ? 'readonly' : ''} />
          </div>
          <div class="field-group">
            <label class="field-label">Trigger</label>
            <input class="field-input tp-field" data-field="trigger" data-index="${idx}" value="${escapeHtml(tp.trigger || '')}" ${readonly ? 'readonly' : ''} />
          </div>
          <div class="field-group">
            <label class="field-label">Goal</label>
            <input class="field-input tp-field" data-field="goal" data-index="${idx}" value="${escapeHtml(tp.goal || '')}" ${readonly ? 'readonly' : ''} />
          </div>
          <div class="field-group">
            <label class="field-label">Related UC ids</label>
            <input class="field-input tp-field" data-field="related_uc_ids" data-index="${idx}" value="${escapeHtml((tp.related_uc_ids || []).join(', '))}" ${readonly ? 'readonly' : ''} />
          </div>
          <div class="field-group">
            <label class="field-label">Notes</label>
            <textarea class="field-textarea tp-field" data-field="notes" data-index="${idx}" ${readonly ? 'readonly' : ''}>${escapeHtml(tp.notes || '')}</textarea>
          </div>
        </div>
      `).join('');
  wsEl.innerHTML = `
    <div class="field-group">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <label class="field-label">UI Touchpoints (Designer handoff)</label>
        <span class="mono" style="font-size:10px;color:var(--accent-cyan);">${items.length} screens</span>
      </div>
      ${cards}
    </div>
    ${readonly ? '' : '<button class="btn btn-cyan" type="button" id="btnSaveTouchpoints">Lưu touchpoints</button>'}
  `;
  const btn = document.getElementById('btnSaveTouchpoints');
  if (btn) {
    btn.addEventListener('click', () => handleSaveTouchpoints(wsEl));
  }
}

async function handleSaveTouchpoints(wsEl) {
  const items = Array.isArray(sectionStates.ui_touchpoints?.data?.ui_touchpoints)
    ? sectionStates.ui_touchpoints.data.ui_touchpoints.map((tp) => ({ ...tp }))
    : [];
  wsEl.querySelectorAll('.tp-field').forEach((el) => {
    const idx = Number(el.getAttribute('data-index'));
    const field = el.getAttribute('data-field');
    if (!items[idx]) return;
    if (field === 'related_uc_ids') {
      items[idx][field] = el.value.split(',').map((s) => s.trim()).filter(Boolean);
    } else {
      items[idx][field] = el.value;
      if (field === 'name') items[idx].screen = el.value;
    }
  });
  try {
    const saved = await saveTouchpoints(sessionId, items);
    sectionStates.ui_touchpoints.data = { ui_touchpoints: saved.ui_touchpoints || items };
    renderWorkspace();
  } catch (err) {
    const sec = SECTIONS[activeSectionIndex];
    chatHistories[sec.id] = chatHistories[sec.id] || [];
    chatHistories[sec.id].push({ sender: 'agent', text: `⚠️ Touchpoints: ${err.message}` });
    renderChatMessages();
  }
}


function truncateChatError(message, maxLen = 480) {
  const text = String(message || 'Unknown error').trim() || 'Unknown error';
  // Prefer first line of API/HTML dumps so the bubble stays readable.
  const firstLine = text.split(/\r?\n/).find((line) => line.trim()) || text;
  const compact = firstLine.replace(/\s+/g, ' ').trim();
  if (compact.length <= maxLen) return compact;
  return `${compact.slice(0, maxLen - 1)}…`;
}

async function loadSectionHistory(sectionId, initialPitch = '') {
  const local = Array.isArray(chatHistories[sectionId]) ? chatHistories[sectionId] : [];
  try {
    const historyRes = await getChatHistory(sessionId, sectionId);
    if (historyRes && historyRes.messages && historyRes.messages.length > 0) {
      const serverMessages = historyRes.messages.map(m => ({
        sender: m.sender,
        text: m.text,
      }));
      // Never shrink an in-memory transcript (e.g. failed turn not yet paired in ADK).
      if (local.length > serverMessages.length) {
        chatHistories[sectionId] = local;
      } else {
        chatHistories[sectionId] = serverMessages;
      }
    } else if (local.length > 0) {
      // Keep rendered history when the API returns empty after an error/reload race.
      chatHistories[sectionId] = local;
    } else {
      chatHistories[sectionId] = [];
      if (sectionId === 'feature_definition') {
        if (initialPitch && initialPitch.trim()) {
          // If initial pitch/description exists, auto-trigger it as first user message!
          chatInput.value = initialPitch.trim();
          setTimeout(() => {
            handleSend();
          }, 150);
        } else {
          // Fallback greeting if pitch is empty
          chatHistories['feature_definition'].push({
            sender: 'agent',
            text: `Xin chào! Tôi là BA Agent.\n\nBạn đang bắt đầu phân tích feature: "${featureTitle}"\n\nỞ section đầu tiên — Feature Definition — tôi cần bạn cung cấp:\n\n1. Goal: Tại sao feature này cần tồn tại? (business value)\n2. Actors: Ai tham gia vào luồng này? (ít nhất 2)\n3. Scope In: Feature này bao gồm những gì?\n4. Scope Out: Feature này KHÔNG bao gồm những gì?\n\nHãy bắt đầu mô tả cho tôi nhé!`,
          });
        }
      } else if (sectionId === 'business_rules') {
        chatHistories[sectionId].push({
          sender: 'agent',
          text: `Chuyển sang **Business Rules**.\n\nHãy nêu các quy tắc nghiệp vụ (điều kiện → kết quả). Cần **ít nhất 2 rules**, mỗi rule nên có nguồn (PO / Policy / System…).`,
        });
      } else if (sectionId === 'workflow') {
        chatHistories[sectionId].push({
          sender: 'agent',
          text: `Chuyển sang **Workflow**.\n\nMô tả Main Flow (≥3 bước: Step | Actor | Action | BR | Gateway — XOR/AND/trống), Exception Flows và End States. Actors khớp Feature Definition.`,
        });
      } else if (sectionId === 'use_cases') {
        chatHistories[sectionId].push({
          sender: 'agent',
          text: `Chuyển sang **User Stories**.\n\nLàm **một** user story tại một thời điểm (dạng *Là …, tôi muốn … để …* + Acceptance Criteria Given / When / Then). Khi story đang active đủ và bạn xác nhận xong, mới mở story tiếp theo.`,
        });
      }
    }
  } catch (err) {
    console.warn('Failed to load chat history:', err);
    if (local.length > 0) {
      chatHistories[sectionId] = local;
    }
  } finally {
    renderChatMessages();
  }
}

// ── Initialization ───────────────────────────────────────────

function setupChecklistToggle() {
  const card = document.getElementById('checklistCard');
  const head = card?.querySelector('.checklist-header');
  if (!card || !head) return;
  let collapsed = false;
  try { collapsed = localStorage.getItem('ba.checklist.collapsed') === '1'; } catch { /* private mode */ }
  card.classList.toggle('is-collapsed', collapsed);
  head.setAttribute('aria-expanded', String(!collapsed));
  head.addEventListener('click', () => {
    const next = !card.classList.contains('is-collapsed');
    card.classList.toggle('is-collapsed', next);
    head.setAttribute('aria-expanded', String(!next));
    try { localStorage.setItem('ba.checklist.collapsed', next ? '1' : '0'); } catch { /* ignore */ }
  });
}

async function init() {
  setupChecklistToggle();
  // Parse URL params
  const params = new URLSearchParams(window.location.search);
  sessionId = params.get('session') || '';
  featureTitle = params.get('title') || 'Feature';
  projectId = params.get('project_id') || '';

  if (!sessionId) {
    alert('Thiếu session ID. Vui lòng tạo dự án mới từ Document Manager.');
    window.location.href = 'index.html';
    return;
  }

  // Set header info (the title comes from the feature itself when the URL has none)
  document.getElementById('headerFeatureTitle').textContent = featureTitle;
  if (!params.get('title')) {
    getFeature(sessionId).then((f) => {
      const title = f?.title || f?.feature_title;
      if (title) {
        featureTitle = title;
        document.getElementById('headerFeatureTitle').textContent = title;
      }
    }).catch(() => {});
  }
  document.getElementById('sessionTag').textContent = projectId
    ? `Phiên ${sessionId.slice(0, 8)} · ${projectId}`
    : `Phiên ${sessionId.slice(0, 8)}`;

  // Initialize chat histories
  SECTIONS.forEach(sec => {
    chatHistories[sec.id] = [];
    const viewOnly = sec.id === 'open_questions' || sec.id === 'assumptions';
    sectionStates[sec.id] = {
      status: sec.group === 1
        ? (sec.id === 'feature_definition' ? 'active' : 'locked')
        : (viewOnly ? 'active' : 'locked'),
      flagValues: {},
      data: {},
      is_completable: false,
    };
  });

  let featureDescription = '';
  // Try to load existing data from DB
  try {
    const feature = await getFeature(sessionId);
    if (feature) {
      featureDescription = feature.description || '';
      if (feature.feature_status) featureStatus = feature.feature_status;
      if (feature.package_exported != null) packageExported = Boolean(feature.package_exported);
      if (feature.designer_enabled != null) designerEnabled = Boolean(feature.designer_enabled);
      if (feature.chat_frozen) packageExported = true;
      if (feature.project_id) projectId = feature.project_id;
      if (Array.isArray(feature.open_questions)) openQuestions = feature.open_questions;
      if (Array.isArray(feature.assumptions)) assumptions = feature.assumptions;
      if (feature.last_validation) lastValidation = feature.last_validation;
      if (feature.can_generate_bpmn) canGenerateBpmn = true;
      if (feature.can_proceed_to_validation != null) {
        canProceedToValidation = Boolean(feature.can_proceed_to_validation);
      }
      if (feature.active_user_story_id !== undefined) {
        activeUserStoryId = feature.active_user_story_id || null;
      }
      if (feature.sections) {
        for (const [secId, secData] of Object.entries(feature.sections)) {
          if (sectionStates[secId]) {
            sectionStates[secId].data = unwrapSectionData(secData.data || {}, secId);
            sectionStates[secId].flagValues = normalizeFlagMap(secData.flags || {});
            applyCompletable(secId, Boolean(secData.is_completable));
          }
        }
        unlockGroup2IfReady();
      }
      syncControlButtons(feature);
    }
  } catch (err) {
    console.warn('Could not load existing feature data:', err);
  }

  bindEvents();
  initColumnResize(document.querySelector('.app-container'), 'ba-chat-column-widths');
  const vaLink = document.getElementById('linkOpenVa');
  if (vaLink && sessionId) {
    vaLink.href = factoryPageHref('va.html');
  }
  syncFactoryDockLinks();
  await loadSectionHistory('feature_definition', featureDescription);
  if (canProceedToValidation) {
    await loadWikiDocuments();
  }
  renderAll();
}

async function loadWikiDocuments() {
  if (!sessionId || !canProceedToValidation) return;
  try {
    const payload = await getFeatureDocuments(sessionId);
    wikiDocuments = payload.documents || [];
    wikiCompanyDocuments = payload.company_documents || null;
    wikiProjectDocuments = payload.project_documents || null;
    wikiValidationSummary = payload.wiki_validation || null;
  } catch (err) {
    console.warn('Could not load wiki documents:', err);
  }
}

function bindEvents() {
  btnSend.addEventListener('click', handleSend);
  if (btnAttachReference && referenceAssetInput) {
    btnAttachReference.addEventListener('click', () => referenceAssetInput.click());
    referenceAssetInput.addEventListener('change', handleReferenceAssetChange);
  }

  const btnValidate = document.getElementById('btnValidate');
  if (btnValidate) {
    btnValidate.addEventListener('click', handleValidate);
  }
  const btnExport = document.getElementById('btnExport');
  if (btnExport) {
    btnExport.addEventListener('click', handleExport);
  }
  const btnExportDesigner = document.getElementById('btnExportDesigner');
  if (btnExportDesigner) {
    btnExportDesigner.addEventListener('click', handleExportAndOpenDesigner);
  }
  const btnExportBpmn = document.getElementById('btnExportBpmn');
  if (btnExportBpmn) {
    btnExportBpmn.addEventListener('click', handleExportBpmn);
  }
  const btnRegenBpmn = document.getElementById('btnRegenBpmn');
  if (btnRegenBpmn) {
    btnRegenBpmn.addEventListener('click', handleRegenerateBpmn);
  }

  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  });

  bindWorkspaceHeader();
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') collapseBpmnExpand();
  });
}

// ── Rendering ────────────────────────────────────────────────

function renderAll() {
  renderSectionList();
  renderChatHeader();
  renderChecklist();
  renderWikiDocuments();
  renderChatMessages();
  renderWorkspace();
  updateGlobalProgress();
}

function renderWikiDocuments() {
  const card = document.getElementById('wikiDocsCard');
  const showButton = document.getElementById('btnWikiToggle');
  const closeButton = document.getElementById('btnWikiClose');
  if (closeButton) {
    closeButton.onclick = () => {
      wikiDocsDismissed = true;
      renderWikiDocuments();
    };
  }
  if (showButton) {
    showButton.onclick = () => {
      wikiDocsDismissed = false;
      renderWikiDocuments();
    };
  }
  // Evidence catalog is for Validate — do not show during Tier-1 drafting.
  if (card) {
    card.hidden = !canProceedToValidation || wikiDocsDismissed;
  }
  if (showButton) showButton.hidden = !canProceedToValidation || !wikiDocsDismissed;
  if (!canProceedToValidation) return;
  renderApprovedWikiDocs(wikiDocuments, {
    escapeHtml,
    expanded: wikiDocsExpanded,
    projectId,
    companyDocuments: wikiCompanyDocuments || undefined,
    projectDocuments: wikiProjectDocuments || undefined,
    wikiValidation: wikiValidationSummary || undefined,
    onToggle: (next) => {
      wikiDocsExpanded = next;
      renderWikiDocuments();
    },
  });
}

function renderSectionList() {
  const g1El = document.getElementById('group1List');
  const g2El = document.getElementById('group2List');
  g1El.innerHTML = '';
  g2El.innerHTML = '';

  SECTIONS.forEach((sec, idx) => {
    const state = sectionStates[sec.id];
    const isActive = idx === activeSectionIndex;
    const isLocked = state.status === 'locked';

    const flagValues = state.flagValues || {};
    const progress = formatFlagProgressParts(sec, flagValues);

    const item = document.createElement('div');
    item.className = `section-item ${isActive ? 'active' : ''} ${isLocked ? 'locked' : ''}`;
    item.dataset.sectionId = sec.id;

    if (!isLocked) {
      item.addEventListener('click', () => selectSection(idx));
    }

    const stampHtml = getStatusStamp(state.status);
    const failStat = progress && progress.fails
      ? `<span class="stat-fail">${progress.fails}</span>`
      : '';
    const statsAria = progress
      ? [progress.pass, progress.warnings, progress.fails].filter(Boolean).join(', ')
      : '';
    const statsHtml = progress
      ? `<span class="section-item-stats" aria-label="${statsAria}">
          <span class="stat-pass">${progress.pass}</span>
          <span class="stat-warn">${progress.warnings}</span>
          ${failStat}
        </span>`
      : '';

    item.innerHTML = `
      <div class="section-item-head">
        <span class="mono section-item-id">${sec.num}</span>
        <span class="section-item-title">${sec.title}</span>
        ${stampHtml}
      </div>
      <div class="section-item-body">
        <span class="section-item-sub">${sec.sub}</span>
        ${statsHtml}
      </div>
    `;

    if (sec.group === 1) g1El.appendChild(item);
    else g2El.appendChild(item);
  });
}

function getStatusStamp(status) {
  const map = {
    locked: '<span class="stamp stamp-pending">Khoá</span>',
    active: '<span class="stamp stamp-auto">Đang làm</span>',
    in_progress: '<span class="stamp stamp-draft">Đang xử lý</span>',
    completed: '<span class="stamp stamp-approved">Hoàn thành</span>',
  };
  return map[status] || map.active;
}

function renderChatHeader() {
  const sec = SECTIONS[activeSectionIndex];
  const state = sectionStates[sec.id];

  const numEl = document.getElementById('activeSecNum');
  if (numEl) numEl.textContent = sec.num;

  const titleEl = document.getElementById('activeSecTitle');
  if (titleEl) titleEl.textContent = `${sec.title} (${sec.sub})`;

  const stampEl = document.getElementById('activeSecStamp');
  if (stampEl) {
    stampEl.innerHTML = getStatusStamp(state.status);
  }
}

function renderChecklist() {
  const sec = SECTIONS[activeSectionIndex];
  const state = sectionStates[sec.id];
  const flagValues = state.flagValues || {};

  checklistGrid.innerHTML = '';

  sec.flags.forEach((flag) => {
    const value = flagStatusOf(flagValues[flag.id]);
    const tone = flagVisualTone(flag, value);
    const isRequired = flag.severity === 'blocker';
    const role = isRequired ? 'bắt buộc' : 'tuỳ chọn';

    const el = document.createElement('div');
    el.className = `check-item ${FLAG_TONE_CLASS[tone]}`;
    el.dataset.flagId = flag.id;
    el.dataset.tone = tone;
    el.dataset.status = value;
    el.title = `${flag.id} · ${role} · ${value}`;
    el.innerHTML = `
      <div class="check-icon">${FLAG_TONE_ICON[tone]}</div>
      <span>${flag.label}<span class="check-sev">${role}</span></span>
    `;
    checklistGrid.appendChild(el);
  });

  document.getElementById('checkProgressRatio').textContent =
    sec.flags.length > 0 ? formatFlagProgressCompact(sec, flagValues) : 'N/A';
}

function renderChatMessages() {
  const sec = SECTIONS[activeSectionIndex];
  const messages = chatHistories[sec.id] || [];

  chatStream.innerHTML = '';

  messages.forEach(msg => {
    const row = document.createElement('div');
    row.className = `message-row ${msg.sender === 'user' ? 'user' : ''} animate-fadeIn`;
    const body =
      msg.sender === 'agent'
        ? `<div class="bubble bubble-md">${formatChatMarkdown(msg.text)}</div>`
        : `<div class="bubble">${escapeHtml(msg.text)}</div>`;
    row.innerHTML = `
      <div class="avatar ${msg.sender === 'user' ? 'user-avatar' : 'agent'}">
        ${msg.sender === 'user' ? 'Bạn' : 'BA'}
      </div>
      ${body}
    `;
    chatStream.appendChild(row);
  });

  chatStream.scrollTop = chatStream.scrollHeight;
}

function renderWorkspace() {
  destroyBpmnPreview();
  const sec = SECTIONS[activeSectionIndex];
  const state = sectionStates[sec.id];
  const data = state.data || {};
  const wsEl = document.getElementById('workspaceBody');
  const view = getWorkspaceView(sec);
  renderWorkspaceHeader(sec, view);

  if (view === 'spec') {
    renderSpecOutput(wsEl, specPayloadFor(sec, data), 'Chưa có spec.');
    return;
  }
  if (view === 'xml') {
    renderBpmnXmlWorkspace(wsEl, data, state);
    return;
  }

  if (sec.id === 'feature_definition') {
    const actorsList = data.actors || [];
    const scopeInList = data.scope_in || [];
    const scopeOutList = data.scope_out || [];

    const renderChips = (list, field, chipClass) => {
      if (!list || list.length === 0) {
        return `<div style="font-size: 11.5px; color: var(--text-dim); padding: 4px 0;">Chưa có dữ liệu</div>`;
      }
      return `<div class="tag-chips-container">` +
        list.map((item, idx) => {
          const text = typeof item === 'string' ? item : (item.name || item.item || JSON.stringify(item));
          return `
            <span class="tag-chip ${chipClass}">
              <span>${escapeHtml(text)}</span>
              <button class="tag-chip-remove" data-field="${field}" data-index="${idx}" title="Xóa tag này">✕</button>
            </span>
          `;
        }).join('') +
        `</div>`;
    };

    wsEl.innerHTML = `
      <div class="field-group">
        <label class="field-label">Mục tiêu (Goal)</label>
        <textarea class="field-textarea" readonly placeholder="Mục tiêu sẽ hiển thị khi được định nghĩa...">${data.goal || ''}</textarea>
      </div>
      <div class="field-group">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <label class="field-label">Tác nhân chính (Actors)</label>
          <span class="count-pill">${actorsList.length}</span>
        </div>
        ${renderChips(actorsList, 'actors', 'chip-cyan')}
      </div>
      <div class="field-group">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <label class="field-label">Phạm vi bao gồm (Scope In)</label>
          <span class="count-pill">${scopeInList.length}</span>
        </div>
        ${renderChips(scopeInList, 'scope_in', 'chip-emerald')}
      </div>
      <div class="field-group">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <label class="field-label">Phạm vi ngoại trừ (Scope Out)</label>
          <span class="count-pill">${scopeOutList.length}</span>
        </div>
        ${renderChips(scopeOutList, 'scope_out', 'chip-amber')}
      </div>
    `;

    bindWorkspaceRemovals(wsEl, 'actors');
    bindWorkspaceRemovals(wsEl, 'scope_in');
    bindWorkspaceRemovals(wsEl, 'scope_out');

  } else if (sec.id === 'business_rules') {
    const rules = Array.isArray(data.business_rules) ? data.business_rules : [];
    const cards = rules.length === 0
      ? emptyWorkspaceHint('Chưa có business rule. Chat với Agent để thêm (≥2 rule).')
      : rules.map((rule, idx) => `
          <div class="ws-item-card">
            <div class="ws-item-header">
              <span class="ws-item-id">${escapeHtml(rule.id || `BR-?`)}</span>
              <span class="ws-item-meta">${escapeHtml(rule.source || 'no source')}</span>
              <button class="ws-item-remove" data-field="business_rules" data-index="${idx}" title="Xóa rule">✕</button>
            </div>
            <div class="ws-item-body">${escapeHtml(rule.statement || '')}</div>
          </div>
        `).join('');
    wsEl.innerHTML = `
      <div class="field-group">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <label class="field-label">Business Rules</label>
          <span style="font-size: 10px; color: var(--accent-cyan); font-family: monospace;">${rules.length} rules</span>
        </div>
        ${cards}
      </div>
    `;
    bindWorkspaceRemovals(wsEl, 'business_rules');

  } else if (sec.id === 'workflow') {
    const md = data.workflow_md_content || '';
    const hasMain = /##\s*Main Flow/i.test(md);
    const hasExc = /##\s*Exception Flows/i.test(md);
    const hasEnd = /##\s*End States/i.test(md);
    wsEl.innerHTML = `
      <div class="field-group">
        <label class="field-label">Artifact</label>
        <div class="ws-meta-row">
          <span class="ws-meta-pill">${escapeHtml(data.artifact_id || 'WF-…')}</span>
          <span class="ws-meta-pill">v${escapeHtml(data.version || '—')}</span>
        </div>
      </div>
      <div class="field-group">
        <label class="field-label">Sections detected</label>
        <div class="tag-chips-container">
          <span class="tag-chip ${hasMain ? 'chip-emerald' : 'chip-amber'}">${hasMain ? '✓' : '○'} Main Flow</span>
          <span class="tag-chip ${hasExc ? 'chip-emerald' : 'chip-amber'}">${hasExc ? '✓' : '○'} Exception Flows</span>
          <span class="tag-chip ${hasEnd ? 'chip-emerald' : 'chip-amber'}">${hasEnd ? '✓' : '○'} End States</span>
        </div>
      </div>
      <div class="field-group">
        <label class="field-label">Workflow Markdown</label>
        ${md
          ? `<textarea class="field-textarea ws-md-preview" readonly>${escapeHtml(md)}</textarea>`
          : emptyWorkspaceHint('Chưa có workflow. Mô tả Main Flow (≥3 bước) với Agent.')}
      </div>
    `;

  } else if (sec.id === 'use_cases') {
    const cases = Array.isArray(data.use_cases) ? data.use_cases : [];
    const activeId = activeUserStoryId || (cases[0] && cases[0].id) || null;
    const cards = cases.length === 0
      ? emptyWorkspaceHint('Chưa có user story. Chat với Agent để thêm một story + AC (một story mỗi lần).')
      : cases.map((uc, idx) => {
          const rules = (uc.rule_ids || []).map(r => `<span class="tag-chip chip-amber">${escapeHtml(r)}</span>`).join('');
          const isActive = activeId && uc.id === activeId;
          const acs = (uc.acceptance_criteria || []).map((ac, ai) => `
            <div class="ws-ac-row">
              <span class="ws-item-id">${escapeHtml(ac.id || `AC-${ai + 1}`)}</span>
              <div class="ws-ac-gwt">
                <div><strong>Given</strong> ${escapeHtml(ac.given || '')}</div>
                <div><strong>When</strong> ${escapeHtml(ac.when || '')}</div>
                <div><strong>Then</strong> ${escapeHtml(ac.then || '')}</div>
              </div>
            </div>
          `).join('');
          return `
            <div class="ws-item-card${isActive ? ' ws-item-active' : ''}">
              <div class="ws-item-header">
                <span class="ws-item-id">${escapeHtml(uc.id || `US-?`)}${isActive ? ' · active' : ''}</span>
                <span class="ws-item-meta">${escapeHtml(uc.actor_id || 'no actor')}</span>
                <button class="ws-item-remove" data-field="use_cases" data-index="${idx}" title="Xóa story">✕</button>
              </div>
              <div class="ws-item-body">${escapeHtml(uc.statement || '')}</div>
              ${rules ? `<div class="tag-chips-container" style="margin-top:6px;">${rules}</div>` : ''}
              ${acs ? `<div class="ws-ac-list">${acs}</div>` : emptyWorkspaceHint('Thiếu Acceptance Criteria')}
            </div>
          `;
        }).join('');
    wsEl.innerHTML = `
      <div class="field-group">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <label class="field-label">User Stories</label>
          <span style="font-size: 10px; color: var(--accent-cyan); font-family: monospace;">${cases.length} stories${activeId ? ` · active ${escapeHtml(String(activeId))}` : ''}</span>
        </div>
        ${cards}
      </div>
    `;
    bindWorkspaceRemovals(wsEl, 'use_cases');

  } else if (sec.id === 'open_questions') {
    if (!openQuestions.length) {
      wsEl.innerHTML = emptyWorkspaceHint('Chưa có open question. Agent sẽ ghi nhận khi thông tin còn thiếu.');
    } else {
      wsEl.innerHTML = openQuestions.map((oq) => `
        <div class="ws-item-card">
          <div class="ws-item-header">
            <span class="ws-item-id">${escapeHtml(oq.id || 'OQ')}</span>
            <span class="ws-item-meta">${escapeHtml(oq.severity || '')} · ${escapeHtml(oq.status || 'open')}</span>
          </div>
          <div class="ws-item-body">${escapeHtml(oq.question || '')}</div>
          ${oq.answer ? `<div class="ws-ac-row"><strong>Answer</strong> ${escapeHtml(oq.answer)}</div>` : ''}
        </div>
      `).join('');
    }
  } else if (sec.id === 'assumptions') {
    if (!assumptions.length) {
      wsEl.innerHTML = emptyWorkspaceHint('Chưa có assumption.');
    } else {
      wsEl.innerHTML = assumptions.map((asm) => `
        <div class="ws-item-card">
          <div class="ws-item-header">
            <span class="ws-item-id">${escapeHtml(asm.id || 'ASM')}</span>
          </div>
          <div class="ws-item-body">${escapeHtml(asm.statement || '')}</div>
        </div>
      `).join('');
    }
  } else if (sec.id === 'bpmn_reference') {
    renderBpmnWorkspace(wsEl, data, state);
  } else if (sec.id === 'ui_touchpoints') {
    renderTouchpointsWorkspace(wsEl, data, state);
  } else if (Object.keys(data).length > 0) {
    wsEl.innerHTML = `
      <div class="field-group">
        <label class="field-label">Section Data</label>
        <pre class="ws-json-fallback">${escapeHtml(JSON.stringify(data, null, 2))}</pre>
      </div>
    `;
  } else {
    wsEl.innerHTML = `
      <div style="padding: 20px; text-align: center; color: var(--text-dim); font-size: 12px;">
        ${state.status === 'locked' ? 'Section này chưa được mở khóa.' : 'Gửi tin nhắn cho Agent để bắt đầu...'}
      </div>
    `;
  }
}

function updateGlobalProgress() {
  const completed = TIER1_IDS.filter(id => sectionStates[id].status === 'completed').length;
  const total = TIER1_IDS.length;
  const pct = Math.round((completed / total) * 100);

  document.getElementById('globalProgressFill').style.width = `${pct}%`;
  document.getElementById('progressLabel').textContent = `${completed} / ${total} bắt buộc`;

  const g1Completed = SECTIONS.filter(s => s.group === 1 && sectionStates[s.id].status === 'completed').length;
  document.getElementById('globalProgressStamp').textContent = `Nhóm 1 · ${g1Completed}/4`;
}

// ── Section Navigation ───────────────────────────────────────

async function selectSection(idx) {
  const sec = SECTIONS[idx];
  if (sectionStates[sec.id].status === 'locked') return;

  activeSectionIndex = idx;
  if (!chatHistories[sec.id] || chatHistories[sec.id].length === 0) {
    await loadSectionHistory(sec.id);
  }
  renderAll();
}

// ── Chat Messaging ───────────────────────────────────────────

async function handleValidate() {
  if (isSending) return;
  if (!VALIDATE_STATUSES.includes(featureStatus)) return;
  chatInput.value = '[VALIDATE] Validate BA package';
  await handleSendWithAction('validate');
}

async function handleExport() {
  if (isSending) return;
  const exportOk = featureStatus === 'VALIDATED' || (featureStatus === 'EXPORTED' && lastValidationPassed());
  if (!exportOk) return;
  try {
    const envelope = await exportFeature(sessionId);
    const blob = new Blob([JSON.stringify(envelope, null, 2)], { type: 'application/json' });
    triggerBlobDownload(blob, `ba-package-${sessionId}.json`);
    featureStatus = 'EXPORTED';
    packageExported = true;
    const sec = SECTIONS[activeSectionIndex];
    chatHistories[sec.id] = chatHistories[sec.id] || [];
    chatHistories[sec.id].push({
      sender: 'agent',
      text: '📦 BA Package exported (Designer handoff envelope). Chat stays frozen; Validate and Export can still refresh against wiki.',
    });
    renderChatMessages();
    try {
      await refreshFeatureState();
    } catch (refreshErr) {
      console.warn('Could not refresh after export:', refreshErr);
      syncControlButtons();
    }
  } catch (err) {
    const sec = SECTIONS[activeSectionIndex];
    chatHistories[sec.id] = chatHistories[sec.id] || [];
    chatHistories[sec.id].push({ sender: 'agent', text: `⚠️ Export: ${err.message}` });
    renderChatMessages();
    syncControlButtons();
  }
}

async function handleExportAndOpenDesigner() {
  if (isSending) return;
  const exportOk = featureStatus === 'VALIDATED' || (featureStatus === 'EXPORTED' && lastValidationPassed());
  if (!exportOk) return;
  const btn = document.getElementById('btnExportDesigner');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Opening Designer...';
  }
  // Platform journey: when embedded, the shell switches to Designer itself (no new tabs).
  const embedded = isEmbedded;
  // Reserve both tabs during the click gesture; browsers may block a popup
  // opened after the async handoff request has started.
  const designerWindow = embedded ? null : window.open('about:blank', 'designer-agent');
  const openpencilWindow = embedded ? null : window.open('about:blank', 'openpencil-editor');
  try {
    const result = await exportAndOpenDesigner(sessionId);
    featureStatus = 'EXPORTED';
    packageExported = true;
    const sec = SECTIONS[activeSectionIndex];
    chatHistories[sec.id] = chatHistories[sec.id] || [];
    chatHistories[sec.id].push({
      sender: 'agent',
      text: `🎨 BA package đã gửi sang Designer. Session: ${result.designer_session_id || 'created'}.`,
    });
    renderChatMessages();
    const designerUrl = result.designer_url ||
      (result.designer_session_id
        ? `http://127.0.0.1:3232/?session=${encodeURIComponent(result.designer_session_id)}`
        : '');
    const openpencilUrl = result.openpencil_url || 'http://127.0.0.1:1420/';
    if (embedded) {
      window.parent.postMessage({ type: 'platform:open-designer', session: result.designer_session_id }, window.location.origin);
      return;
    }
    if (designerUrl) {
      if (designerWindow) designerWindow.location.replace(designerUrl);
      else window.open(designerUrl, 'designer-agent');
    }
    if (openpencilUrl) {
      if (openpencilWindow) openpencilWindow.location.replace(openpencilUrl);
      else window.location.assign(openpencilUrl);
    }
  } catch (err) {
    if (designerWindow && !designerWindow.closed) designerWindow.close();
    if (openpencilWindow && !openpencilWindow.closed) openpencilWindow.close();
    const sec = SECTIONS[activeSectionIndex];
    chatHistories[sec.id] = chatHistories[sec.id] || [];
    chatHistories[sec.id].push({
      sender: 'agent',
      text: `⚠️ Không mở được Designer: ${err.message}`,
    });
    renderChatMessages();
  } finally {
    if (btn) btn.textContent = 'Export & Open in Designer';
    syncControlButtons();
  }
}

async function handleExportBpmn() {
  try {
    const { blob, filename } = await downloadBpmn(sessionId, false);
    triggerBlobDownload(blob, filename);
    const sec = SECTIONS[activeSectionIndex];
    chatHistories[sec.id] = chatHistories[sec.id] || [];
    chatHistories[sec.id].push({
      sender: 'agent',
      text: `📊 BPMN downloaded (${filename}). Preview unchanged — use Regenerate diagram to rebuild layout.`,
    });
    renderChatMessages();
    try {
      await refreshFeatureState();
    } catch (refreshErr) {
      console.warn('Could not refresh after BPMN download:', refreshErr);
    }
  } catch (err) {
    const sec = SECTIONS[activeSectionIndex];
    chatHistories[sec.id] = chatHistories[sec.id] || [];
    chatHistories[sec.id].push({ sender: 'agent', text: `⚠️ BPMN: ${err.message}` });
    renderChatMessages();
  } finally {
    syncControlButtons();
  }
}

async function handleRegenerateBpmn() {
  if (isReadonlyFeature()) {
    const sec = SECTIONS[activeSectionIndex];
    chatHistories[sec.id] = chatHistories[sec.id] || [];
    chatHistories[sec.id].push({
      sender: 'agent',
      text: '⚠️ BPMN regenerate is locked while feature_status is EXPORTED.',
    });
    renderChatMessages();
    return;
  }
  try {
    const { blob, filename } = await downloadBpmn(sessionId, true);
    // Persist happens server-side; still offer the fresh file, then reload preview from state.
    triggerBlobDownload(blob, filename);
    await refreshFeatureState();
    const engine = sectionStates.bpmn_reference?.data?.layout_engine
      || (String(sectionStates.bpmn_reference?.data?.bpmn_xml_content || '').includes('exporterVersion')
        ? 'elk'
        : 'diy');
    const sec = SECTIONS[activeSectionIndex];
    chatHistories[sec.id] = chatHistories[sec.id] || [];
    chatHistories[sec.id].push({
      sender: 'agent',
      text: `🔄 BPMN regenerated (${filename}, layout=${engine}). Preview refreshed from session state.`,
    });
    renderChatMessages();
  } catch (err) {
    const sec = SECTIONS[activeSectionIndex];
    chatHistories[sec.id] = chatHistories[sec.id] || [];
    chatHistories[sec.id].push({ sender: 'agent', text: `⚠️ BPMN regenerate: ${err.message}` });
    renderChatMessages();
  } finally {
    syncControlButtons();
  }
}

function injectValidationReport(sectionId, agentMsg) {
  const report = lastValidation && (lastValidation.agent_response || '');
  if (!report) return;
  if (agentMsg && (!agentMsg.text || agentMsg.text.trim() === '')) {
    agentMsg.text = report;
    return;
  }
  const history = chatHistories[sectionId] || [];
  const last = history[history.length - 1];
  if (last && last.sender === 'agent' && last.text && last.text.includes('Validation')) return;
  if (last && last.sender === 'agent' && last.text === report) return;
  history.push({ sender: 'agent', text: report });
  chatHistories[sectionId] = history;
}

async function refreshFeatureState() {
  const feature = await getFeature(sessionId);
  if (feature?.feature_status) {
    featureStatus = feature.feature_status;
  }
  if (feature?.package_exported != null) packageExported = Boolean(feature.package_exported);
  if (feature?.chat_frozen) packageExported = true;
  if (feature?.project_id) projectId = feature.project_id;
  if (Array.isArray(feature?.open_questions)) openQuestions = feature.open_questions;
  if (Array.isArray(feature?.assumptions)) assumptions = feature.assumptions;
  if (feature?.last_validation) lastValidation = feature.last_validation;
  if (feature?.can_generate_bpmn != null) canGenerateBpmn = Boolean(feature.can_generate_bpmn);
  if (feature?.can_proceed_to_validation != null) {
    canProceedToValidation = Boolean(feature.can_proceed_to_validation);
  }
  await loadWikiDocuments();
  if (feature?.sections) {
    for (const [secId, secData] of Object.entries(feature.sections)) {
      if (!sectionStates[secId]) continue;
      sectionStates[secId].data = unwrapSectionData(secData.data || {}, secId);
      sectionStates[secId].flagValues = normalizeFlagMap(secData.flags || {});
      applyCompletable(secId, Boolean(secData.is_completable));
    }
  }
  unlockGroup2IfReady();
  syncControlButtons(feature || {});
  renderChatHeader();
  renderChecklist();
  renderWikiDocuments();
  renderWorkspace();
  renderSectionList();
  updateGlobalProgress();
}

async function handleSendWithAction(action = null) {
  const text = chatInput.value.trim();
  if (!text || isSending) return;
  if (isChatFrozen() && action !== 'validate') return;

  const sec = SECTIONS[activeSectionIndex];
  let fullPayloadText = text;
  if (pendingEdits.length > 0) {
    const preambleLines = pendingEdits.map(edit => {
      const verb = edit.type === 'REMOVE' ? 'Xóa' : 'Thêm';
      const prep = edit.type === 'REMOVE' ? 'ra khỏi' : 'vào';
      return `- ${verb} "${edit.value}" ${prep} "${edit.field}" - bạn không cần làm gì thêm`;
    });
    fullPayloadText = `Tôi đã có điều chỉnh thủ công:\n${preambleLines.join('\n')}\n\n${text}`;
    pendingEdits = [];
    renderPendingEditsBanner();
  }

  chatHistories[sec.id].push({ sender: 'user', text: fullPayloadText });
  chatInput.value = '';
  renderChatMessages();

  if (sectionStates[sec.id].status === 'active') {
    sectionStates[sec.id].status = 'in_progress';
    renderSectionList();
    renderChatHeader();
  }

  isSending = true;
  setSendBusy(true);
  syncControlButtons();
  showTypingIndicator();
  receivedStateUpdate = false;

  let currentAgentMsg = null;
  try {
    await sendChatMessage(sessionId, fullPayloadText, sec.id, { action, assets: referenceAssets }, {
      onMessage: (data) => {
        removeTypingIndicator();
        if (!currentAgentMsg) {
          currentAgentMsg = { sender: 'agent', text: data.text || '' };
          chatHistories[sec.id].push(currentAgentMsg);
        } else {
          currentAgentMsg.text += data.text || '';
        }
        renderChatMessages();
      },
      onStateUpdate: (stateData) => {
        applyStateUpdate(stateData, sec.id);
        if (action === 'validate' && stateData.last_validation) {
          lastValidation = stateData.last_validation;
        }
      },
      onDone: async () => {
        removeTypingIndicator();
        if (!receivedStateUpdate) {
          try {
            await refreshFeatureState();
          } catch (err) {
            console.warn('Fallback getFeature after chat failed:', err);
          }
        }
        if (action === 'validate') {
          try {
            if (!lastValidation || !lastValidation.agent_response) {
              await refreshFeatureState();
            }
          } catch (err) {
            console.warn('Could not refresh validation report:', err);
          }
          injectValidationReport(sec.id, currentAgentMsg);
          renderChatMessages();
        }
      },
      onError: async (err) => {
        removeTypingIndicator();
        // Snapshot before any refresh so a failed getFeature/wiki call cannot blank the thread.
        const preserved = (chatHistories[sec.id] || []).map((m) => ({ ...m }));
        chatHistories[sec.id] = preserved;
        chatHistories[sec.id].push({
          sender: 'agent',
          text: `⚠️ Lỗi: ${truncateChatError(err && err.message)}`,
        });
        renderChatMessages();
        try {
          await refreshFeatureState();
        } catch (refreshErr) {
          console.warn('Failed to refresh feature after chat error:', refreshErr);
        }
        // Re-assert transcript if anything in refresh cleared or replaced this section.
        if (!chatHistories[sec.id] || chatHistories[sec.id].length < preserved.length + 1) {
          chatHistories[sec.id] = [
            ...preserved,
            {
              sender: 'agent',
              text: `⚠️ Lỗi: ${truncateChatError(err && err.message)}`,
            },
          ];
        }
        renderChatMessages();
      },
    });
  } finally {
    referenceAssets = [];
    setAttachLabel('Ảnh tham chiếu');
    isSending = false;
    setSendBusy(false);
    syncControlButtons();
  }
}

async function handleSend() {
  await handleSendWithAction(null);
}

// ── Typing Indicator ─────────────────────────────────────────

function showTypingIndicator() {
  const existing = chatStream.querySelector('.typing-row');
  if (existing) return;

  const row = document.createElement('div');
  row.className = 'message-row typing-row animate-fadeIn';
  row.innerHTML = `
    <div class="avatar agent">BA</div>
    <div class="bubble typing-indicator">
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
    </div>
  `;
  chatStream.appendChild(row);
  chatStream.scrollTop = chatStream.scrollHeight;
}

function removeTypingIndicator() {
  const el = chatStream.querySelector('.typing-row');
  if (el) el.remove();
}

// ── Boot ─────────────────────────────────────────────────────
// The platform journey asks the embedded page to show a section (its step strip).
window.addEventListener('message', (event) => {
  if (event.origin !== window.location.origin) return;
  if (event.data?.type !== 'platform:select-section') return;
  const idx = SECTIONS.findIndex((sec) => sec.id === event.data.key);
  if (idx >= 0 && idx !== activeSectionIndex && sectionStates[SECTIONS[idx].id]?.status !== 'locked') {
    void selectSection(idx);
  }
});

init();

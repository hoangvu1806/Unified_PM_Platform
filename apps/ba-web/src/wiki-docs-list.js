/**
 * Approved wiki documents card — company (shared) + this project only.
 * Shared by BA chat (after Validate unlock) and Validate Agent.
 * BA chat hides #wikiDocsCard until can_proceed_to_validation.
 *
 * Per-item validation_status is relative to last Validate snapshot:
 * pass | fail | unchecked (not silent “all good”).
 */

export const WIKI_DOCS_PREVIEW_COUNT = 3;

const EMPTY_TEXT =
  'Chưa có trang wiki approved trong phạm vi này. Drafts stay invisible until human Approve.';

const STATUS_LABELS = {
  pass: 'pass',
  fail: 'fail',
  unchecked: 'unchecked',
};

function isCompanyDoc(doc) {
  return String(doc?.namespace || '').toLowerCase() === 'company';
}

function splitDocs(documents) {
  const docs = Array.isArray(documents) ? documents : [];
  const company = [];
  const project = [];
  for (const doc of docs) {
    if (isCompanyDoc(doc)) company.push(doc);
    else project.push(doc);
  }
  return { company, project };
}

function normalizeValidationStatus(raw) {
  const s = String(raw || '').toLowerCase();
  if (s === 'pass' || s === 'fail' || s === 'unchecked') return s;
  return 'unchecked';
}

function statusStamp(doc, escapeHtml) {
  const status = normalizeValidationStatus(doc?.validation_status);
  const label = STATUS_LABELS[status];
  const stampClass =
    status === 'pass'
      ? 'stamp-approved'
      : status === 'fail'
        ? 'stamp-error'
        : 'stamp-pending';
  const findings = Array.isArray(doc?.validation_findings) ? doc.validation_findings : [];
  const tipParts = [`Validation vs last Validate: ${label}`];
  for (const f of findings.slice(0, 3)) {
    const others = (f.conflict_page_ids || []).join(', ');
    const ref = others || f.conflict_ref || '';
    tipParts.push(
      `${f.check_id || 'V-WIKI'}${ref ? ` vs ${ref}` : ''}: ${(f.detail || f.name || '').slice(0, 120)}`,
    );
  }
  return `<span class="stamp ${stampClass} wiki-docs-va-stamp" title="${escapeHtml(tipParts.join(' | '))}">${escapeHtml(label)}</span>`;
}

function failDetailHtml(doc, escapeHtml) {
  const status = normalizeValidationStatus(doc?.validation_status);
  if (status !== 'fail') return '';
  const findings = Array.isArray(doc?.validation_findings) ? doc.validation_findings : [];
  if (!findings.length) {
    return `<div class="wiki-docs-fail">Last Validate marked this page fail — open Wiki to demote/delete, then re-Validate.</div>`;
  }
  return findings
    .map((f) => {
      const code = escapeHtml(f.check_id || 'V-WIKI');
      const detail = escapeHtml((f.detail || f.name || '').slice(0, 180));
      const others = (f.conflict_page_ids || []).map((id) => escapeHtml(id)).join(', ');
      const pair = others
        ? `<span class="wiki-docs-pair">vs ${others}</span>`
        : f.conflict_ref
          ? `<span class="wiki-docs-pair">ref ${escapeHtml(String(f.conflict_ref).slice(0, 60))}</span>`
          : '';
      return `<div class="wiki-docs-fail"><span class="mono">${code}</span> ${pair}<br>${detail}</div>`;
    })
    .join('');
}

function itemHtml(doc, escapeHtml) {
  const title = escapeHtml(doc.title || doc.page_id || 'Untitled');
  const pid = escapeHtml(doc.page_id || '');
  const snip = escapeHtml(doc.snippet || '');
  const ns = isCompanyDoc(doc) ? 'company' : 'project';
  const status = normalizeValidationStatus(doc?.validation_status);
  return `<div class="wiki-docs-item" data-namespace="${ns}" data-validation-status="${status}">
      <div class="wiki-docs-item-head">
        <div class="mono wiki-docs-id">${pid}</div>
        ${statusStamp(doc, escapeHtml)}
      </div>
      <div class="wiki-docs-title">${title}</div>
      ${snip ? `<div class="wiki-docs-snip">${snip}</div>` : ''}
      ${failDetailHtml(doc, escapeHtml)}
    </div>`;
}

function sectionHtml(label, docs, escapeHtml, { showAll, previewCount }) {
  const shown = showAll ? docs : docs.slice(0, previewCount);
  const body = docs.length
    ? shown.map((doc) => itemHtml(doc, escapeHtml)).join('')
    : `<div class="wiki-docs-empty">${EMPTY_TEXT}</div>`;
  return `<div class="wiki-docs-group">
      <div class="wiki-docs-group-label">${escapeHtml(label)}
        <span class="mono wiki-docs-group-count">${docs.length}</span>
      </div>
      ${body}
    </div>`;
}

function ensureToggle(listEl) {
  const card = listEl.closest('.wiki-docs-card') || listEl.parentElement;
  if (!card) return null;
  let toggleEl = card.querySelector('#wikiDocsToggle');
  if (!toggleEl) {
    toggleEl = document.createElement('button');
    toggleEl.type = 'button';
    toggleEl.id = 'wikiDocsToggle';
    toggleEl.className = 'wiki-docs-toggle';
    listEl.insertAdjacentElement('afterend', toggleEl);
  }
  return toggleEl;
}

function ensureSummaryEl(listEl) {
  const card = listEl.closest('.wiki-docs-card') || listEl.parentElement;
  if (!card) return null;
  let summaryEl = card.querySelector('#wikiDocsSummary');
  if (!summaryEl) {
    summaryEl = document.createElement('div');
    summaryEl.id = 'wikiDocsSummary';
    summaryEl.className = 'wiki-docs-summary';
    listEl.insertAdjacentElement('beforebegin', summaryEl);
  }
  return summaryEl;
}

function summaryLine(wikiValidation, documents) {
  const summary = wikiValidation && typeof wikiValidation === 'object' ? wikiValidation : {};
  const counts = summary.counts || {};
  const docs = Array.isArray(documents) ? documents : [];
  let pass = Number(counts.pass) || 0;
  let fail = Number(counts.fail) || 0;
  let unchecked = Number(counts.unchecked) || 0;
  if (!summary.counts && docs.length) {
    pass = fail = unchecked = 0;
    for (const d of docs) {
      const s = normalizeValidationStatus(d?.validation_status);
      if (s === 'pass') pass += 1;
      else if (s === 'fail') fail += 1;
      else unchecked += 1;
    }
  }
  const overall = String(summary.overall || '').toLowerCase();
  const hasRun = Boolean(summary.has_run);
  if (!docs.length) {
    return { text: '', tone: 'muted' };
  }
  if (!hasRun || (pass === 0 && fail === 0 && unchecked === docs.length)) {
    return {
      text: 'Not validated yet — each page is unchecked until you run Validate.',
      tone: 'pending',
    };
  }
  if (fail > 0 || overall === 'fail') {
    const uncheckedBit = unchecked
      ? ` · ${unchecked} unchecked since last Validate`
      : '';
    return {
      text: `Wiki validation failed (${fail} fail · ${pass} pass${uncheckedBit}). Expand a fail row for V-WIKI code + paired page_id — demote/delete one on Wiki, then re-Validate.`,
      tone: 'error',
    };
  }
  if (unchecked > 0) {
    return {
      text: `${pass} pass · ${unchecked} unchecked since last Validate — re-Validate to check new pages.`,
      tone: 'pending',
    };
  }
  return {
    text: `Last Validate: wiki pass (${pass}).`,
    tone: 'ok',
  };
}

/**
 * @param {object[]} documents
 * @param {{
 *   escapeHtml: Function,
 *   expanded: boolean,
 *   onToggle: (next: boolean) => void,
 *   projectId?: string,
 *   companyDocuments?: object[],
 *   projectDocuments?: object[],
 *   wikiValidation?: object,
 * }} options
 */
export function renderApprovedWikiDocs(documents, options) {
  const {
    escapeHtml,
    expanded,
    onToggle,
    projectId = '',
    companyDocuments,
    projectDocuments,
    wikiValidation,
  } = options;
  const listEl = document.getElementById('wikiDocsList');
  const countEl = document.getElementById('wikiDocsCount');
  if (!listEl || !countEl) return;

  let company;
  let project;
  if (Array.isArray(companyDocuments) || Array.isArray(projectDocuments)) {
    company = Array.isArray(companyDocuments) ? companyDocuments : [];
    project = Array.isArray(projectDocuments) ? projectDocuments : [];
  } else {
    ({ company, project } = splitDocs(documents));
  }

  const allDocs = [...company, ...project];
  const total = allDocs.length;
  countEl.textContent = String(total);

  const summaryEl = ensureSummaryEl(listEl);
  if (summaryEl) {
    const line = summaryLine(wikiValidation, allDocs);
    if (!line.text) {
      summaryEl.hidden = true;
      summaryEl.textContent = '';
      summaryEl.dataset.tone = '';
    } else {
      summaryEl.hidden = false;
      summaryEl.textContent = line.text;
      summaryEl.dataset.tone = line.tone;
    }
  }

  const projectLabel = projectId
    ? `This project only (${projectId})`
    : 'This project only';

  if (!total) {
    listEl.innerHTML = sectionHtml('Company (shared)', [], escapeHtml, {
      showAll: true,
      previewCount: WIKI_DOCS_PREVIEW_COUNT,
    }) + sectionHtml(projectLabel, [], escapeHtml, {
      showAll: true,
      previewCount: WIKI_DOCS_PREVIEW_COUNT,
    });
    const toggleEl = document.getElementById('wikiDocsToggle');
    if (toggleEl) toggleEl.hidden = true;
    return;
  }

  const canCollapse = total > WIKI_DOCS_PREVIEW_COUNT;
  const showAll = expanded || !canCollapse;
  // When collapsed, prefer previewing project pages first, then company.
  let previewLeft = WIKI_DOCS_PREVIEW_COUNT;
  let projectPreview = project;
  let companyPreview = company;
  if (!showAll) {
    projectPreview = project.slice(0, previewLeft);
    previewLeft -= projectPreview.length;
    companyPreview = company.slice(0, Math.max(0, previewLeft));
  }

  listEl.innerHTML =
    sectionHtml('Company (shared)', showAll ? company : companyPreview, escapeHtml, {
      showAll: true,
      previewCount: WIKI_DOCS_PREVIEW_COUNT,
    }) +
    sectionHtml(projectLabel, showAll ? project : projectPreview, escapeHtml, {
      showAll: true,
      previewCount: WIKI_DOCS_PREVIEW_COUNT,
    });
  listEl.dataset.expanded = showAll ? 'true' : 'false';
  if (projectId) listEl.dataset.projectId = projectId;

  const toggleEl = ensureToggle(listEl);
  if (!toggleEl) return;
  if (!canCollapse) {
    toggleEl.hidden = true;
    return;
  }
  toggleEl.hidden = false;
  toggleEl.setAttribute('aria-expanded', showAll ? 'true' : 'false');
  toggleEl.textContent = showAll ? 'Show less' : `Show all (${total})`;
  toggleEl.onclick = () => onToggle(!expanded);
}

/**
 * BA Document Manager — Main Script
 *
 * Handles feature listing, search/filter, and create modal.
 */

// Platform: login, project context and read-only mode (must load first).
import './platform.js';
import { listFeatures, createFeature, deleteFeature } from './api.js';

// ── State ────────────────────────────────────────────────────
let features = [];
let currentFilter = 'ALL';

// ── DOM References ───────────────────────────────────────────
const packageGrid = document.getElementById('packageGrid');
const searchInput = document.getElementById('searchInput');
const filterTabs = document.getElementById('filterTabs');
const createModal = document.getElementById('createModal');
const newFeatureTitle = document.getElementById('newFeatureTitle');
const newFeaturePitch = document.getElementById('newFeaturePitch');

// ── Initialization ───────────────────────────────────────────

async function init() {
  bindEvents();
  await loadFeatures();
}

function bindEvents() {
  // Create modal triggers
  document.getElementById('btnCreateFeature').addEventListener('click', openModal);
  document.getElementById('btnCreateFeature2').addEventListener('click', openModal);
  document.getElementById('btnCloseModal').addEventListener('click', closeModal);
  document.getElementById('btnCancelModal').addEventListener('click', closeModal);
  document.getElementById('btnStartChat').addEventListener('click', handleCreateFeature);

  // Search
  searchInput.addEventListener('input', renderFeatures);

  // Filter tabs
  filterTabs.addEventListener('click', (e) => {
    const btn = e.target.closest('.filter-btn');
    if (!btn) return;
    filterTabs.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentFilter = btn.dataset.filter;
    renderFeatures();
  });

  // Close modal on overlay click
  createModal.addEventListener('click', (e) => {
    if (e.target === createModal) closeModal();
  });

  // Escape key closes modal
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
  });
}

// ── Data Loading ─────────────────────────────────────────────

async function loadFeatures() {
  packageGrid.innerHTML = `
    <div style="grid-column: 1/-1; text-align: center; padding: 40px;">
      <div class="loading-spinner animate-spin" style="margin: 0 auto 12px;"></div>
      <div class="text-dim" style="font-size: 12px;">Đang tải danh sách features...</div>
    </div>
  `;

  try {
    features = await listFeatures();
    renderFeatures();
  } catch (err) {
    console.error('Failed to load features:', err);
    features = [];
    packageGrid.innerHTML = `
      <div class="empty-state" style="grid-column: 1/-1;">
        <div class="empty-state-icon">⚠</div>
        <div class="empty-state-title">Không tải được danh sách Feature</div>
        <div class="empty-state-desc">${escapeHtml(err.message || String(err))}. API :8000 must be up — this is not an empty wiki clear.</div>
      </div>
    `;
  }
}

// ── Rendering ────────────────────────────────────────────────

function renderFeatures() {
  const query = searchInput.value.toLowerCase().trim();

  let filtered = features.filter(f => {
    // Search filter
    if (query && !f.title.toLowerCase().includes(query)) return false;

    // Status filter
    if (currentFilter === 'COMPLETED') return f.sections_completed >= f.sections_total;
    if (currentFilter === 'IN_PROGRESS') return f.sections_completed < f.sections_total;
    return true;
  });

  if (filtered.length === 0) {
    packageGrid.innerHTML = renderEmptyState(query);
    return;
  }

  packageGrid.innerHTML = filtered.map(renderFeatureCard).join('');

  // Bind card click events
  packageGrid.querySelectorAll('.package-card').forEach(card => {
    card.addEventListener('click', () => {
      const sessionId = card.dataset.sessionId;
      const title = card.dataset.title;
      const projectId = card.dataset.projectId || '';
      const q = new URLSearchParams({ session: sessionId, title });
      if (projectId) q.set('project_id', projectId);
      window.location.href = `chat.html?${q.toString()}`;
    });
  });

  packageGrid.querySelectorAll('.btn-open-va').forEach((link) => {
    link.addEventListener('click', (e) => {
      e.stopPropagation();
    });
  });

  // Bind delete button events for all features (any status)
  packageGrid.querySelectorAll('.btn-delete-feature').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const sessionId = btn.dataset.deleteSession;
      const title = btn.dataset.title;
      if (confirm(`Bạn có chắc chắn muốn xóa Feature "${title}" không?`)) {
        try {
          await deleteFeature(sessionId);
          await loadFeatures();
        } catch (err) {
          alert('Không thể xóa Feature: ' + err.message);
        }
      }
    });
  });
}

function renderFeatureCard(feature) {
  const isCompleted = feature.sections_completed >= feature.sections_total;
  const stampClass = isCompleted ? 'stamp-approved' : 'stamp-draft';
  const stampText = isCompleted ? 'COMPLETED' : 'IN_PROGRESS';
  const progressColor = isCompleted ? 'var(--accent-emerald)' : 'var(--status-warning)';
  const footerText = isCompleted ? 'Mở Chat với Agent →' : 'Tiếp tục làm việc →';
  const timeAgo = feature.updated_at ? formatTimeAgo(feature.updated_at) : '';

  return `
    <div class="package-card animate-fadeIn" data-session-id="${feature.session_id}" data-title="${escapeHtml(feature.title)}" data-project-id="${escapeHtml(feature.project_id || '')}">
      <div class="card-head">
        <div>
          <span class="tag tag-cyan" style="margin-bottom: 6px;">[SESSION] ${feature.session_id.slice(0, 12)}...</span>
          ${feature.project_id ? `<span class="tag tag-violet mono" style="margin-bottom: 6px;margin-left:6px;">${escapeHtml(feature.project_id)}</span>` : ''}
          <h3 class="card-title">${escapeHtml(feature.title)}</h3>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <span class="stamp ${stampClass}">[${stampText}]</span>
          <button class="btn-delete-feature" data-delete-session="${feature.session_id}" data-title="${escapeHtml(feature.title)}" title="Xóa Feature" style="padding: 3px 8px; font-size: 11px; background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.4); color: #FCA5A5; border-radius: 4px; cursor: pointer; transition: all 0.15s ease;">
            ✕ Xóa
          </button>
        </div>
      </div>
      ${feature.description ? `<p class="card-desc">${escapeHtml(feature.description)}</p>` : ''}
      <div class="section-progress-bar">
        <span>Tiến trình bắt buộc:</span>
        <strong style="color: ${progressColor}">${feature.sections_completed} / ${feature.sections_total} Sections</strong>
      </div>
      <div class="card-foot">
        <span>${timeAgo ? `Cập nhật: ${timeAgo}` : ''}</span>
        <span style="display:flex;gap:10px;align-items:center;">
          <a class="mono btn-open-va" data-session-id="${feature.session_id}" data-title="${escapeHtml(feature.title)}" href="va.html?session=${encodeURIComponent(feature.session_id)}&title=${encodeURIComponent(feature.title)}${feature.project_id ? `&project_id=${encodeURIComponent(feature.project_id)}` : ''}" style="color:var(--accent-violet);text-decoration:none;">Open VA</a>
          <span class="mono" style="color: var(--accent-cyan)">${footerText}</span>
        </span>
      </div>
    </div>
  `;
}

function renderEmptyState(hasQuery) {
  if (hasQuery) {
    return `
      <div class="empty-state" style="grid-column: 1/-1;">
        <div class="empty-state-icon">🔍</div>
        <div class="empty-state-title">Không tìm thấy kết quả</div>
        <div class="empty-state-desc">Thử tìm kiếm với từ khóa khác.</div>
      </div>
    `;
  }

  return `
    <div class="empty-state" style="grid-column: 1/-1;">
      <div class="empty-state-icon">📋</div>
      <div class="empty-state-title">Chưa có Feature nào</div>
      <div class="empty-state-desc">Bấm "Tạo Dự Án Mới" để bắt đầu phân tích nghiệp vụ cùng BA Agent.</div>
      <button class="btn btn-cyan" style="padding: 10px 20px;" onclick="document.getElementById('btnCreateFeature').click()">
        Tạo Dự Án Mới
      </button>
    </div>
  `;
}

// ── Modal ────────────────────────────────────────────────────

function openModal() {
  createModal.classList.add('active');
  newFeatureTitle.value = '';
  newFeaturePitch.value = '';
  setTimeout(() => newFeatureTitle.focus(), 100);
}

function closeModal() {
  createModal.classList.remove('active');
}

async function handleCreateFeature() {
  const title = newFeatureTitle.value.trim();
  if (!title) {
    newFeatureTitle.style.borderColor = 'var(--status-error)';
    newFeatureTitle.focus();
    return;
  }

  const description = newFeaturePitch.value.trim();
  const btn = document.getElementById('btnStartChat');
  btn.disabled = true;
  btn.textContent = 'Đang tạo...';

  try {
    const feature = await createFeature(title, description);
    closeModal();
    const q = new URLSearchParams({
      session: feature.session_id,
      title,
    });
    if (feature.project_id) q.set('project_id', feature.project_id);
    window.location.href = `chat.html?${q.toString()}`;
  } catch (err) {
    console.error('Failed to create feature:', err);
    alert('Lỗi tạo dự án: ' + err.message);
    btn.disabled = false;
    btn.textContent = 'Start Chat với BA Agent';
  }
}

// ── Utilities ────────────────────────────────────────────────

function formatTimeAgo(dateStr) {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now - date;
  const diffMin = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMin < 1) return 'Vừa xong';
  if (diffMin < 60) return `${diffMin} phút trước`;
  if (diffHours < 24) return `${diffHours} giờ trước`;
  return `${diffDays} ngày trước`;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ── Boot ─────────────────────────────────────────────────────
init();

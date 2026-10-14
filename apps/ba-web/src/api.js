/**
 * BA Agent — API Client Module
 *
 * REST API calls + SSE streaming for chat communication.
 * All endpoints are proxied via Vite dev server (/api → localhost:8000).
 */

const API_BASE = '/api';

// ── Feature CRUD ─────────────────────────────────────────────

/**
 * Create a new BA feature.
 * @param {string} title - Feature title
 * @param {string} description - Feature description
 * @returns {Promise<Object>} Created feature data
 */
export async function createFeature(title, description = '') {
  const res = await fetch(`${API_BASE}/features`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, description }),
  });
  if (!res.ok) throw new Error(`Create feature failed: ${res.status}`);
  return res.json();
}

/**
 * List all BA features.
 * @returns {Promise<Object[]>} Array of feature items
 */
export async function listFeatures() {
  const res = await fetch(`${API_BASE}/features`);
  if (!res.ok) throw new Error(`List features failed: ${res.status}`);
  return res.json();
}

/**
 * Get feature detail with section data.
 * @param {string} sessionId - Feature session ID
 * @returns {Promise<Object>} Feature detail with sections
 */
export async function getFeature(sessionId) {
  const res = await fetch(`${API_BASE}/features/${sessionId}`);
  if (!res.ok) throw new Error(`Get feature failed: ${res.status}`);
  return res.json();
}

/**
 * Delete a BA feature.
 * @param {string} sessionId - Feature session ID
 */
export async function deleteFeature(sessionId) {
  const res = await fetch(`${API_BASE}/features/${sessionId}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(`Delete feature failed: ${res.status}`);
}

/**
 * Get chat history for a session and section.
 * @param {string} sessionId - Feature session ID
 * @param {string} selectSection - Section ID (default: 'feature_definition')
 * @returns {Promise<Object>} History response object { session_id, select_section, messages }
 */
export async function exportFeature(sessionId) {
  const res = await fetch(`${API_BASE}/features/${sessionId}/export`, {
    method: 'POST',
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Export failed: ${res.status} — ${errText}`);
  }
  return res.json();
}

export async function exportAndOpenDesigner(sessionId) {
  const res = await fetch(`${API_BASE}/features/${sessionId}/designer-handoff`, {
    method: 'POST',
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Designer handoff failed: ${res.status} — ${errText}`);
  }
  return res.json();
}

export async function getFeatureDocuments(sessionId, query = '') {
  const qs = query ? `?q=${encodeURIComponent(query)}` : '';
  const res = await fetch(`${API_BASE}/features/${sessionId}/documents${qs}`);
  if (!res.ok) throw new Error(`List documents failed: ${res.status}`);
  return res.json();
}

function formatFetchError(action, err) {
  const msg = String(err?.message || err || 'Unknown error');
  if (err?.name === 'AbortError') {
    return `${action} timed out — API may be slow or unreachable`;
  }
  // Browser TypeError "Failed to fetch" = network/CORS/proxy down, not HTTP 4xx/5xx
  if (/failed to fetch|networkerror|load failed|fetch failed/i.test(msg)) {
    return (
      `${action}: network error (${msg}). ` +
      `Check API on :8000 and Vite /api proxy (API_PROXY → localhost:8000).`
    );
  }
  return `${action}: ${msg}`;
}

export async function downloadBpmn(sessionId, regenerate = false) {
  const qs = regenerate ? '?regenerate=true' : '';
  const label = regenerate ? 'BPMN regenerate' : 'BPMN export';
  let res;
  try {
    res = await fetch(`${API_BASE}/features/${sessionId}/bpmn${qs}`);
  } catch (err) {
    throw new Error(formatFetchError(label, err));
  }
  if (!res.ok) {
    let errText = '';
    try {
      errText = await res.text();
    } catch {
      errText = '';
    }
    const compact = String(errText || '')
      .replace(/<[^>]+>/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 400);
    throw new Error(
      `${label} failed: HTTP ${res.status}${compact ? ` — ${compact}` : ''}`,
    );
  }
  const blob = await res.blob();
  const disposition = res.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="([^"]+)"/);
  return { blob, filename: match ? match[1] : `ba-${sessionId}.bpmn` };
}

export async function saveTouchpoints(sessionId, uiTouchpoints) {
  const res = await fetch(`${API_BASE}/features/${sessionId}/touchpoints`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ui_touchpoints: uiTouchpoints }),
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Save touchpoints failed: ${res.status} — ${errText}`);
  }
  return res.json();
}

export async function getChatHistory(sessionId, selectSection = 'feature_definition') {
  const qs = selectSection ? `?section=${encodeURIComponent(selectSection)}` : '';
  const res = await fetch(`${API_BASE}/features/${sessionId}/history${qs}`);
  if (!res.ok) throw new Error(`Get chat history failed: ${res.status}`);
  return res.json();
}

// ── Chat (SSE Streaming) ─────────────────────────────────────

/**
 * Send a message to the BA agent and receive SSE events.
 *
 * Uses POST with fetch + ReadableStream to process SSE events
 * (POST-based SSE — not EventSource which only supports GET).
 *
 * @param {string} sessionId - Feature session ID
 * @param {string} message - User message text
 * @param {string} sectionId - Current section ID
 * @param {Object} handlers - Event handlers
 * @param {Function} handlers.onMessage - Called with {sender, text}
 * @param {Function} handlers.onStateUpdate - Called with state data
 * @param {Function} handlers.onDone - Called when stream completes
 * @param {Function} handlers.onError - Called on error
 * @returns {Promise<void>}
 */
export async function sendChatMessage(sessionId, message, sectionId, options = {}, handlers = {}) {
  const { action = null, assets = [], timeoutMs = 330000 } = options;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  let streamDone = false;
  try {
    const body = {
      user_id: 'ba-user',
      ticket_type: 'NEW_FEATURE',
      user_message: message,
      active_section: sectionId,
    };
    if (action) body.action = action;
    if (Array.isArray(assets) && assets.length) body.assets = assets;

    const res = await fetch(`${API_BASE}/v1/chat/${sessionId}/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    });

    if (!res.ok) {
      const errText = await res.text();
      const compact = String(errText || '')
        .replace(/<[^>]+>/g, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .slice(0, 400);
      await handlers.onError?.(
        new Error(`Chat failed: ${res.status}${compact ? ` — ${compact}` : ''}`),
      );
      return;
    }

    // Parse SSE from the response body stream
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Process complete SSE messages (double newline separated)
      const messages = buffer.split('\n\n');
      buffer = messages.pop(); // Keep incomplete message in buffer

      for (const msg of messages) {
        if (!msg.trim()) continue;

        const lines = msg.trim().split('\n');
        let eventType = '';
        let data = '';

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7);
          } else if (line.startsWith('data: ')) {
            data = line.slice(6);
          }
        }

        if (!eventType || !data) continue;

        try {
          const parsed = JSON.parse(data);

          switch (eventType) {
            case 'chat.message':
              handlers.onMessage?.(parsed);
              break;
            case 'state.update':
              handlers.onStateUpdate?.(parsed);
              break;
            case 'chat.done':
              streamDone = true;
              try {
                await handlers.onDone?.();
              } catch (handlerErr) {
                console.warn('onDone handler failed:', handlerErr);
              }
              break;
            case 'chat.error':
              streamDone = true;
              try {
                await handlers.onError?.(new Error(parsed.error || 'Unknown error'));
              } catch (handlerErr) {
                console.warn('onError handler failed:', handlerErr);
              }
              break;
          }
        } catch (parseErr) {
          console.warn('SSE parse error:', parseErr, data);
        }
      }
    }

    // Process any remaining buffer
    if (buffer.trim()) {
      const lines = buffer.trim().split('\n');
      let eventType = '';
      let data = '';
      for (const line of lines) {
        if (line.startsWith('event: ')) eventType = line.slice(7);
        else if (line.startsWith('data: ')) data = line.slice(6);
      }
      if (eventType === 'chat.done') {
        streamDone = true;
        try {
          await handlers.onDone?.();
        } catch (handlerErr) {
          console.warn('onDone handler failed:', handlerErr);
        }
      }
    }

    if (!streamDone) {
      try {
        await handlers.onDone?.();
      } catch (handlerErr) {
        console.warn('onDone handler failed:', handlerErr);
      }
    }

  } catch (err) {
    if (err.name === 'AbortError') {
      await handlers.onError?.(new Error(`Hết thời gian chờ phản hồi (>${Math.ceil(timeoutMs / 60000)} phút). Vui lòng thử lại.`));
    } else {
      await handlers.onError?.(err);
    }
  } finally {
    clearTimeout(timeoutId);
  }
}

// ── Health Check ─────────────────────────────────────────────

// ── Wiki Knowledge (same MVP SQLite; human approve only) ──

export async function listWikiPages(projectId, status = '') {
  if (!projectId) throw new Error('project_id is required to list wiki pages');
  const qs = new URLSearchParams({ project_id: projectId });
  if (status) qs.set('status', status);
  const res = await fetch(`${API_BASE}/wiki/pages?${qs.toString()}`);
  if (!res.ok) throw new Error(`List wiki pages failed: ${res.status}`);
  return res.json();
}

export async function uploadWikiSource(file, {
  namespace = 'project',
  projectId = '',
  actor = 'ba.lead',
  sortMode = 'auto',
} = {}) {
  if (namespace === 'project' && !projectId) {
    throw new Error('project_id is required for project-namespace upload');
  }
  const body = new FormData();
  body.append('file', file);
  body.append('namespace', namespace);
  body.append('project_id', projectId || '');
  body.append('actor', actor);
  body.append('sort_mode', sortMode);
  const res = await fetch(`${API_BASE}/wiki/sources`, { method: 'POST', body });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Wiki upload failed: ${res.status} — ${errText}`);
  }
  return res.json();
}

export async function approveWikiPage(pageId, {
  actor = 'ba.lead',
  projectId = '',
} = {}) {
  if (!projectId) throw new Error('project_id is required to approve');
  const body = new FormData();
  body.append('actor', actor);
  body.append('project_id', projectId);
  const res = await fetch(`${API_BASE}/wiki/pages/${encodeURIComponent(pageId)}/approve`, {
    method: 'POST',
    body,
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Wiki approve failed: ${res.status} — ${errText}`);
  }
  return res.json();
}

export async function demoteWikiPage(pageId, {
  actor = 'ba.lead',
  projectId = '',
} = {}) {
  if (!projectId) throw new Error('project_id is required to demote');
  const body = new FormData();
  body.append('actor', actor);
  body.append('project_id', projectId);
  const res = await fetch(`${API_BASE}/wiki/pages/${encodeURIComponent(pageId)}/demote`, {
    method: 'POST',
    body,
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Wiki demote failed: ${res.status} — ${errText}`);
  }
  return res.json();
}

export async function deleteWikiPage(pageId, {
  actor = 'ba.lead',
  projectId = '',
} = {}) {
  if (!projectId) throw new Error('project_id is required to delete');
  const body = new FormData();
  body.append('actor', actor);
  body.append('project_id', projectId);
  const res = await fetch(`${API_BASE}/wiki/pages/${encodeURIComponent(pageId)}/delete`, {
    method: 'POST',
    body,
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Wiki delete failed: ${res.status} — ${errText}`);
  }
  return res.json();
}

export async function clearWikiStore({
  confirm = 'CLEAR',
  actor = 'ba.lead',
} = {}) {
  const body = new FormData();
  body.append('confirm', confirm);
  body.append('actor', actor);
  const res = await fetch(`${API_BASE}/wiki/clear`, { method: 'POST', body });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Wiki clear failed: ${res.status} — ${errText}`);
  }
  return res.json();
}

export async function healthCheck() {
  const res = await fetch(`${API_BASE}/health`);
  return res.json();
}

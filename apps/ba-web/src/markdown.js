/**
 * Lightweight markdown → HTML for agent chat bubbles.
 * Supports: # headings, **bold**, `code`, nested lists, paragraphs.
 */

export function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text == null ? '' : String(text);
  return div.innerHTML;
}

export function formatChatMarkdown(text) {
  if (!text) return '';
  const escaped = escapeHtml(String(text));
  const lines = escaped.replace(/\r\n/g, '\n').split('\n');

  const inline = (line) =>
    line
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/__(.+?)__/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>');

  const html = [];
  const listStack = [];

  const closeAllLists = () => {
    while (listStack.length) {
      const closed = listStack.pop();
      html.push(`</li></${closed.tag}>`);
    }
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      closeAllLists();
      continue;
    }

    const indent = (line.match(/^ */) || [''])[0].length;
    const trimmed = line.trim();

    const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      closeAllLists();
      const level = Math.min(heading[1].length + 2, 6);
      html.push(`<h${level} class="md-h">${inline(heading[2])}</h${level}>`);
      continue;
    }

    const ulMatch = trimmed.match(/^[-*•◦▪▸]\s+(.+)$/);
    const olMatch = trimmed.match(/^\d+[.)]\s+(.+)$/);

    if (ulMatch || olMatch) {
      const tag = ulMatch ? 'ul' : 'ol';
      const content = inline(ulMatch ? ulMatch[1] : olMatch[1]);

      while (listStack.length && listStack[listStack.length - 1].indent > indent) {
        const closed = listStack.pop();
        html.push(`</li></${closed.tag}>`);
      }

      const top = listStack[listStack.length - 1];

      if (top && top.indent === indent && top.tag === tag) {
        html.push(`</li><li>${content}`);
      } else if (top && top.indent === indent && top.tag !== tag) {
        listStack.pop();
        html.push(`</li></${top.tag}><${tag}><li>${content}`);
        listStack.push({ indent, tag });
      } else if (top && indent > top.indent) {
        html.push(`<${tag}><li>${content}`);
        listStack.push({ indent, tag });
      } else {
        closeAllLists();
        html.push(`<${tag}><li>${content}`);
        listStack.push({ indent, tag });
      }
      continue;
    }

    if (listStack.length) {
      html.push(`<br>${inline(trimmed)}`);
      continue;
    }

    closeAllLists();
    html.push(`<p>${inline(trimmed)}</p>`);
  }

  closeAllLists();
  return html.join('');
}

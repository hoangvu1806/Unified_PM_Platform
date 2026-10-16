/**
 * Lightweight markdown → HTML for agent chat bubbles.
 * Supports: headings, **bold**, *italic*, ~~strike~~, `code`, ``` fences, links,
 * nested lists, tables, > quotes, --- rules, paragraphs. Input is escaped first.
 */

export function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text == null ? '' : String(text);
  return div.innerHTML;
}

const inline = (line) =>
  line
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/__(.+?)__/g, '<strong>$1</strong>')
    .replace(/(^|[\s(])\*([^*\s][^*]*?)\*(?=[\s).,;:!?]|$)/g, '$1<em>$2</em>')
    .replace(/~~(.+?)~~/g, '<del>$1</del>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

const cells = (row) => row.replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
const isTableRule = (row) => /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$/.test(row.trim());

export function formatChatMarkdown(text) {
  if (!text) return '';
  const lines = escapeHtml(String(text)).replace(/\r\n/g, '\n').split('\n');
  const html = [];
  const listStack = [];

  const closeAllLists = () => {
    while (listStack.length) html.push(`</li></${listStack.pop().tag}>`);
  };

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i].trimEnd();
    const trimmed = line.trim();
    if (!trimmed) {
      closeAllLists();
      continue;
    }

    if (trimmed.startsWith('```')) {
      closeAllLists();
      const body = [];
      for (i += 1; i < lines.length && !lines[i].trim().startsWith('```'); i += 1) body.push(lines[i]);
      html.push(`<pre class="md-pre"><code>${body.join('\n')}</code></pre>`);
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      closeAllLists();
      html.push('<hr class="md-hr">');
      continue;
    }

    if (trimmed.startsWith('|') && i + 1 < lines.length && isTableRule(lines[i + 1])) {
      closeAllLists();
      const head = cells(trimmed).map((c) => `<th>${inline(c)}</th>`).join('');
      const rows = [];
      for (i += 2; i < lines.length && lines[i].trim().startsWith('|'); i += 1) {
        rows.push(`<tr>${cells(lines[i].trim()).map((c) => `<td>${inline(c)}</td>`).join('')}</tr>`);
      }
      i -= 1;
      html.push(`<div class="md-table"><table><thead><tr>${head}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`);
      continue;
    }

    const quote = trimmed.match(/^&gt;\s?(.*)$/);
    if (quote) {
      closeAllLists();
      html.push(`<blockquote class="md-quote">${inline(quote[1])}</blockquote>`);
      continue;
    }

    const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      closeAllLists();
      const level = Math.min(heading[1].length + 2, 6);
      html.push(`<h${level} class="md-h">${inline(heading[2])}</h${level}>`);
      continue;
    }

    const indent = (line.match(/^ */) || [''])[0].length;
    const ulMatch = trimmed.match(/^[-*•◦▪▸]\s+(.+)$/);
    const olMatch = trimmed.match(/^\d+[.)]\s+(.+)$/);
    if (ulMatch || olMatch) {
      const tag = ulMatch ? 'ul' : 'ol';
      const content = inline(ulMatch ? ulMatch[1] : olMatch[1]);
      while (listStack.length && listStack[listStack.length - 1].indent > indent) {
        html.push(`</li></${listStack.pop().tag}>`);
      }
      const top = listStack[listStack.length - 1];
      if (top && top.indent === indent && top.tag === tag) {
        html.push(`</li><li>${content}`);
      } else if (top && top.indent === indent) {
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
    html.push(`<p>${inline(trimmed)}</p>`);
  }

  closeAllLists();
  return html.join('');
}

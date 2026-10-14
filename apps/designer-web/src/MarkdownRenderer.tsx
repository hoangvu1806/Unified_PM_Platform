import { Check, Copy, Terminal } from "lucide-react";
import { marked, type Tokens } from "marked";
import React, { useMemo, useState } from "react";

function CodeBlock({ code, lang }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* Clipboard is optional. */ }
  };
  return (
    <div className="md-code-block">
      <div className="md-code-header">
        <div className="md-code-lang"><Terminal size={13} /><span>{lang || "text"}</span></div>
        <button className="md-copy-btn" onClick={copy} type="button">
          {copied ? <Check size={13} /> : <Copy size={13} />}
          <span>{copied ? "Copied" : "Copy"}</span>
        </button>
      </div>
      <pre tabIndex={0}><code>{code}</code></pre>
    </div>
  );
}

function resolveImgSrc(href: string): string {
  if (!href) return "";
  if (href.startsWith("http://") || href.startsWith("https://") || href.startsWith("data:")) {
    return href;
  }
  const apiBase = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8282/api/v1").replace(/\/api\/v1\/?$/, "");
  return `${apiBase}${href.startsWith("/") ? "" : "/"}${href}`;
}

function inline(token: Tokens.Generic, key: React.Key): React.ReactNode {
  const children = token.tokens?.map(
    (child: Tokens.Generic, index: number) => inline(child, `${key}-${index}`),
  ) ?? token.text;
  switch (token.type) {
    case "text": return token.text;
    case "strong": return <strong key={key}>{children}</strong>;
    case "em": return <em key={key}>{children}</em>;
    case "codespan": return <code key={key} className="md-inline-code">{token.text}</code>;
    case "link": return (
      <a
        key={key}
        href={token.href}
        title={token.title ?? undefined}
        target="_blank"
        rel="noopener noreferrer"
        className="md-link"
      >
        {children}
      </a>
    );
    case "image": return (
      <img
        key={key}
        src={resolveImgSrc(token.href)}
        alt={token.text || "Mockup preview"}
        title={token.title ?? undefined}
        className="md-image"
        style={{
          maxWidth: "100%",
          maxHeight: "540px",
          objectFit: "contain",
          borderRadius: "10px",
          border: "1px solid #E2E8F0",
          display: "block",
          margin: "12px 0",
          boxShadow: "0 6px 16px rgba(15, 23, 42, 0.08)",
          backgroundColor: "#FFFFFF",
        }}
        loading="lazy"
      />
    );
    case "del": return <del key={key}>{children}</del>;
    case "br": return <br key={key} />;
    case "escape": return token.text;
    default: return token.raw;
  }
}

function tableCell(cell: Tokens.TableCell, key: React.Key, header = false) {
  const Cell = header ? "th" : "td";
  return (
    <Cell key={key} style={{ textAlign: cell.align ?? undefined }}>
      {cell.tokens?.map((token: Tokens.Generic, index: number) => inline(token, index)) ?? cell.text}
    </Cell>
  );
}

function block(token: Tokens.Generic, key: React.Key): React.ReactNode {
  if (token.type === "heading") {
    const tag = `h${Math.min(6, Math.max(1, token.depth))}` as keyof React.JSX.IntrinsicElements;
    return React.createElement(
      tag,
      { key, className: `md-${tag}` },
      token.tokens?.map((child: Tokens.Generic, index: number) => inline(child, index)) ?? token.text,
    );
  }
  if (token.type === "paragraph") {
    return <p key={key}>{token.tokens?.map((child: Tokens.Generic, index: number) => inline(child, index)) ?? token.text}</p>;
  }
  if (token.type === "code") return <CodeBlock key={key} code={token.text} lang={token.lang} />;
  if (token.type === "list") {
    const List = token.ordered ? "ol" : "ul";
    return (
      <List key={key} start={token.start || undefined} className={token.ordered ? "md-ol" : "md-ul"}>
        {token.items.map((item: Tokens.ListItem, index: number) => (
          <li key={index} className={item.task ? "md-task-item" : undefined}>
            {item.task && <input type="checkbox" checked={item.checked} readOnly className="md-checkbox" />}
            {item.tokens?.map((child: Tokens.Generic, childIndex: number) => (
              child.type === "text" && child.tokens
                ? child.tokens.map((nested: Tokens.Generic, nestedIndex: number) => inline(nested, `${childIndex}-${nestedIndex}`))
                : block(child, childIndex)
            )) ?? item.text}
          </li>
        ))}
      </List>
    );
  }
  if (token.type === "blockquote") {
    return <blockquote key={key} className="md-blockquote">{token.tokens?.map(block)}</blockquote>;
  }
  if (token.type === "table") {
    return (
      <div key={key} className="md-table-wrap">
        <table className="md-table">
          <thead><tr>{token.header.map((cell: Tokens.TableCell, index: number) => tableCell(cell, index, true))}</tr></thead>
          <tbody>{token.rows.map((row: Tokens.TableCell[], rowIndex: number) => (
            <tr key={rowIndex}>{row.map((cell, index) => tableCell(cell, index))}</tr>
          ))}</tbody>
        </table>
      </div>
    );
  }
  if (token.type === "hr") return <hr key={key} className="md-hr" />;
  if (token.type === "space") return null;
  if (token.type === "image") {
    return (
      <div key={key} className="md-image-block">
        <img
          src={resolveImgSrc(token.href)}
          alt={token.text || "Mockup preview"}
          title={token.title ?? undefined}
          className="md-image"
          style={{
            maxWidth: "100%",
            maxHeight: "540px",
            objectFit: "contain",
            borderRadius: "10px",
            border: "1px solid #E2E8F0",
            display: "block",
            margin: "12px 0",
            boxShadow: "0 6px 16px rgba(15, 23, 42, 0.08)",
            backgroundColor: "#FFFFFF",
          }}
          loading="lazy"
        />
      </div>
    );
  }
  if (token.tokens) return <div key={key}>{token.tokens.map(block)}</div>;
  return token.raw ? <span key={key}>{token.raw}</span> : null;
}

export const MarkdownRenderer = React.memo(function MarkdownRenderer({
  content, className = "",
}: {
  content: string;
  className?: string;
}) {
  const tokens = useMemo(() => {
    try { return content ? marked.lexer(content, { gfm: true, breaks: true }) : []; }
    catch { return []; }
  }, [content]);
  if (!content) return null;
  return <div className={`md-content ${className}`}>{tokens.map(block)}</div>;
});


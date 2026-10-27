"""Model replies for a screen: a whole HTML fragment, ``OK``, or SEARCH/REPLACE edit blocks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n(.*?)\n```\s*$", re.S)
_HTML_FENCE = re.compile(r"```(?:html)?[ \t]*\n(.*?)(?:\n```|\Z)", re.S)
_TAG_LINE = re.compile(r"(?m)^[ \t]*<(?:[a-zA-Z]|!--)")
_BLOCK = re.compile(r"<{5,9} ?SEARCH\s*\n(.*?)\n={5,9}\s*\n(.*?)\n?>{5,9} ?REPLACE", re.S)


def strip_fences(text: str) -> str:
    text = text.strip()
    match = _FENCE.match(text)
    return match.group(1).strip() if match else text


def extract_html(text: str) -> str:
    """The HTML fragment of a reply. Models sometimes think aloud first (and mention tags in that
    prose), so prefer the largest fenced block, else start at the first line that opens a tag."""
    fenced = [m.group(1) for m in _HTML_FENCE.finditer(text) if "<" in m.group(1)]
    if fenced:
        text = max(fenced, key=len)
    else:
        start = _TAG_LINE.search(text)
        text = text[start.start():] if start else text
    end = text.rfind(">")
    return text[: end + 1].strip() if end >= 0 else text.strip()


@dataclass
class Edit:
    html: str
    applied: int = 0
    failed: list[str] = field(default_factory=list)
    ok: bool = False
    rewrite: bool = False


def apply_reply(html: str, reply: str) -> Edit:
    text = strip_fences(reply)
    if re.fullmatch(r"\W*OK\W*", text, re.I):
        return Edit(html, ok=True)
    blocks = _BLOCK.findall(text)
    if not blocks:
        candidate = extract_html(text)
        if candidate.startswith("<") and len(candidate) > 200:
            return Edit(candidate, applied=1, rewrite=True)
        return Edit(html, failed=["Reply had neither OK, edit blocks nor HTML."])
    result = Edit(html)
    for search, replace in blocks:
        if search and result.html.count(search) == 1:
            result.html = result.html.replace(search, replace, 1)
            result.applied += 1
            continue
        # Tolerate whitespace differences: match on collapsed whitespace, replace the original span.
        pattern = r"\s+".join(map(re.escape, search.split()))
        matches = list(re.finditer(pattern, result.html)) if search.strip() else []
        if len(matches) == 1:
            m = matches[0]
            result.html = result.html[: m.start()] + replace + result.html[m.end():]
            result.applied += 1
        else:
            result.failed.append(search[:120] + (" (not found)" if not matches else f" ({len(matches)} matches)"))
    return result

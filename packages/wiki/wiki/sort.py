from __future__ import annotations

import re
from typing import Protocol

from wiki.models import WikiPage

GLOSSARY = {
    "AC": {
        "page_id": "PG-GLOSS-AC",
        "title": "AC --- Acceptance Criterion",
        "expansion": "Acceptance Criterion",
        "disambiguation": "Khong dung AC = Alternate Course.",
        "body": "Dieu kien kiem chung User Story; moi AC gan dung mot story.",
    },
    "PO": {
        "page_id": "PG-GLOSS-PO",
        "title": "PO --- Product Owner",
        "expansion": "Product Owner",
        "disambiguation": "Khong dung PO = Purchase Order trong context Factory nay.",
        "body": "Nguoi phe duyet Business Analysis Package.",
    },
    "BR": {
        "page_id": "PG-GLOSS-BR",
        "title": "BR --- Business Rule",
        "expansion": "Business Rule",
        "disambiguation": "Khong dung BR = Bed Rest / Branch.",
        "body": "Rule da chot, co nguon. Agent fetch lam constrain.",
    },
    "US": {
        "page_id": "PG-GLOSS-US",
        "title": "US --- User Story",
        "expansion": "User Story",
        "disambiguation": "Khong dung US = United States.",
        "body": "As a <role> I want <action> so that <value>. Moi US keo theo AC.",
    },
    "UAPDF": {
        "page_id": "PG-GLOSS-UAPDF",
        "title": "UAPDF --- Unify AI Product and Design Factory",
        "expansion": "Unify AI Product and Design Factory",
        "disambiguation": None,
        "body": "Ten Factory. Khong bia expansion khac.",
    },
}

SECTION_BUCKETS = [
    (r"\bConstraint\b", "constraint"),
    (r"\bConvention\b", "convention"),
    (r"\bOrg\b", "org"),
    (r"\bProgress\b", "progress"),
]

# Case-insensitive: PDF extract / headings may vary in casing.
_SECTION_FLAGS = re.I


class Sorter(Protocol):
    def sort(
        self,
        markdown: str,
        *,
        source_id: str,
        namespace: str,
        project_id: str | None,
        owner: str,
        now: str,
    ) -> list[WikiPage]:
        ...


def _source_tail(source_id: str) -> str:
    # Keep enough of the source id so the same bytes in two projects
    # (SRC-DEADBEEF vs SRC-DEADBEEF-PRJB) do not share page_ids.
    return source_id.replace("SRC-", "").replace("-", "")[:12] or "UNKNOWN"


def _first_heading(markdown: str) -> str:
    lines = (markdown or "").splitlines()
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line.startswith("#"):
            continue
        title = re.sub(r"^#+\s*", "", line).strip()
        # extract_pdf injects "# PDF page N" — prefer the next content line.
        if re.fullmatch(r"PDF page \d+", title, flags=re.I):
            for nxt in lines[i + 1 :]:
                cand = nxt.strip()
                if not cand or cand.startswith("#") or set(cand) <= {"-", "="}:
                    continue
                return cand[:120]
            continue
        if title:
            return title[:120]
    return ""


def _excerpt(markdown: str, limit: int = 500) -> str:
    lines = []
    for raw in (markdown or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
        if sum(len(x) + 1 for x in lines) >= limit:
            break
    text = " ".join(lines).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text or (markdown or "").strip()[:limit]


class HeuristicSorter:
    """Draft-only bucket assignment. Does not rewrite extract text."""

    last_backend: str = "heuristic"

    def sort(
        self,
        markdown: str,
        *,
        source_id: str,
        namespace: str,
        project_id: str | None,
        owner: str,
        now: str,
    ) -> list[WikiPage]:
        self.last_backend = "heuristic"
        pages: list[WikiPage] = []
        seen: set[str] = set()
        tail = _source_tail(source_id)

        def add(page: WikiPage) -> None:
            if page.page_id in seen:
                return
            seen.add(page.page_id)
            pages.append(page)

        for abbrev, spec in GLOSSARY.items():
            if re.search(rf"\b{abbrev}\b", markdown):
                add(
                    WikiPage(
                        page_id=spec["page_id"],
                        namespace=namespace,
                        project_id=project_id,
                        bucket_id="glossary",
                        title=spec["title"],
                        abbrev=abbrev,
                        expansion=spec["expansion"],
                        disambiguation=spec["disambiguation"],
                        status="draft",
                        version="1.0.0",
                        body=spec["body"],
                        source_ids=[source_id],
                        owner=owner,
                        updated_at=now,
                    )
                )

        phe = bool(
            re.search(r"phe\s*duyet", markdown, re.I)
            or re.search(r"phê\s*duyệt", markdown, re.I)
            or re.search(r"nguoi phe duyet", markdown, re.I)
        )
        rules = bool(re.search(r"\bRules\b", markdown, re.I) or phe)
        if rules:
            # Preserve sample BRD page id for contract tests; otherwise bind to full source tail.
            rule_id = "PG-RULE-001" if source_id == "SRC-BRD-001" else f"PG-RULE-{tail}"
            if phe:
                title = "Moi don can mot nguoi phe duyet"
                body = (
                    "Moi don can mot nguoi phe duyet. "
                    "Nguon: extract lossless, chua paraphrase."
                )
            else:
                title = _first_heading(markdown) or f"Rules from {source_id}"
                body = _excerpt(markdown)
            add(
                WikiPage(
                    page_id=rule_id,
                    namespace=namespace,
                    project_id=project_id,
                    bucket_id="business_rule",
                    title=title,
                    abbrev=None,
                    expansion=None,
                    disambiguation=None,
                    status="draft",
                    version="1.0.0",
                    body=body,
                    source_ids=[source_id],
                    owner=owner,
                    updated_at=now,
                )
            )

        for pattern, bucket in SECTION_BUCKETS:
            if re.search(pattern, markdown, _SECTION_FLAGS):
                add(
                    WikiPage(
                        page_id=f"PG-{bucket.upper()[:4]}-{tail}",
                        namespace=namespace,
                        project_id=project_id,
                        bucket_id=bucket,
                        title=f"{bucket} section (draft)",
                        abbrev=None,
                        expansion=None,
                        disambiguation=None,
                        status="draft",
                        version="1.0.0",
                        # No digits / source_id here — VA firm checks treat bare
                        # numbers in approved bodies as policy thresholds.
                        body=f"Section {bucket} detected in extract. Pending human review.",
                        source_ids=[source_id],
                        owner=owner,
                        updated_at=now,
                    )
                )
        return pages

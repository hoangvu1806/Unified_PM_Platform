"""LLM sorter: propose DRAFT wiki pages from lossless extract. No paraphrase of source."""

from __future__ import annotations

import re
from typing import Any

from wiki.llm_client import LlmClient, LlmError
from wiki.models import WikiPage
from wiki.sort import HeuristicSorter, Sorter

ALLOWED_BUCKETS = frozenset(
    {
        "glossary",
        "business_rule",
        "org",
        "convention",
        "constraint",
        "progress",
    }
)

STABLE_GLOSSARY = {
    "AC": "PG-GLOSS-AC",
    "PO": "PG-GLOSS-PO",
    "BR": "PG-GLOSS-BR",
    "US": "PG-GLOSS-US",
    "UAPDF": "PG-GLOSS-UAPDF",
}

SYSTEM_PROMPT = """You are the Wiki Knowledge Module sorter for UAPDF-WKM-001.
You ONLY propose DRAFT wiki pages from a lossless Markdown extract.
You MUST NOT paraphrase, rewrite, or invent facts. body must be verbatim excerpts
or short quotes copied from the extract.
Forbidden: invent glossary expansions not in the extract; invent thresholds;
invent SKU / stock rows; invent roles.

Return JSON only:
{"pages":[{"page_id":"...","bucket_id":"...","title":"...","abbrev":null,"expansion":null,"disambiguation":null,"body":"..."}]}

bucket_id must be one of: glossary, business_rule, org, convention, constraint, progress.
Prefer stable page_id when obvious: PG-GLOSS-AC, PG-GLOSS-PO, PG-GLOSS-BR, PG-GLOSS-US, PG-GLOSS-UAPDF.
Otherwise use PG-{BUCKET}-{suffix} where suffix is derived from source_id (e.g. SRC-ABC12345 -> ABC12345).
Propose at most 20 pages. Skip empty noise.
"""


class LlmSorter:
    """Draft-only bucket assignment via LLM Gate. Does not rewrite extract text."""

    last_backend: str = "llm"

    def __init__(self, client: LlmClient, *, max_chars: int = 24000) -> None:
        self.client = client
        self.max_chars = max_chars
        self.last_backend = "llm"

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
        extract = markdown
        if len(extract) > self.max_chars:
            extract = (
                extract[: self.max_chars]
                + "\n\n[TRUNCATED for sorter; full extract remains on wiki_source.]"
            )

        user = (
            f"source_id={source_id}\n"
            f"namespace={namespace}\n"
            f"project_id={project_id or ''}\n\n"
            f"EXTRACT:\n{extract}"
        )
        raw = self.client.chat_json(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
        )
        pages = self._pages_from_payload(
            raw,
            source_id=source_id,
            namespace=namespace,
            project_id=project_id,
            owner=owner,
            now=now,
        )
        if not pages:
            raise LlmError("LLM returned zero valid pages")
        self.last_backend = "llm"
        return pages

    def _pages_from_payload(
        self,
        raw: dict[str, Any],
        *,
        source_id: str,
        namespace: str,
        project_id: str | None,
        owner: str,
        now: str,
    ) -> list[WikiPage]:
        items = raw.get("pages")
        if not isinstance(items, list):
            raise LlmError("LLM JSON missing pages array")

        pages: list[WikiPage] = []
        seen: set[str] = set()
        for item in items[:20]:
            if not isinstance(item, dict):
                continue
            page = self._one_page(
                item,
                source_id=source_id,
                namespace=namespace,
                project_id=project_id,
                owner=owner,
                now=now,
            )
            if page is None or page.page_id in seen:
                continue
            seen.add(page.page_id)
            pages.append(page)
        return pages

    def _one_page(
        self,
        item: dict[str, Any],
        *,
        source_id: str,
        namespace: str,
        project_id: str | None,
        owner: str,
        now: str,
    ) -> WikiPage | None:
        bucket = str(item.get("bucket_id") or "").strip()
        if bucket not in ALLOWED_BUCKETS:
            return None
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or "").strip()
        if not title or not body:
            return None

        abbrev = item.get("abbrev")
        abbrev_s = str(abbrev).strip() if abbrev else None
        if abbrev_s == "":
            abbrev_s = None

        page_id = str(item.get("page_id") or "").strip()
        if abbrev_s and abbrev_s.upper() in STABLE_GLOSSARY:
            page_id = STABLE_GLOSSARY[abbrev_s.upper()]
            bucket = "glossary"
        if not page_id:
            page_id = self._default_page_id(bucket, source_id, abbrev_s)
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$", page_id):
            return None

        expansion = item.get("expansion")
        disambiguation = item.get("disambiguation")
        return WikiPage(
            page_id=page_id,
            namespace=namespace,
            project_id=project_id,
            bucket_id=bucket,
            title=title[:200],
            abbrev=abbrev_s,
            expansion=str(expansion).strip() if expansion else None,
            disambiguation=str(disambiguation).strip() if disambiguation else None,
            status="draft",
            version="1.0.0",
            body=body[:8000],
            source_ids=[source_id],
            owner=owner,
            updated_at=now,
        )

    @staticmethod
    def _default_page_id(bucket: str, source_id: str, abbrev: str | None) -> str:
        if abbrev and abbrev.upper() in STABLE_GLOSSARY:
            return STABLE_GLOSSARY[abbrev.upper()]
        tail = source_id.replace("SRC-", "")[:8] or "PAGE"
        prefix = bucket.upper()[:4]
        return f"PG-{prefix}-{tail}"


class FallbackSorter:
    """Try primary sorter; on any failure use secondary (usually HeuristicSorter)."""

    last_backend: str = "heuristic"

    def __init__(self, primary: Sorter, secondary: Sorter | None = None) -> None:
        self.primary = primary
        self.secondary = secondary or HeuristicSorter()
        self.last_backend = "heuristic"

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
        try:
            pages = self.primary.sort(
                markdown,
                source_id=source_id,
                namespace=namespace,
                project_id=project_id,
                owner=owner,
                now=now,
            )
            self.last_backend = getattr(self.primary, "last_backend", "llm")
            return pages
        except Exception:
            pages = self.secondary.sort(
                markdown,
                source_id=source_id,
                namespace=namespace,
                project_id=project_id,
                owner=owner,
                now=now,
            )
            self.last_backend = "heuristic_fallback"
            if hasattr(self.secondary, "last_backend"):
                self.secondary.last_backend = "heuristic_fallback"  # type: ignore[attr-defined]
            return pages


def _tag_pages(pages: list[WikiPage], *, prefix: str, label: str) -> list[WikiPage]:
    out: list[WikiPage] = []
    for page in pages:
        pid = page.page_id if page.page_id.startswith(f"{prefix}-") else f"{prefix}-{page.page_id}"
        title = page.title if page.title.startswith(f"[{label}]") else f"[{label}] {page.title}"
        out.append(
            page.model_copy(
                update={
                    "page_id": pid[:64],
                    "title": title[:200],
                }
            )
        )
    return out


class BothSorter:
    """Run heuristic and LLM; prefix page_ids so drafts can be compared side by side."""

    last_backend: str = "both"

    def __init__(self, heuristic: Sorter, llm: Sorter | None) -> None:
        self.heuristic = heuristic
        self.llm = llm
        self.last_backend = "both"

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
        h_pages = _tag_pages(
            self.heuristic.sort(
                markdown,
                source_id=source_id,
                namespace=namespace,
                project_id=project_id,
                owner=owner,
                now=now,
            ),
            prefix="H",
            label="heuristic",
        )
        l_pages: list[WikiPage] = []
        llm_ok = False
        if self.llm is not None:
            try:
                l_pages = _tag_pages(
                    self.llm.sort(
                        markdown,
                        source_id=source_id,
                        namespace=namespace,
                        project_id=project_id,
                        owner=owner,
                        now=now,
                    ),
                    prefix="L",
                    label="llm",
                )
                llm_ok = True
            except Exception:
                l_pages = []
                llm_ok = False

        if self.llm is None:
            self.last_backend = "both_heuristic_only"
        elif llm_ok:
            self.last_backend = "both"
        else:
            self.last_backend = "both_llm_failed"
        return h_pages + l_pages

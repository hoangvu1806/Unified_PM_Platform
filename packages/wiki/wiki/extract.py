from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from wiki.models import WikiError

_TEXT_SUFFIXES = {".txt", ".md", ".markdown"}


def extract_pdf(path: Path, filename: str | None = None) -> tuple[str, list[dict]]:
    """Deterministic source → Markdown. PDF via pypdf; .txt/.md as UTF-8. Never paraphrase."""
    name = (filename or path.name).lower()
    suffix = Path(name).suffix
    raw = path.read_bytes()
    if raw.startswith(b"%PDF"):
        return _extract_pdf_file(path)
    if suffix in _TEXT_SUFFIXES or _looks_like_text(raw):
        return _extract_text_bytes(raw)
    raise WikiError(
        "COMMON_SCHEMA_INVALID",
        "supported uploads: PDF, .txt, .md",
        400,
    )


def _looks_like_text(raw: bytes) -> bool:
    if not raw or b"\x00" in raw[:4096]:
        return False
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _extract_text_bytes(raw: bytes) -> tuple[str, list[dict]]:
    text = raw.decode("utf-8-sig")
    if not text.strip():
        raise WikiError("COMMON_SCHEMA_INVALID", "empty file", 400)
    heading = "# Text source"
    markdown = f"{heading}\n{text.rstrip()}\n"
    return markdown, [{"md_heading": "Text source", "pdf_page": 1}]


def _extract_pdf_file(path: Path) -> tuple[str, list[dict]]:
    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001 — surface as contract error
        raise WikiError("COMMON_SCHEMA_INVALID", f"cannot read PDF: {exc}", 400) from exc

    if not reader.pages:
        raise WikiError("COMMON_SCHEMA_INVALID", "PDF has no pages", 400)

    md_parts: list[str] = []
    page_map: list[dict] = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        heading = f"# PDF page {i}"
        md_parts.append(heading)
        md_parts.append(text.rstrip())
        md_parts.append("")
        page_map.append({"md_heading": heading.lstrip("# ").strip(), "pdf_page": i})

    markdown = "\n".join(md_parts).strip() + "\n"
    if not markdown.strip():
        raise WikiError(
            "COMMON_PRECONDITION_FAILED",
            "extract produced empty text (OCR is out of MVP)",
            422,
        )
    return markdown, page_map

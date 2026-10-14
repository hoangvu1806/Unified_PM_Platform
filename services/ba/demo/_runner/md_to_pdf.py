"""Convert demo wiki Markdown sources into simple extractable PDFs."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Allow importing MVP pdf helper when WIKI_MVP_ROOT or sibling mvp exists.
_REPO = Path(__file__).resolve().parents[2]
_MVP_CANDIDATES = [
    Path(__file__).resolve().parents[3] / "mvp",  # WikiFactoryAI/mvp
    _REPO.parent.parent / "mvp",
]


def _ensure_mvp() -> Path:
    for root in _MVP_CANDIDATES:
        if (root / "wiki" / "pdf_write.py").is_file():
            sys.path.insert(0, str(root))
            return root
    raise SystemExit(
        "Cannot find Wiki MVP (wiki/pdf_write.py). Set WIKI_MVP_ROOT or keep mvp next to the BA repo."
    )


def _md_to_pages(text: str, *, max_lines: int = 48) -> list[list[str]]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("#"):
            title = re.sub(r"^#+\s*", "", line).strip()
            # Keep original casing so MVP HeuristicSorter can match \bRules\b etc.
            # ASCII-safe for Helvetica extractable PDFs.
            safe_title = title.encode("ascii", errors="replace").decode("ascii")
            lines.append("")
            lines.append(safe_title[:98])
            lines.append("-" * min(len(safe_title), 60))
            continue
        if not line.strip():
            lines.append("")
            continue
        # Keep ASCII-safe for Helvetica extractable PDFs.
        safe = line.encode("ascii", errors="replace").decode("ascii")
        while len(safe) > 98:
            lines.append(safe[:98])
            safe = safe[98:]
        lines.append(safe)

    pages: list[list[str]] = []
    buf: list[str] = []
    for line in lines:
        buf.append(line)
        if len(buf) >= max_lines:
            pages.append(buf)
            buf = []
    if buf:
        pages.append(buf)
    return pages or [["(empty)"]]


def build_pdf_from_md(md_path: Path, pdf_path: Path | None = None) -> Path:
    _ensure_mvp()
    from wiki.pdf_write import write_pdf

    out = pdf_path or md_path.with_suffix(".pdf")
    # Prefer sibling of src/: .../src/01.md -> .../01.pdf
    if md_path.parent.name == "src" and pdf_path is None:
        out = md_path.parent.parent / f"{md_path.stem}.pdf"
    pages = _md_to_pages(md_path.read_text(encoding="utf-8"))
    write_pdf(out, pages)
    return out


def build_tree(root: Path) -> list[Path]:
    built: list[Path] = []
    for md in sorted(root.rglob("src/*.md")):
        built.append(build_pdf_from_md(md))
    return built


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build demo wiki PDFs from src/*.md")
    parser.add_argument(
        "roots",
        nargs="*",
        type=Path,
        default=[Path(__file__).resolve().parents[1]],
        help="Demo roots to scan (default: demo/)",
    )
    args = parser.parse_args(argv)
    all_built: list[Path] = []
    for root in args.roots:
        root = root.resolve()
        if not root.exists():
            print(f"skip missing {root}", file=sys.stderr)
            continue
        built = build_tree(root)
        all_built.extend(built)
        for path in built:
            print(f"wrote {path}")
    if not all_built:
        print("No src/*.md found", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

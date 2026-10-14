"""Resolve the Wiki Knowledge MVP checkout used as the document store."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_BA_REPO = Path(__file__).resolve().parents[1]


def _looks_like_mvp(root: Path) -> bool:
    return (root / "wiki" / "__init__.py").is_file()


def _candidate_mvp_roots() -> list[Path]:
    """Host layouts: WikiFactoryAI/mvp, ~/apps/wiki-mvp beside ba-factory, Docker /opt."""
    out: list[Path] = []
    for raw in (
        _BA_REPO.parents[1] / "mvp" if len(_BA_REPO.parents) > 1 else None,
        _BA_REPO.parent / "wiki-mvp",
        _BA_REPO.parent / "mvp",
        Path("/opt/wiki-mvp"),
        Path.home() / "mvp",
        Path.home() / "apps" / "wiki-mvp",
    ):
        if raw is None:
            continue
        try:
            out.append(raw.resolve())
        except OSError:
            out.append(raw)
    # Dedupe while preserving order
    seen: set[str] = set()
    unique: list[Path] = []
    for p in out:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


def _default_mvp() -> Path:
    for candidate in _candidate_mvp_roots():
        if _looks_like_mvp(candidate):
            return candidate
    # Fall back to the historical relative path even if missing (clearer errors).
    try:
        return (_BA_REPO.parents[1] / "mvp").resolve()
    except (IndexError, OSError):
        return Path("/opt/wiki-mvp")


_MINIMAL_MANIFEST = """{
  "agents": {
    "ba-agent": {
      "tools.allowed": ["wiki.search_pages", "wiki.fetch_page"],
      "tools.denied": ["wiki.approve_page", "wiki.demote_page", "wiki.delete_page"]
    },
    "validation-agent": {
      "tools.allowed": ["wiki.search_pages", "wiki.fetch_page"],
      "tools.denied": ["wiki.approve_page", "wiki.demote_page", "wiki.delete_page", "wiki.ingest_source", "wiki.propose_page"]
    }
  }
}
"""


def mvp_root() -> Path:
    raw = os.environ.get("WIKI_MVP_ROOT", "").strip()
    if raw:
        configured = Path(raw).expanduser().resolve()
        if _looks_like_mvp(configured):
            return configured
        # Stale Mac/Docker path on VPS — keep looking.
    try:
        from config.base_config import settings

        configured = (getattr(settings, "wiki_mvp_root", "") or "").strip()
        if configured:
            path = Path(configured).expanduser().resolve()
            if _looks_like_mvp(path):
                return path
    except Exception:
        pass
    return _default_mvp()


def wiki_service_root(explicit: Path | None = None) -> Path:
    """Directory the wiki store treats as root (`config/manifest.json` + `data/wiki.db`)."""
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    data_dir = os.environ.get("WIKI_DATA_DIR", "").strip()
    if not data_dir:
        try:
            from config.base_config import settings

            data_dir = (getattr(settings, "wiki_data_dir", "") or "").strip()
        except Exception:
            data_dir = ""
    if data_dir:
        return Path(data_dir).expanduser().resolve()
    return mvp_root()


def ensure_mvp_importable() -> Path:
    root = mvp_root()
    if not _looks_like_mvp(root):
        # Env may point at a stale/missing checkout; discover a sibling mvp.
        for candidate in _candidate_mvp_roots():
            if _looks_like_mvp(candidate):
                root = candidate
                break
    path = str(root)
    if path not in sys.path:
        sys.path.insert(0, path)
    if not _looks_like_mvp(root):
        raise ModuleNotFoundError(
            "No module named 'wiki': set WIKI_MVP_ROOT to the Wiki MVP checkout "
            f"(expected {path}/wiki/__init__.py). Tried: "
            + ", ".join(str(p) for p in _candidate_mvp_roots())
        )
    return root


def ensure_manifest(root: Path) -> None:
    manifest = root / "config" / "manifest.json"
    if manifest.exists():
        return
    src = mvp_root() / "config" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        manifest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        return
    manifest.write_text(_MINIMAL_MANIFEST, encoding="utf-8")

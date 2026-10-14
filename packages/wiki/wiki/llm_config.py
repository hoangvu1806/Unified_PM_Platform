"""Env config for LLM Gate sort. Secrets stay in env / .env — never commit keys."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from wiki.paths import MVP_ROOT
from wiki.sort import HeuristicSorter, Sorter


def load_dotenv(root: Path | None = None) -> None:
    """Load mvp/.env if present. Does not override existing env vars."""
    try:
        from dotenv import load_dotenv as _load
    except ImportError:
        return
    path = (root or MVP_ROOT) / ".env"
    if path.is_file():
        _load(path, override=False)
    get_llm_settings.cache_clear()


@dataclass(frozen=True)
class LlmSettings:
    sort_mode: str  # heuristic | llm | auto
    base_url: str
    api_key: str
    model: str
    timeout_s: float
    max_chars: int

    @property
    def want_llm(self) -> bool:
        if self.sort_mode == "heuristic":
            return False
        if self.sort_mode == "llm":
            return True
        return bool(self.api_key.strip())


@lru_cache(maxsize=1)
def get_llm_settings() -> LlmSettings:
    mode = os.environ.get("WIKI_SORT", "auto").strip().lower() or "auto"
    if mode not in {"heuristic", "llm", "auto"}:
        mode = "auto"
    return LlmSettings(
        sort_mode=mode,
        # Platform: fall back to the shared LLM_* gateway variables.
        base_url=(
            os.environ.get("WIKI_LLM_BASE_URL")
            or os.environ.get("LLM_BASE_URL")
            or "https://llm-gate.imespro.ai/v1"
        ).rstrip("/"),
        api_key=(
            os.environ.get("WIKI_LLM_API_KEY") or os.environ.get("LLM_API_KEY") or ""
        ).strip(),
        model=os.environ.get("WIKI_LLM_MODEL", "Qwen3.5-27B-AWQ").strip()
        or "Qwen3.5-27B-AWQ",
        timeout_s=float(os.environ.get("WIKI_LLM_TIMEOUT_S", "60")),
        max_chars=int(os.environ.get("WIKI_LLM_MAX_CHARS", "24000")),
    )


def build_sorter(mode: str | None = None) -> Sorter:
    """Pick sorter: heuristic, LLM(+fallback), or both for side-by-side demo.

    mode: None → use WIKI_SORT env; or explicit heuristic|llm|auto|both
    """
    load_dotenv()
    settings = get_llm_settings()
    chosen = (mode or settings.sort_mode).strip().lower()
    if chosen not in {"heuristic", "llm", "auto", "both"}:
        chosen = "auto"

    if chosen == "both":
        from wiki.sort_llm import BothSorter

        return BothSorter(
            heuristic=HeuristicSorter(),
            llm=_llm_sorter(settings) if settings.api_key else None,
        )

    want_llm = chosen == "llm" or (chosen == "auto" and bool(settings.api_key.strip()))
    if chosen == "heuristic" or not want_llm:
        return HeuristicSorter()

    from wiki.sort_llm import FallbackSorter

    return FallbackSorter(primary=_llm_sorter(settings), secondary=HeuristicSorter())


def _llm_sorter(settings: LlmSettings):
    from wiki.llm_client import LlmClient
    from wiki.sort_llm import LlmSorter

    client = LlmClient(
        base_url=settings.base_url,
        api_key=settings.api_key,
        model=settings.model,
        timeout_s=settings.timeout_s,
    )
    return LlmSorter(client=client, max_chars=settings.max_chars)

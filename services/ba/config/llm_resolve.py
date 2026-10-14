"""Resolve the OpenAI-compatible endpoint used by the BA Agent."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from config.base_config import settings


@dataclass(frozen=True)
class LlmEndpoint:
    provider: str
    api_base_url: str
    model_name: str
    api_key: str


def _is_internal_litellm(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"litellm", "localhost", "127.0.0.1"} and (
        urlparse(url).port in {4000, None} or ":4000" in url
    )


def resolve_llm_endpoint() -> LlmEndpoint:
    """Prefer the company gate unless the optional LiteLLM proxy is requested."""
    if settings.use_litellm_proxy:
        return LlmEndpoint(
            provider="litellm",
            api_base_url=settings.litellm_api_base_url.rstrip("/"),
            model_name=settings.litellm_model_name,
            api_key=settings.litellm_master_key,
        )

    gate_base = (settings.llm_gate_api_base_url or "").strip().rstrip("/")
    gate_key = (settings.llm_gate_api_key or "").strip()
    gate_model = (settings.llm_gate_model_name or "").strip() or "Qwen3.5-27B-AWQ"
    litellm_base = settings.litellm_api_base_url.rstrip("/")

    if gate_base and gate_key and (
        _is_internal_litellm(litellm_base) or "llm-gate.imespro.ai" in litellm_base
        or litellm_base.rstrip("/") == gate_base
    ):
        return LlmEndpoint(
            provider="company-gate",
            api_base_url=gate_base,
            model_name=gate_model,
            api_key=gate_key,
        )

    return LlmEndpoint(
        provider="litellm",
        api_base_url=litellm_base,
        model_name=settings.litellm_model_name,
        api_key=settings.litellm_master_key or gate_key,
    )

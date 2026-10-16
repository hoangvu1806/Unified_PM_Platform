"""ADK model client pointed at the internal LiteLLM Proxy."""

from __future__ import annotations

from google.adk.models.lite_llm import LiteLlm

from config.base_config import settings
from config.llm_resolve import resolve_llm_endpoint

_ep = resolve_llm_endpoint()
model_name = _ep.model_name
api_base_url = _ep.api_base_url
api_key = _ep.api_key
llm_provider = _ep.provider

base_model = LiteLlm(
    model=f"openai/{model_name}",
    api_base=api_base_url,
    api_key=api_key,
    top_p=settings.top_p,
    temperature=settings.temperature,
    presence_penalty=settings.presence_penalty,
    frequency_penalty=settings.frequency_penalty,
    max_tokens=settings.max_tokens,
    timeout=100,
    num_retries=0,
    chat_template_kwargs={"enable_thinking": False},
    # Models that reject top_p / penalties (e.g. OpenAI reasoning models) get them dropped.
    drop_params=True,
)

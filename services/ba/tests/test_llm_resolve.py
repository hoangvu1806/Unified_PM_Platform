"""Company gate is used when LiteLLM is not requested."""

from __future__ import annotations

from types import SimpleNamespace

from config import llm_resolve


def test_resolve_uses_company_gate_by_default(monkeypatch):
    monkeypatch.setattr(
        llm_resolve,
        "settings",
        SimpleNamespace(
            use_litellm_proxy=False,
            litellm_api_base_url="http://litellm:4000/v1",
            litellm_model_name="ba-company",
            litellm_master_key="sk-ba-local-dev",
            llm_gate_api_base_url="https://llm-gate.imespro.ai/v1",
            llm_gate_api_key="gate-key",
            llm_gate_model_name="Qwen3.5-27B-AWQ",
        ),
    )
    endpoint = llm_resolve.resolve_llm_endpoint()
    assert endpoint.provider == "company-gate"
    assert endpoint.api_base_url == "https://llm-gate.imespro.ai/v1"
    assert endpoint.model_name == "Qwen3.5-27B-AWQ"
    assert endpoint.api_key == "gate-key"


def test_resolve_uses_litellm_when_proxy_flag_set(monkeypatch):
    monkeypatch.setattr(
        llm_resolve,
        "settings",
        SimpleNamespace(
            use_litellm_proxy=True,
            litellm_api_base_url="http://litellm:4000/v1",
            litellm_model_name="ba-company",
            litellm_master_key="sk-ba-local-dev",
            llm_gate_api_base_url="https://llm-gate.imespro.ai/v1",
            llm_gate_api_key="gate-key",
            llm_gate_model_name="Qwen3.5-27B-AWQ",
        ),
    )
    endpoint = llm_resolve.resolve_llm_endpoint()
    assert endpoint.provider == "litellm"
    assert endpoint.api_base_url == "http://litellm:4000/v1"
    assert endpoint.model_name == "ba-company"

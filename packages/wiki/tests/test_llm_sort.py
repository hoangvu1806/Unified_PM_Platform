from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from wiki.llm_client import LlmClient, LlmError
from wiki.sort import HeuristicSorter
from wiki.sort_llm import FallbackSorter, LlmSorter


SAMPLE_MD = """
BRD-F-001 Rules
AC --- Acceptance Criterion
PO --- Product Owner
phe duyet don
Constraint
No agent approve.
Convention
sku = VT-family-seq
Org
BA Lead owns glossary.
Progress
M1 drafted.
"""


def test_llm_sorter_parses_valid_json() -> None:
    client = MagicMock(spec=LlmClient)
    client.chat_json.return_value = {
        "pages": [
            {
                "page_id": "PG-GLOSS-AC",
                "bucket_id": "glossary",
                "title": "AC --- Acceptance Criterion",
                "abbrev": "AC",
                "expansion": "Acceptance Criterion",
                "disambiguation": "Khong dung AC = Alternate Course.",
                "body": "AC --- Acceptance Criterion",
            },
            {
                "page_id": "PG-RULE-DEMO",
                "bucket_id": "business_rule",
                "title": "Moi don can mot nguoi phe duyet",
                "body": "phe duyet don",
            },
        ]
    }
    sorter = LlmSorter(client=client)
    pages = sorter.sort(
        SAMPLE_MD,
        source_id="SRC-TEST001",
        namespace="project",
        project_id="PRJ-MES-01",
        owner="ba.lead",
        now="2026-08-20T00:00:00Z",
    )
    assert sorter.last_backend == "llm"
    assert len(pages) == 2
    assert pages[0].page_id == "PG-GLOSS-AC"
    assert pages[0].status == "draft"
    assert pages[0].source_ids == ["SRC-TEST001"]
    assert pages[1].bucket_id == "business_rule"


def test_llm_sorter_rejects_bad_bucket() -> None:
    client = MagicMock(spec=LlmClient)
    client.chat_json.return_value = {
        "pages": [
            {
                "page_id": "PG-BAD",
                "bucket_id": "not_a_bucket",
                "title": "x",
                "body": "y",
            }
        ]
    }
    sorter = LlmSorter(client=client)
    with pytest.raises(LlmError, match="zero valid"):
        sorter.sort(
            SAMPLE_MD,
            source_id="SRC-TEST001",
            namespace="project",
            project_id="PRJ-MES-01",
            owner="ba.lead",
            now="2026-08-20T00:00:00Z",
        )


def test_fallback_on_llm_error() -> None:
    primary = MagicMock()
    primary.sort.side_effect = LlmError("LLM gate status 500")
    primary.last_backend = "llm"
    fb = FallbackSorter(primary=primary, secondary=HeuristicSorter())
    pages = fb.sort(
        SAMPLE_MD,
        source_id="SRC-BRD-001",
        namespace="project",
        project_id="PRJ-MES-01",
        owner="ba.lead",
        now="2026-08-20T00:00:00Z",
    )
    assert fb.last_backend == "heuristic_fallback"
    assert any(p.page_id == "PG-GLOSS-AC" for p in pages)
    assert any(p.page_id == "PG-RULE-001" for p in pages)


def test_both_sorter_prefixes() -> None:
    from wiki.sort_llm import BothSorter

    llm = MagicMock()
    llm.sort.return_value = [
        __import__("wiki.models", fromlist=["WikiPage"]).WikiPage(
            page_id="PG-RULE-X",
            namespace="project",
            project_id="PRJ-MES-01",
            bucket_id="business_rule",
            title="rule from llm",
            status="draft",
            version="1.0.0",
            body="phe duyet",
            source_ids=["SRC-BRD-001"],
            owner="ba.lead",
            updated_at="2026-08-20T00:00:00Z",
        )
    ]
    llm.last_backend = "llm"
    both = BothSorter(heuristic=HeuristicSorter(), llm=llm)
    pages = both.sort(
        SAMPLE_MD,
        source_id="SRC-BRD-001",
        namespace="project",
        project_id="PRJ-MES-01",
        owner="ba.lead",
        now="2026-08-20T00:00:00Z",
    )
    assert both.last_backend == "both"
    assert any(p.page_id.startswith("H-") and "[heuristic]" in p.title for p in pages)
    assert any(p.page_id == "L-PG-RULE-X" and p.title.startswith("[llm]") for p in pages)


def test_llm_client_parses_fenced_json(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "choices": [
            {
                "message": {
                    "content": '```json\n{"pages":[{"page_id":"PG-A","bucket_id":"org","title":"t","body":"b"}]}\n```'
                }
            }
        ]
    }

    class FakeResponse:
        status_code = 200

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    client = LlmClient(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="Qwen3.5-27B-AWQ",
    )
    obj = client.chat_json([{"role": "user", "content": "hi"}])
    assert obj["pages"][0]["page_id"] == "PG-A"


def test_llm_client_empty_key() -> None:
    client = LlmClient(base_url="https://example.test/v1", api_key="", model="x")
    with pytest.raises(LlmError, match="empty"):
        client.chat_json([{"role": "user", "content": "hi"}])


@pytest.mark.skipif(
    __import__("os").environ.get("WIKI_LLM_LIVE") != "1",
    reason="set WIKI_LLM_LIVE=1 and WIKI_LLM_API_KEY for live gate smoke",
)
def test_live_gate_smoke() -> None:
    import os

    from wiki.llm_config import get_llm_settings, load_dotenv

    load_dotenv()
    get_llm_settings.cache_clear()
    settings = get_llm_settings()
    assert settings.api_key, "need WIKI_LLM_API_KEY"
    client = LlmClient(
        base_url=settings.base_url,
        api_key=settings.api_key,
        model=settings.model,
        timeout_s=settings.timeout_s,
    )
    obj = client.chat_json(
        [
            {
                "role": "user",
                "content": 'Return JSON: {"pages":[{"page_id":"PG-LIVE","bucket_id":"constraint","title":"t","body":"b"}]}',
            }
        ]
    )
    assert "pages" in obj
    assert isinstance(obj["pages"], list)

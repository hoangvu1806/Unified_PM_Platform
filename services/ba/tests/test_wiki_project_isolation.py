"""Project isolation: feature wiki sees own project pages + company, never other projects."""

from __future__ import annotations

import tempfile
from pathlib import Path

from factory_wiki.store import NAMESPACE_COMPANY, WikiStore


def _seed_isolation_corpus(store: WikiStore) -> None:
    store.seed_page(
        page_id="PAGE-A-PRIVATE",
        title="Project A private rule",
        body="SECRET_A only for PRJ-A spend policy.",
        project_id="PRJ-A",
        bucket_id="business_rule",
    )
    store.seed_page(
        page_id="PAGE-B-PRIVATE",
        title="Project B private rule",
        body="SECRET_B only for PRJ-B warehouse policy.",
        project_id="PRJ-B",
        bucket_id="business_rule",
    )
    store.seed_page(
        page_id="PAGE-COMPANY-SHARED",
        title="Company convention",
        body="SHARED_COMPANY naming rules for all projects.",
        project_id=None,
        namespace=NAMESPACE_COMPANY,
        bucket_id="convention",
    )
    store.seed_page(
        page_id="PAGE-A-DRAFT",
        title="Project A draft",
        body="Draft must stay invisible to agents.",
        project_id="PRJ-A",
        status="draft",
    )


def test_list_approved_includes_company_excludes_other_project():
    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        _seed_isolation_corpus(store)

        hits_a = store.list_approved(project_id="PRJ-A", agent_name="ba-agent")
        ids_a = {h["page_id"] for h in hits_a}
        assert ids_a == {"PAGE-A-PRIVATE", "PAGE-COMPANY-SHARED"}
        assert all(h["status"] == "approved" for h in hits_a)

        hits_b = store.list_approved(project_id="PRJ-B", agent_name="validation-agent")
        ids_b = {h["page_id"] for h in hits_b}
        assert ids_b == {"PAGE-B-PRIVATE", "PAGE-COMPANY-SHARED"}
        assert "PAGE-A-PRIVATE" not in ids_b


def test_search_never_leaks_other_project_or_drafts():
    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        _seed_isolation_corpus(store)

        hits = store.search("SECRET", project_id="PRJ-A", agent_name="ba-agent", limit=20)
        ids = {h["page_id"] for h in hits}
        assert "PAGE-A-PRIVATE" in ids
        assert "PAGE-B-PRIVATE" not in ids
        assert "PAGE-A-DRAFT" not in ids

        company = store.search("SHARED_COMPANY", project_id="PRJ-B", agent_name="ba-agent")
        assert any(h["page_id"] == "PAGE-COMPANY-SHARED" for h in company)


def test_fetch_project_and_company_scope():
    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        _seed_isolation_corpus(store)

        assert store.fetch("PAGE-A-PRIVATE", project_id="PRJ-A") is not None
        assert store.fetch("PAGE-A-PRIVATE", project_id="PRJ-B") is None
        assert store.fetch("PAGE-B-PRIVATE", project_id="PRJ-A") is None

        shared = store.fetch("PAGE-COMPANY-SHARED", project_id="PRJ-A")
        assert shared is not None
        assert shared["namespace"] == "company"
        shared_b = store.fetch("PAGE-COMPANY-SHARED", project_id="PRJ-B")
        assert shared_b is not None


def test_va_wiki_pull_respects_project_scope():
    from agents.sub_graph.validation_agent.logic import run_wiki_pull

    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        _seed_isolation_corpus(store)
        state = {
            "project_id": "PRJ-A",
            "_va_payload": {
                "project_id": "PRJ-A",
                "artifacts": {
                    "feature_definition": {
                        "goal": "Spend policy",
                        "actors": ["A", "B"],
                        "scope_in": ["x"],
                    },
                    "business_rules": [{"id": "BR-01", "statement": "Must approve"}],
                },
            },
        }
        evidence, _failed, _warnings = run_wiki_pull(state, store)
        ids = {e["page_id"] for e in evidence}
        assert "PAGE-A-PRIVATE" in ids
        assert "PAGE-COMPANY-SHARED" in ids
        assert "PAGE-B-PRIVATE" not in ids
        assert "PAGE-A-DRAFT" not in ids


def test_wiki_context_inject_respects_project_scope():
    from agents.sub_graph.shared.wiki_context import collect_approved_wiki_hits

    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp))
        _seed_isolation_corpus(store)
        hits = collect_approved_wiki_hits(
            {"project_id": "PRJ-B", "feature_title": "Warehouse", "artifacts": {}},
            store=store,
            limit=20,
        )
        ids = {h["page_id"] for h in hits}
        assert "PAGE-B-PRIVATE" in ids
        assert "PAGE-COMPANY-SHARED" in ids
        assert "PAGE-A-PRIVATE" not in ids

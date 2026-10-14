from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from wiki.models import Actor
from wiki.paths import MVP_ROOT
from wiki.service import WikiService
from wiki.sort import HeuristicSorter


@pytest.fixture(autouse=True)
def force_heuristic_sort(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIKI_SORT", "heuristic")
    monkeypatch.delenv("WIKI_LLM_API_KEY", raising=False)
    from wiki.llm_config import get_llm_settings

    get_llm_settings.cache_clear()


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    shutil.copytree(MVP_ROOT / "config", tmp_path / "config")
    return tmp_path


@pytest.fixture()
def svc(root: Path) -> WikiService:
    service = WikiService(root, sorter=HeuristicSorter())
    yield service
    service.close()


@pytest.fixture()
def human() -> Actor:
    return Actor(actor="ba.lead", actor_type="human", project_id="PRJ-MES-01")


@pytest.fixture()
def agent() -> Actor:
    return Actor(
        actor="ba-agent",
        actor_type="agent",
        agent_name="ba-agent",
        project_id="PRJ-MES-01",
        agent_run_id="run-1",
    )

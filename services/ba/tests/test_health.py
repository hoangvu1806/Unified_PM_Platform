"""Health is demo-ready when ADK + DB are up; LLM is diagnostic only."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import anyio

from server import health_check


def test_health_ok_when_llm_proxy_is_down():
    session = MagicMock()
    session.__enter__.return_value.execute.return_value = None
    session.__exit__.return_value = False

    async def _run():
        with (
            patch("server.get_runner", return_value=object()),
            patch("server.SessionLocal", return_value=session),
            patch("server._llm_endpoint_ready", new=AsyncMock(return_value=False)),
            patch(
                "server.resolve_llm_endpoint",
                return_value=MagicMock(
                    provider="company-gate",
                    api_base_url="https://llm-gate.imespro.ai/v1",
                ),
            ),
        ):
            return await health_check()

    response = anyio.run(_run)
    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["status"] == "ok"
    assert body["adk_ready"] is True
    assert body["database_ready"] is True
    assert body["llm_proxy_ready"] is False


def test_health_not_ready_when_database_is_down():
    session = MagicMock()
    session.__enter__.side_effect = RuntimeError("db down")

    async def _run():
        with (
            patch("server.get_runner", return_value=object()),
            patch("server.SessionLocal", return_value=session),
            patch("server._llm_endpoint_ready", new=AsyncMock(return_value=True)),
            patch(
                "server.resolve_llm_endpoint",
                return_value=MagicMock(
                    provider="company-gate",
                    api_base_url="https://llm-gate.imespro.ai/v1",
                ),
            ),
        ):
            return await health_check()

    response = anyio.run(_run)
    assert response.status_code == 503
    body = json.loads(response.body)
    assert body["status"] == "not_ready"
    assert body["database_ready"] is False

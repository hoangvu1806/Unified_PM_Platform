"""OpenAI-compatible client for ImesPro LLM Gate. Never logs the API key."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx


class LlmError(Exception):
    """Gate / parse failure. Message must not include secrets."""


class LlmClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise LlmError("WIKI_LLM_API_KEY is empty")

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        base_payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        content: str | None = None
        last_err: LlmError | None = None
        for with_format in (True, False):
            payload = dict(base_payload)
            if with_format:
                payload["response_format"] = {"type": "json_object"}
            try:
                content = self._post(url, headers, payload)
                break
            except LlmError as exc:
                last_err = exc
                continue
        if content is None:
            raise last_err or LlmError("LLM gate failed")

        return self._parse_json_object(content)

    def _post(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> str:
        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                res = client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LlmError(f"LLM gate timeout after {self.timeout_s}s") from exc
        except httpx.HTTPError as exc:
            raise LlmError(f"LLM gate HTTP error: {exc.__class__.__name__}") from exc

        if res.status_code >= 400:
            raise LlmError(f"LLM gate status {res.status_code}")

        try:
            data = res.json()
        except json.JSONDecodeError as exc:
            raise LlmError("LLM gate returned non-JSON") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmError("LLM gate response missing choices[0].message.content") from exc

        if not isinstance(content, str) or not content.strip():
            raise LlmError("LLM gate returned empty content")
        return content

    @staticmethod
    def _parse_json_object(content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
            text = re.sub(r"\s*```$", "", text)
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            match = re.search(r"\{.*\}", text, flags=re.S)
            if not match:
                raise LlmError("LLM content is not JSON") from exc
            try:
                obj = json.loads(match.group(0))
            except json.JSONDecodeError as exc2:
                raise LlmError("LLM content is not JSON") from exc2
        if not isinstance(obj, dict):
            raise LlmError("LLM JSON root must be an object")
        return obj

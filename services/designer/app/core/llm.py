import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any, TypeVar
from uuid import uuid4

from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel, ValidationError

from .config import Settings
from .errors import AppError
from .logger import log_agent_error

logger = logging.getLogger("designer_agent.llm")

ModelT = TypeVar("ModelT", bound=BaseModel)
LLM_TIMEOUT_SECONDS = 90
STRUCTURED_PARSER_VERSION = "2026-09-22.tool-loop"


def build_structured_content(
    prompt: str,
    schema_json: str,
    *,
    image_bytes: bytes | None = None,
    image_mime_type: str = "image/jpeg",
) -> types.Content:
    parts = [
        types.Part.from_text(
            text=(
                f"{prompt}\n\nJSON SCHEMA (authoritative):\n"
                f"{schema_json}\n\n"
                "Return exactly one JSON object matching this schema."
            )
        )
    ]
    if image_bytes:
        parts.append(types.Part.from_bytes(data=image_bytes, mime_type=image_mime_type))
    return types.Content(role="user", parts=parts)


def parse_structured_output(content: str, schema: type[ModelT]) -> ModelT:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().lower() in {"```", "```json"}:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        return schema.model_validate_json(text)
    except ValidationError as primary_error:
        log_agent_error(
            "llm_json_parse",
            f"Structured schema validation failed for {schema.__name__}",
            primary_error,
            {"content_preview": content[:300]},
        )
        raise AppError(
            "LLM_OUTPUT_INVALID",
            "The model returned invalid structured JSON",
            str(primary_error),
            502,
            retryable=True,
            action="Retry the run; the response did not match the requested structured schema.",
        ) from primary_error


class AdkProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._is_warmed: bool = False
        self._warming_lock: asyncio.Lock = asyncio.Lock()

    async def run_tools(
        self,
        *,
        prompt: str,
        tools: list[Any],
        before_model_callback: Any = None,
        max_turns: int = 0,
        message: types.Content | None = None,
        timeout_seconds: float | None = None,
        model: str | None = None,
        stop_when: Callable[[], bool] | None = None,
        progress_token: Callable[[], str] | None = None,
        continuation_message: str = "",
    ) -> str:
        """One conversation: tool results (including errors) stay in model context."""
        if not self.settings.api_key or not self.settings.base_url:
            raise AppError(
                "LLM_NOT_CONFIGURED",
                "Model connection is not configured",
                "Set API_KEY and BASE_URL before creating a design.",
                503,
            )

        last_tool_error = ""
        repeated_tool_error = 0

        async def tool_error(tool: Any, args: dict[str, Any], tool_context: Any, error: Exception) -> dict[str, Any]:
            nonlocal last_tool_error, repeated_tool_error
            signature = json.dumps([getattr(tool, "name", str(tool)), args, str(error)], sort_keys=True, default=str)
            repeated_tool_error = repeated_tool_error + 1 if signature == last_tool_error else 1
            last_tool_error = signature
            if repeated_tool_error >= 3:
                raise AppError(
                    "AGENT_STALLED", "Designer repeated an invalid tool call", str(error), 502, True
                )
            return {"ok": False, "error": str(error), "next_step": "Correct the tool arguments and retry."}

        agent = LlmAgent(
            name="page_designer",
            model=LiteLlm(
                model=model or self.settings.llm_model,
                api_key=self.settings.api_key,
                api_base=self.settings.cleaned_base_url,
            ),
            # Markdown/JSX is already rendered; bypass ADK's {state} expansion.
            instruction=lambda _context: prompt,
            tools=tools,
            before_model_callback=before_model_callback,
            on_tool_error_callback=tool_error,
        )
        runner = InMemoryRunner(agent=agent, app_name="page_designer")
        try:
            session = await runner.session_service.create_session(
                app_name="page_designer", user_id="designer", session_id=str(uuid4())
            )
            reply = ""
            next_message = message or types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text=(
                            "Work in a private Plan → Reason → Act → Observe → Reflect loop. "
                            "Use tool results as truth, correct errors in this conversation, "
                            "and finish only after reflecting on the latest inspection."
                        )
                    )
                ],
            )
            async with asyncio.timeout(timeout_seconds):
                stalled_at: str | None = None
                while True:
                    response_error = None
                    async for event in runner.run_async(
                        user_id="designer",
                        session_id=session.id,
                        new_message=next_message,
                        run_config=RunConfig(max_llm_calls=max_turns),
                    ):
                        if event.error_code:
                            response_error = AppError(
                                "LLM_RESPONSE_FAILED",
                                "Model response failed",
                                f"{event.error_code}: {event.error_message or ''}",
                                502,
                                True,
                            )
                        elif event.content is not None and not event.content.parts:
                            response_error = AppError(
                                "LLM_EMPTY_RESPONSE",
                                "Model returned an empty response",
                                f"Endpoint returned no text or tool calls ({event.finish_reason}). Check the API protocol.",
                                502,
                                True,
                            )
                        if event.is_final_response() and event.content:
                            reply = "".join(part.text or "" for part in event.content.parts or [])
                    if response_error:
                        raise response_error
                    if stop_when is None or stop_when():
                        return reply
                    current_progress = progress_token() if progress_token else ""
                    if progress_token and stalled_at == current_progress:
                        raise AppError(
                            "AGENT_STALLED",
                            "Designer stopped without changing the canvas",
                            (
                                "The model returned a final response twice at the same canvas state instead of "
                                f"calling a tool. Last response: {reply[:800]}"
                            ),
                            502,
                            True,
                            action="Retry this stage; saved canvas progress will be reused.",
                        )
                    stalled_at = current_progress
                    next_message = types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(
                                text=continuation_message
                                or (
                                    "You returned final text before the task's completion gate passed. "
                                    "Continue using the available tools now. Do not narrate or emit pseudo-code."
                                )
                            )
                        ],
                    )
        finally:
            await runner.close()

    async def prewarm(self) -> None:
        """Pre-warm LLM model connection, TLS handshake and DNS resolution in background."""
        if self._is_warmed or not self.settings.api_key or not self.settings.base_url:
            return
        async with self._warming_lock:
            if self._is_warmed:
                return
            logger.info("Pre-warming LLM connection to %s (%s)...", self.settings.base_url, self.settings.llm_model)
            try:
                async with asyncio.timeout(15):
                    await self.text(prompt="ping", max_attempts=1)
                self._is_warmed = True
                logger.info("LLM connection pre-warmed successfully!")
            except Exception as exc:
                logger.warning("LLM pre-warm skipped or failed (non-critical): %s", exc)

    async def structured(
        self,
        *,
        prompt: str,
        schema: type[ModelT],
        image_bytes: bytes | None = None,
        image_mime_type: str = "image/jpeg",
        max_attempts: int = 3,
        model: str | None = None,
    ) -> ModelT:
        correction = ""
        last_error: Exception | None = None
        for attempt in range(max_attempts):
            content = ""
            try:
                content = await self.run_tools(
                    prompt="Return exactly one JSON object matching the supplied schema.",
                    tools=[],
                    message=build_structured_content(
                        prompt + correction,
                        json.dumps(schema.model_json_schema(), ensure_ascii=False),
                        image_bytes=image_bytes,
                        image_mime_type=image_mime_type,
                    ),
                    max_turns=1,
                    timeout_seconds=LLM_TIMEOUT_SECONDS,
                    model=model,
                )
                return parse_structured_output(content, schema)
            except Exception as error:
                if isinstance(error, AppError) and error.code == "LLM_NOT_CONFIGURED":
                    raise
                last_error = error
                log_agent_error("llm_structured", f"Attempt {attempt + 1}/{max_attempts}", error)
                if content:
                    correction = (
                        f"\nPrevious response:\n{content}\nValidation error:\n{error}"
                        "\nCorrect this response. Preserve the requested design and all content."
                    )
                if attempt + 1 < max_attempts:
                    await asyncio.sleep(1)
        raise AppError(
            "LLM_OUTPUT_INVALID", "Model could not produce valid JSON", str(last_error), 502, True
        ) from last_error

    async def text(self, *, prompt: str, max_attempts: int = 3) -> str:
        last_error: Exception | None = None
        for attempt in range(max_attempts):
            try:
                content = await self.run_tools(
                    prompt="Follow the user's request.",
                    tools=[],
                    max_turns=1,
                    message=types.Content(role="user", parts=[types.Part.from_text(text=prompt)]),
                    timeout_seconds=LLM_TIMEOUT_SECONDS,
                )
                if not content.strip():
                    raise ValueError("Model returned no text")
                self._is_warmed = True
                return content
            except Exception as error:
                if isinstance(error, AppError) and error.code == "LLM_NOT_CONFIGURED":
                    raise
                last_error = error
                if attempt + 1 < max_attempts:
                    await asyncio.sleep(1)
        raise AppError("LLM_REQUEST_FAILED", "Model request failed", str(last_error), 502, True) from last_error

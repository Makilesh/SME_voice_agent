"""Gemini LLM handler — streaming generation with per-task model routing.

Upgraded from voice_engine_MVP's multi-provider llm_handler to target Gemini
via the google-genai SDK. Everything streams token deltas so the overlay can
render words as they arrive (perceived-latency win).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from google import genai
from google.genai import types

from backend.config import get_settings
from backend.core.models import GenConfig, Task, config_for

logger = logging.getLogger(__name__)


class LLMHandler:
    def __init__(self) -> None:
        s = get_settings()
        if not s.has_gemini:
            raise RuntimeError("GEMINI_API_KEY is not set — cannot start LLM handler.")
        self._client = genai.Client(api_key=s.gemini_api_key)

    def _mk_config(self, cfg: GenConfig, system_instruction: str | None) -> types.GenerateContentConfig:
        kwargs: dict = dict(
            temperature=cfg.temperature,
            max_output_tokens=cfg.max_output_tokens,
        )
        if system_instruction:
            kwargs["system_instruction"] = system_instruction
        # Thinking budget: only pass when the SDK/model supports it; guard softly.
        try:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=cfg.thinking_budget)
        except Exception:  # older SDaK / model without thinking support
            pass
        return types.GenerateContentConfig(**kwargs)

    async def stream(
        self,
        task: Task,
        prompt: str,
        *,
        system_instruction: str | None = None,
    ) -> AsyncIterator[str]:
        """Yield text deltas for a task. Runs the blocking SDK call off-thread."""
        cfg = config_for(task)
        gen_config = self._mk_config(cfg, system_instruction)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        def _produce() -> None:
            try:
                stream = self._client.models.generate_content_stream(
                    model=cfg.model, contents=prompt, config=gen_config
                )
                for chunk in stream:
                    text = getattr(chunk, "text", None)
                    if text:
                        loop.call_soon_threadsafe(queue.put_nowait, text)
            except Exception as e:  # surface errors to the stream consumer
                logger.error("LLM stream error (%s): %s", cfg.model, e)
                loop.call_soon_threadsafe(queue.put_nowait, f"\n[error: {e}]")
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        loop.run_in_executor(None, _produce)
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    async def complete(
        self, task: Task, prompt: str, *, system_instruction: str | None = None
    ) -> str:
        """Non-streaming convenience wrapper (e.g. intent classification)."""
        parts = [chunk async for chunk in self.stream(task, prompt, system_instruction=system_instruction)]
        return "".join(parts).strip()

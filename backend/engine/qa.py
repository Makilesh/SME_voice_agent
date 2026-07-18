"""On-demand Q&A: user asks (typed / hotkey), grounded in transcript + docs.

Default uses the deep PRO model; ``fast=True`` routes to FLASH for speed.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from backend.core.models import Task
from backend.core.session import MeetingSession
from backend.rag.pipeline import RAGPipeline
from backend.voice_engine.llm_handler import LLMHandler

_SYSTEM = (
    "You are the user's private meeting assistant. Answer their question using the "
    "meeting transcript and reference material when relevant, otherwise your own "
    "knowledge. Be concise and directly useful."
)


class QAEngine:
    def __init__(self, llm: LLMHandler, rag: RAGPipeline) -> None:
        self._llm = llm
        self._rag = rag

    async def ask(
        self, session: MeetingSession, question: str, fast: bool = False
    ) -> AsyncIterator[str]:
        rag_ctx = self._rag.context_block(question, k=5)
        parts = []
        if rag_ctx:
            parts.append(f"[Reference material]\n{rag_ctx}")
        transcript = session.recent_text(max_chars=4000)
        if transcript:
            parts.append(f"[Meeting transcript]\n{transcript}")
        parts.append(f"[User question]\n{question}")
        prompt = "\n\n".join(parts)
        task = Task.QA_FAST if fast else Task.QA
        async for delta in self._llm.stream(task, prompt, system_instruction=_SYSTEM):
            yield delta

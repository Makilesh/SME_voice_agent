"""Copilot: turn a detected 'them' question into an on-screen suggested answer.

Latency strategy (priority #1):
  1. Retrieve RAG context (local, fast) + rolling transcript.
  2. Stream a FLASH "instant draft" so words hit the overlay in ~1 s.
  3. Stream a PRO "refine" pass that replaces the draft with a sharper answer.

Both stages stream token deltas. The orchestrator forwards them to the overlay
as ``copilot.draft`` / ``copilot.final`` events with the same card id.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from backend.core.models import Task
from backend.core.session import MeetingSession
from backend.rag.pipeline import RAGPipeline
from backend.voice_engine.llm_handler import LLMHandler

_SYSTEM = (
    "You are a real-time meeting copilot whispering to ONE person during a live "
    "call. The other party just asked a question. Give that person a crisp, "
    "confident answer they can say out loud. Be direct and specific. No preamble, "
    "no 'as an AI', no restating the question. Prefer 2-5 short sentences or tight "
    "bullets. Use the provided context and meeting transcript when relevant."
)


@dataclass
class CopilotEvent:
    stage: str   # "draft" | "final"
    delta: str


def _build_prompt(session: MeetingSession, question: str, rag_ctx: str) -> str:
    parts = []
    if session.context_note:
        parts.append(f"[Meeting context] {session.context_note}")
    if session.glossary:
        parts.append(f"[Names/terms] {session.glossary}")
    if rag_ctx:
        parts.append(f"[Reference material]\n{rag_ctx}")
    transcript = session.recent_text(max_chars=2500)
    if transcript:
        parts.append(f"[Recent transcript]\n{transcript}")
    parts.append(f"[Question from the other party]\n{question}")
    parts.append("[Your suggested answer]")
    return "\n\n".join(parts)


class CopilotEngine:
    def __init__(self, llm: LLMHandler, rag: RAGPipeline) -> None:
        self._llm = llm
        self._rag = rag

    async def answer(self, session: MeetingSession, question: str) -> AsyncIterator[CopilotEvent]:
        rag_ctx = self._rag.context_block(question, k=4)
        prompt = _build_prompt(session, question, rag_ctx)

        # Stage 1 — instant draft (FLASH, no thinking).
        async for delta in self._llm.stream(Task.COPILOT_DRAFT, prompt, system_instruction=_SYSTEM):
            yield CopilotEvent("draft", delta)

        # Stage 2 — refine (PRO). Overlay swaps the card content on first 'final' delta.
        async for delta in self._llm.stream(Task.COPILOT_REFINE, prompt, system_instruction=_SYSTEM):
            yield CopilotEvent("final", delta)

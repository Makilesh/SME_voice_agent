"""Meeting orchestrator: wires capture → STT → turn-detect → copilot / notes.

Owns one ``MeetingSession`` and the audio + STT engines. Emits UI events through
an async callback (``emit``) that the FastAPI layer forwards to the overlay over
WebSocket. This is the text-only analogue of voice_engine_MVP's duplex loop —
there is no TTS in the meeting hot path.

Event shapes (all JSON):
  {"type":"transcript","speaker":"them|you","text":..,"final":bool}
  {"type":"copilot","card_id":..,"stage":"start|draft|final|done","delta":..}
  {"type":"notes","summary":..,"decisions":[..],"action_items":[..]}
  {"type":"status","text":..}
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from backend.audio.capture import DualChannelCapture
from backend.config import get_settings
from backend.core.session import MeetingSession
from backend.engine import turn_detector
from backend.engine.copilot import CopilotEngine
from backend.engine.notes import NotesEngine
from backend.engine.qa import QAEngine
from backend.rag.pipeline import RAGPipeline
from backend.voice_engine.llm_handler import LLMHandler
from backend.voice_engine.stt_handler import DualChannelSTT

logger = logging.getLogger(__name__)

Emit = Callable[[dict], Awaitable[None]]

# While the user has spoken within this window, suppress copilot (they're talking).
_YOU_ACTIVE_WINDOW = 2.0
# Re-summarize every N committed 'them/you' finals.
_NOTES_EVERY = 6


class Orchestrator:
    def __init__(self, emit: Emit) -> None:
        self._emit = emit
        self._loop = asyncio.get_event_loop()
        self._settings = get_settings()

        self.session = MeetingSession(session_id=uuid.uuid4().hex[:12])
        self._llm = LLMHandler()
        self._rag = RAGPipeline()
        self._copilot = CopilotEngine(self._llm, self._rag)
        self._notes = NotesEngine(self._llm)
        self._qa = QAEngine(self._llm, self._rag)

        self._stt: DualChannelSTT | None = None
        self._capture: DualChannelCapture | None = None

        self._last_you_ts = 0.0
        self._final_count = 0
        self._auto_copilot = True
        self._active_copilot: asyncio.Task | None = None

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self, glossary: str = "", context_note: str = "") -> None:
        self.session.glossary = glossary
        self.session.context_note = context_note
        self._stt = DualChannelSTT(
            mode=self._settings.stt_mode,
            on_partial=self._on_partial,     # called from STT threads
            on_final=self._on_final,
            glossary=glossary,
        )
        self._stt.start()
        self._capture = DualChannelCapture(
            on_them_pcm=self._stt.feed_them,
            on_you_pcm=self._stt.feed_you,
        )
        self._capture.start()
        logger.info("▶ Orchestrator started (session %s)", self.session.session_id)

    def stop(self) -> None:
        if self._capture:
            self._capture.stop()
        if self._stt:
            self._stt.stop()
        logger.info("⏹ Orchestrator stopped")

    # ── STT thread callbacks (bridge to the event loop) ──────────────────
    def _on_partial(self, channel: str, text: str) -> None:
        if channel == "you":
            self._last_you_ts = time.time()
        self._schedule(self._emit({
            "type": "transcript", "speaker": channel, "text": text, "final": False,
        }))

    def _on_final(self, channel: str, text: str) -> None:
        text = turn_detector.normalize(text)
        if not text:
            return
        if channel == "you":
            self._last_you_ts = time.time()
        self.session.add(channel, text, final=True)
        self._final_count += 1
        self._schedule(self._emit({
            "type": "transcript", "speaker": channel, "text": text, "final": True,
        }))

        if channel == "them" and self._auto_copilot and self._should_answer(text):
            self._schedule(self._run_copilot(text))

        if self._final_count % _NOTES_EVERY == 0:
            self._schedule(self._run_notes())

    def _should_answer(self, text: str) -> bool:
        # Don't answer if the user is currently speaking / just spoke.
        if time.time() - self._last_you_ts < _YOU_ACTIVE_WINDOW:
            return False
        return turn_detector.looks_like_question(text)

    def _schedule(self, coro: Awaitable) -> None:
        """Run a coroutine on the main loop from an STT worker thread."""
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    # ── generation tasks ─────────────────────────────────────────────────
    async def _run_copilot(self, question: str) -> None:
        # Cancel any in-flight suggestion — the newest question wins.
        if self._active_copilot and not self._active_copilot.done():
            self._active_copilot.cancel()
        self._active_copilot = asyncio.current_task()

        card_id = uuid.uuid4().hex[:8]
        await self._emit({"type": "copilot", "card_id": card_id, "stage": "start",
                          "question": question})
        try:
            async for ev in self._copilot.answer(self.session, question):
                await self._emit({"type": "copilot", "card_id": card_id,
                                  "stage": ev.stage, "delta": ev.delta})
            await self._emit({"type": "copilot", "card_id": card_id, "stage": "done"})
        except asyncio.CancelledError:
            await self._emit({"type": "copilot", "card_id": card_id, "stage": "cancelled"})
            raise

    async def _run_notes(self) -> None:
        try:
            data = await self._notes.update(self.session)
            await self._emit({"type": "notes", **data})
        except Exception as e:
            logger.debug("notes update failed: %s", e)

    # ── external commands (from the overlay) ─────────────────────────────
    async def ask(self, question: str, fast: bool = False) -> None:
        card_id = uuid.uuid4().hex[:8]
        await self._emit({"type": "qa", "card_id": card_id, "stage": "start",
                          "question": question})
        async for delta in self._qa.ask(self.session, question, fast=fast):
            await self._emit({"type": "qa", "card_id": card_id, "stage": "delta",
                              "delta": delta})
        await self._emit({"type": "qa", "card_id": card_id, "stage": "done"})

    async def force_copilot(self) -> None:
        q = self.session.last_them_question() or self.session.recent_text(400)
        if q:
            await self._run_copilot(q)

    def set_auto_copilot(self, enabled: bool) -> None:
        self._auto_copilot = enabled

    def ingest_doc(self, path: str) -> int:
        return self._rag.ingest_file(path)

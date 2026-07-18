"""Rolling meeting notes: summary, decisions, action items (FLASH, throughput).

Triggered periodically by the orchestrator (every N final utterances or T
seconds). Produces a compact JSON-ish block the overlay renders in the notes
panel. Not latency-critical.
"""
from __future__ import annotations

import json
import logging

from backend.core.models import Task
from backend.core.session import MeetingSession
from backend.voice_engine.llm_handler import LLMHandler

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You maintain live notes for a meeting. Given the running transcript, output "
    "STRICT JSON with keys: summary (string, <=4 sentences), decisions (array of "
    "strings), action_items (array of strings, each starting with an owner if "
    "known). No prose outside the JSON."
)


class NotesEngine:
    def __init__(self, llm: LLMHandler) -> None:
        self._llm = llm

    async def update(self, session: MeetingSession) -> dict:
        transcript = session.recent_text(max_chars=6000)
        if not transcript:
            return {"summary": "", "decisions": [], "action_items": []}
        prompt = f"[Transcript]\n{transcript}\n\n[Output JSON]"
        raw = await self._llm.complete(Task.NOTES, prompt, system_instruction=_SYSTEM)
        data = _safe_json(raw)
        session.notes_summary = data.get("summary", "")
        session.action_items = data.get("action_items", [])
        return data


def _safe_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{"):]
    try:
        start, end = raw.find("{"), raw.rfind("}")
        return json.loads(raw[start : end + 1]) if start >= 0 else {}
    except Exception as e:
        logger.debug("notes JSON parse failed: %s", e)
        return {"summary": raw[:400], "decisions": [], "action_items": []}

"""Per-meeting state: rolling transcript, notes, and session context.

Kept intentionally simple and in-memory (single-user desktop app). One
``MeetingSession`` per active meeting; the orchestrator owns the instance.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class Utterance:
    speaker: str          # "you" | "them"
    text: str
    ts: float = field(default_factory=time.time)
    final: bool = True


@dataclass
class MeetingSession:
    session_id: str
    started_at: float = field(default_factory=time.time)

    # Session priming — biases both STT and answers.
    glossary: str = ""            # names, company, product terms
    context_note: str = ""        # free text: "job interview for X role", etc.

    transcript: list[Utterance] = field(default_factory=list)
    notes_summary: str = ""
    action_items: list[str] = field(default_factory=list)

    _lock: Lock = field(default_factory=Lock, repr=False)

    def add(self, speaker: str, text: str, final: bool = True) -> Utterance:
        u = Utterance(speaker=speaker, text=text.strip(), final=final)
        with self._lock:
            self.transcript.append(u)
        return u

    def recent_text(self, max_chars: int = 4000) -> str:
        """Rolling transcript window (most recent), labeled by speaker."""
        with self._lock:
            lines = [f"{u.speaker.upper()}: {u.text}" for u in self.transcript if u.text]
        out, total = [], 0
        for line in reversed(lines):
            total += len(line)
            if total > max_chars:
                break
            out.append(line)
        return "\n".join(reversed(out))

    def last_them_question(self) -> str:
        with self._lock:
            for u in reversed(self.transcript):
                if u.speaker == "them" and u.final and u.text:
                    return u.text
        return ""

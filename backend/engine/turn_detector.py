"""Decide when a 'them' utterance warrants a copilot suggestion.

Cheap, synchronous heuristics first (punctuation / question words / length).
The orchestrator may optionally escalate ambiguous cases to a FLASH intent
classifier, but the heuristic alone covers most real questions with near-zero
latency.
"""
from __future__ import annotations

import re

_QUESTION_WORDS = (
    "what", "why", "how", "when", "where", "who", "which", "whose", "whom",
    "can you", "could you", "would you", "do you", "did you", "are you",
    "have you", "tell me", "walk me", "explain", "describe", "give me",
    "what's", "how's", "any thoughts", "your take", "thoughts on",
)

_TOO_SHORT = 3  # words


def looks_like_question(text: str) -> bool:
    t = text.strip().lower()
    if not t or len(t.split()) < _TOO_SHORT:
        return False
    if t.endswith("?"):
        return True
    if any(t.startswith(w) or f" {w} " in f" {t} " for w in _QUESTION_WORDS):
        return True
    # Imperative asks ("tell me about…", "give me…") handled above; otherwise no.
    return False


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

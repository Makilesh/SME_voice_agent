"""Model routing: one place to swap Gemini model IDs and pick per-task tiers.

Priority #1 is latency for the copilot suggestion, so the copilot uses a
two-stage strategy: a fast FLASH "instant draft" streamed immediately, then a
PRO "refine" pass for depth/accuracy. Notes/summary use FLASH (throughput).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.config import get_settings


class Task(str, Enum):
    COPILOT_DRAFT = "copilot_draft"    # instant, latency-critical
    COPILOT_REFINE = "copilot_refine"  # accuracy pass
    NOTES = "notes"                    # rolling summary / action items
    QA = "qa"                          # on-demand, default deep
    QA_FAST = "qa_fast"                # on-demand, fast mode
    INTENT = "intent"                  # is-this-a-question classifier


@dataclass(frozen=True)
class GenConfig:
    model: str
    temperature: float
    max_output_tokens: int
    # Gemini "thinking budget": lower = faster first token. 0 disables thinking.
    thinking_budget: int


def config_for(task: Task) -> GenConfig:
    s = get_settings()
    pro, flash = s.model_pro, s.model_flash
    table = {
        Task.COPILOT_DRAFT:  GenConfig(flash, 0.4, 220, thinking_budget=0),
        Task.COPILOT_REFINE: GenConfig(pro,   0.5, 512, thinking_budget=512),
        Task.NOTES:          GenConfig(flash, 0.3, 512, thinking_budget=0),
        Task.QA:             GenConfig(pro,   0.5, 900, thinking_budget=1024),
        Task.QA_FAST:        GenConfig(flash, 0.5, 700, thinking_budget=0),
        Task.INTENT:         GenConfig(flash, 0.0, 8,   thinking_budget=0),
    }
    return table[task]

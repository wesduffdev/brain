"""MemorySummaryService — turns the being's memory log into a readable summary
(card v9, BRIEF §17).

The companion to `NarrationService`: where narration describes the being's
present state, this looks back over what it has lived through. Given the memory
snapshots from `Simulation.memories()` (and, optionally, the raw interaction
log), it builds a factual prompt and asks the language model to summarise. Like
all of the language layer it is read-only and non-authoritative — it reads plain
snapshot dicts and mutates neither them nor the simulation; the summary is a
description laid on top, never an input back into the being's psychology.
"""
from __future__ import annotations

from typing import Mapping, Optional, Sequence

from app.ports.language_model import LanguageModelPort


class MemorySummaryService:
    def __init__(self, model: LanguageModelPort):
        self._model = model

    def summarize(
        self,
        memories: Sequence[Mapping],
        *,
        interactions: Optional[Sequence[Mapping]] = None,
    ) -> str:
        """Return a readable summary of the being's ``memories`` (and optional
        ``interactions``). Read-only: reads the snapshots, mutates nothing."""
        return self._model.complete(self._prompt(memories, interactions or [])).strip()

    @staticmethod
    def _prompt(
        memories: Sequence[Mapping], interactions: Sequence[Mapping]
    ) -> str:
        lines = [
            "Summarise, in a few plain sentences, what the being remembers of "
            "its experiences so far. Use only these records; do not invent "
            "events.",
            f"Memories kept: {len(memories)}",
        ]
        for memory in memories:
            outcome = ", ".join(memory.get("observedOutcome", []) or []) or "nothing"
            lines.append(
                f"- {memory.get('action')} {memory.get('objectId')} -> {outcome}"
            )
        if interactions:
            lines.append(f"Total interactions: {len(interactions)}")
        return "\n".join(lines)

"""MemorySummaryService — turns the being's memory log into a readable summary
(card v9, BRIEF §17; wired to a surface by S1, ADR 0032).

The companion to `NarrationService`: where narration describes the being's
present state, this looks back over what it has lived through. Given the memory
snapshots from `Simulation.memories()` (and, optionally, the raw interaction
log), it serializes each into a compact, machine-readable FACT-LINE and asks the
language model to render them. Like all of the language layer it is read-only and
non-authoritative — it reads plain snapshot dicts and mutates neither them nor
the simulation; the summary is a description laid on top, never an input back
into the being's psychology.

The fact-line is the grounding contract (ADR 0032). Each memory becomes::

    - action=push object=obj_red_ball perceived=round,red observed=rolls felt=calm salience=0.00

carrying the action, the object AS PERCEIVED (its properties — never a developer
label, ADR 0002), the observed outcome, the emotion the moment left, and its
salience. The deterministic template narrator parses these and renders prose from
them alone; a real model reads the same lines as facts under the "use only these
records; do not invent" instruction. Either way the being can only say what it
has lived.
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
            "Summarise, in a few plain first-person sentences, what the being "
            "remembers of its experiences so far. Use only these records; do not "
            "invent events, objects, outcomes, or feelings.",
            f"Memories kept: {len(memories)}",
        ]
        lines.extend(MemorySummaryService._fact_line(memory) for memory in memories)
        if interactions:
            lines.append(f"Total interactions: {len(interactions)}")
        return "\n".join(lines)

    @staticmethod
    def _fact_line(memory: Mapping) -> str:
        """One memory as a fact-line the narrator parses (ADR 0032). Object
        properties/outcomes are single-word vocabulary tokens, so a comma-joined
        list stays whitespace-free and unambiguous to split back apart."""

        def _csv(key: str) -> str:
            return ",".join(str(item) for item in (memory.get(key) or []))

        parts = [
            f"action={memory.get('action', '')}",
            f"object={memory.get('objectId', '')}",
            f"perceived={_csv('perceivedProperties')}",
            f"observed={_csv('observedOutcome')}",
            f"felt={memory.get('emotionAfter', '')}",
            f"salience={float(memory.get('priority', 0.0) or 0.0):.2f}",
        ]
        return "- " + " ".join(parts)

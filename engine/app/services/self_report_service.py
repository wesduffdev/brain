"""SelfReportService — the being tells you what it has done, grounded in its own
memories (S1, ADR 0032).

This is the surface behind `POST /ask`. Handed the being's read-back snapshots —
its `memories()` and its `state()`, plain dicts it never mutates — it SELECTS the
relevant slice of experience for a question and hands it to the narrator through
`MemorySummaryService` (the "what have you done" half) or `NarrationService` (the
present-tense fallback for a being with nothing to look back on). It orchestrates;
the narrator renders. Because it only ever reads snapshots and the narrator only
ever reads the facts it is given, the whole path sits on top of the sim and
controls nothing (ADR 0022): asking changes neither the being nor its log.

Selection is config-driven (`SelfReportPolicy`, `config/language.yaml`): a "what
have you done recently?" report covers the most-recent `recent_count` memories,
in the order they were lived, so it reads as a little chronological story. Every
word traces to a logged memory — the being can only say what it has lived, named
by what it PERCEIVED (never a developer label, ADR 0002). Subject queries ("how
do you feel about hot things?") and salience-ranked recall are later slices (S3);
this slice answers every question with the recent-experience report, or the
present when there is no experience yet.
"""
from __future__ import annotations

from typing import List, Mapping, Sequence

from app.services.memory_summary_service import MemorySummaryService
from app.services.narration_service import NarrationService


class SelfReportService:
    def __init__(
        self,
        summary: MemorySummaryService,
        narration: NarrationService,
        *,
        recent_count: int = 5,
    ) -> None:
        self._summary = summary
        self._narration = narration
        self._recent_count = int(recent_count)

    def report(
        self,
        query: str,
        *,
        memories: Sequence[Mapping],
        state: Mapping,
    ) -> str:
        """A grounded self-report for ``query``. Built only from ``memories`` when
        the being has any (the recent slice), else from the present ``state``.
        ``query`` is the person's question; S1 answers every question with the
        recent-experience report — subject routing is a later slice (S3)."""
        selected = self._recent(memories)
        if selected:
            return self._summary.summarize(selected)
        return self._narration.narrate(state)

    def _recent(self, memories: Sequence[Mapping]) -> List[Mapping]:
        """The most-recent `recent_count` memories, oldest-of-those first (so the
        report reads chronologically). A non-positive count means "all of them"."""
        memories = list(memories)
        if self._recent_count <= 0:
            return memories
        return memories[-self._recent_count:]

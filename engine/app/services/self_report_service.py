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

from typing import List, Mapping, Optional, Sequence

from app.services.memory_summary_service import MemorySummaryService
from app.services.narration_service import NarrationService
from app.services.subject_report_service import SubjectReportService


class SelfReportService:
    def __init__(
        self,
        summary: MemorySummaryService,
        narration: NarrationService,
        *,
        recent_count: int = 5,
        subject: Optional[SubjectReportService] = None,
    ) -> None:
        self._summary = summary
        self._narration = narration
        self._recent_count = int(recent_count)
        # The S3 subject path; when absent, `report` is byte-identical to S1 —
        # every question answered with the recent-experience report.
        self._subject = subject

    def report(
        self,
        query: str,
        *,
        memories: Sequence[Mapping],
        state: Mapping,
        concepts: Sequence[Mapping] = (),
        beliefs: Sequence[Mapping] = (),
        explanations: Sequence[Mapping] = (),
    ) -> str:
        """A grounded self-report for ``query``. A SUBJECT query — "what do you know
        / how do you feel about X?" (S3) — is answered from the being's learned
        ``concepts`` / ``beliefs`` / ``explanations`` and the emotions its
        ``memories`` recorded; every other question is the recent-experience report
        built from ``memories`` (the recent slice), or, when the being has lived
        nothing, the present ``state``. Read-only throughout (ADR 0022)."""
        if self._subject is not None:
            subject = self._subject.subject_of(query)
            if subject is not None:
                return self._subject.report(
                    subject,
                    concepts=concepts,
                    beliefs=beliefs,
                    explanations=explanations,
                    memories=memories,
                )
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

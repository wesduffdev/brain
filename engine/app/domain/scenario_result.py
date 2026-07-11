"""Verdict value objects for the scenario system (cards V10a, v10).

A scenario seeds the being, runs it N ticks, and reads its learning back off the
public surface: the headline metric (the target concept's confidence, before vs
after) and any developmental MILESTONE stages it crossed. `ScenarioResult` is
that reading plus the pass/fail judgment on the headline metric; `RegressionOutcome`
is the wider regression verdict `RegressionEvaluationService` produces — the run's
result plus every expectation (metric floor and milestone stages) that went
unmet. They are plain readings, not stores: deleting them would push these fields
and rules back into the runner, the evaluator, and their callers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple

from app.domain.milestone import MilestoneProgress


@dataclass(frozen=True)
class ScenarioResult:
    scenario: str
    metric: str
    ticks: int
    before: float
    after: float
    threshold: float
    # The developmental milestones this run exercised and how far each moved
    # (card v10); empty for a headline-metric-only scenario (card V10a shape).
    milestones: Tuple[MilestoneProgress, ...] = field(default_factory=tuple)

    @property
    def delta(self) -> float:
        """How far the headline learning metric moved over the run."""
        return self.after - self.before

    @property
    def passed(self) -> bool:
        """The run demonstrated learning: the headline metric rose to at least the
        scenario's configured floor."""
        return self.delta >= self.threshold

    def milestone(self, name: str) -> MilestoneProgress:
        """The stage progression this run produced for a named milestone. Fail-loud
        if the scenario did not track it, so a test cannot silently assert on a
        milestone the run never measured."""
        for progress in self.milestones:
            if progress.milestone == name:
                return progress
        raise ValueError(
            f"scenario {self.scenario!r} tracked no milestone {name!r}; "
            f"tracked: {[p.milestone for p in self.milestones]}"
        )

    def snapshot(self) -> Dict:
        """A plain, serializable view of the run's verdict and milestone moves."""
        return {
            "scenario": self.scenario,
            "metric": self.metric,
            "ticks": self.ticks,
            "before": self.before,
            "after": self.after,
            "delta": self.delta,
            "threshold": self.threshold,
            "passed": self.passed,
            "milestones": [progress.snapshot() for progress in self.milestones],
        }

    def summary(self) -> str:
        """A one-line, human-readable before/after report — the documented runner
        output ("watch it learn"), with any milestone stage transitions appended."""
        verdict = "LEARNED" if self.passed else "NO LEARNING"
        line = (
            f"[{verdict}] {self.scenario}: {self.metric} "
            f"{self.before:.3f} -> {self.after:.3f} "
            f"(delta {self.delta:+.3f}, needs >= {self.threshold:.3f}) "
            f"over {self.ticks} ticks"
        )
        if self.milestones:
            line += " | " + "; ".join(p.summary() for p in self.milestones)
        return line


@dataclass(frozen=True)
class RegressionOutcome:
    """The regression verdict for one scenario run: the run's result plus every
    unmet expectation. `passed` is simply "nothing went unmet" — the scenario
    doubles as a regression test that FAILS the moment expected learning is
    absent."""

    scenario: str
    result: ScenarioResult
    failures: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        """The run met every expectation — the headline metric cleared its floor
        and every tracked milestone reached its expected stage."""
        return not self.failures

    def snapshot(self) -> Dict:
        """A plain, serializable view of the regression verdict."""
        return {
            "scenario": self.scenario,
            "passed": self.passed,
            "failures": list(self.failures),
            "result": self.result.snapshot(),
        }

    def summary(self) -> str:
        """A one-line PASS/FAIL report naming the unmet expectations, if any."""
        verdict = "PASS" if self.passed else "FAIL"
        line = f"[REGRESSION {verdict}] {self.scenario}"
        if self.failures:
            line += ": " + "; ".join(self.failures)
        return line

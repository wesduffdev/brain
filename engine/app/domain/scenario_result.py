"""ScenarioResult — the verdict of one scenario run (card V10a).

A scenario seeds the being, runs it N ticks, and reads ONE learning metric — the
target concept's confidence — before and after. This value object carries that
reading and the pass/fail judgment: whether the metric rose past the scenario's
configured floor. `passed` is the regression signal; `summary` is the documented
before/after line a run prints. It is a plain reading, not a store — deleting it
would push these fields and the pass rule back into the runner and its callers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ScenarioResult:
    scenario: str
    metric: str
    ticks: int
    before: float
    after: float
    threshold: float

    @property
    def delta(self) -> float:
        """How far the learning metric moved over the run."""
        return self.after - self.before

    @property
    def passed(self) -> bool:
        """The run demonstrated learning: the metric rose to at least the
        scenario's configured floor."""
        return self.delta >= self.threshold

    def snapshot(self) -> Dict:
        """A plain, serializable view of the run's verdict."""
        return {
            "scenario": self.scenario,
            "metric": self.metric,
            "ticks": self.ticks,
            "before": self.before,
            "after": self.after,
            "delta": self.delta,
            "threshold": self.threshold,
            "passed": self.passed,
        }

    def summary(self) -> str:
        """A one-line, human-readable before/after report — the documented runner
        output ("watch it learn")."""
        verdict = "LEARNED" if self.passed else "NO LEARNING"
        return (
            f"[{verdict}] {self.scenario}: {self.metric} "
            f"{self.before:.3f} -> {self.after:.3f} "
            f"(delta {self.delta:+.3f}, needs >= {self.threshold:.3f}) "
            f"over {self.ticks} ticks"
        )

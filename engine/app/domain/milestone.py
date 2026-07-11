"""Milestone — a rung on the being's developmental ladder (card v10).

A MILESTONE is a named developmental capability the being grows into — e.g.
"round things roll when pushed". It reads ONE learning metric (the confidence of
a named perceived concept, card v2) and defines an ordered ladder of STAGES, each
gated by a `min_value` floor; the being sits on the highest stage whose floor its
metric has reached. As a run drives the metric up, the being CROSSES stages — and
that crossing, captured as a `MilestoneProgress`, is the developmental progress
the scenario system records and a regression check verifies.

These are pure value objects: the stage-ladder math lives here, with the data;
`MilestoneService` only loads them from config/milestones.yaml and looks them up,
and `ScenarioRunner` reads the concept confidence that drives them. Milestone
thresholds and stage names are config, never code — retuning a ladder is a
config change. See docs/BRIEF.md §16.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Tuple


@dataclass(frozen=True)
class MilestoneStage:
    """One rung: a stage name and the metric floor the being must reach to sit on
    it. Stages are ordered low → high within a milestone."""

    name: str
    min_value: float


@dataclass(frozen=True)
class Milestone:
    name: str
    description: str
    # The perceived concept whose confidence is this milestone's metric —
    # feature + action + outcome (card v2), never a developer label (ADR 0002).
    concept: Dict[str, str]
    stages: Tuple[MilestoneStage, ...]  # ordered low → high

    def stage_for(self, value: float) -> MilestoneStage:
        """The highest stage whose floor the metric `value` has reached — the
        being's current developmental stage on this milestone."""
        reached = self.stages[0]
        for stage in self.stages:
            if value >= stage.min_value:
                reached = stage
        return reached

    def stage_index(self, stage_name: str) -> int:
        """The position of a named stage on the ladder (0 = lowest). Fail-loud on
        an unknown stage name, so a scenario cannot expect a stage that isn't
        defined."""
        for index, stage in enumerate(self.stages):
            if stage.name == stage_name:
                return index
        raise ValueError(
            f"milestone {self.name!r} has no stage {stage_name!r}; "
            f"stages: {[stage.name for stage in self.stages]}"
        )

    def progress(self, value_before: float, value_after: float) -> "MilestoneProgress":
        """Read the developmental move a run produced: the stage the being sat on
        before vs. after, from the metric's before/after value."""
        before = self.stage_for(value_before)
        after = self.stage_for(value_after)
        return MilestoneProgress(
            milestone=self.name,
            stage_before=before.name,
            stage_after=after.name,
            stage_index_before=self.stage_index(before.name),
            stage_index_after=self.stage_index(after.name),
            value_before=value_before,
            value_after=value_after,
        )

    @classmethod
    def from_mapping(cls, name: str, mapping: Mapping) -> "Milestone":
        """Build a milestone from its config block (parsed YAML). The stage ladder
        is sorted low → high by floor regardless of the order it was written in,
        so `stage_for` is well-defined."""
        stages = tuple(
            sorted(
                (
                    MilestoneStage(name=str(s["name"]), min_value=float(s["min_value"]))
                    for s in mapping["stages"]
                ),
                key=lambda stage: stage.min_value,
            )
        )
        concept = mapping["concept"]
        return cls(
            name=str(name),
            description=str(mapping.get("description", "")).strip(),
            concept={key: str(concept[key]) for key in ("feature", "action", "outcome")},
            stages=stages,
        )


@dataclass(frozen=True)
class MilestoneProgress:
    """The developmental move one run produced on one milestone: the stage the
    being sat on before and after, and whether it climbed. `advanced` is the
    observable "it grew up a little" signal a scenario reports."""

    milestone: str
    stage_before: str
    stage_after: str
    stage_index_before: int
    stage_index_after: int
    value_before: float
    value_after: float

    @property
    def advanced(self) -> bool:
        """The run moved the being up at least one developmental stage."""
        return self.stage_index_after > self.stage_index_before

    def snapshot(self) -> Dict:
        """A plain, serializable view of the milestone move."""
        return {
            "milestone": self.milestone,
            "stageBefore": self.stage_before,
            "stageAfter": self.stage_after,
            "advanced": self.advanced,
            "valueBefore": self.value_before,
            "valueAfter": self.value_after,
        }

    def summary(self) -> str:
        """A one-line, human-readable stage-transition report."""
        arrow = "->" if self.advanced else "=="
        return (
            f"{self.milestone}: {self.stage_before} {arrow} {self.stage_after} "
            f"({self.value_before:.3f} -> {self.value_after:.3f})"
        )

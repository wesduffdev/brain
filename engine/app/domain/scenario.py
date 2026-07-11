"""Scenario — an authored developmental experiment (card v10).

A SCENARIO is the parsed, validated form of one config/scenarios/*.yaml file: the
objects that seed the room, how many ticks the being lives, the LEARNING TARGET
concept whose confidence is the headline metric plus its success floor, and the
developmental MILESTONES the run exercises with the stage each is expected to
reach. It is a plain value object `ScenarioService` produces and both
`ScenarioRunner` and `RegressionEvaluationService` consume — so the YAML shape is
read in exactly one place and everything downstream works with typed fields.

The scenario file is a HARNESS INPUT, not engine config: it is parsed directly
(PyYAML) and never routed through ConfigService — the being's own config still
comes from config/*.yaml. See docs/BRIEF.md §16.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Tuple


@dataclass(frozen=True)
class MilestoneExpectation:
    """One developmental milestone a scenario exercises and the stage the being is
    expected to have reached by the run's end — that milestone's regression bar."""

    milestone: str
    expect_stage: str


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    object_selectors: Tuple[str, ...]
    ticks: int
    # The headline learning metric: a perceived concept (feature/action/outcome).
    target: Dict[str, str]
    min_confidence_delta: float
    milestones: Tuple[MilestoneExpectation, ...] = ()

    @classmethod
    def from_mapping(cls, mapping: Mapping) -> "Scenario":
        """Build a scenario from its parsed YAML. `milestones` is optional — a
        scenario may track the headline metric only (card V10a shape) or declare
        developmental milestones with an expected end stage (card v10)."""
        room = mapping.get("room") or {}
        target = mapping["learning_target"]
        success = mapping.get("success_condition") or {}
        milestones = tuple(
            MilestoneExpectation(
                milestone=str(item["name"]), expect_stage=str(item["expect_stage"])
            )
            for item in (mapping.get("milestones") or [])
        )
        return cls(
            name=str(mapping["name"]),
            description=str(mapping.get("description", "")).strip(),
            object_selectors=tuple(str(sel) for sel in (room.get("objects") or [])),
            ticks=int(mapping["ticks"]),
            target={key: str(target[key]) for key in ("feature", "action", "outcome")},
            min_confidence_delta=float(success.get("min_confidence_delta", 0.0)),
            milestones=milestones,
        )

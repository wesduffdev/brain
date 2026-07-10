"""Typed, immutable policies produced by the ConfigService and consumed by the
services. Nothing here reads files or knows about YAML — a policy is just the
already-resolved answer to "how does this need drift?" or "which emotion does
this rule assert?". Keeping them frozen dataclasses means a service can hold
one without any risk of mutating shared config.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

# Valid values for NeedTickPolicy.direction.
INCREASE = "increase"
DECREASE = "decrease"
CONTEXTUAL = "contextual"
DIRECTIONS = frozenset({INCREASE, DECREASE, CONTEXTUAL})


@dataclass(frozen=True)
class NeedTickPolicy:
    """How one need moves over time and the band it lives in.

    A `contextual` need has no autonomous drift — something in the world
    (a later slice) moves it. `increase`/`decrease` needs drift by `amount`
    every `every_ticks` ticks, clamped to [min_value, max_value].
    """

    name: str
    direction: str
    amount: int
    every_ticks: int
    min_value: int
    max_value: int
    start: int

    def __post_init__(self) -> None:
        if self.direction not in DIRECTIONS:
            raise ValueError(
                f"need '{self.name}': unknown direction {self.direction!r} "
                f"(expected one of {sorted(DIRECTIONS)})"
            )
        if self.min_value > self.max_value:
            raise ValueError(f"need '{self.name}': min {self.min_value} > max {self.max_value}")


@dataclass(frozen=True)
class EmotionRule:
    """One line of the emotion-derivation table: if `need op value`, the
    dominant emotion is `emotion`. Rules are evaluated in order; first match
    wins.
    """

    emotion: str
    need: str
    op: str
    value: int


@dataclass(frozen=True)
class EnvironmentPolicy:
    """How a room's environmental conditions push the being's *contextual*
    needs. `every_ticks` is how often the deltas land (apply when
    `tick % every_ticks == 0`). `impacts` is a table keyed
    dimension -> category -> {need_name: delta}: for the room's current
    category in each dimension, the matching deltas are summed and applied,
    clamped by each need's own band. An empty policy (no config) moves nothing.
    """

    every_ticks: int = 0
    impacts: Mapping[str, Mapping[str, Mapping[str, int]]] = field(default_factory=dict)

    def deltas_for(self, conditions: Mapping[str, str]) -> Mapping[str, int]:
        """Sum the per-need deltas for a room's current `conditions`
        (dimension -> category). A category naming nothing in the table for its
        dimension is a config error — it fails loudly rather than silently
        doing nothing (the same discipline as the object-property vocabulary).
        """
        totals: dict = {}
        for dimension, category in conditions.items():
            if category is None:
                continue
            table = self.impacts.get(dimension)
            if table is None:
                continue
            if category not in table:
                raise ValueError(
                    f"room condition {dimension}={category!r} is not a known "
                    f"category (have {sorted(table)})"
                )
            for need_name, delta in table[category].items():
                totals[need_name] = totals.get(need_name, 0) + int(delta)
        return totals


@dataclass(frozen=True)
class CommandSpec:
    """One entry in the player-command vocabulary (ADR 0004): the command's name
    and whether a valid `player_command` for it must carry a target object id.
    """

    name: str
    requires_target: bool = False


@dataclass(frozen=True)
class RenderHintsPolicy:
    """Resolved presentation hints for the render frame (ADR 0004): the neutral
    `intensity` to report until the emotion model carries one, the fallback
    `default` visual, and the per-emotion visual draw hints keyed by emotion.
    Pure presentation vocabulary — it carries no psychology; the emotion is
    already decided before these hints are looked up.
    """

    intensity_default: float
    default: Mapping[str, object]
    by_emotion: Mapping[str, Mapping[str, object]]

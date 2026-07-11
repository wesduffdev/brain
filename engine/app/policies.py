"""Typed, immutable policies produced by the ConfigService and consumed by the
services. Nothing here reads files or knows about YAML — a policy is just the
already-resolved answer to "how does this need drift?" or "which emotion does
this rule assert?". Keeping them frozen dataclasses means a service can hold
one without any risk of mutating shared config.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple

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
class NeedBands:
    """The single authority on where each need may sit — its ``[floor, ceiling]``
    band. A need's band lives on its NeedTickPolicy (``min_value``/``max_value``,
    from ``tick_rates.yaml``); this aggregates those into one place that clamps a
    need to its band. Every force that moves a need — autonomous drift, the
    environment's push, a felt-consequence effect — clamps through here, so a
    need's floor/ceiling has exactly one home rather than being re-derived at each
    site. A need with no configured band is returned unchanged (never happens for
    the shipped needs, which all have bands).
    """

    bands: Mapping[str, Tuple[int, int]] = field(default_factory=dict)

    @classmethod
    def from_policies(cls, policies: Mapping[str, "NeedTickPolicy"]) -> "NeedBands":
        """Read each need's band off its tick policy — the single source of truth
        for a need's floor/ceiling."""
        return cls({name: (p.min_value, p.max_value) for name, p in policies.items()})

    def clamp(self, need: str, value: int) -> int:
        """`value` held inside `need`'s band; unchanged if the need has no band."""
        band = self.bands.get(need)
        if band is None:
            return value
        low, high = band
        return max(low, min(high, value))


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
class ActionPolicy:
    """One action the being can take, fully resolved from config (ADR 0009).

    `affordance` is the object affordance the action needs (e.g. `touch`); an
    action with `affordance=None` is **free** — self-/world-directed movement
    (approach/withdraw) that any perceived object can be the target of. Utility
    is `base` + `sum(need_weights[n] * needs[n])` + `emotion_bonuses[emotion]`;
    weights may be negative. `expected_outcomes` are always anticipated, and each
    perceived property in `property_outcomes` adds its outcomes on top — the rule
    layer that fills an InteractionEvent's expected/observed outcomes. `reason` is
    the human-readable justification surfaced to the renderer. Timing:
    `duration_ticks` + `cooldown_ticks` set how long before the action may be
    taken again (`tick_rates.yaml`, BRIEF §10).
    """

    name: str
    affordance: Optional[str]
    base: float
    need_weights: Mapping[str, float]
    emotion_bonuses: Mapping[str, float]
    expected_outcomes: Tuple[str, ...]
    property_outcomes: Mapping[str, Tuple[str, ...]]
    reason: str
    duration_ticks: int = 0
    cooldown_ticks: int = 0

    @property
    def is_free(self) -> bool:
        return self.affordance is None

    def score(self, needs: Mapping[str, int], emotion: str) -> float:
        """The action's utility given the being's current needs and emotion."""
        total = float(self.base)
        for need_name, weight in self.need_weights.items():
            total += float(weight) * float(needs.get(need_name, 0))
        total += float(self.emotion_bonuses.get(emotion, 0.0))
        return total

    def outcomes_for(self, properties) -> Tuple[str, ...]:
        """The outcomes this action produces on an object with `properties`:
        the always-expected ones, plus any keyed to a property that is present.
        Order-stable and de-duplicated, so the same object always reads the
        same."""
        present = set(properties)
        ordered: list = list(self.expected_outcomes)
        for prop, outcomes in self.property_outcomes.items():
            if prop in present:
                ordered.extend(outcomes)
        seen: set = set()
        unique: list = []
        for outcome in ordered:
            if outcome not in seen:
                seen.add(outcome)
                unique.append(outcome)
        return tuple(unique)


@dataclass(frozen=True)
class SafetyRule:
    """One rule of the **invariant floor** (ADR 0009, narrowed by ADR 0013/0014):
    taking `action` on an object that has `blocked_property` is forbidden, with
    `reason` explaining why. The floor is absolute — no utility or learned score
    can override a matching rule — but it now blocks only genuinely
    simulation-breaking actions, not merely harmful ones. Recoverable-but-harmful
    actions (touching something hot) are *allowed* and their harm plays out as
    felt consequences (see `OutcomeEffectPolicy`), not as a block.
    """

    action: str
    blocked_property: str
    reason: str


@dataclass(frozen=True)
class OutcomeEffectPolicy:
    """How an action's observed OUTCOMES push the being's needs — the felt
    consequence of an experience (ADR 0014). Keyed `outcome_label -> {need:
    delta}`: a harmful outcome (`causes_pain`) raises the being's pain and lowers
    its felt safety and comfort at once; an outcome with no entry moves nothing.
    Magnitudes are config (`outcome_effects.yaml`); the being's own need bands
    clamp the result (`tick_rates.yaml`), so a need's floor/ceiling has one home.
    This is what makes a harmful action land real, possibly-lasting consequences
    instead of being hard-blocked.
    """

    effects: Mapping[str, Mapping[str, int]] = field(default_factory=dict)

    def deltas_for(self, outcomes) -> Mapping[str, int]:
        """Sum the per-need deltas across all of `outcomes` the action produced.
        Order-independent; an outcome not in the table contributes nothing."""
        totals: dict = {}
        for outcome in outcomes:
            for need_name, delta in self.effects.get(outcome, {}).items():
                totals[need_name] = totals.get(need_name, 0) + int(delta)
        return totals

    def anticipated_cost(self, probabilities: Mapping[str, float]) -> float:
        """The being's anticipated aversive cost of a *predicted* set of outcomes
        (card v3): each outcome's probability weights how much that outcome is
        expected to ERODE the being's needs (the sum of its need *drops*, from the
        same felt-consequence table). Always ``>= 0`` — a predicted harm (felt
        safety/comfort falling) has a positive cost; a predicted-neutral or
        pleasant outcome (no need drop) costs nothing. This is what lets the
        decision layer penalize an action it predicts will hurt without a hard
        block, and it is config-driven: retuning how aversive an experience is
        anticipated to be is an `outcome_effects.yaml` change. (A symmetric bonus
        for anticipated need *gains* is a future extension; v0 penalizes only.)"""
        total = 0.0
        for outcome, probability in probabilities.items():
            drop = sum(-delta for delta in self.effects.get(outcome, {}).values() if delta < 0)
            total += float(probability) * float(drop)
        return total


@dataclass(frozen=True)
class PredictionBlendPolicy:
    """How the decision layer blends the neural predictor with the rule-based one
    (card v3, extends ADR 0011). `neural_enabled` is the shadow -> active flip:
    off, prediction stays observational and the being decides on raw utility; on,
    the blended prediction actively shapes the decision. `neural_weight` /
    `rule_weight` weight the two predictors' probabilities in the blend;
    `fallback_to_rules_on_error` makes a neural inference failure degrade to the
    rule layer (the sim keeps running) rather than propagate. All four live in the
    `prediction:` block of `outcome_labels.yaml`, so retuning the blend — or
    turning the model off entirely — is a config change, never a code one.
    """

    neural_enabled: bool = False
    neural_weight: float = 0.5
    rule_weight: float = 0.5
    fallback_to_rules_on_error: bool = True


@dataclass(frozen=True)
class MemoryPriorityPolicy:
    """How a Memory's PRIORITY (salience) is scored (card v1). Salience is a
    weighted sum of two signals the being cares about most:

        priority = baseline
                 + prediction_error_weight * prediction_error   (how *surprised* it was)
                 + emotion_intensity_weight * emotional_intensity (how much it was *felt*)

    `emotional_intensity` is the strongest of the emotion-before / emotion-after
    intensities, read from the `emotion_intensity` table (an emotion not listed
    contributes none). Every weight and every intensity lives in
    `config/learning_rates.yaml`, so retuning what the being holds onto — making
    it dwell more on surprise, or more on fear — is a config change, never a code
    one. An empty policy (no config) falls back to "priority == prediction_error".
    """

    baseline: float = 0.0
    prediction_error_weight: float = 1.0
    emotion_intensity_weight: float = 1.0
    emotion_intensity: Mapping[str, float] = field(default_factory=dict)

    def priority_for(
        self, *, prediction_error: float, emotion_before: str, emotion_after: str
    ) -> float:
        """The salience of an interaction with this prediction error and these
        emotions. Monotonic in both the error and the felt emotional intensity —
        the more wrong or the more affected, the higher the priority."""
        intensity = max(
            float(self.emotion_intensity.get(emotion_before, 0.0)),
            float(self.emotion_intensity.get(emotion_after, 0.0)),
        )
        return (
            float(self.baseline)
            + float(self.prediction_error_weight) * float(prediction_error)
            + float(self.emotion_intensity_weight) * intensity
        )


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

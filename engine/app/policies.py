"""Typed, immutable policies produced by the ConfigService and consumed by the
services. Nothing here reads files or knows about YAML — a policy is just the
already-resolved answer to "how does this need drift?" or "which emotion does
this rule assert?". Keeping them frozen dataclasses means a service can hold
one without any risk of mutating shared config.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import ClassVar, Dict, Mapping, Optional, Tuple

from app.domain.motion import Motion
from app.ports.voice import VoiceParams

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

    def net_effect(self, outcomes) -> int:
        """The net felt consequence of `outcomes` — the sum of every need delta they
        produce. Negative means the experience eroded the being on balance (a burn:
        safety and comfort falling), positive means it was rewarding (something
        pleasant), zero means it left the being unmoved. This is the single scalar
        VALENCE of an experience the being's learned preferences and trait drift read
        from — so "was that good or bad for me?" has one config-driven answer."""
        deltas = self.deltas_for(outcomes)
        return sum(int(delta) for delta in deltas.values())

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
class ConceptLearningPolicy:
    """How a CONCEPT SCHEMA's confidence forms and strengthens (card v2, extended
    by card AVERSIVE-LEARN). Every confirming interaction reinforces the concept a
    fraction of the way toward full certainty (1.0) from where it stood before
    (0.0 before any evidence):

        confidence_next = prior + effective_rate * (1 - prior)

    where `prior` is the concept's current confidence (0.0 on the first sighting),
    the base rate is `seed_confidence` on the first sighting and `reinforce_rate`
    thereafter, and

        effective_rate = min(1.0, base_rate * (1 + intensity_gain * intensity)).

    So confidence rises monotonically and asymptotes at 1.0 with diminishing
    returns — but how big each step is now depends on how INTENSELY the being felt
    that interaction. `intensity` is the interaction's salience (its emotional
    intensity / prediction error — the same signal that scores a memory's
    priority): a high-intensity aversive experience is learned in (nearly) one shot
    — ONE emotionally-searing burn lifts `hot -> causes_pain` toward high
    confidence — while an ordinary, low-salience interaction lands only the usual
    small step. With `intensity_gain` 0 (or `intensity` 0) the curve is exactly the
    pre-slice one: first sighting == seed, each repeat a `reinforce_rate` step.

    All three numbers live in `config/learning_rates.yaml`, so retuning how boldly
    the being commits to a pattern — and how much trauma accelerates it — is a
    config change, never a code one. The default (seed 0.3, rate 0.2, gain 0.0)
    forms concepts, intensity-blind, even with no learning-rates file.
    """

    seed_confidence: float = 0.3
    reinforce_rate: float = 0.2
    intensity_gain: float = 0.0

    def reinforce(self, current: "float | None", *, intensity: float = 0.0) -> float:
        """The confidence of a concept after one more confirming interaction felt
        at `intensity`. ``None`` is the first sighting (reinforces from 0.0 at the
        seed rate); otherwise the current confidence is the prior. A higher
        `intensity` amplifies the step, so one intense experience teaches more than
        one flat one; `intensity` 0 reproduces the pre-slice curve exactly."""
        prior = 0.0 if current is None else float(current)
        base_rate = self.seed_confidence if current is None else self.reinforce_rate
        boost = 1.0 + float(self.intensity_gain) * max(0.0, float(intensity))
        effective_rate = min(1.0, float(base_rate) * boost)
        return prior + effective_rate * (1.0 - prior)


@dataclass(frozen=True)
class BeliefDecisionPolicy:
    """How strongly a concept-derived BELIEF steers the being's decision (card
    AVERSIVE-LEARN). When the being believes an action on an object will produce an
    aversive outcome (it expects `touch` on a `hot` thing to `cause_pain`), that
    expectation raises the action's ANTICIPATED-DISCOMFORT cost in the decision —
    even with the neural predictor off — so the being avoids a never-seen hot
    object COGNITIVELY, from what it already understands, before it is ever burned
    again.

    The belief's anticipated cost is valued exactly as the predictor's is
    (`OutcomeEffectPolicy.anticipated_cost`, the belief's confidence standing in for
    a predicted probability); `discomfort_weight` scales that cost into a negative
    score bias the decision adds to the *safe* candidates alongside the v6
    remembered-preference bias — the two compose (add), and, like every learned
    signal, the bias only ever reshapes candidates the safety floor has already
    cleared, so it can never buy a blocked action past a guardrail (BRIEF §12).
    `discomfort_weight` defaults to 0.0 — beliefs form and persist but do not steer
    the decision (the pre-slice baseline); only a config that opts in turns the
    cognitive avoidance on. Retuning it is a `config/learning_rates.yaml` change.
    """

    discomfort_weight: float = 0.0

    def bias(self, anticipated_cost: float) -> float:
        """The (non-positive) score bias for an action whose believed outcomes carry
        this anticipated aversive `cost` (always ``>= 0`` from the outcome-effect
        table). 0.0 when the being believes nothing aversive, or when the weight is
        off."""
        return -float(self.discomfort_weight) * max(0.0, float(anticipated_cost))


@dataclass(frozen=True)
class GraphEdgePolicy:
    """How a CONCEPT-GRAPH EDGE's confidence forms and strengthens (card v7). An
    edge starts at `seed_confidence` the first time the being lays it down, and
    each later confirming interaction moves its confidence a fraction
    `reinforce_rate` of the way toward full certainty (1.0):

        confidence_next = confidence + reinforce_rate * (1 - confidence)

    So an edge's confidence rises monotonically with the evidence behind it and
    asymptotes at 1.0 — the more often the being sees ``round → rolls``, the surer
    that edge is, with diminishing returns. Both numbers live in
    `config/learning_rates.yaml` (`graph.edge`), so retuning how boldly the graph
    commits to a relationship is a config change, never a code one. The default
    (seed 0.3, rate 0.2) strengthens edges even with no learning-rates file. It
    mirrors `ConceptLearningPolicy`'s curve but is a distinct seam so graph tuning
    moves independently of concept tuning."""

    seed_confidence: float = 0.3
    reinforce_rate: float = 0.2

    def reinforce(self, current: "float | None") -> float:
        """The confidence of an edge after one more confirming interaction.
        ``None`` is the first sighting (returns the seed); otherwise the current
        confidence is nudged toward 1.0 by `reinforce_rate`."""
        if current is None:
            return float(self.seed_confidence)
        return float(current) + float(self.reinforce_rate) * (1.0 - float(current))


@dataclass(frozen=True)
class CuriosityWeights:
    """How the being's CURIOSITY toward a perceived object is composed from four
    cognitive signals (card v4). The being is drawn to what it cannot yet predict:

        curiosity = novelty*novelty_weight
                  + uncertainty*uncertainty_weight
                  + recent_surprise*surprise_weight
                  - familiarity*familiarity_weight

    - `novelty` is the share of the object's perceived properties the being has
      never encountered (a wholly-new thing is maximally novel);
    - `uncertainty` is how unsure the being is about the properties it HAS met
      (met-but-not-mastered — high while a concept is still forming);
    - `recent_surprise` is the decayed trace of how wrong the being recently was
      about this object (from the SurprisePolicy);
    - `familiarity` is how well the being understands the object; it pulls
      curiosity back DOWN, so a mastered object stops drawing attention.

    Familiarity itself rises as the being acts on an object: `familiarity_rate`
    is how far each interaction moves a property's familiarity toward full mastery
    (`familiarity_next = familiarity + familiarity_rate*(1 - familiarity)`), the
    same saturating curve concept confidence uses. Every weight lives in
    `config/decision_weights.yaml`, so retuning how curious / novelty-seeking the
    being is is a config change, never a code one.
    """

    novelty: float = 1.0
    uncertainty: float = 1.0
    recent_surprise: float = 1.0
    familiarity: float = 1.0
    familiarity_rate: float = 0.3

    def combine(
        self, *, novelty: float, uncertainty: float, recent_surprise: float, familiarity: float
    ) -> float:
        """The composed curiosity for the four measured signals."""
        return (
            self.novelty * float(novelty)
            + self.uncertainty * float(uncertainty)
            + self.recent_surprise * float(recent_surprise)
            - self.familiarity * float(familiarity)
        )

    def reinforce(self, current: float) -> float:
        """A property's familiarity after one more interaction with it — nudged a
        `familiarity_rate` fraction of the way toward full mastery (1.0)."""
        return float(current) + self.familiarity_rate * (1.0 - float(current))


@dataclass(frozen=True)
class SurprisePolicy:
    """How a fresh SURPRISE fades over time (card v4). `decay` in ``[0, 1]`` is the
    per-tick retention of a recorded surprise: ``recent = surprise * decay**elapsed``
    — 1.0 never forgets, 0.0 forgets instantly. Lives in the `surprise:` block of
    `config/decision_weights.yaml`, so retuning how long a shock lingers is a config
    change.
    """

    decay: float = 0.7


@dataclass(frozen=True)
class ExplorationPolicy:
    """How the exploration drive adjusts an action's decision score (card v4). The
    adjustment for taking `action` on an object is

        action_weight(action) * curiosity_weight * curiosity
            - discomfort_weight * anticipated_discomfort

    so the being is pulled toward exploring novel/uncertain objects and pushed off
    actions it anticipates will hurt. `action_weights` says how strongly each
    action chases novelty — epistemic, low-risk actions (observe, approach) chase
    it most, contact actions less; an action absent from the table uses
    `default_action_weight`. With `curiosity_weight == 0` the adjustment is zero
    for every action: a purely utility-driven being, byte-identical to the pre-v4
    baseline. All the numbers live in `config/decision_weights.yaml`.

    This shapes only the ranking of the *safe* candidates; it is applied after the
    safety floor has dropped any blocked action, so a curiosity bonus can never buy
    an action past a safety rule (BRIEF §12).
    """

    curiosity_weight: float = 0.0
    discomfort_weight: float = 1.0
    action_weights: Mapping[str, float] = field(default_factory=dict)
    default_action_weight: float = 0.0

    def action_weight(self, action: str) -> float:
        """How strongly `action` chases novelty; the table default when unlisted."""
        return float(self.action_weights.get(action, self.default_action_weight))


@dataclass(frozen=True)
class RenderHintsPolicy:
    """Resolved presentation hints for the render frame (ADR 0004): the neutral
    `intensity` to report until the emotion model carries one, the fallback
    `default` visual, the per-emotion visual draw hints keyed by emotion, and the
    per-reaction draw hints keyed by instinct-reaction label (RENDER-RX). Pure
    presentation vocabulary — it carries no psychology; the emotion and the
    reaction are already decided before these hints are looked up.
    """

    intensity_default: float
    default: Mapping[str, object]
    by_emotion: Mapping[str, Mapping[str, object]]
    by_reaction: Mapping[str, Mapping[str, object]] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalPolicy:
    """How strongly a remembered interaction is RECALLED for the object the being
    now perceives (card v6). Relevance combines the signals the being cares about:

        relevance = (similarity_weight · property_similarity
                     + same_object_weight · [same object])
                    · action_match
                    · (1 + salience_weight · priority)

    where ``action_match`` is 1.0 when the memory was the SAME action being weighed
    and ``same_action_floor`` otherwise (0.0 by default — a burn while *touching*
    does not weigh on whether to *look*). `property_similarity` is the Jaccard
    overlap of perceived-property sets (`SimilarityService`, ADR 0019), so a
    never-seen object recalls what the being learned about things that look like it
    — the generalization the hot-lamp story rests on. `salience_weight` lets a
    high-emotion / high-error memory (its `priority`) be recalled more strongly. All
    the numbers live in `config/traits.yaml`; retuning what the being recalls is a
    config change only.
    """

    similarity_weight: float = 1.0
    same_object_weight: float = 1.0
    same_action_floor: float = 0.0
    salience_weight: float = 0.0

    def relevance(
        self, *, similarity: float, same_object: bool, same_action: bool, priority: float
    ) -> float:
        """The relevance of a memory with this perceived-property `similarity`, on an
        object it is/na't about (`same_object`), taken with the same/a different
        action (`same_action`), and this `priority` (salience). 0.0 when nothing
        connects the memory to the present choice."""
        action_match = 1.0 if same_action else float(self.same_action_floor)
        base = self.similarity_weight * float(similarity) + (
            self.same_object_weight if same_object else 0.0
        )
        return base * action_match * (1.0 + self.salience_weight * float(priority))


@dataclass(frozen=True)
class PreferencePolicy:
    """How strongly recalled memories bias the decision (card v6). A memory's
    contribution is its relevance times the VALENCE of what it observed (the
    felt-consequence net effect: a burn is negative, something pleasant positive),
    summed over the recalled memories; `weight` scales that sum into the score bias
    the decision adds to the *safe* candidate. ``weight`` defaults to 0.0 — so a
    config with no `preference` block leaves the being deciding on utility exactly as
    before (the pre-v6 baseline), even while it forms and stores memories. Only a
    config that opts in turns the learned like/dislike on. Retuning how much the past
    steers the present is a `config/traits.yaml` change, never a code one.
    """

    weight: float = 0.0

    def bias(self, valence_sum: float) -> float:
        """The decision score bias for a total recalled `valence_sum`."""
        return float(self.weight) * float(valence_sum)


@dataclass(frozen=True)
class TraitDriftPolicy:
    """One slow personality TRAIT and how it drifts from repeated experience (card
    v6). A trait is a level in ``[min, max]`` that starts at `start` and moves a
    `drift_rate` fraction of the way toward its ceiling each time an experience
    pushes it — the same saturating curve concept confidence and familiarity use, so
    it rises fast at first and then settles into a stable temperament:

        level_next = level + drift_rate · signal · (max − level)

    `signal` in ``[0, 1]`` is how strongly this experience pushed the trait (for
    caution, how bad-and-surprising the moment was; for curiosity, that it was a safe,
    rewarding exploration). `decision_gain` is how strongly the *current* level shapes
    behaviour — caution amplifies the being's aversion to its bad memories. Every
    number lives in `config/traits.yaml`, so a being's temperament, and how fast it
    forms, is tuned in config only.
    """

    start: float = 0.0
    drift_rate: float = 0.0
    decision_gain: float = 0.0
    min: float = 0.0
    max: float = 1.0

    def drift(self, level: float, signal: float) -> float:
        """`level` after one experience of strength `signal`, nudged toward `max`
        and clamped to the trait's band."""
        moved = float(level) + float(self.drift_rate) * float(signal) * (self.max - float(level))
        return max(self.min, min(self.max, moved))


@dataclass(frozen=True)
class TraitPolicy:
    """The being's slow-drifting personality (card v6): a CAUTION tendency and a
    CURIOSITY tendency, each a `TraitDriftPolicy`. Caution rises from repeated
    negative surprise (being hurt worse than expected) and amplifies how strongly the
    being's bad memories hold it back; curiosity rises from repeated positive
    exploration (safe, rewarding interactions). Both are transient this slice (held in
    process, like the ADR 0020 familiarity signal). Retuning temperament is a
    `config/traits.yaml` change only.
    """

    caution: TraitDriftPolicy = field(default_factory=TraitDriftPolicy)
    curiosity: TraitDriftPolicy = field(default_factory=TraitDriftPolicy)


@dataclass(frozen=True)
class InstinctModelPolicy:
    """Trainer hyperparameters for the instinct model (ADR 0026), from the
    `training:` block of `config/instinct.yaml`. `intensity_loss` selects how the
    scalar reaction-intensity head is trained — ``"bce"`` (BCEWithLogits on the
    [0, 1] target, the default) or ``"mse"`` (mean-squared error on the
    sigmoid-activated output). The instinct feature order and reaction-label set
    are the encode CONTRACT, read separately off the ConfigService
    (`instinct_feature_order()`/`instinct_labels()`), so this policy carries only
    the tuning — retuning instinct training is a config change, never a code one.
    """

    epochs: int = 400
    hidden_size: int = 16
    learning_rate: float = 0.05
    seed: int = 0
    intensity_loss: str = "bce"


@dataclass(frozen=True)
class EventTopicsPolicy:
    """The being.* Kafka topic catalogue and the partition / dead-letter
    conventions the runtime broker is provisioned with (EVT-KAFKA, ADR 0024). It
    is the resolved answer to "which topics exist, how many partitions, and where
    does a failed event go?" — read from ``config/events.yaml`` by
    ``ConfigService.event_topics_policy``. Topic NAMES, the partition count, and
    the DLQ suffix all come from config; the ``KafkaEventBus`` learns them from
    here and never hardcodes one, so retuning the topology is a config change only.
    (The broker URL is the lone Kafka setting that is NOT here — it is env-only
    deploy config, ``KAFKA_BOOTSTRAP_SERVERS``, like ``DATABASE_URL``.)

    ``partitions`` is sized for a SINGLE being (1): one being is a single ordered
    stream, so one partition preserves its per-being order; scaling to many beings
    raises it in config, never in code. ``dlq_for`` names an event topic's
    dead-letter companion (``being.perception.events`` ->
    ``being.perception.events.dlq``), where the consumer routes an event it cannot
    process, so a poison message parks off to the side instead of wedging the flow.
    ``bootstrap_topics`` is the full set the broker must be provisioned with —
    every catalogue topic followed by its DLQ companion.
    """

    names: Tuple[str, ...] = ()
    partitions: int = 1
    dlq_suffix: str = ".dlq"

    def dlq_for(self, topic: str) -> str:
        """The dead-letter topic a failed ``topic`` event is routed to."""
        return f"{topic}{self.dlq_suffix}"

    def dlq_topics(self) -> Tuple[str, ...]:
        """The DLQ companion of every catalogue topic, in authored order."""
        return tuple(self.dlq_for(name) for name in self.names)

    def bootstrap_topics(self) -> Tuple[str, ...]:
        """Every topic the broker must be provisioned with: each being.* topic
        followed immediately by its ``.dlq`` companion."""
        provisioned: list = []
        for name in self.names:
            provisioned.append(name)
            provisioned.append(self.dlq_for(name))
        return tuple(provisioned)
# The FROZEN instinct feature vector (ADR 0026), in contract order. WORLD-MOTION
# produces exactly this vector on every ObjectApproached stimulus; reordering,
# inserting, or renaming a slot is a contract change (a retrain), so it lives in
# one place both the emitter (`MotionPolicy.features`) and any consumer read.
MOTION_FEATURE_NAMES: Tuple[str, ...] = (
    "distance",
    "velocity",
    "acceleration",
    "trajectory_toward_body",
    "time_to_contact",
    "object_size",
    "size_change_rate",
    "unexpectedness",
    "visibility_confidence",
    "sound_spike_intensity",
    "touch_intensity",
    "current_focus_level",
    "current_stability",
    "prior_prediction_error",
)

# The features with no source in today's world (no sound/touch sensing, and the
# being's fast-loop internal state — focus/stability/prior-error — is folded in
# by the instinct consumer, not the world). Each defaults to 0.0 until a slice
# supplies it, and the default is config-overridable (never hard-coded).
_MOTION_DEFAULTED_FEATURES: Tuple[str, ...] = (
    "unexpectedness",
    "sound_spike_intensity",
    "touch_intensity",
    "current_focus_level",
    "current_stability",
    "prior_prediction_error",
)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class MotionPolicy:
    """How perceived object MOTION becomes the being's approach STIMULUS (ADR 0027)
    — the tuning that normalizes raw kinematics (`Motion`) into the frozen 14-feature
    instinct vector (ADR 0026), plus the authored per-object kinematic SEEDS the
    world starts from. Both are authored in `config/motion.yaml`; like
    `EnvironmentPolicy`, one policy bundles the table (here, the seed motions) with
    the constants that read it.

    Normalization maxima map a raw quantity onto ``[0, 1]`` (distance, velocity,
    time-to-contact, object size) or a signed ``[-1, 1]`` rate (acceleration,
    size-change): a value at its max reads as 1.0. `min_closing_speed` is the gate
    on what counts as an *approach* — an object closing on the body faster than this
    raises a stimulus; anything slower, static, or receding raises none.
    `sensory_defaults` fills the features the world still has no source for (the
    being's internal state, 0.0 unless overridden). SENSORY-STIM adds two real
    sources this policy also owns: `sound_features` turns a sudden loud/unknown
    sound category into a `sound_spike_intensity` startle vector, and
    `contact_features` turns an object reaching the body (`is_contact`) into a
    `touch_intensity` vector — both config-driven (`sound:` / `contact:` in
    `config/motion.yaml`). Retuning any of it — or moving an object — is a config
    change only.
    """

    max_distance: float = 10.0
    max_speed: float = 5.0
    max_acceleration: float = 5.0
    max_time_to_contact: float = 10.0
    max_size: float = 1.0
    max_size_change_rate: float = 1.0
    min_closing_speed: float = 0.0
    sensory_defaults: Mapping[str, float] = field(default_factory=dict)
    motions: Mapping[str, Motion] = field(default_factory=dict)
    # SENSORY-STIM sourcing (extends ADR 0027): a sudden SOUND category becomes a
    # real `sound_spike_intensity` (+ the low-visibility / high-unexpectedness that
    # make it a startle), and an object reaching the body becomes a real
    # `touch_intensity`. `sound_spikes` maps a spike category -> its sensory
    # feature values; `contact_distance` is the body radius a crossing counts as a
    # touch (0 = contact sensing off); `contact_min_touch` floors how hard any real
    # contact feels; `contact_unexpectedness` is how startling an unforeseen touch is.
    sound_spikes: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    contact_distance: float = 0.0
    contact_min_touch: float = 0.0
    contact_unexpectedness: float = 0.0

    FEATURE_NAMES: ClassVar[Tuple[str, ...]] = MOTION_FEATURE_NAMES

    def initial_motions(self) -> Dict[str, Motion]:
        """A fresh per-object kinematic seed map — the world's starting motion,
        copied so the caller can advance it without touching the policy."""
        return dict(self.motions)

    def is_approaching(self, motion: Motion) -> bool:
        """Whether `motion` is an approach worth a stimulus (closing fast enough)."""
        return motion.is_approaching(self.min_closing_speed)

    def _default(self, name: str) -> float:
        return float(self.sensory_defaults.get(name, 0.0))

    def features(
        self, motion: Motion, prior: Optional[Motion], *, visibility_confidence: float
    ) -> Dict[str, float]:
        """The frozen 14-feature instinct vector for `motion`, normalized — the exact
        `MOTION_FEATURE_NAMES` keys, in order. `prior` (last tick's motion, or None on
        the first sighting) gives the between-tick rates (acceleration, looming).
        `visibility_confidence` is how clearly the being perceives the object (ADR
        0002). Features with no world source fall to their config default (0.0)."""
        speed = motion.speed()
        prior_speed = prior.speed() if prior is not None else speed
        acceleration = speed - prior_speed

        apparent = motion.apparent_size()
        prior_apparent = prior.apparent_size() if prior is not None else apparent
        size_change = apparent - prior_apparent

        ttc = motion.time_to_contact()
        ttc_norm = 1.0 if ttc == float("inf") else _clamp(ttc / self.max_time_to_contact, 0.0, 1.0)

        return {
            "distance": _clamp(motion.distance() / self.max_distance, 0.0, 1.0),
            "velocity": _clamp(speed / self.max_speed, 0.0, 1.0),
            "acceleration": _clamp(acceleration / self.max_acceleration, -1.0, 1.0),
            "trajectory_toward_body": _clamp(motion.trajectory_toward_body(), 0.0, 1.0),
            "time_to_contact": ttc_norm,
            "object_size": _clamp(motion.size / self.max_size, 0.0, 1.0),
            "size_change_rate": _clamp(size_change / self.max_size_change_rate, -1.0, 1.0),
            "unexpectedness": self._default("unexpectedness"),
            "visibility_confidence": _clamp(float(visibility_confidence), 0.0, 1.0),
            "sound_spike_intensity": self._default("sound_spike_intensity"),
            "touch_intensity": self._default("touch_intensity"),
            "current_focus_level": self._default("current_focus_level"),
            "current_stability": self._default("current_stability"),
            "prior_prediction_error": self._default("prior_prediction_error"),
        }

    def sound_features(self, category: Optional[str]) -> Optional[Dict[str, float]]:
        """The full 14-feature vector for a SUDDEN sound in `category` — a startle
        the being HEARS but cannot see. Every motion feature is null (distance and
        time-to-contact at their "nothing here" 1.0, the rest 0.0) and
        `sound_spike_intensity` / `unexpectedness` / `visibility_confidence` come
        from config — a loud/unknown sound reads as intense, unexpected, and
        unseen, exactly the shape the instinct model learned to FREEZE at (ADR
        0026). ``None`` when `category` names no configured spike, so an ordinary
        sound raises no stimulus. The internal-state features stay at their
        defaults (folded in later)."""
        spike = self.sound_spikes.get(category or "")
        if not spike:
            return None
        features = {name: self._default(name) for name in self.FEATURE_NAMES}
        features["distance"] = 1.0
        features["time_to_contact"] = 1.0
        features["sound_spike_intensity"] = _clamp(
            float(spike.get("sound_spike_intensity", 0.0)), 0.0, 1.0
        )
        features["unexpectedness"] = _clamp(float(spike.get("unexpectedness", 0.0)), 0.0, 1.0)
        features["visibility_confidence"] = _clamp(
            float(spike.get("visibility_confidence", 0.0)), 0.0, 1.0
        )
        return features

    def is_contact(self, prior_distance: float, distance: float) -> bool:
        """Whether an object CROSSED into contact this step — its distance fell from
        beyond the contact radius to at/within it. A crossing, not a steady state,
        so an object resting at the body is not a fresh contact every tick, and a
        being born already touching something is not startled by it. Contact sensing
        is off (never true) when `contact_distance` is 0."""
        if self.contact_distance <= 0.0:
            return False
        return prior_distance > self.contact_distance >= distance

    def contact_features(
        self, base: Mapping[str, float], *, impact_speed: float
    ) -> Dict[str, float]:
        """`base` (the object's normalized motion vector) with the CONTACT sensory
        signals layered on: a `touch_intensity` scaled by the impact speed
        (`impact_speed / max_speed`) but floored at `contact_min_touch` so any real
        contact is felt, and the config `contact_unexpectedness` that makes an
        unforeseen touch a startle — the shape the instinct model learned to
        WITHDRAW from (ADR 0026). The object's perceived visibility and kinematics
        are left exactly as `base` measured them."""
        features = dict(base)
        scaled = _clamp(float(impact_speed) / self.max_speed, 0.0, 1.0) if self.max_speed else 0.0
        features["touch_intensity"] = _clamp(max(self.contact_min_touch, scaled), 0.0, 1.0)
        features["unexpectedness"] = _clamp(self.contact_unexpectedness, 0.0, 1.0)
        return features


@dataclass(frozen=True)
class InstinctRuntimePolicy:
    """How the instinct CONSUMER (INS-RT, extends ADR 0011's shadow precedent to the
    instinct layer) turns a per-stimulus prediction into a selected protective
    REACTION — the reaction-selection tuning the model is forbidden to own (ADR
    0026: the model only predicts; selection, thresholds, and cooldowns are a
    downstream concern that can never bypass the safety floor). For each protective
    reaction label, `thresholds[label]` is the probability at or above which that
    reaction may fire, and `cooldowns[label]` is how many ticks must elapse after it
    fires before it may fire again — so one stimulus stream cannot machine-gun the
    same reaction. `shadow` is the record-only gate: ON (the default), the consumer
    persists and publishes its prediction/reaction but changes NO simulation
    behavior (decision / emotion / render untouched); the active integration that
    reads a `False` here is INS-ACT's, not this slice's. Every number lives in the
    `reaction:` block of `config/instinct.yaml`, so retuning instinct sensitivity —
    or flipping it out of shadow — is a config change, never a code one. An empty
    policy (no config) fires no reaction and stays in shadow: the safe default.
    """

    thresholds: Mapping[str, float] = field(default_factory=dict)
    cooldowns: Mapping[str, int] = field(default_factory=dict)
    shadow: bool = True

    def thresholded_labels(self) -> Tuple[str, ...]:
        """The reaction labels that CAN fire — those given a threshold, in authored
        order. A label with no configured threshold is never a candidate."""
        return tuple(self.thresholds.keys())

    def threshold(self, label: str) -> float:
        """The probability at or above which `label` fires; an unconfigured label
        gets an unreachable 1.0 so it never fires by accident."""
        return float(self.thresholds.get(label, 1.0))

    def cooldown(self, label: str) -> int:
        """How many ticks must elapse between firings of `label` (0 = no cooldown)."""
        return int(self.cooldowns.get(label, 0))


@dataclass(frozen=True)
class InstinctConsumePolicy:
    """How the DEPLOYED runtime PULLS pending events off a broker-backed EventBus
    each tick (KAFKA-RUNTIME-LOOP). On the in-memory default `publish` delivers
    synchronously, so nothing is pulled and this policy is inert; on the Kafka
    runtime `publish` only produces and handlers fire on `consume()`, which the tick
    loop must drive. Each tick the runtime polls a BOUNDED batch on the tick thread
    (never a background consumer that would race the single writer):
    `max_messages` caps how many events one tick pulls, and `poll_timeout_seconds`
    is how long each poll waits for a message before giving up — kept small so an
    idle tick is not stalled, since the chain self-heals over ticks (offsets committed
    only after handling, `earliest` reset). Both live in the `runtime.consume:` block
    of `config/instinct.yaml`, so tuning the runtime's poll cadence is a config change,
    never a code one."""

    max_messages: int = 16
    poll_timeout_seconds: float = 0.2


@dataclass(frozen=True)
class ReactionTemperamentPolicy:
    """How the being's EFFECTIVE instinct thresholds DRIFT with experience — the slow
    PERSONALIZATION of the reaction GATING owned by `InstinctRuntimePolicy` (adaptive
    temperament, INS-TEMPERAMENT, ADR 0031). Two harm-driven forces move a per-label
    threshold on the same saturating curve the v6 trait / ADR 0020 familiarity signals
    use, so sensitivity shifts fast at first and then settles:

    - HABITUATION: a startle that FIRES and proves HARMLESS (the being's `pain` did not
      rise that tick) nudges that label's threshold a `habituate_rate` fraction toward
      the `ceiling`, so a repeated harmless startle gradually STOPS firing (less
      reactive).
    - SENSITIZATION: a HARMFUL outcome (the being's `pain` spiked) nudges EVERY
      threshold a `sensitize_rate` fraction toward the `floor`, so the being is jumpier
      next time — a previously sub-threshold stimulus may now fire (more reactive).

        habituated = t + habituate_rate * (ceiling - t)
        sensitized = t - sensitize_rate * (t - floor)

    Both rates default 0.0 — no drift, so the effective threshold stays exactly the
    static `InstinctRuntimePolicy` one (byte-identical to the pre-slice consumer). Slow
    by construction, like the v6 traits. `floor`/`ceiling` bound the threshold in
    PROBABILITY space; they are NOT the SafetyService invariant floor — temperament only
    ever reshapes which REACTION fires, never whether an action is allowed (ADR
    0026/0029). Every number lives in the `reaction.temperament:` block of
    `config/instinct.yaml`, so retuning how fast a being habituates or sensitizes is a
    config change, never a code one.
    """

    habituate_rate: float = 0.0
    sensitize_rate: float = 0.0
    floor: float = 0.0
    ceiling: float = 1.0

    def habituate(self, threshold: float) -> float:
        """`threshold` after one harmless startle — nudged a `habituate_rate` fraction
        toward the ceiling (less reactive), clamped to ``[floor, ceiling]``. Rate 0
        returns it unchanged."""
        moved = float(threshold) + self.habituate_rate * (self.ceiling - float(threshold))
        return max(self.floor, min(self.ceiling, moved))

    def sensitize(self, threshold: float) -> float:
        """`threshold` after one harmful outcome — nudged a `sensitize_rate` fraction
        toward the floor (more reactive), clamped to ``[floor, ceiling]``. Rate 0
        returns it unchanged."""
        moved = float(threshold) - self.sensitize_rate * (float(threshold) - self.floor)
        return max(self.floor, min(self.ceiling, moved))


@dataclass(frozen=True)
class ReactionResponsePolicy:
    """How the being ACTS on a triggered instinct reaction (INS-ACT, ADR 0029) —
    the active counterpart to `InstinctRuntimePolicy`'s shadow selection. Staged
    behind two flags that BOTH default to the prior (byte-identical) behavior, so
    activation is a config change, never code:

    - `visual_only` (step 1): a triggered reaction is SURFACED in the being's state
      (the render `reaction` field) and BIASES the being's DERIVED emotion — a
      TRANSIENT affect signal fed into the same needs->emotion derivation (never an
      assignment), keyed per reaction label by `emotion_bias` (`label -> {need:
      delta}`). The stored needs are untouched; only the derivation input is nudged.
    - `allow_interrupt` (step 2): a reaction at or above `intensity_threshold` may
      CANCEL the current action when that action is in `interruptible_actions` AND
      the SafetyService permits the `protective_action` on the target. The invariant
      floor is never bypassed — an interruption the floor forbids is SUPPRESSED, not
      forced.

    Every value lives in the `reaction:` block of `config/instinct.yaml`; an empty
    policy (no config) leaves both steps off, so a reaction changes no behavior —
    the safe default.
    """

    visual_only: bool = False
    allow_interrupt: bool = False
    emotion_bias: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    intensity_threshold: float = 1.0
    interruptible_actions: Tuple[str, ...] = ()
    protective_action: str = "withdraw"

    @property
    def surfaces_reaction(self) -> bool:
        """Whether an active reaction is exposed at all — true once either step is
        on, so the `reaction` field never appears while both flags are off (the
        byte-identical default)."""
        return self.visual_only or self.allow_interrupt

    def bias_for(self, label: str) -> Mapping[str, int]:
        """The transient per-need affect signal a `label` reaction feeds into the
        emotion derivation; empty (no nudge) for a label with no configured bias."""
        return self.emotion_bias.get(label, {})

    def is_interruptible(self, action: str) -> bool:
        """Whether `action` is one the being may break off on a strong reaction."""
        return action in self.interruptible_actions


@dataclass(frozen=True)
class NarrationPhrasing:
    """How the deterministic narrator turns a structured memory/state fact into
    prose (S1, ADR 0032) — the WORD CHOICES only, held as config vocabulary
    (`config/language.yaml`), never in service code (the config-driven-tuning
    rule). Three lookup tables map the being's internal vocabulary to plain
    English: an action to its past-tense verb (`push -> pushed`), an outcome
    label to a clause (`causes_pain -> it hurt me`), and a derived emotion to a
    feeling word (`scared -> scared`). Each lookup falls back to the raw token,
    so an unmapped label still renders (grounded, if terse) rather than dropping
    — and retuning the being's voice is a YAML change, never a code one.
    """

    action_past: Mapping[str, str] = field(default_factory=dict)
    outcome_clause: Mapping[str, str] = field(default_factory=dict)
    feeling: Mapping[str, str] = field(default_factory=dict)

    def action(self, name: str) -> str:
        """The past-tense verb for an action; the raw name when unmapped."""
        return self.action_past.get(name, name)

    def outcome(self, label: str) -> str:
        """The plain clause for an observed outcome; the raw label when unmapped."""
        return self.outcome_clause.get(label, label)

    def feel(self, emotion: str) -> str:
        """The feeling word for a derived emotion; the raw emotion when unmapped."""
        return self.feeling.get(emotion, emotion)


@dataclass(frozen=True)
class SelfReportPolicy:
    """How the being reports its own experience (S1, ADR 0032), from the
    `narrator:`/`report:` blocks of `config/language.yaml`. `narrator_kind`
    selects the PROVIDER behind the shared `LanguageModelPort` — ``"deterministic"``
    (the offline template narrator, the default), ``"fake"`` (the in-memory test
    model), ``"claude"`` (the env-gated Claude adapter; ``"model"`` is a back-compat
    alias), or ``"local"`` (an Ollama-style local endpoint, S2). `recent_count` is
    how many of the most-recent memories a "what have you done recently?" report
    covers; `salience_emphasis_threshold` is the priority at or above which a
    memory's felt affect is emphasized. `fallback_to_template` (default ``True``)
    is the fallback-safe rule (mirroring `PredictionBlendPolicy`'s
    `fallback_to_rules_on_error`): when a selected model raises or is unavailable,
    the narrator degrades to the deterministic template — which sees the SAME
    structured-experience prompt, so the report stays grounded. Absent config
    yields the safe defaults (deterministic, 5, 1.0, fallback on), so retuning what
    the being says — and how it fails safe — is a config change only.
    """

    narrator_kind: str = "deterministic"
    recent_count: int = 5
    salience_emphasis_threshold: float = 1.0
    fallback_to_template: bool = True


@dataclass(frozen=True)
class LocalModelPolicy:
    """How the being's `local` narrator provider reaches a LOCALLY-served language
    model (S2, extends ADR 0022/0032) — the CLIENT config for an Ollama-style HTTP
    endpoint, from the `narrator.local:` block of `config/language.yaml`. `base_url`
    is the endpoint the client POSTs to (`{base_url}/api/generate`) and `model` the
    served model name; `base_url_env` names the environment variable that OVERRIDES
    `base_url` at deploy time (like `DATABASE_URL` — a deploy detail, not authored
    config), and `timeout_seconds` bounds the request. The model is not served here
    (that is reading R1/R2); this policy only wires the client, so with no endpoint
    the adapter refuses rather than blind-calls. Retuning where the being's local
    voice lives is a config/env change only.
    """

    base_url: str = ""
    model: str = ""
    base_url_env: str = "OLLAMA_BASE_URL"
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class SubjectQueryPolicy:
    """How the being answers a SUBJECT query — "what do you know / how do you feel
    about X?" (S3, ADR 0034), from the `subject:` block of `config/language.yaml`.
    `query_markers` are the connectives that INTRODUCE a subject in a question (the
    word after which the subject term begins — e.g. ``about`` in "what do you know
    *about* hot things"); a question with none is not a subject query and stays on
    the S1 recent-experience path. `max_facts` bounds how many learned facts an
    answer cites (the strongest concepts first). `unknown_response` is what the
    being says about a subject it has NO learned concept for — an honest
    no-knowledge line, never an invented one; ``{subject}`` is filled with the term.
    Absent config yields the safe defaults, so retuning how the being fields a
    subject — and how honestly it declines an unknown one — is a config change only.
    """

    query_markers: Tuple[str, ...] = ("about",)
    max_facts: int = 6
    unknown_response: str = (
        "I don't know anything about {subject} — I haven't encountered anything like that."
    )


@dataclass(frozen=True)
class VoicePolicy:
    """How the being SPEAKS its self-report aloud (S4, ADR 0035), from
    ``config/voice.yaml``. `engine` selects the `VoicePort` engine (the open-source
    ``espeak-ng`` by default; ``fake`` for a demo/test); `voice`/`rate`/`pitch` are
    the neutral voice the being speaks with, and `emotion_params` is the optional
    per-emotion override (a scared voice faster and higher, a sleepy one slower and
    lower) — so what the being SOUNDS like tracks how it FEELS. `params_for(emotion)`
    resolves the two into a `VoiceParams`, falling back to the neutral voice for an
    unmapped emotion. Every value lives in config, so retuning the being's voice — or
    switching engines — is a config change, never a code one (the config-driven-tuning
    rule); an absent file yields the safe espeak-ng defaults.
    """

    engine: str = "espeak-ng"
    voice: str = "en"
    rate: int = 175
    pitch: int = 50
    emotion_params: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    # Reading a whole DOCUMENT aloud (reading R8): the largest utterance the being
    # voices in one go — a long file is chunked to this before synthesis.
    read_aloud_max_chars: int = 2000

    def default_params(self) -> VoiceParams:
        """The neutral voice, before any emotion override."""
        return VoiceParams(voice=self.voice, rate=self.rate, pitch=self.pitch)

    def params_for(self, emotion: str) -> VoiceParams:
        """The voice for a being feeling `emotion` — the neutral voice with the
        emotion's authored `rate`/`pitch` override applied; the neutral voice for
        an emotion with no mapping."""
        override = self.emotion_params.get(str(emotion), {}) or {}
        return VoiceParams(
            voice=self.voice,
            rate=int(override.get("rate", self.rate)),
            pitch=int(override.get("pitch", self.pitch)),
        )


@dataclass(frozen=True)
class LoRAFinetunePolicy:
    """How the being LEARNS from a document it reads — the config for a host-native
    MLX-LM LoRA fine-tune of OUR OWN open-source base model (reading R1, ADR 0036),
    from the `finetune:` block of ``config/language.yaml``. It bundles three groups,
    all config-driven so retuning training never touches Python:

    - the MODEL: `base_model` (the open base to fine-tune, Qwen2.5-3B-Instruct by
      default) and `adapter_path` (where the trained LoRA adapter — "our model" — is
      saved);
    - INGEST: `max_chars` / `overlap` / `min_chunk_chars` shape the document into
      training-ready chunks, and `valid_fraction` is the held-out validation share;
    - LoRA TRAINING: `iters`, `batch_size`, `learning_rate`, `num_layers`, `rank`,
      `scale`, `dropout`, `max_seq_length`, `seed` — the MLX-LM LoRA hyperparameters.

    Plus SAMPLING: `sample_prompt` / `sample_max_tokens` drive the post-train
    generation so you can watch the model write in the corpus's style. The defaults
    match READING_VOICEBOX §6's test-scale choice, so the policy is usable even
    before the config file carries a `finetune` block.
    """

    base_model: str = "Qwen/Qwen2.5-3B-Instruct"
    adapter_path: str = "models/language/adapter"
    # ingest
    max_chars: int = 1000
    overlap: int = 100
    min_chunk_chars: int = 1
    valid_fraction: float = 0.1
    # LoRA training
    iters: int = 200
    batch_size: int = 4
    learning_rate: float = 1e-5
    num_layers: int = 8
    rank: int = 8
    scale: float = 20.0
    dropout: float = 0.0
    max_seq_length: int = 512
    seed: int = 0
    # sampling
    sample_prompt: str = "Tell me, in your own words, what you just read about:"
    sample_max_tokens: int = 200


@dataclass(frozen=True)
class OllamaServePolicy:
    """How OUR fine-tuned model is SERVED locally and reached behind the
    `LanguageModelPort` (reading R2, ADR 0037), from the `serve:` block of
    ``config/language.yaml`` — the host-native Mac pipeline that fuses R1's LoRA
    into the base, exports GGUF, and `ollama create`s a named model Ollama serves
    on :11434. `base_model` and `adapter_path` are REUSED from the `finetune:`
    block (one source of truth — R1's artifacts, never re-declared); this policy
    adds only the serving surface: `model_name` (the Ollama model created — it MUST
    equal `narrator.local.model`, so the `local` narrator calls our model),
    `fused_path` / `gguf_file` (the fuse + GGUF artifact locations, `gguf_path`
    joining them for the Modelfile `FROM`), `port` (Ollama's serve port, for the
    informative message), and the config-driven Ollama Modelfile knobs `params`
    (baked-in generation PARAMETERs) and `system` (an optional SYSTEM preamble) — so
    no generation value is hard-coded. The model is served only on a Mac with MLX +
    Ollama (the runner refuses loudly off-host); the defaults match
    READING_VOICEBOX §6, so the policy is usable before the config carries a
    `serve` block. Retuning what/how the being's voice is served is a config change
    only.
    """

    model_name: str = "jarvis-reader"
    base_model: str = "Qwen/Qwen2.5-3B-Instruct"
    adapter_path: str = "models/language/adapter"
    fused_path: str = "models/language/fused"
    gguf_file: str = "jarvis-reader-f16.gguf"
    port: int = 11434
    params: Mapping[str, object] = field(default_factory=dict)
    system: str = ""

    @property
    def gguf_path(self) -> str:
        """The full path to the exported GGUF (the Modelfile `FROM`): the GGUF file
        inside the fused-model directory."""
        return f"{self.fused_path.rstrip('/')}/{self.gguf_file}"


@dataclass(frozen=True)
class KnowledgeRetrievalPolicy:
    """How the being retrieves from its GROWING KNOWLEDGE STORE (reading R3, ADR
    0038), from the `retrieval:` block of ``config/language.yaml``. `embedder`
    selects how a passage becomes a vector -- ``"hashing"`` (the deterministic,
    OFFLINE bag-of-words embedder, the default) or ``"sentence-transformers"`` (the
    real semantic embedder, gated on the optional library). `dim` is the hashing
    embedder's vector dimension; `k` is how many passages a query retrieves by
    default; `model` is the sentence-transformers model to load (only when that
    embedder is selected). Distinct from the memory-recall `RetrievalPolicy` (card
    v6): this is the reading faculty's DOCUMENT store, not memory recall. The
    defaults are fully offline, so a config with no `retrieval:` block still
    retrieves; retuning what/how the being retrieves is a config change only --
    never a code one.
    """

    embedder: str = "hashing"
    dim: int = 256
    k: int = 4
    model: str = "BAAI/bge-small-en-v1.5"


@dataclass(frozen=True)
class ReadingQAPolicy:
    """How the being answers a question about what it has READ (reading R4, ADR
    0039), from the `reading_qa:` block of ``config/language.yaml``. Retrieval
    finds the top-`k` passages; a passage scoring below `min_relevance` is treated
    as not relevant, so a query that matches nothing the being has read yields the
    honest unread answer rather than a forced, ungrounded one. The rest are the
    VOCABULARY the answer is composed from (config-driven, never hard-coded):

    - `read_label` prefixes a grounded answer, and the retrieved passages' source
      document(s) are appended via `cite_template` (`{sources}` slot) -- so a
      grounded answer always says WHERE it read the fact.
    - `unread_response` (`{topic}` slot) is the honest line for a topic the being
      has not read about; `topic_markers` are the connective(s) after which the
      asked-about topic begins ("about" in "what do you know *about* dinosaurs").
    - `blend_base_knowledge` toggles whether an unread answer ALSO offers a
      base-knowledge answer (from the model, WITHOUT any retrieved context, so it
      can carry no citation), labelled with `base_label` so what the being READ is
      always distinguished from what it already KNEW.

    Absent config yields safe defaults, so retuning how the being answers -- and how
    honestly it declines the unread -- is a config change only. Distinct from
    `KnowledgeRetrievalPolicy` (that tunes the STORE; this tunes the ANSWER)."""

    k: int = 4
    min_relevance: float = 0.05
    unread_response: str = "I haven't read anything about {topic} yet."
    blend_base_knowledge: bool = True
    read_label: str = "From what I read"
    base_label: str = "From what I already knew"
    cite_template: str = "(source: {sources})"
    topic_markers: Tuple[str, ...] = ("about",)


@dataclass(frozen=True)
class ConversationPolicy:
    """How the being holds a MULTI-TURN conversation about what it has READ (reading
    R6, extends ADR 0039), from the `conversation:` block of ``config/language.yaml``.
    A conversation is built on single-turn reading QA; this policy tunes only what R6
    adds on top — HISTORY-AWARE grounding:

    - `followup_cues` are the referential words that mark a FOLLOW-UP — a message that
      refers back ("tell me more about *that*", "what *else*?") but names no subject of
      its own. Such a message has the recent turns' questions folded into its retrieval
      query, so it resolves to the subject established earlier and stays grounded +
      cited. A message with NONE of these cues stands alone, so a NEW topic — even one
      the being has not read about — is judged on its own words and declined honestly,
      never dragged onto a prior topic.
    - `history_window` bounds how many recent turns fold into a follow-up, so an old,
      unrelated exchange never bleeds into a fresh one.

    Absent config yields safe defaults, so retuning how far back the being looks and
    what counts as a follow-up is a config change only — never a code one."""

    history_window: int = 6
    followup_cues: Tuple[str, ...] = (
        "that", "it", "this", "they", "them", "those", "these",
        "more", "else", "again", "another",
    )

    def is_followup(self, message: str) -> bool:
        """Whether `message` refers BACK to the conversation rather than naming its
        own subject — true when it contains any referential `followup_cues` word."""
        tokens = set(re.findall(r"[a-z']+", str(message).lower()))
        return bool(tokens & {cue.lower() for cue in self.followup_cues})

    def recent(self, history: "Sequence") -> list:
        """The most recent turns to fold into a follow-up's query — the last
        `history_window` of them (all of them when the window is <= 0)."""
        turns = list(history)
        if self.history_window <= 0:
            return turns
        return turns[-self.history_window:]


@dataclass(frozen=True)
class ReadingPerceptionPolicy:
    """How a READ section becomes a validated perceptual OBSERVATION (reading R7,
    ADR 0040), from the `reading_perception:` block of ``config/language.yaml``.

    Reading changes the being only through the SAME perception/cognition door a
    lived interaction goes through -- never by letting language-model output write
    state (the language-on-top invariant, ADR 0022). This policy governs the
    deterministic, model-free bridge from a document's text to that door:

    - SECTIONING -- `section_max_chars` / `section_overlap` / `min_section_chars`
      chunk a document into the sections the being reads one at a time (reusing the
      R1 ingest chunker), so a long document is MANY observations, not one.
    - PERCEPTION -- from a section's text the being perceives its salient CONTENT
      TOKENS: lowercased word tokens at least `min_token_length` long, minus the
      `stopwords`, the `max_tokens` most frequent (ties broken by first appearance,
      so extraction is order-stable and deterministic). These are the perceived
      properties the memory/concept key on; the source/developer label is never
      among them (ADR 0002).
    - COGNITION -- `action` is the reading action the observation is VALIDATED as
      (through the ActionValidationService), and `outcome` is the reading outcome a
      read section yields, so a token that recurs across sections builds a
      (token -> outcome) concept exactly as repeated interactions strengthen one.

    Absent config yields safe defaults, so retuning what the being takes from a
    document is a config change only -- never a code one."""

    action: str = "read"
    outcome: str = "informs"
    max_tokens: int = 6
    min_token_length: int = 4
    section_max_chars: int = 120
    section_overlap: int = 0
    min_section_chars: int = 1
    stopwords: Tuple[str, ...] = (
        "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at", "for",
        "with", "from", "by", "as", "is", "are", "was", "were", "be", "been",
        "being", "it", "its", "this", "that", "these", "those", "they", "them",
        "their", "when", "then", "than", "so", "if", "we", "you", "your", "he",
        "she", "his", "her", "do", "does", "did", "has", "have", "had", "will",
        "would", "can", "could", "not", "no", "yes", "there", "here", "what",
        "which", "who", "whom", "into", "over", "under", "about",
    )

    def salient_tokens(self, text: str) -> Tuple[str, ...]:
        """The content tokens the being PERCEIVES of `text` -- a deterministic,
        model-free reading of the section into its most-frequent meaningful words.

        Lowercased word tokens shorter than `min_token_length` or in `stopwords` are
        dropped; the rest are ranked by frequency (ties broken by first appearance),
        and the top `max_tokens` are returned in that order. No model, no network --
        so what the being takes from a section is fixed by the text, never invented.
        """
        words = re.findall(r"[a-z0-9]+", str(text).lower())
        stops = {word.lower() for word in self.stopwords}
        counts: Dict[str, int] = {}
        first_index: Dict[str, int] = {}
        for index, word in enumerate(words):
            if len(word) < self.min_token_length or word in stops:
                continue
            if word not in counts:
                counts[word] = 0
                first_index[word] = index
            counts[word] += 1
        ranked = sorted(counts, key=lambda word: (-counts[word], first_index[word]))
        return tuple(ranked[: self.max_tokens])


@dataclass(frozen=True)
class ConsolidationPolicy:
    """How the being CONSOLIDATES what it has read into its own weights on its
    'sleep' cycle (reading R5, ADR 0041), from the `consolidation:` block of
    ``config/language.yaml``.

    Consolidation is the being's "learn it for good" step: on the sleep cycle it
    LoRA-fine-tunes over Q/A pairs synthesized FROM its accumulated knowledge store,
    so recurring facts are baked into the model itself (recalled WITHOUT retrieval),
    not only held in the retrieval store. This policy governs when it fires and how
    its training set is built:

    - `enabled` gates the whole thing. The default is OFF, so the shipped tick is
      byte-identical — turning consolidation on is a config change only.
    - `sleep_threshold` is the `sleep` need level (>=) that marks the sleep cycle;
      the trigger fires on the RISING EDGE across it (the being just fell asleep). It
      defaults to 80, the same level that reads as the `sleepy` emotion.
    - `pair_count` caps how many consolidation pairs are synthesized per pass (the
      strongest / first accumulated chunks).
    - `synthesis_prompt` (`{passage}` slot) is what the build-time model is asked to
      turn each knowledge chunk into a Q/A pair with; `pair_template`
      (`{passage}`/`{completion}` slots) shapes the model's completion into the
      training line. Runtime inference stays local — the synthesis model (Claude) is
      a BUILD/HOST-time data step, never the being's runtime voice.
    - `source` is the dataset label the consolidation training set carries.

    Absent config yields these safe, disabled defaults, so retuning consolidation —
    and turning it on — is a config change only, never a code one."""

    enabled: bool = False
    sleep_threshold: int = 80
    pair_count: int = 32
    synthesis_prompt: str = (
        "From the following passage the being has read, write ONE factual question "
        "and its answer, as 'Q: <question>\nA: <answer>'. Answer only from the passage.\n\n"
        "Passage:\n{passage}"
    )
    pair_template: str = "{completion}"
    source: str = "consolidation"

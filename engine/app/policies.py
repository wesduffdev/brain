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
    `default` visual, and the per-emotion visual draw hints keyed by emotion.
    Pure presentation vocabulary — it carries no psychology; the emotion is
    already decided before these hints are looked up.
    """

    intensity_default: float
    default: Mapping[str, object]
    by_emotion: Mapping[str, Mapping[str, object]]


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

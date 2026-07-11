"""ConfigService — the one place that knows configuration exists.

It turns authored config (YAML files, or a dict in tests) into typed policies
the services consume. Consumers never see file paths, YAML, or raw dicts; they
ask for `need_policies()`, `emotion_rules()`, and so on. This is the seam the
brief calls for: fine-tuning happens in `config/*.yaml`, and only this module
changes shape if the config format ever does.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

from app.domain.object_entity import ObjectEntity
from app.domain.room import Room
from app.policies import (
    ActionPolicy,
    BeliefDecisionPolicy,
    CommandSpec,
    ConceptLearningPolicy,
    CuriosityWeights,
    EmotionRule,
    EnvironmentPolicy,
    ExplorationPolicy,
    GraphEdgePolicy,
    InstinctModelPolicy,
    MemoryPriorityPolicy,
    NeedTickPolicy,
    OutcomeEffectPolicy,
    PredictionBlendPolicy,
    PreferencePolicy,
    RenderHintsPolicy,
    RetrievalPolicy,
    SafetyRule,
    SurprisePolicy,
    TraitDriftPolicy,
    TraitPolicy,
)

# Trainer tuning defaults, used when outcome_labels.yaml omits a `training` key
# (e.g. the from_dict tests). The authored config overrides these.
_DEFAULT_TRAINING = {"epochs": 300, "hidden_size": 16, "learning_rate": 0.05, "seed": 0}


class ConfigService:
    # The authored config sections, declared in ONE place. `tick_rates` and
    # `emotions` are required; every other section defaults to empty when absent.
    # Adding a section is a one-line change here: construction stores it and the
    # copy `with_room_contents` makes carries it through — neither has to name the
    # section individually, so a section can never be silently dropped (the
    # demo-caught V0-SAFE regression that motivated this shape).
    _REQUIRED_SECTIONS: Tuple[str, ...] = ("tick_rates", "emotions")
    _OPTIONAL_SECTIONS: Tuple[str, ...] = (
        "rooms",
        "objects",
        "environment",
        "render_hints",
        "commands",
        "outcome",
        "actions",
        "safety",
        "outcome_effects",
        "learning_rates",
        "decision_weights",
        "traits",
        "instinct",
    )
    _SECTIONS: Tuple[str, ...] = _REQUIRED_SECTIONS + _OPTIONAL_SECTIONS

    def __init__(self, **sections: Optional[Mapping]):
        """Build from the declared config sections, passed by name. Internal:
        callers construct via `from_dict` / `from_files` (public) or the `_with`
        copy — the public construction API stays those, so a new section threads
        through this one storage loop rather than a positional argument list."""
        unknown = set(sections) - set(self._SECTIONS)
        if unknown:
            raise ValueError(
                f"ConfigService: unknown config section(s) {sorted(unknown)}; "
                f"known sections are {list(self._SECTIONS)}"
            )
        missing = [name for name in self._REQUIRED_SECTIONS if sections.get(name) is None]
        if missing:
            raise ValueError(f"ConfigService: missing required config section(s) {missing}")
        # One representation, keyed by the declared section names. Absent optional
        # sections become empty so accessors need no per-call None-guards.
        for name in self._SECTIONS:
            value = sections.get(name)
            setattr(self, f"_{name}", value if value is not None else {})

    def _with(self, **overrides: Mapping) -> "ConfigService":
        """Return a copy of this config with the named sections replaced and
        every OTHER section carried through unchanged. The single place a copy is
        built: it enumerates the declared section set, so a copy can never
        silently drop a section."""
        sections = {name: getattr(self, f"_{name}") for name in self._SECTIONS}
        sections.update(overrides)
        return ConfigService(**sections)

    # --- construction -----------------------------------------------------

    @classmethod
    def from_dict(
        cls,
        tick_rates: Mapping,
        emotions: Mapping,
        rooms: Optional[Mapping] = None,
        objects: Optional[Mapping] = None,
        environment: Optional[Mapping] = None,
        render_hints: Optional[Mapping] = None,
        commands: Optional[Mapping] = None,
        outcome: Optional[Mapping] = None,
        actions: Optional[Mapping] = None,
        safety: Optional[Mapping] = None,
        outcome_effects: Optional[Mapping] = None,
        learning_rates: Optional[Mapping] = None,
        decision_weights: Optional[Mapping] = None,
        traits: Optional[Mapping] = None,
        instinct: Optional[Mapping] = None,
    ) -> "ConfigService":
        """Build from already-parsed config. Used by tests so behavior is
        pinned to explicit values, not to whatever the shipped files hold."""
        return cls(
            tick_rates=tick_rates,
            emotions=emotions,
            rooms=rooms,
            objects=objects,
            environment=environment,
            render_hints=render_hints,
            commands=commands,
            outcome=outcome,
            actions=actions,
            safety=safety,
            outcome_effects=outcome_effects,
            learning_rates=learning_rates,
            decision_weights=decision_weights,
            traits=traits,
            instinct=instinct,
        )

    @classmethod
    def from_files(cls, config_root: str) -> "ConfigService":
        """Load the authored YAML under `config_root`. `yaml` is imported here,
        lazily, so the pure-Python core imports with zero third-party deps."""
        import yaml  # noqa: PLC0415 — kept out of module import path on purpose

        root = Path(config_root)
        # Section name -> the YAML file it is authored in. One entry per declared
        # section; adding a section adds its filename here (its only file-facing
        # site) and the loader threads it through unchanged.
        files = {
            "tick_rates": "tick_rates.yaml",
            "emotions": "emotions.yaml",
            "rooms": "rooms.yaml",
            "objects": "object_properties.yaml",
            "environment": "environment.yaml",
            "render_hints": "render_hints.yaml",
            "commands": "commands.yaml",
            "outcome": "outcome_labels.yaml",
            "actions": "actions.yaml",
            "safety": "safety_rules.yaml",
            "outcome_effects": "outcome_effects.yaml",
            "learning_rates": "learning_rates.yaml",
            "decision_weights": "decision_weights.yaml",
            "traits": "traits.yaml",
            "instinct": "instinct.yaml",
        }
        sections = {
            name: yaml.safe_load((root / filename).read_text())
            for name, filename in files.items()
        }
        return cls(**sections)

    # --- ticks / needs ----------------------------------------------------

    def tick_duration_ms(self) -> int:
        return int(self._tick_rates["tick"]["duration_ms"])

    def need_policies(self) -> Dict[str, NeedTickPolicy]:
        policies: Dict[str, NeedTickPolicy] = {}
        for name, spec in self._tick_rates["needs"].items():
            policies[name] = NeedTickPolicy(
                name=name,
                direction=spec["direction"],
                amount=int(spec["amount"]),
                every_ticks=int(spec["every_ticks"]),
                min_value=int(spec["min"]),
                max_value=int(spec["max"]),
                start=int(spec["start"]),
            )
        return policies

    def initial_needs(self) -> Dict[str, int]:
        return {name: policy.start for name, policy in self.need_policies().items()}

    # --- emotions ---------------------------------------------------------

    def emotion_rules(self) -> List[EmotionRule]:
        return [
            EmotionRule(
                emotion=rule["emotion"],
                need=rule["need"],
                op=rule["op"],
                value=int(rule["value"]),
            )
            for rule in self._emotions.get("rules", [])
        ]

    def default_emotion(self) -> str:
        return self._emotions.get("default", "calm")

    # --- world: room + objects -------------------------------------------

    def room(self) -> Room:
        """The one room the being lives in, as world-truth. An absent config
        yields an empty room (no objects, no conditions) so the pure
        need/emotion tests need not describe a world."""
        spec = self._rooms.get("room", {}) or {}
        return Room(
            room_id=str(spec.get("id", "room_001")),
            contains=tuple(spec.get("contains", []) or []),
            base_confidence=float(spec.get("base_confidence", 1.0)),
            light=spec.get("light"),
            sound=spec.get("sound"),
            temperature=spec.get("temperature"),
        )

    # --- environment ------------------------------------------------------

    def environment_policy(self) -> EnvironmentPolicy:
        """How the room's conditions push contextual needs. An absent config
        yields an empty policy that moves nothing, so the pure tests (and the
        no-environment slices before this one) behave unchanged."""
        impacts = {
            dimension: {
                category: {need: int(delta) for need, delta in (deltas or {}).items()}
                for category, deltas in (categories or {}).items()
            }
            for dimension, categories in self._environment.items()
            if dimension != "every_ticks"
        }
        return EnvironmentPolicy(
            every_ticks=int(self._environment.get("every_ticks", 0)),
            impacts=impacts,
        )

    def object_catalog(self) -> Dict[str, ObjectEntity]:
        """Every object definition, keyed by id. The `properties`/`affordances`
        lists in the config are the vocabulary — the single source of truth for
        what a property even is — so an object may not claim one outside it."""
        vocab_properties = set(self._objects.get("properties", []) or [])
        vocab_affordances = set(self._objects.get("affordances", []) or [])

        catalog: Dict[str, ObjectEntity] = {}
        for object_id, spec in (self._objects.get("objects", {}) or {}).items():
            properties = tuple(spec.get("properties", []) or [])
            affordances = tuple(spec.get("affordances", []) or [])

            unknown_properties = set(properties) - vocab_properties
            if unknown_properties:
                raise ValueError(
                    f"object {object_id!r}: properties {sorted(unknown_properties)} "
                    f"are not in the vocabulary"
                )
            unknown_affordances = set(affordances) - vocab_affordances
            if unknown_affordances:
                raise ValueError(
                    f"object {object_id!r}: affordances {sorted(unknown_affordances)} "
                    f"are not in the vocabulary"
                )

            catalog[str(object_id)] = ObjectEntity(
                object_id=str(object_id),
                developer_label=str(spec.get("developerLabel", "")),
                properties=properties,
                affordances=affordances,
            )
        return catalog

    def resolve_object(self, selector: str) -> str:
        """Map a human-typed selector (`ball`, `Red Ball`, `obj_red_ball`) to a
        catalogued object id. Matches an exact id, the id without its `obj_`
        prefix, or a unique substring of either the id or the developer label —
        so `make demo OBJ=ball` finds `obj_red_ball`. Fails loud (same discipline
        as the catalog) when nothing matches or the match is ambiguous."""
        catalog = self.object_catalog()
        norm = selector.strip().lstrip("-").strip().lower().replace(" ", "_")
        if not norm:
            raise ValueError("empty object selector")

        def short(object_id: str) -> str:
            return object_id.lower()[4:] if object_id.lower().startswith("obj_") else object_id.lower()

        for object_id in catalog:
            if norm in (object_id.lower(), short(object_id)):
                return object_id

        matches = [
            object_id
            for object_id, obj in catalog.items()
            if norm in short(object_id) or norm in obj.developer_label.lower().replace(" ", "_")
        ]
        if len(matches) == 1:
            return matches[0]

        choices = ", ".join(sorted(short(object_id) for object_id in catalog))
        if not matches:
            raise ValueError(f"no object matches {selector!r}; try one of: {choices}")
        raise ValueError(
            f"object selector {selector!r} is ambiguous ({', '.join(sorted(matches))}); "
            f"be more specific — one of: {choices}"
        )

    def with_room_contents(self, object_ids: List[str]) -> "ConfigService":
        """Return a copy of this config whose room contains exactly `object_ids`
        and nothing else — the seam the demo uses to put the being alone with one
        object. Every id must be catalogued (fail-loud). All other config
        (needs, actions, safety, the room's own conditions) is carried through
        unchanged."""
        import copy  # noqa: PLC0415 — only needed on this rarely-used path

        ids = list(object_ids)
        catalog = self.object_catalog()
        unknown = [object_id for object_id in ids if object_id not in catalog]
        if unknown:
            known = ", ".join(sorted(catalog))
            raise ValueError(f"unknown object id(s) {unknown}; known objects: {known}")

        rooms = copy.deepcopy(dict(self._rooms)) if self._rooms else {}
        room = dict(rooms.get("room") or {})
        room["contains"] = ids
        rooms["room"] = room
        # Replace ONLY the rooms section; `_with` carries every other section
        # through unchanged, so none can be silently dropped here.
        return self._with(rooms=rooms)

    # --- actions / safety (the decision + guardrail seam, ADR 0009) -------

    def action_policies(self) -> Dict[str, ActionPolicy]:
        """Every action the being can take, keyed by name, in authored order.
        Utility weights + outcome rules come from `actions.yaml`; the timing
        (duration/cooldown) from the `actions` block of `tick_rates.yaml` — the
        single tuning surface for time (BRIEF §10). An action either is `free`
        (self-directed, no affordance) or names an object affordance from the
        vocabulary; the outcomes it references must be real outcome labels. An
        absent file yields no actions (so pre-decision slices are unchanged)."""
        affordance_vocab = set(self._objects.get("affordances", []) or [])
        outcome_vocab = set(self.outcome_labels())
        timing = self._tick_rates.get("actions", {}) or {}

        def _check_outcome(action_name: str, outcome: str) -> None:
            if outcome_vocab and outcome not in outcome_vocab:
                raise ValueError(
                    f"action {action_name!r}: outcome {outcome!r} is not in the "
                    f"outcome vocabulary (config/outcome_labels.yaml)"
                )

        policies: Dict[str, ActionPolicy] = {}
        for name, raw in (self._actions.get("actions", {}) or {}).items():
            spec = raw or {}
            free = bool(spec.get("free", False))
            affordance = None if free else spec.get("affordance")
            if not free and affordance is None:
                raise ValueError(
                    f"action {name!r}: must be `free: true` or name an `affordance`"
                )
            if affordance is not None and affordance_vocab and affordance not in affordance_vocab:
                raise ValueError(
                    f"action {name!r}: affordance {affordance!r} is not in the vocabulary"
                )

            utility = spec.get("utility", {}) or {}
            expected = tuple(spec.get("expected_outcomes", []) or [])
            property_outcomes = {
                str(prop): tuple(outcomes or [])
                for prop, outcomes in (spec.get("property_outcomes", {}) or {}).items()
            }
            for outcome in expected:
                _check_outcome(name, outcome)
            for outcomes in property_outcomes.values():
                for outcome in outcomes:
                    _check_outcome(name, outcome)

            time_spec = timing.get(name, {}) or {}
            policies[str(name)] = ActionPolicy(
                name=str(name),
                affordance=affordance,
                base=float(utility.get("base", 0.0)),
                need_weights={n: float(w) for n, w in (utility.get("needs", {}) or {}).items()},
                emotion_bonuses={e: float(b) for e, b in (utility.get("emotions", {}) or {}).items()},
                expected_outcomes=expected,
                property_outcomes=property_outcomes,
                reason=str(spec.get("reason", "")),
                duration_ticks=int(time_spec.get("duration_ticks", 0)),
                cooldown_ticks=int(time_spec.get("cooldown_ticks", 0)),
            )
        return policies

    def safety_rules(self) -> Tuple[SafetyRule, ...]:
        """The hard guardrails SafetyService enforces (ADR 0009), in authored
        order. A rule's `blocked_property` must be a real object property — the
        same fail-loud vocabulary discipline as the object catalog. An absent
        file yields no rules."""
        property_vocab = set(self._objects.get("properties", []) or [])
        rules = []
        for spec in (self._safety.get("rules", []) or []):
            prop = str(spec["blocked_property"])
            if property_vocab and prop not in property_vocab:
                raise ValueError(
                    f"safety rule: blocked_property {prop!r} is not in the vocabulary"
                )
            rules.append(
                SafetyRule(
                    action=str(spec["action"]),
                    blocked_property=prop,
                    reason=str(spec.get("reason", "")),
                )
            )
        return tuple(rules)

    def outcome_effects(self) -> OutcomeEffectPolicy:
        """How each outcome felt-consequence pushes the being's needs (ADR 0014):
        the config that turns a harmful action into real, possibly-lasting
        deltas (pain up, safety/comfort down) instead of a hard block. An effect
        keyed to an outcome outside the label vocabulary (outcome_labels.yaml) is
        rejected at load, the same fail-loud discipline as the object catalog. An
        absent file moves nothing (so pre-V0-SAFE slices behave unchanged)."""
        label_vocab = set(self.outcome_labels())
        effects: Dict[str, Dict[str, int]] = {}
        for outcome, deltas in (self._outcome_effects.get("effects", {}) or {}).items():
            if label_vocab and outcome not in label_vocab:
                raise ValueError(
                    f"outcome effect: {outcome!r} is not a known outcome label "
                    f"(config/outcome_labels.yaml)"
                )
            effects[str(outcome)] = {
                str(need): int(delta) for need, delta in (deltas or {}).items()
            }
        return OutcomeEffectPolicy(effects=effects)

    # --- learning: memory salience ---------------------------------------

    def memory_priority_policy(self) -> MemoryPriorityPolicy:
        """How the being scores the PRIORITY (salience) of a memory (card v1),
        from the `memory.priority` block of `learning_rates.yaml`. Surprise (the
        prediction error) and emotional intensity weight the score; the
        per-emotion intensity table says how strongly each emotion is felt.
        Absent config yields the neutral default (``priority == prediction_error``),
        so a sim with no learning-rates file still forms memories. Retuning what
        the being holds onto is a config change only."""
        priority = (self._learning_rates.get("memory", {}) or {}).get("priority", {}) or {}
        return MemoryPriorityPolicy(
            baseline=float(priority.get("baseline", 0.0)),
            prediction_error_weight=float(priority.get("prediction_error_weight", 1.0)),
            emotion_intensity_weight=float(priority.get("emotion_intensity_weight", 1.0)),
            emotion_intensity={
                str(emotion): float(value)
                for emotion, value in (priority.get("emotion_intensity", {}) or {}).items()
            },
        )

    def concept_learning_policy(self) -> ConceptLearningPolicy:
        """How the being forms and strengthens CONCEPT SCHEMAS (card v2), from the
        `concept.learning` block of `learning_rates.yaml`. `seed_confidence` is the
        confidence a concept takes on its first sighting; `reinforce_rate` is how
        far each confirming interaction moves it toward full certainty. Absent
        config yields the neutral default (seed 0.3, rate 0.2), so a sim with no
        learning-rates file still generalizes. Retuning how fast the being commits
        to a pattern is a config change only."""
        learning = (self._learning_rates.get("concept", {}) or {}).get("learning", {}) or {}
        return ConceptLearningPolicy(
            seed_confidence=float(learning.get("seed_confidence", 0.3)),
            reinforce_rate=float(learning.get("reinforce_rate", 0.2)),
            intensity_gain=float(learning.get("intensity_gain", 0.0)),
        )

    def belief_decision_policy(self) -> BeliefDecisionPolicy:
        """How strongly the being's concept-derived BELIEFS steer its decision (card
        AVERSIVE-LEARN), from the `belief.decision` block of `learning_rates.yaml`.
        `discomfort_weight` defaults to ``0.0`` — so with no config the being forms
        beliefs but decides on utility exactly as before; only an opt-in weight turns
        the cognitive avoidance of anticipated harm on. Retuning it is a config
        change only."""
        decision = (self._learning_rates.get("belief", {}) or {}).get("decision", {}) or {}
        return BeliefDecisionPolicy(
            discomfort_weight=float(decision.get("discomfort_weight", 0.0)),
        )

    def graph_edge_policy(self) -> GraphEdgePolicy:
        """How the being's CONCEPT-GRAPH EDGES form and strengthen (card v7), from
        the `graph.edge` block of `learning_rates.yaml`. `seed_confidence` is an
        edge's confidence the first time it is laid down; `reinforce_rate` is how
        far each confirming interaction moves it toward full certainty. Absent
        config yields the neutral default (seed 0.3, rate 0.2), so a sim with no
        learning-rates file still builds a strengthening graph. Retuning how boldly
        the graph commits to a relationship is a config change only."""
        edge = (self._learning_rates.get("graph", {}) or {}).get("edge", {}) or {}
        return GraphEdgePolicy(
            seed_confidence=float(edge.get("seed_confidence", 0.3)),
            reinforce_rate=float(edge.get("reinforce_rate", 0.2)),
        )

    # --- decision weights: curiosity / surprise / exploration (card v4) ---

    def curiosity_weights(self) -> CuriosityWeights:
        """How the being's CURIOSITY is composed from novelty, uncertainty, recent
        surprise, and familiarity (card v4), from the `curiosity:` block of
        `decision_weights.yaml`. Absent config yields neutral defaults, so a sim
        with no decision-weights file still feels curiosity. Retuning how curious /
        novelty-seeking the being is is a config change only."""
        curiosity = self._decision_weights.get("curiosity", {}) or {}
        return CuriosityWeights(
            novelty=float(curiosity.get("novelty", 1.0)),
            uncertainty=float(curiosity.get("uncertainty", 1.0)),
            recent_surprise=float(curiosity.get("recent_surprise", 1.0)),
            familiarity=float(curiosity.get("familiarity", 1.0)),
            familiarity_rate=float(curiosity.get("familiarity_rate", 0.3)),
        )

    def surprise_policy(self) -> SurprisePolicy:
        """How fast a recorded SURPRISE fades each tick (card v4), from the
        `surprise:` block. Absent config keeps the neutral default decay."""
        surprise = self._decision_weights.get("surprise", {}) or {}
        return SurprisePolicy(decay=float(surprise.get("decay", 0.7)))

    def exploration_policy(self) -> ExplorationPolicy:
        """How the exploration drive adjusts action scores (card v4), from the
        `exploration:` block. `curiosity_weight` defaults to ``0.0`` — so with no
        decision-weights file the adjustment is zero for every action and the being
        decides on pure utility exactly as before (the pre-v4 baseline). Retuning
        how strongly curiosity steers the being is a config change only."""
        exploration = self._decision_weights.get("exploration", {}) or {}
        return ExplorationPolicy(
            curiosity_weight=float(exploration.get("curiosity_weight", 0.0)),
            discomfort_weight=float(exploration.get("discomfort_weight", 1.0)),
            action_weights={
                str(action): float(weight)
                for action, weight in (exploration.get("action_weights", {}) or {}).items()
            },
            default_action_weight=float(exploration.get("default_action_weight", 0.0)),
        )

    # --- learning: memory retrieval, preference, and personality traits (v6) ---

    def retrieval_policy(self) -> RetrievalPolicy:
        """How strongly the being RECALLS a memory for the object it now perceives
        (card v6), from the `preference:` block of `traits.yaml`. Absent config
        yields neutral defaults (property similarity + same object, strict same
        action, no salience amplification). Retuning what the being recalls is a
        config change only."""
        preference = self._traits.get("preference", {}) or {}
        return RetrievalPolicy(
            similarity_weight=float(preference.get("similarity_weight", 1.0)),
            same_object_weight=float(preference.get("same_object_weight", 1.0)),
            same_action_floor=float(preference.get("same_action_floor", 0.0)),
            salience_weight=float(preference.get("salience_weight", 0.0)),
        )

    def preference_policy(self) -> PreferencePolicy:
        """How strongly recalled memories bias the decision (card v6), from the same
        `preference:` block. `weight` defaults to ``0.0`` — so a config with no
        `traits` section forms and stores memories but decides on pure utility
        exactly as before (the pre-v6 baseline). Retuning how much the past steers
        the present is a config change only."""
        preference = self._traits.get("preference", {}) or {}
        return PreferencePolicy(weight=float(preference.get("weight", 0.0)))

    def trait_policy(self) -> TraitPolicy:
        """The being's slow-drifting personality (card v6), from the `traits:` block:
        a caution and a curiosity tendency, each with a start level, a drift rate,
        and a decision gain. Absent config yields neutral (zero-drift, zero-gain)
        traits, so a sim with no `traits` section has a personality that neither
        drifts nor steers behaviour — byte-identical to the pre-v6 baseline. Retuning
        temperament is a config change only."""
        traits = self._traits.get("traits", {}) or {}
        return TraitPolicy(
            caution=self._trait_drift(traits.get("caution", {}) or {}),
            curiosity=self._trait_drift(traits.get("curiosity", {}) or {}),
        )

    @staticmethod
    def _trait_drift(spec: Mapping) -> TraitDriftPolicy:
        return TraitDriftPolicy(
            start=float(spec.get("start", 0.0)),
            drift_rate=float(spec.get("drift_rate", 0.0)),
            decision_gain=float(spec.get("decision_gain", 0.0)),
            min=float(spec.get("min", 0.0)),
            max=float(spec.get("max", 1.0)),
        )

    # --- render / commands ------------------------------------------------

    def render_hints(self) -> RenderHintsPolicy:
        """The presentation hints RenderStateService maps emotion onto (ADR
        0004). An absent config yields a neutral default so the pure model tests
        need not describe presentation."""
        return RenderHintsPolicy(
            intensity_default=float(self._render_hints.get("intensity_default", 0.5)),
            default=dict(self._render_hints.get("default", {}) or {}),
            by_emotion={
                name: dict(hint or {})
                for name, hint in (self._render_hints.get("emotions", {}) or {}).items()
            },
        )

    def command_specs(self) -> Dict[str, CommandSpec]:
        """The v0 player-command vocabulary CommandService validates against
        (ADR 0004), keyed by command name."""
        specs: Dict[str, CommandSpec] = {}
        for name, spec in (self._commands.get("commands", {}) or {}).items():
            specs[str(name)] = CommandSpec(
                name=str(name),
                requires_target=bool((spec or {}).get("requires_target", False)),
            )
        return specs

    # --- ML: the outcome predictor's feature/label vocabulary ------------
    #
    # The object property/affordance vocabularies double as the ML feature
    # vocabulary (an object's properties and the action taken on it); the
    # outcome labels and situational context features live in
    # outcome_labels.yaml. These expose them, in authored order, as the fixed
    # encode contract the FeatureEncoder is built from (ADR 0008).

    def object_property_vocab(self) -> Tuple[str, ...]:
        return tuple(self._objects.get("properties", []) or [])

    def object_action_vocab(self) -> Tuple[str, ...]:
        return tuple(self._objects.get("affordances", []) or [])

    def outcome_labels(self) -> Tuple[str, ...]:
        return tuple(self._outcome.get("labels", []) or [])

    def outcome_context_features(self) -> Tuple[str, ...]:
        return tuple(self._outcome.get("context_features", []) or [])

    def prediction_threshold(self) -> float:
        """The probability at or above which a shadow-mode prediction counts an
        outcome as predicted (ADR 0011). Config-driven so retuning shadow-mode
        sensitivity never touches Python; defaults to 0.5 (ADR 0008's eval
        threshold) when unset."""
        prediction = self._outcome.get("prediction", {}) or {}
        return float(prediction.get("threshold", 0.5))

    def prediction_policy(self) -> PredictionBlendPolicy:
        """How the decision layer blends the neural and rule-based predictors
        (card v3), from the same `prediction:` block. `neural_enabled` defaults to
        ``False`` — so prediction stays observational (shadow) until the config is
        flipped to active — and the weights default to an even 50/50 blend with
        fallback-to-rules on error. Retuning the blend, or activating the model,
        is a config change only."""
        prediction = self._outcome.get("prediction", {}) or {}
        return PredictionBlendPolicy(
            neural_enabled=bool(prediction.get("neural_enabled", False)),
            neural_weight=float(prediction.get("neural_weight", 0.5)),
            rule_weight=float(prediction.get("rule_weight", 0.5)),
            fallback_to_rules_on_error=bool(prediction.get("fallback_to_rules_on_error", True)),
        )


    # --- ML: the instinct model's feature/label contract + tuning (ADR 0026) ---
    #
    # The instinct model is a SEPARATE net from the outcome predictor, with a
    # disjoint input space: 14 continuous fast-sensory scalars (not the multi-hot
    # categorical vocab above). Its `feature_order` and reaction `labels` in
    # `config/instinct.yaml` are the fixed encode contract the
    # InstinctFeatureEncoder is built from; the artifact carries them so a drifted
    # `instinct.pt` is rejected on load. Reaction thresholds/cooldowns are a
    # consumer concern (INS-RT) and live in a later config block.

    def instinct_feature_order(self) -> Tuple[str, ...]:
        return tuple(self._instinct.get("feature_order", []) or [])

    def instinct_labels(self) -> Tuple[str, ...]:
        return tuple(self._instinct.get("labels", []) or [])

    def instinct_model_policy(self) -> InstinctModelPolicy:
        """The instinct trainer's hyperparameters, config-driven with safe defaults
        so retuning training never touches Python."""
        training = self._instinct.get("training", {}) or {}
        return InstinctModelPolicy(
            epochs=int(training.get("epochs", 400)),
            hidden_size=int(training.get("hidden_size", 16)),
            learning_rate=float(training.get("learning_rate", 0.05)),
            seed=int(training.get("seed", 0)),
            intensity_loss=str(training.get("intensity_loss", "bce")),
        )

    def outcome_training_params(self) -> Dict[str, float]:
        """Trainer hyperparameters, config-driven with safe defaults so
        retuning training never touches Python."""
        params = dict(_DEFAULT_TRAINING)
        params.update(self._outcome.get("training", {}) or {})
        return {
            "epochs": int(params["epochs"]),
            "hidden_size": int(params["hidden_size"]),
            "learning_rate": float(params["learning_rate"]),
            "seed": int(params["seed"]),
        }

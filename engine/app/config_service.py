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
    CommandSpec,
    EmotionRule,
    EnvironmentPolicy,
    NeedTickPolicy,
    RenderHintsPolicy,
    SafetyRule,
)

# Trainer tuning defaults, used when outcome_labels.yaml omits a `training` key
# (e.g. the from_dict tests). The authored config overrides these.
_DEFAULT_TRAINING = {"epochs": 300, "hidden_size": 16, "learning_rate": 0.05, "seed": 0}


class ConfigService:
    def __init__(
        self,
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
    ):
        self._tick_rates = tick_rates
        self._emotions = emotions
        self._rooms = rooms or {}
        self._objects = objects or {}
        self._environment = environment or {}
        self._render_hints = render_hints or {}
        self._commands = commands or {}
        self._outcome = outcome or {}
        self._actions = actions or {}
        self._safety = safety or {}

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
    ) -> "ConfigService":
        """Build from already-parsed config. Used by tests so behavior is
        pinned to explicit values, not to whatever the shipped files hold."""
        return cls(
            tick_rates,
            emotions,
            rooms,
            objects,
            environment,
            render_hints,
            commands,
            outcome,
            actions,
            safety,
        )

    @classmethod
    def from_files(cls, config_root: str) -> "ConfigService":
        """Load the authored YAML under `config_root`. `yaml` is imported here,
        lazily, so the pure-Python core imports with zero third-party deps."""
        import yaml  # noqa: PLC0415 — kept out of module import path on purpose

        root = Path(config_root)
        tick_rates = yaml.safe_load((root / "tick_rates.yaml").read_text())
        emotions = yaml.safe_load((root / "emotions.yaml").read_text())
        rooms = yaml.safe_load((root / "rooms.yaml").read_text())
        objects = yaml.safe_load((root / "object_properties.yaml").read_text())
        environment = yaml.safe_load((root / "environment.yaml").read_text())
        render_hints = yaml.safe_load((root / "render_hints.yaml").read_text())
        commands = yaml.safe_load((root / "commands.yaml").read_text())
        outcome = yaml.safe_load((root / "outcome_labels.yaml").read_text())
        actions = yaml.safe_load((root / "actions.yaml").read_text())
        safety = yaml.safe_load((root / "safety_rules.yaml").read_text())
        return cls(
            tick_rates,
            emotions,
            rooms,
            objects,
            environment,
            render_hints,
            commands,
            outcome,
            actions,
            safety,
        )

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
        return ConfigService(
            self._tick_rates,
            self._emotions,
            rooms,
            self._objects,
            self._environment,
            self._render_hints,
            self._commands,
            self._outcome,
            self._actions,
            self._safety,
        )

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

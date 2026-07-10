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
from app.policies import EmotionRule, NeedTickPolicy

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
        outcome: Optional[Mapping] = None,
    ):
        self._tick_rates = tick_rates
        self._emotions = emotions
        self._rooms = rooms or {}
        self._objects = objects or {}
        self._outcome = outcome or {}

    # --- construction -----------------------------------------------------

    @classmethod
    def from_dict(
        cls,
        tick_rates: Mapping,
        emotions: Mapping,
        rooms: Optional[Mapping] = None,
        objects: Optional[Mapping] = None,
        outcome: Optional[Mapping] = None,
    ) -> "ConfigService":
        """Build from already-parsed config. Used by tests so behavior is
        pinned to explicit values, not to whatever the shipped files hold."""
        return cls(tick_rates, emotions, rooms, objects, outcome)

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
        outcome = yaml.safe_load((root / "outcome_labels.yaml").read_text())
        return cls(tick_rates, emotions, rooms, objects, outcome)

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
        yields an empty room so the pure need/emotion tests need not describe a
        world."""
        spec = self._rooms.get("room", {}) or {}
        return Room(
            room_id=str(spec.get("id", "room_001")),
            contains=tuple(spec.get("contains", []) or []),
            base_confidence=float(spec.get("base_confidence", 1.0)),
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

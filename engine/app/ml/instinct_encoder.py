"""InstinctFeatureEncoder — the fixed, deterministic (stimulus -> feature vector)
contract for the instinct model (ADR 0026).

The being's instinct net maps *fast-sensory / kinematic* features of a perceived
stimulus to protective *reactions*. Unlike the outcome encoder's multi-hot
categorical slots, each slot here is a single continuous, normalized scalar
(distance, velocity, time-to-contact…). The authored `feature_order` in
`config/instinct.yaml` IS the contract: a `Stimulus` always encodes to the same
14 slots and the model's five reaction slots always mean the same reactions, so
`WORLD-MOTION` (the feature source), this encoder, and shadow-mode inference all
agree — exactly the stability ADR 0008 pins for the outcome encoder, mirrored here.

Like `FeatureEncoder`, it is deliberately pure — no PyTorch, no file IO, no
config-file knowledge. It is handed its vocabulary (via
`InstinctFeatureEncoder.from_config`, reading the typed order off a
`ConfigService`) and turns a `Stimulus` into plain tuples of floats, so it is
importable in the lean runtime image alongside inference. It rejects a feature
name outside the frozen contract, and an unknown reaction label, loudly
(`ValueError`).
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Dict, Iterable, Tuple


@dataclass(frozen=True)
class Stimulus:
    """One perceived fast-sensory stimulus to encode — the frozen 14-feature
    vector of ADR 0026, each field a normalized scalar (a `[0, 1]` magnitude or a
    signed rate). These are the being's *perceived* kinematics/stimulus; they key
    on nothing authored (no `developer_label`, ADR 0002). `WORLD-MOTION` produces
    one of these per perception/approach event; inference encodes it here. Every
    field defaults to 0.0 so a test (or a partial percept) can name only the
    features it cares about."""

    distance: float = 0.0
    velocity: float = 0.0
    acceleration: float = 0.0
    trajectory_toward_body: float = 0.0
    time_to_contact: float = 0.0
    object_size: float = 0.0
    size_change_rate: float = 0.0
    unexpectedness: float = 0.0
    visibility_confidence: float = 0.0
    sound_spike_intensity: float = 0.0
    touch_intensity: float = 0.0
    current_focus_level: float = 0.0
    current_stability: float = 0.0
    prior_prediction_error: float = 0.0


# The stimulus fields that may appear in `feature_order` — the frozen feature
# universe. A config that names anything outside this is a contract error.
_STIMULUS_FIELDS = frozenset(f.name for f in fields(Stimulus))


@dataclass(frozen=True)
class InstinctSpec:
    """The ordered feature and reaction-label vocabularies that define the encode
    contract. Kept separate from the encoder so a tiny fixed spec can be built in
    tests without config (the instinct analogue of `FeatureSpec`)."""

    feature_order: Tuple[str, ...] = ()
    label_vocab: Tuple[str, ...] = ()


class InstinctFeatureEncoder:
    def __init__(self, spec: InstinctSpec):
        self._spec = spec
        self._feature_names: Tuple[str, ...] = tuple(spec.feature_order)
        self._label_names: Tuple[str, ...] = tuple(spec.label_vocab)
        # Fail loud: every feature must be a real Stimulus field, and no name may
        # repeat — a typo can't silently create a dead slot (mirrors FeatureEncoder).
        self._feature_index: Dict[str, int] = _index(self._feature_names, "feature")
        unknown = [name for name in self._feature_names if name not in _STIMULUS_FIELDS]
        if unknown:
            raise ValueError(
                f"instinct feature(s) {sorted(unknown)} are not stimulus features; "
                f"the frozen contract is {sorted(_STIMULUS_FIELDS)}"
            )
        self._label_index: Dict[str, int] = _index(self._label_names, "reaction")

    @classmethod
    def from_config(cls, config) -> "InstinctFeatureEncoder":
        """Build the encoder from the typed vocabulary on a ConfigService. Duck-
        typed so the ML package never imports the config module."""
        return cls(
            InstinctSpec(
                feature_order=tuple(config.instinct_feature_order()),
                label_vocab=tuple(config.instinct_labels()),
            )
        )

    # --- the contract, as read by tests and inference --------------------

    def feature_names(self) -> Tuple[str, ...]:
        return self._feature_names

    def label_names(self) -> Tuple[str, ...]:
        return self._label_names

    @property
    def feature_size(self) -> int:
        return len(self._feature_names)

    @property
    def label_size(self) -> int:
        return len(self._label_names)

    # --- encoding --------------------------------------------------------

    def encode_features(self, stimulus: Stimulus) -> Tuple[float, ...]:
        """The stimulus as its ordered scalar feature vector — slot `i` is the
        `feature_order[i]` reading, so the vector always means the same thing."""
        return tuple(float(getattr(stimulus, name)) for name in self._feature_names)

    def encode_labels(self, reactions: Iterable[str]) -> Tuple[float, ...]:
        """A multi-hot vector over the reaction vocabulary — 1.0 for each reaction
        present. An unknown reaction is rejected loudly (the same fail-loud
        discipline as the outcome encoder's labels)."""
        vector = [0.0] * len(self._label_names)
        for reaction in reactions:
            if reaction not in self._label_index:
                raise ValueError(
                    f"unknown reaction {reaction!r}: not in the reaction vocabulary"
                )
            vector[self._label_index[reaction]] = 1.0
        return tuple(vector)


def _index(names: Iterable[str], kind: str) -> Dict[str, int]:
    index: Dict[str, int] = {}
    for position, name in enumerate(names):
        if name in index:
            raise ValueError(f"duplicate {kind} {name!r} in the vocabulary")
        index[name] = position
    return index

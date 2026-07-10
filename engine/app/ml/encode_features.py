"""FeatureEncoder — the fixed, deterministic (interaction -> feature vector)
contract for the outcome predictor.

The being's first neural network (BRIEF §11) maps *object properties + action +
context* to likely *outcomes*. Both sides are multi-hot over authored
vocabularies, so an interaction always encodes to the same slots and the model's
output slots always mean the same outcomes. That stability is the whole point:
the trainer (V0-8) and shadow-mode inference (V0-9) must encode identically, so
this module is the single home of the contract and is pinned in ADR 0008.

It is deliberately pure — no PyTorch, no file IO, no config-file knowledge. It is
handed its vocabulary (via `FeatureEncoder.from_config`, reading the typed
vocab off `ConfigService`) and turns an `Example` into plain tuples of floats.
That keeps it importable in the lean runtime image alongside inference.

The feature vector is, in order:
    property_vocab  ++  action_vocab  ++  context_vocab
and the label vector is `label_vocab`. Order is authored config order, so the
config files are the contract's source of truth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Tuple


@dataclass(frozen=True)
class Example:
    """One interaction to encode: the object's perceived `properties`, the
    `action` taken on it, the situational `context`, and (for training) the
    observed `outcomes`. Inference builds one with `outcomes` left empty."""

    properties: Tuple[str, ...] = ()
    action: str = ""
    context: Tuple[str, ...] = ()
    outcomes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class FeatureSpec:
    """The ordered vocabularies that define the encode contract. Kept separate
    from the encoder so a tiny fixed spec can be built in tests without config."""

    property_vocab: Tuple[str, ...] = ()
    action_vocab: Tuple[str, ...] = ()
    context_vocab: Tuple[str, ...] = ()
    label_vocab: Tuple[str, ...] = ()


class FeatureEncoder:
    def __init__(self, spec: FeatureSpec):
        self._spec = spec
        self._feature_names: Tuple[str, ...] = (
            tuple(spec.property_vocab) + tuple(spec.action_vocab) + tuple(spec.context_vocab)
        )
        self._label_names: Tuple[str, ...] = tuple(spec.label_vocab)
        self._feature_index: Dict[str, int] = _index(self._feature_names, "feature")
        self._label_index: Dict[str, int] = _index(self._label_names, "label")
        # Actions are one block within the feature space; an action name must be
        # a known action, not any feature, so a typo can't set a property slot.
        self._action_vocab = frozenset(spec.action_vocab)
        self._context_vocab = frozenset(spec.context_vocab)
        self._property_vocab = frozenset(spec.property_vocab)

    @classmethod
    def from_config(cls, config) -> "FeatureEncoder":
        """Build the encoder from the typed vocabulary on a ConfigService. Duck-
        typed so the ML package never imports the config module."""
        return cls(
            FeatureSpec(
                property_vocab=tuple(config.object_property_vocab()),
                action_vocab=tuple(config.object_action_vocab()),
                context_vocab=tuple(config.outcome_context_features()),
                label_vocab=tuple(config.outcome_labels()),
            )
        )

    # --- the contract, as read by tests and V0-9 -------------------------

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

    def encode_features(self, example: Example) -> Tuple[float, ...]:
        vector = [0.0] * len(self._feature_names)
        for prop in example.properties:
            vector[self._require(prop, self._property_vocab, "property")] = 1.0
        if example.action:
            vector[self._require(example.action, self._action_vocab, "action")] = 1.0
        for ctx in example.context:
            vector[self._require(ctx, self._context_vocab, "context")] = 1.0
        return tuple(vector)

    def encode_labels(self, example: Example) -> Tuple[float, ...]:
        vector = [0.0] * len(self._label_names)
        for outcome in example.outcomes:
            if outcome not in self._label_index:
                raise ValueError(f"unknown outcome {outcome!r}: not in the label vocabulary")
            vector[self._label_index[outcome]] = 1.0
        return tuple(vector)

    def _require(self, term: str, allowed: frozenset, kind: str) -> int:
        if term not in allowed:
            raise ValueError(f"unknown {kind} {term!r}: not in the vocabulary")
        return self._feature_index[term]


def _index(names: Iterable[str], kind: str) -> Dict[str, int]:
    index: Dict[str, int] = {}
    for position, name in enumerate(names):
        if name in index:
            raise ValueError(f"duplicate {kind} {name!r} in the vocabulary")
        index[name] = position
    return index

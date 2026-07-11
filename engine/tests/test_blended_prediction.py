"""Behavior of ACTIVE (blended) outcome prediction (card v3, extends ADR 0011).

V0-9 ran the outcome predictor in *shadow* mode — it recorded predictions but
never touched what the being did. This slice makes prediction **active**: the
decision system blends a neural predictor with a rule-based predictor (by config
weight) and lets the blended anticipation shape which action the being picks —
so the being can learn to avoid an action it predicts will hurt, all *within*
the safety guardrails (BRIEF §12, v2). Two forces are proven here:

  - the ensemble blends neural + rule probabilities and falls back to rules on a
    neural error (a `PredictorPort` behavior — no torch needed, driven by fakes);
  - the being's chosen action changes when prediction is flipped on, yet the
    SafetyService floor still blocks a forbidden action no matter what the
    prediction says.

Everything is asserted through public surfaces: the `PredictorPort`
(`RuleBasedPredictor`, `EnsemblePredictor`) and `Simulation.tick()` /
`.state()` / `.interactions()`. Activation is a config flip — the
`neural_enabled` flag in `outcome_labels.yaml`'s `prediction:` block.
"""
from __future__ import annotations

from typing import Dict

import pytest

from app.config_service import ConfigService
from app.ml.encode_features import Example
from app.policies import PredictionBlendPolicy
from app.ports.predictor import EnsemblePredictor, RuleBasedPredictor
from app.simulation import Simulation

# --- shared fixtures ---------------------------------------------------------

_LABELS = ["rolls", "bounces", "falls", "causes_pain", "makes_noise", "pleasant", "scary"]

_OBJECTS = {
    "properties": ["round", "soft", "hard", "heavy", "hot", "red"],
    "affordances": ["look", "touch", "push", "grab", "drop"],
    "objects": {
        "obj_ball": {
            "developerLabel": "Ball",
            "properties": ["round", "red", "soft"],
            "affordances": ["look", "touch", "push", "grab"],
        },
        "obj_hot": {
            "developerLabel": "Hot Thing",
            "properties": ["hot", "hard", "heavy"],
            "affordances": ["look", "touch", "push", "grab"],
        },
    },
}

# touch scores far above observe on raw utility, so ONLY an anticipated cost (or a
# safety block) can keep the being from touching.
_TOUCH_TOP = {
    "actions": {
        "touch": {
            "affordance": "touch",
            "utility": {"base": 10.0, "needs": {}, "emotions": {}},
            "expected_outcomes": [],
            "property_outcomes": {"hot": ["causes_pain", "scary"], "soft": ["pleasant"]},
            "reason": "reaching out to touch",
        },
        "observe": {
            "affordance": "look",
            "utility": {"base": 1.0, "needs": {}, "emotions": {}},
            "expected_outcomes": ["pleasant"],
            "reason": "taking a careful look instead",
        },
    }
}

# felt consequences: touching something hot hurts (pain up, safety/comfort down);
# a frightening experience erodes felt safety. Pleasant moves nothing (v0).
_EFFECTS = {
    "effects": {
        "causes_pain": {"pain": 45, "safety": -40, "comfort": -20},
        "scary": {"safety": -20},
    }
}

_EMOTIONS = {"rules": [], "default": "calm"}


def _needs():
    """Contextual needs (no autonomous drift) so the decision is a pure function
    of the state we set — the levels never move under us."""
    levels = {
        "curiosity": 40, "safety": 80, "comfort": 70,
        "hunger": 30, "sleep": 30, "warmth": 50, "pain": 0,
    }
    return {
        name: {"direction": "contextual", "amount": 0, "every_ticks": 1, "min": 0, "max": 100, "start": val}
        for name, val in levels.items()
    }


def _prediction_block(*, neural_enabled, neural_weight=0.5, rule_weight=0.5, fallback=True):
    return {
        "threshold": 0.5,
        "neural_enabled": neural_enabled,
        "neural_weight": neural_weight,
        "rule_weight": rule_weight,
        "fallback_to_rules_on_error": fallback,
    }


def _config(*, contains, actions=_TOUCH_TOP, safety=None, prediction=None):
    outcome = {"labels": _LABELS, "context_features": ["surface_hard", "surface_soft"]}
    if prediction is not None:
        outcome["prediction"] = prediction
    return ConfigService.from_dict(
        {"tick": {"duration_ms": 1000}, "needs": _needs()},
        _EMOTIONS,
        rooms={"room": {"id": "room_001", "contains": list(contains)}},
        objects=_OBJECTS,
        actions=actions,
        safety=safety or {"rules": []},
        outcome=outcome,
        outcome_effects=_EFFECTS,
    )


class _Fixed:
    """A PredictorPort that returns fixed probabilities and counts its calls."""

    def __init__(self, probabilities: Dict[str, float]):
        self._probabilities = probabilities
        self.calls = 0

    def predict_outcomes(self, example: Example) -> Dict[str, float]:
        self.calls += 1
        return dict(self._probabilities)


class _Boom:
    """A PredictorPort whose neural inference fails — the model-error case."""

    def __init__(self):
        self.calls = 0

    def predict_outcomes(self, example: Example) -> Dict[str, float]:
        self.calls += 1
        raise RuntimeError("model inference failed")


# --- the RuleBasedPredictor: the rule layer, as a PredictorPort --------------


def test_rule_based_predictor_returns_the_rule_layers_outcomes_as_probabilities():
    config = _config(contains=["obj_hot"])
    rule = RuleBasedPredictor(config.action_policies(), config.outcome_labels())

    probs = rule.predict_outcomes(Example(properties=("hot", "hard", "heavy"), action="touch"))

    assert probs["causes_pain"] == 1.0  # touching something hot is predicted to hurt
    assert probs["scary"] == 1.0
    assert probs["pleasant"] == 0.0
    assert set(probs) == set(_LABELS)  # a probability for every label


# --- the EnsemblePredictor: blend + safe fallback ----------------------------


def test_ensemble_blends_neural_and_rule_probabilities_by_config_weight():
    neural = _Fixed({label: 0.0 for label in _LABELS} | {"causes_pain": 0.8})
    rule = _Fixed({label: 0.0 for label in _LABELS} | {"causes_pain": 1.0})
    ensemble = EnsemblePredictor(
        rule=rule,
        neural=neural,
        policy=PredictionBlendPolicy(
            neural_enabled=True, neural_weight=0.7, rule_weight=0.3, fallback_to_rules_on_error=True
        ),
    )

    probs = ensemble.predict_outcomes(Example())

    assert probs["causes_pain"] == pytest.approx(0.7 * 0.8 + 0.3 * 1.0)


def test_ensemble_falls_back_to_rules_when_the_neural_predictor_errors():
    rule = _Fixed({label: 0.0 for label in _LABELS} | {"pleasant": 1.0})
    neural = _Boom()
    ensemble = EnsemblePredictor(
        rule=rule,
        neural=neural,
        policy=PredictionBlendPolicy(
            neural_enabled=True, neural_weight=0.7, rule_weight=0.3, fallback_to_rules_on_error=True
        ),
    )

    probs = ensemble.predict_outcomes(Example())

    assert neural.calls == 1  # the neural model was tried
    assert probs == rule.predict_outcomes(Example())  # and the rule layer carried the call


def test_ensemble_uses_rules_only_when_the_neural_predictor_is_disabled():
    rule = _Fixed({label: 0.0 for label in _LABELS} | {"pleasant": 1.0})
    neural = _Boom()  # would raise if ever consulted
    ensemble = EnsemblePredictor(
        rule=rule,
        neural=neural,
        policy=PredictionBlendPolicy(
            neural_enabled=False, neural_weight=0.7, rule_weight=0.3, fallback_to_rules_on_error=True
        ),
    )

    probs = ensemble.predict_outcomes(Example())

    assert neural.calls == 0  # a disabled model is never called
    assert probs == rule.predict_outcomes(Example())


def test_ensemble_reraises_a_neural_error_when_fallback_is_disabled():
    rule = _Fixed({label: 0.0 for label in _LABELS})
    ensemble = EnsemblePredictor(
        rule=rule,
        neural=_Boom(),
        policy=PredictionBlendPolicy(
            neural_enabled=True, neural_weight=0.7, rule_weight=0.3, fallback_to_rules_on_error=False
        ),
    )

    with pytest.raises(RuntimeError):
        ensemble.predict_outcomes(Example())


# --- active prediction wired through the Simulation --------------------------


def test_prediction_is_inactive_by_default_so_the_utility_winner_is_chosen():
    # No prediction block at all -> shadow/inactive: the raw utility winner wins.
    sim = Simulation(_config(contains=["obj_hot"], prediction=None))

    state = sim.tick()

    assert state["currentAction"]["type"] == "touch"


def test_flipping_prediction_active_changes_the_chosen_action_within_safety():
    # The config flip: neural_enabled off -> the being touches the hot thing
    # (raw utility). Flipped on, the rule-based prediction anticipates pain, which
    # penalizes touch below observe -> the being looks instead. No rule hard-blocks
    # touch here, so this is behavior changing *within* the guardrails.
    off = Simulation(_config(contains=["obj_hot"], prediction=_prediction_block(neural_enabled=False)))
    on = Simulation(_config(contains=["obj_hot"], prediction=_prediction_block(neural_enabled=True)))

    assert off.tick()["currentAction"]["type"] == "touch"
    assert on.tick()["currentAction"]["type"] == "observe"


def test_active_prediction_blends_an_injected_neural_model_into_the_decision():
    # A neural model that predicts NO harm for touching the hot thing. Blended
    # 50/50 with the rule layer (which predicts pain), the anticipated cost is
    # halved but still enough to keep the being from touching — the neural model
    # genuinely moved the blended anticipation and the decision consumed it.
    neural = _Fixed({label: 0.0 for label in _LABELS})
    sim = Simulation(
        _config(contains=["obj_hot"], prediction=_prediction_block(neural_enabled=True)),
        predictor=neural,
    )

    state = sim.tick()

    assert neural.calls > 0  # the neural model was consulted in the decision path
    assert state["currentAction"]["type"] == "observe"


def test_a_floor_rule_still_blocks_an_action_the_prediction_would_choose():
    # Prediction endorses touch (rule predicts `pleasant` for a soft object, so no
    # anticipated cost) AND touch has the top utility -> prediction would pick it.
    # An injected floor rule forbids it anyway: learned/neural scores never bypass
    # the safety floor (BRIEF §12-§13).
    floor = {"rules": [{"action": "touch", "blocked_property": "soft", "reason": "injected floor: hands off"}]}
    sim = Simulation(
        _config(contains=["obj_ball"], safety=floor, prediction=_prediction_block(neural_enabled=True))
    )

    state = sim.tick()

    assert state["currentAction"]["type"] == "observe"
    assert all(e["action"] != "touch" for e in sim.interactions())


def test_a_neural_model_error_falls_back_to_rules_and_the_sim_keeps_running():
    # The neural model raises on every inference. With fallback on, the decision
    # falls back to the rule layer, so the sim continues and the being still
    # anticipates pain from the rule layer -> it never touches the hot thing.
    sim = Simulation(
        _config(contains=["obj_hot"], prediction=_prediction_block(neural_enabled=True, fallback=True)),
        predictor=_Boom(),
    )

    for _ in range(10):
        sim.tick()

    assert sim.interactions()  # the being kept acting despite the model error
    touched_hot = [e for e in sim.interactions() if e["objectId"] == "obj_hot" and e["action"] == "touch"]
    assert touched_hot == []

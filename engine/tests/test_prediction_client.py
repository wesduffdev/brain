"""Behavior of the PredictionClient seam — WHERE model inference runs (v8, ADR 0043).

The two learned models (outcome + instinct) sit behind stable ports
(`PredictorPort`, `InstinctPredictorPort`). This slice adds a `PredictionClient`
seam — one object covering BOTH ports — so inference can run in-process (today) or
OUT-OF-PROCESS behind a `model-service` sidecar, selected by config, and DEGRADE
to the safe baseline when the service is unavailable so the sim never stalls.

Everything here is asserted OFFLINE through public surfaces (the client methods,
`Simulation.tick()` / `.interactions()`, `build_simulation`) with a stub HTTP
transport — no network, no torch, no running service. The single live round-trip
against a real sidecar is `@pytest.mark.model_service` in test_model_service_app.py.
"""
from __future__ import annotations

import os
from typing import Dict, List

import pytest

from app.adapters.http_prediction_client import HttpPredictionClient
from app.bootstrap import build_simulation
from app.config_service import ConfigService
from app.ml.encode_features import Example
from app.ml.instinct_encoder import Stimulus
from app.ports.instinct import InstinctPrediction
from app.ports.prediction_client import (
    FallbackPredictionClient,
    InProcessPredictionClient,
)
from app.ports.predictor import RuleBasedPredictor
from app.simulation import Simulation

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")
_OUTCOME_LABELS = ("rolls", "causes_pain", "pleasant")
_INSTINCT_LABELS = ("flinch", "freeze", "orient", "withdraw", "ignore")


# --- test doubles ------------------------------------------------------------


class _StubResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self._status = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self._status >= 400:
            raise RuntimeError(f"HTTP {self._status}")


class _StubTransport:
    """A stand-in for httpx.Client: records POSTs, answers by URL suffix."""

    def __init__(self, by_suffix):
        self._by_suffix = by_suffix
        self.posts: List = []

    def post(self, url, json=None):
        self.posts.append((url, json))
        for suffix, resp in self._by_suffix.items():
            if url.endswith(suffix):
                return resp
        raise AssertionError(f"unexpected POST to {url}")


class _FixedOutcome:
    """A PredictorPort returning fixed probabilities."""

    def __init__(self, probs):
        self._probs = probs

    def predict_outcomes(self, example: Example) -> Dict[str, float]:
        return dict(self._probs)


class _BoomClient:
    """A PredictionClient whose every call fails — the service-outage case."""

    def predict_outcomes(self, example: Example) -> Dict[str, float]:
        raise RuntimeError("model-service unreachable")

    def predict_reactions(self, stimulus: Stimulus) -> InstinctPrediction:
        raise RuntimeError("model-service unreachable")


def _needs():
    levels = {"curiosity": 40, "safety": 80, "comfort": 70, "hunger": 30, "pain": 0}
    return {
        name: {"direction": "contextual", "amount": 0, "every_ticks": 1, "min": 0, "max": 100, "start": val}
        for name, val in levels.items()
    }


def _sim_config(*, contains, safety=None, neural_enabled=False, models=None):
    return ConfigService.from_dict(
        {"tick": {"duration_ms": 1000}, "needs": _needs()},
        {"rules": [], "default": "calm"},
        rooms={"room": {"id": "room_001", "contains": list(contains)}},
        objects={
            "properties": ["round", "soft", "hot", "hard", "heavy", "red"],
            "affordances": ["look", "touch"],
            "objects": {
                "obj_ball": {"developerLabel": "Ball", "properties": ["round", "red", "soft"], "affordances": ["look", "touch"]},
                "obj_hot": {"developerLabel": "Hot", "properties": ["hot", "hard"], "affordances": ["look", "touch"]},
            },
        },
        actions={"actions": {
            "touch": {"affordance": "touch", "utility": {"base": 10.0, "needs": {}, "emotions": {}},
                      "expected_outcomes": [], "property_outcomes": {"hot": ["causes_pain"], "soft": ["pleasant"]},
                      "reason": "reaching out to touch"},
            "observe": {"affordance": "look", "utility": {"base": 1.0, "needs": {}, "emotions": {}},
                        "expected_outcomes": ["pleasant"], "reason": "taking a careful look"},
        }},
        safety=safety or {"rules": []},
        outcome={"labels": list(_OUTCOME_LABELS), "context_features": [],
                 "prediction": {"neural_enabled": neural_enabled, "neural_weight": 0.5,
                                "rule_weight": 0.5, "fallback_to_rules_on_error": True}},
        outcome_effects={"effects": {"causes_pain": {"pain": 45, "safety": -40}}},
        models=models,
    )


# --- Http client parses the sidecar's responses ------------------------------


def test_http_client_parses_served_outcome_probabilities():
    transport = _StubTransport({"/predict/outcome": _StubResponse({"outcomes": {"causes_pain": 0.9, "pleasant": 0.1}})})
    client = HttpPredictionClient(base_url="http://model-service:8500", client=transport)

    probs = client.predict_outcomes(Example(properties=("hot",), action="touch"))

    assert probs["causes_pain"] == pytest.approx(0.9)
    assert probs["pleasant"] == pytest.approx(0.1)
    url, body = transport.posts[0]
    assert url.endswith("/predict/outcome")
    assert body["action"] == "touch"
    assert body["properties"] == ["hot"]


def test_http_client_parses_served_reaction_and_intensity():
    transport = _StubTransport({"/predict/instinct": _StubResponse({"reactions": {"flinch": 0.8, "ignore": 0.05}, "intensity": 0.7})})
    client = HttpPredictionClient(base_url="http://model-service:8500", client=transport)

    pred = client.predict_reactions(Stimulus(distance=0.1, velocity=0.9))

    assert isinstance(pred, InstinctPrediction)
    assert pred.reactions["flinch"] == pytest.approx(0.8)
    assert pred.intensity == pytest.approx(0.7)
    url, body = transport.posts[0]
    assert url.endswith("/predict/instinct")
    assert body["stimulus"]["velocity"] == pytest.approx(0.9)


def test_http_client_refuses_without_an_endpoint_never_a_blind_call():
    client = HttpPredictionClient(base_url="", env={})
    with pytest.raises(RuntimeError):
        client.predict_outcomes(Example(action="touch"))


# --- InProcess client: delegates, with a safe null when a model is absent ----


def test_inprocess_client_delegates_outcome_and_returns_safe_baseline_for_missing_instinct():
    client = InProcessPredictionClient(
        outcome=_FixedOutcome({"causes_pain": 0.9}), instinct=None,
        outcome_labels=_OUTCOME_LABELS, instinct_labels=_INSTINCT_LABELS,
    )

    assert client.predict_outcomes(Example(action="touch")) == {"causes_pain": 0.9}

    pred = client.predict_reactions(Stimulus(distance=0.1))
    assert set(pred.reactions) == set(_INSTINCT_LABELS)
    assert all(v == 0.0 for v in pred.reactions.values())  # no reaction ever fires
    assert pred.intensity == 0.0


def test_inprocess_client_returns_all_zero_outcomes_when_no_outcome_model():
    client = InProcessPredictionClient(
        outcome=None, instinct=None,
        outcome_labels=_OUTCOME_LABELS, instinct_labels=_INSTINCT_LABELS,
    )
    probs = client.predict_outcomes(Example(action="touch"))
    assert probs == {label: 0.0 for label in _OUTCOME_LABELS}


# --- Fallback client: degrade to the safe baseline on a service outage -------


def test_fallback_uses_the_rule_baseline_when_the_service_errors_on_outcome():
    fallback = InProcessPredictionClient(
        outcome=_FixedOutcome({"pleasant": 1.0}), instinct=None,
        outcome_labels=_OUTCOME_LABELS, instinct_labels=_INSTINCT_LABELS,
    )
    client = FallbackPredictionClient(primary=_BoomClient(), fallback=fallback)

    assert client.predict_outcomes(Example(action="touch")) == {"pleasant": 1.0}  # no raise


def test_fallback_uses_the_safe_no_reaction_baseline_when_the_service_errors_on_instinct():
    fallback = InProcessPredictionClient(
        outcome=None, instinct=None,
        outcome_labels=_OUTCOME_LABELS, instinct_labels=_INSTINCT_LABELS,
    )
    client = FallbackPredictionClient(primary=_BoomClient(), fallback=fallback)

    pred = client.predict_reactions(Stimulus(velocity=0.9))
    assert all(v == 0.0 for v in pred.reactions.values())
    assert pred.intensity == 0.0


def test_fallback_returns_the_primary_result_when_the_service_is_healthy():
    primary = InProcessPredictionClient(
        outcome=_FixedOutcome({"causes_pain": 0.9}), instinct=None,
        outcome_labels=_OUTCOME_LABELS, instinct_labels=_INSTINCT_LABELS,
    )
    fallback = InProcessPredictionClient(
        outcome=_FixedOutcome({"pleasant": 1.0}), instinct=None,
        outcome_labels=_OUTCOME_LABELS, instinct_labels=_INSTINCT_LABELS,
    )
    client = FallbackPredictionClient(primary=primary, fallback=fallback)

    assert client.predict_outcomes(Example(action="touch")) == {"causes_pain": 0.9}


# --- SAFETY: a served score never bypasses the floor -------------------------


def test_a_served_score_never_buys_a_blocked_action_past_the_safety_floor():
    # Prediction is active and the served client scores everything harmless, so
    # anticipation would endorse the top-utility `touch`. A floor rule forbids
    # touching a soft object anyway: learned/served scores never bypass the safety
    # floor (BRIEF §12).
    harmless = FallbackPredictionClient(
        primary=_BoomClient(),  # even a dead service degrades to...
        fallback=InProcessPredictionClient(
            outcome=_FixedOutcome({label: 0.0 for label in _OUTCOME_LABELS}), instinct=None,
            outcome_labels=_OUTCOME_LABELS, instinct_labels=_INSTINCT_LABELS,
        ),
    )
    floor = {"rules": [{"action": "touch", "blocked_property": "soft", "reason": "floor: hands off"}]}
    sim = Simulation(_sim_config(contains=["obj_ball"], safety=floor, neural_enabled=True), predictor=harmless)

    state = sim.tick()

    assert state["currentAction"]["type"] == "observe"
    assert all(e["action"] != "touch" for e in sim.interactions())


# --- Bootstrap selection: default inprocess; http degrades and keeps running --


def test_default_models_routing_is_inprocess_so_the_being_is_unchanged():
    policy = ConfigService.from_files(_CONFIG_ROOT).models_policy()
    assert policy.outcome.mode == "inprocess"
    assert policy.instinct.mode == "inprocess"


def test_inprocess_default_bootstrap_ticks_without_any_service(monkeypatch):
    monkeypatch.delenv("MODEL_SERVICE_URL", raising=False)
    with build_simulation(ConfigService.from_files(_CONFIG_ROOT), env={}) as sim:
        state = sim.tick()
    assert state is not None


def test_http_routing_without_a_reachable_service_falls_back_and_keeps_running(monkeypatch):
    monkeypatch.delenv("MODEL_SERVICE_URL", raising=False)
    config = _sim_config(
        contains=["obj_hot"], neural_enabled=True,
        models={"routing": {"outcome": {"mode": "http", "fallback": True}}},
    )
    with build_simulation(config, env={}) as sim:  # no endpoint => service unavailable
        for _ in range(5):
            sim.tick()
    assert sim.interactions()  # the being kept acting despite the model outage
    touched_hot = [e for e in sim.interactions() if e["objectId"] == "obj_hot" and e["action"] == "touch"]
    assert touched_hot == []  # the rule baseline still anticipates pain

"""Behavior: the DEPLOYED runtime (bootstrap/main) drives the perception ->
instinct -> reaction chain LIVE, in shadow (RUNTIME-WIRE).

The event-instinct layer already runs end-to-end when a caller hands `Simulation`
a shared bus + an instinct predictor (EVT-VALID). The gap this slice closes: the
deployed engine assembled by `build_simulation` never built a bus, so a running
being — even with a trained artifact — never fired instinct. These tests pin the
bootstrap's new contract through its public surface (`build_simulation` ->
`Simulation.tick()`/`.state()` and the events on the shared bus):

- given an instinct predictor, the bootstrap builds a shared EventBus and wires
  the chain, so a moving object drives a reaction the being surfaces (proven with
  the activation flag on) -- WITHOUT any caller-injected bus;
- in shadow (flags off, the shipped default) the wired chain really fires yet the
  being's state()/decisions are byte-identical to an un-wired being;
- with no predictor (no torch / no artifact -> None) the chain is inert and the
  being is byte-identical, so the lean runtime and the whole suite are untouched.

A torch-free fake instinct predictor stands in for the trained model; no broker,
no database.
"""
from __future__ import annotations

import os

from typing import List

from app.adapters.in_memory_event_bus import InMemoryEventBus
from app.bootstrap import build_simulation
from app.config_service import ConfigService
from app.domain.event import DomainEvent
from app.domain.instinct import REACTION_LABELS
from app.ml.instinct_encoder import Stimulus
from app.policies import MOTION_FEATURE_NAMES
from app.ports.instinct import InstinctPrediction as PortPrediction
from app.services.instinct_service import INSTINCT_REACTIONS_TOPIC
from app.simulation import Simulation


_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


class FakeInstinctPredictor:
    """Torch-free `InstinctPredictorPort`: the being flinches at a fast, body-bound
    approach -- flinch probability and intensity both track velocity*trajectory."""

    def predict_reactions(self, stimulus: Stimulus) -> PortPrediction:
        threat = _clamp(stimulus.velocity * stimulus.trajectory_toward_body)
        reactions = {label: 0.0 for label in REACTION_LABELS}
        reactions["flinch"] = threat
        reactions["ignore"] = 1.0 - threat
        return PortPrediction(reactions=reactions, intensity=threat)


def _config(*, visual_only=False, allow_interrupt=False, runtime_enabled=True):
    tick_rates = {"tick": {"duration_ms": 1000}, "needs": {}}
    emotions = {
        "rules": [{"emotion": "scared", "need": "safety", "op": "<=", "value": 30}],
        "default": "calm",
    }
    rooms = {"room": {"id": "room_001", "contains": ["obj_mover"]}}
    objects = {
        "properties": ["round"],
        "affordances": ["look"],
        "objects": {
            "obj_mover": {"developerLabel": "M", "properties": ["round"], "affordances": ["look"]},
        },
    }
    actions = {
        "actions": {
            "observe": {
                "affordance": "look",
                "utility": {"base": 10.0, "needs": {}, "emotions": {}},
                "expected_outcomes": ["pleasant"],
                "reason": "taking a careful look",
            },
        }
    }
    # A fast object heading dead-on at the body (velocity -4 over distance 8).
    motion = {
        "normalization": {
            "max_distance": 10.0,
            "max_speed": 5.0,
            "max_acceleration": 5.0,
            "max_time_to_contact": 10.0,
            "max_size": 1.0,
            "max_size_change_rate": 1.0,
        },
        "approach": {"min_closing_speed": 0.0},
        "objects": {"obj_mover": {"position": [8.0, 0.0], "velocity": [-4.0, 0.0], "size": 0.3}},
    }
    instinct = {
        "feature_order": list(MOTION_FEATURE_NAMES),
        "labels": list(REACTION_LABELS),
        "runtime": {"enabled": runtime_enabled},
        "reaction": {
            "shadow": True,
            "thresholds": {"flinch": 0.5},
            "cooldowns": {"flinch": 0},
            "visual_only": visual_only,
            "allow_interrupt": allow_interrupt,
            "emotion_bias": {"flinch": {"safety": -60}},
            "interrupt": {
                "intensity_threshold": 0.5,
                "interruptible_actions": ["observe"],
                "protective_action": "withdraw",
            },
        },
    }
    return ConfigService.from_dict(
        tick_rates,
        emotions,
        rooms=rooms,
        objects=objects,
        actions=actions,
        safety={"rules": []},
        outcome={"labels": ["pleasant"], "context_features": []},
        instinct=instinct,
        motion=motion,
    )


def _recorder(bus, topic):
    seen: List[DomainEvent] = []
    bus.subscribe(topic, seen.append)
    return seen


# --- the bootstrap builds the bus and drives the live chain -------------------


def test_bootstrap_drives_the_instinct_chain_live_with_a_predictor_and_no_injected_bus():
    # No bus is injected: only the bootstrap can supply the shared EventBus the
    # chain needs. With the visual_only flag on, a moving object must drive a
    # reaction the being surfaces and feels -- proof the deployed wiring fired the
    # whole perception->instinct->reaction chain in-process.
    with build_simulation(
        _config(visual_only=True),
        env={},
        instinct_predictor=FakeInstinctPredictor(),
    ) as sim:
        sim.tick()          # stimulus -> instinct reaction, drained onto the bus
        state = sim.tick()  # the between-ticks reaction now surfaces

        assert state["reaction"]["type"] == "flinch"
        assert state["emotion"] == "scared"


# --- shadow (flags off): the wired chain fires yet changes NO behaviour --------


def test_bootstrap_shadow_chain_fires_but_state_is_byte_identical_to_an_unwired_being():
    bus = InMemoryEventBus()
    reactions = _recorder(bus, INSTINCT_REACTIONS_TOPIC)
    with build_simulation(
        _config(),  # flags default off (shadow)
        env={},
        event_publisher=bus,
        event_consumer=bus,
        instinct_predictor=FakeInstinctPredictor(),
    ) as wired, build_simulation(
        _config(runtime_enabled=False),  # no chain at all
        env={},
    ) as baseline:
        for _ in range(4):
            a = wired.tick()
            b = baseline.tick()
            assert a == b
            assert "reaction" not in a

    # the chain genuinely fired a triggered reaction on the bus -- yet nothing in
    # the being's observable state moved (true shadow).
    assert any(r.payload.get("triggered") for r in reactions)


# --- None-safe: no predictor => inert => byte-identical (lean runtime) ---------


def test_bootstrap_without_a_predictor_wires_no_chain_and_is_byte_identical():
    # The runtime enable flag is on, but the artifact path does not exist, so the
    # predictor loads as None and the chain stays out entirely -- the lean-runtime
    # path (no torch / no artifact). The being is byte-identical to a plain one.
    plain = Simulation(_config())
    with build_simulation(
        _config(),
        env={"INSTINCT_MODEL_PATH": "/nonexistent/instinct.pt"},
    ) as sim:
        for _ in range(4):
            a = sim.tick()
            b = plain.tick()
            assert a == b
            assert "reaction" not in a
        assert sim.instinct_lag() == 0


# --- the runtime-enable flag (config seam) ------------------------------------


def test_runtime_instinct_is_enabled_by_default_and_config_can_disable_it():
    assert _config().instinct_runtime_enabled() is True
    assert _config(runtime_enabled=False).instinct_runtime_enabled() is False
    # An instinct config with no runtime block at all still defaults on.
    cfg = ConfigService.from_dict(
        {"tick": {"duration_ms": 1000}, "needs": {}},
        {"rules": [], "default": "calm"},
        instinct={"feature_order": list(MOTION_FEATURE_NAMES), "labels": list(REACTION_LABELS)},
    )
    assert cfg.instinct_runtime_enabled() is True


# --- the SHIPPED config, end to end: a legible flinch, action unchanged --------


def test_shipped_config_visual_only_surfaces_a_flinch_on_the_ball_without_changing_the_action():
    # The slice outcome on the SHIPPED config + shipped world motion: the red ball
    # is a fast, body-bound approach; with visual_only shipped ON and an instinct
    # predictor wired, the being SURFACES a flinch and its DERIVED emotion shifts to
    # `scared` -- while the action it decides is identical, tick for tick, to the
    # same being with no instinct chain (no interruption -- allow_interrupt is off).
    # Torch-free (a fake predictor stands in for models/instinct.pt), so this holds
    # in the artifact-free canonical suite too.
    config = ConfigService.from_files(_CONFIG_ROOT).with_room_contents(["obj_red_ball"])

    bus = InMemoryEventBus()
    interrupts = _recorder(bus, "being.action.events")
    baseline = Simulation(config)  # no predictor -> instinct chain inert
    with build_simulation(
        config,
        env={},
        event_publisher=bus,
        event_consumer=bus,
        instinct_predictor=FakeInstinctPredictor(),
    ) as wired:
        reacted = False
        for _ in range(4):
            a = wired.tick()
            b = baseline.tick()
            # visual-only never touches the decision; allow_interrupt is off -> the
            # decided action is byte-identical to the no-chain being every tick.
            assert a.get("currentAction") == b.get("currentAction")
            if a.get("reaction") is not None:
                reacted = True
                assert a["reaction"]["type"] == "flinch"
                assert a["emotion"] == "scared"

    assert reacted, "the fast body-bound ball should have surfaced a flinch"
    assert interrupts == []  # allow_interrupt off -> nothing is ever interrupted

"""Behaviors: how the being selects and performs ONE action toward an object
each tick — by utility scoring, with a stated reason — and how the safety
guardrail hard-blocks unsafe actions so a high score can never bypass it.

Every test asserts through the public surface only: `Simulation.tick()`,
`Simulation.state()` (which now carries `currentAction`), and
`Simulation.interactions()` (the in-memory InteractionEvent log). The
decision/utility + safety-guardrail seam is ADR 0009.
"""
from __future__ import annotations

from app.config_service import ConfigService
from app.simulation import Simulation

# --- emotion table: curious when curiosity is high, scared when safety is low.
_EMOTIONS = {
    "rules": [
        {"emotion": "scared", "need": "safety", "op": "<=", "value": 30},
        {"emotion": "curious", "need": "curiosity", "op": ">=", "value": 70},
    ],
    "default": "calm",
}

# --- object vocabulary + two objects: a safe ball and a hot (unsafe) thing.
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

# --- the being's actions: some affordance-gated (observe/touch/grab/push), some
# self-directed and always available (approach/withdraw). Utility is base +
# per-need coefficients + per-emotion bonuses. Tuned so a curious being explores
# (observe/approach) and a scared one withdraws.
_ACTIONS = {
    "actions": {
        "observe": {
            "affordance": "look",
            "utility": {"base": 2.0, "needs": {"curiosity": 0.04}, "emotions": {"curious": 2.0}},
            "expected_outcomes": ["pleasant"],
            "reason": "curiosity is high, so I take a careful look",
        },
        "approach": {
            "free": True,
            "utility": {"base": 1.5, "needs": {"curiosity": 0.03}, "emotions": {"curious": 2.5, "scared": -4.0}},
            "expected_outcomes": ["pleasant"],
            "reason": "curiosity is high and it looks safe to approach",
        },
        "withdraw": {
            "free": True,
            "utility": {"base": 0.2, "needs": {}, "emotions": {"scared": 6.0, "curious": -2.0}},
            "expected_outcomes": [],
            "reason": "this feels unsafe, so I move away",
        },
        "touch": {
            "affordance": "touch",
            "utility": {"base": 1.0, "needs": {"curiosity": 0.02}, "emotions": {"curious": 0.5, "scared": -5.0}},
            "expected_outcomes": ["pleasant"],
            "property_outcomes": {"hot": ["causes_pain", "scary"], "soft": ["pleasant"]},
            "reason": "reaching out to touch",
        },
        "grab": {
            "affordance": "grab",
            "utility": {"base": 0.8, "needs": {"curiosity": 0.01}, "emotions": {"curious": 0.3, "scared": -5.0}},
            "expected_outcomes": [],
            "property_outcomes": {"hot": ["causes_pain", "scary"], "soft": ["pleasant"]},
            "reason": "reaching to hold it",
        },
        "push": {
            "affordance": "push",
            "utility": {"base": 0.7, "needs": {"curiosity": 0.02}, "emotions": {"curious": 0.5, "scared": -1.0}},
            "expected_outcomes": [],
            "property_outcomes": {"round": ["rolls"], "hard": ["makes_noise"]},
            "reason": "giving it a push to see what happens",
        },
    }
}

# --- safety: direct hand-contact with a hot surface is hard-blocked.
_SAFETY = {
    "rules": [
        {"action": "touch", "blocked_property": "hot", "reason": "a hot surface would cause pain"},
        {"action": "grab", "blocked_property": "hot", "reason": "grasping a hot surface would cause pain"},
    ]
}


def _needs(**overrides):
    """Contextual needs (no autonomous drift) so a test's chosen levels hold
    steady and the decision is a function of exactly the state we set."""
    levels = {"curiosity": 40, "safety": 80, "comfort": 70, "hunger": 30, "sleep": 30, "warmth": 50}
    levels.update(overrides)
    return {
        name: {"direction": "contextual", "amount": 0, "every_ticks": 1, "min": 0, "max": 100, "start": val}
        for name, val in levels.items()
    }


def _room(*contains):
    return {"id": "room_001", "contains": list(contains)}


def _sim(*, room, needs=None, actions=_ACTIONS, safety=_SAFETY, timing=None, objects=_OBJECTS, emotions=_EMOTIONS):
    tick_rates = {"tick": {"duration_ms": 1000}, "needs": needs or _needs()}
    if timing is not None:
        tick_rates["actions"] = timing
    return Simulation(
        ConfigService.from_dict(
            tick_rates,
            emotions,
            rooms={"room": room},
            objects=objects,
            actions=actions,
            safety=safety,
        )
    )


def test_a_high_curiosity_being_approaches_or_observes_a_safe_object():
    sim = _sim(room=_room("obj_ball"), needs=_needs(curiosity=75))

    state = sim.tick()

    assert state["emotion"] == "curious"
    assert state["currentAction"]["type"] in {"observe", "approach"}
    assert state["currentAction"]["targetId"] == "obj_ball"
    assert state["currentAction"]["reason"]  # a stated reason, not empty


def test_currentAction_is_absent_at_birth_before_any_tick():
    sim = _sim(room=_room("obj_ball"))
    assert "currentAction" not in sim.state()


def test_a_scared_being_withdraws_because_emotion_drives_utility():
    sim = _sim(room=_room("obj_ball"), needs=_needs(safety=10, curiosity=40))

    state = sim.tick()

    assert state["emotion"] == "scared"
    assert state["currentAction"]["type"] == "withdraw"


def test_touch_on_a_hot_object_is_blocked_and_a_safe_action_is_chosen():
    # touch has by far the highest utility here (base 10) — yet it must never be
    # chosen on a hot object: a score can never bypass safety.
    touch_top = {
        "actions": {
            "touch": {
                "affordance": "touch",
                "utility": {"base": 10.0, "needs": {}, "emotions": {}},
                "property_outcomes": {"hot": ["causes_pain", "scary"]},
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
    sim = _sim(room=_room("obj_hot"), actions=touch_top)

    state = sim.tick()

    # the top-scoring action (touch) was blocked; a safe action was chosen
    assert state["currentAction"]["type"] == "observe"
    # and the guardrail is visible in the stated reason
    assert "block" in state["currentAction"]["reason"].lower()
    # no interaction event ever touched the hot object
    assert all(e["action"] != "touch" for e in sim.interactions())


def test_the_hot_object_is_never_touched_even_over_many_ticks():
    sim = _sim(room=_room("obj_ball", "obj_hot"), needs=_needs(curiosity=75))

    for _ in range(25):
        sim.tick()

    assert sim.interactions()  # the being did act
    touched_hot = [
        e for e in sim.interactions() if e["objectId"] == "obj_hot" and e["action"] in {"touch", "grab"}
    ]
    assert touched_hot == []


def test_an_action_respects_its_cooldown():
    # One object affording one action, cooldown 3: after it fires the being has
    # nothing else to do until the cooldown expires.
    single = {
        "actions": {
            "observe": {
                "affordance": "look",
                "utility": {"base": 1.0, "needs": {}, "emotions": {}},
                "expected_outcomes": ["pleasant"],
                "reason": "looking",
            }
        }
    }
    timing = {"observe": {"duration_ticks": 0, "cooldown_ticks": 3}}
    sim = _sim(room=_room("obj_ball"), actions=single, safety={"rules": []}, timing=timing)

    first = sim.tick()  # tick 1: observe fires
    assert first["currentAction"]["type"] == "observe"

    for _ in range(3):  # ticks 2, 3, 4: observe on cooldown, nothing else to do
        assert "currentAction" not in sim.tick()

    resumed = sim.tick()  # tick 5: cooldown expired, observe fires again
    assert resumed["currentAction"]["type"] == "observe"


def test_each_action_produces_an_interaction_event_with_expected_and_observed_outcomes():
    sim = _sim(room=_room("obj_ball"), needs=_needs(curiosity=75))

    sim.tick()

    events = sim.interactions()
    assert events
    event = events[-1]
    assert event["objectId"] == "obj_ball"
    assert isinstance(event["action"], str)
    assert isinstance(event["expectedOutcome"], list)
    assert isinstance(event["observedOutcome"], list)
    assert isinstance(event["emotionBefore"], str)
    assert isinstance(event["emotionAfter"], str)


def test_the_observed_outcome_reflects_the_object_acted_on():
    # Force a touch on a soft object: the outcome table says touching something
    # soft is pleasant, and that lands in the event's observed outcome.
    touch_top = {
        "actions": {
            "touch": {
                "affordance": "touch",
                "utility": {"base": 10.0, "needs": {}, "emotions": {}},
                "expected_outcomes": [],
                "property_outcomes": {"soft": ["pleasant"]},
                "reason": "reaching out to touch",
            }
        }
    }
    sim = _sim(room=_room("obj_ball"), actions=touch_top, safety={"rules": []})

    sim.tick()

    event = sim.interactions()[-1]
    assert event["action"] == "touch"
    assert "pleasant" in event["observedOutcome"]


def test_a_being_with_no_perceivable_object_takes_no_action():
    sim = _sim(room=_room())  # empty room

    state = sim.tick()

    assert "currentAction" not in state
    assert sim.interactions() == []


def test_the_chosen_action_is_config_only():
    # Same code, same being; only the utility weights differ — and the action the
    # being takes flips. Retuning the decision is a config change, not a code one.
    observe_heavy = {
        "actions": {
            "observe": {"affordance": "look", "utility": {"base": 5.0, "needs": {}, "emotions": {}}, "reason": "look"},
            "approach": {"free": True, "utility": {"base": 1.0, "needs": {}, "emotions": {}}, "reason": "approach"},
        }
    }
    approach_heavy = {
        "actions": {
            "observe": {"affordance": "look", "utility": {"base": 1.0, "needs": {}, "emotions": {}}, "reason": "look"},
            "approach": {"free": True, "utility": {"base": 5.0, "needs": {}, "emotions": {}}, "reason": "approach"},
        }
    }

    a = _sim(room=_room("obj_ball"), actions=observe_heavy, safety={"rules": []}).tick()
    b = _sim(room=_room("obj_ball"), actions=approach_heavy, safety={"rules": []}).tick()

    assert a["currentAction"]["type"] == "observe"
    assert b["currentAction"]["type"] == "approach"

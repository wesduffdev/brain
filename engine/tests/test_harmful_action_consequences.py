"""Behaviors (ADR 0009/0013/0014): a recoverable-but-harmful action — touching a
hot object — is ALLOWED now that the safety guardrail is a minimal *invariant
floor* rather than a hard block on harm. Taking it lands honest negative
consequences as abstract state deltas (a pain spike, a fall in felt safety that
reads as fear, lost comfort), and the harmful experience is recorded as a
`causes_pain` outcome the model can later learn from. Recovery is modeled only
where it plausibly exists (acute pain decays over ticks; the fear can linger).
Only a genuinely simulation-breaking action stays on the invariant floor.

Everything is asserted through the public surface only: `Simulation.tick()`,
`Simulation.state()` (needs + emotion), and `Simulation.interactions()` (the
InteractionEvent log). Magnitudes and the invariant/risk split are config, and a
test proves each is retunable in config alone.
"""
from __future__ import annotations

from app.config_service import ConfigService
from app.ml.encode_features import FeatureEncoder
from app.repositories import InMemoryTrainingExampleRepository
from app.simulation import Simulation

# --- emotion table: scared when felt safety is low; curious when curiosity high.
_EMOTIONS = {
    "rules": [
        {"emotion": "scared", "need": "safety", "op": "<=", "value": 30},
        {"emotion": "curious", "need": "curiosity", "op": ">=", "value": 70},
    ],
    "default": "calm",
}

# --- outcome vocabulary the felt-consequence effects and the ML encoder share.
_OUTCOME = {
    "labels": ["pleasant", "causes_pain", "scary"],
    "context_features": ["surface_hard", "surface_soft"],
}

# --- a hot object (touching it hurts) and a soft one (touching it is pleasant).
_OBJECTS = {
    "properties": ["soft", "hard", "hot"],
    "affordances": ["look", "touch", "grab"],
    "objects": {
        "obj_hot": {"developerLabel": "Hot Thing", "properties": ["hot", "hard"], "affordances": ["look", "touch", "grab"]},
        "obj_soft": {"developerLabel": "Soft Thing", "properties": ["soft"], "affordances": ["look", "touch"]},
    },
}

# --- the felt consequence of each outcome, as need deltas (ADR 0014). Touching
# something hot causes pain: a pain spike, felt safety crashes (-> fear), comfort
# drops. Magnitudes are config, proven retunable by a test below.
_EFFECTS = {
    "effects": {
        "causes_pain": {"pain": 40, "safety": -60, "comfort": -20},
        "scary": {"safety": -10},
    }
}

# --- touch dominates utility so the choice is deterministic; observe is the safe
# fallback when touch is on the invariant floor.
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

# --- a being that touches once, is hurt (scared), then withdraws — so pain can
# be seen to decay with no further harm.
_REALISTIC = {
    "actions": {
        "touch": {
            "affordance": "touch",
            "utility": {"base": 3.0, "needs": {}, "emotions": {"scared": -5.0}},
            "expected_outcomes": [],
            "property_outcomes": {"hot": ["causes_pain", "scary"]},
            "reason": "reaching out to touch",
        },
        "observe": {
            "affordance": "look",
            "utility": {"base": 2.0, "needs": {}, "emotions": {"scared": 0.5}},
            "expected_outcomes": [],
            "reason": "looking",
        },
        "withdraw": {
            "free": True,
            "utility": {"base": 0.2, "needs": {}, "emotions": {"scared": 6.0}},
            "expected_outcomes": [],
            "reason": "this feels unsafe, so I move away",
        },
    }
}
_REALISTIC_TIMING = {"observe": {"cooldown_ticks": 1}, "touch": {"cooldown_ticks": 2}}


def _needs(pain_decay=(5, 2), **overrides):
    """Contextual needs (no drift) so a test's chosen levels hold steady, plus a
    `pain` need that starts at 0 and decays down over ticks — the recovery path
    for acute pain (ADR 0014). `pain_decay=(amount, every_ticks)`."""
    levels = {"curiosity": 40, "safety": 80, "comfort": 70, "hunger": 30, "sleep": 30, "warmth": 50}
    levels.update(overrides)
    needs = {
        name: {"direction": "contextual", "amount": 0, "every_ticks": 1, "min": 0, "max": 100, "start": val}
        for name, val in levels.items()
    }
    amount, every = pain_decay
    needs["pain"] = {"direction": "decrease", "amount": amount, "every_ticks": every, "min": 0, "max": 100, "start": 0}
    return needs


def _room(*contains):
    return {"id": "room_001", "contains": list(contains)}


def _config(*, room, needs=None, actions=_TOUCH_TOP, safety=None, effects=None, timing=None):
    tick_rates = {"tick": {"duration_ms": 1000}, "needs": needs or _needs()}
    if timing is not None:
        tick_rates["actions"] = timing
    return ConfigService.from_dict(
        tick_rates,
        _EMOTIONS,
        rooms={"room": room},
        objects=_OBJECTS,
        outcome=_OUTCOME,
        actions=actions,
        safety=safety if safety is not None else {"rules": []},
        outcome_effects=effects if effects is not None else _EFFECTS,
    )


def _sim(**kwargs):
    return Simulation(_config(**kwargs))


def test_touching_a_hot_object_is_allowed_now_that_the_floor_is_empty():
    # With no invariant rule, touching a hot object is no longer hard-blocked.
    sim = _sim(room=_room("obj_hot"))

    sim.tick()

    touched = [e for e in sim.interactions() if e["objectId"] == "obj_hot" and e["action"] == "touch"]
    assert touched  # the being reached out and touched it


def test_touching_a_hot_object_spikes_pain_and_reads_as_fear():
    sim = _sim(room=_room("obj_hot"))
    before = sim.state()
    assert before["needs"]["pain"] == 0

    after = sim.tick()

    assert after["needs"]["pain"] > before["needs"]["pain"]      # a pain spike
    assert after["needs"]["safety"] < before["needs"]["safety"]  # felt safety fell
    assert after["needs"]["comfort"] < before["needs"]["comfort"]  # comfort lost
    assert after["emotion"] == "scared"                           # ... enough to read as fear


def test_a_harmful_touch_records_the_causes_pain_outcome():
    sim = _sim(room=_room("obj_hot"))

    sim.tick()

    event = sim.interactions()[-1]
    assert event["action"] == "touch"
    assert "causes_pain" in event["observedOutcome"]
    # the experience itself changed how the being felt: before vs after diverge
    assert event["emotionBefore"] != event["emotionAfter"]
    assert event["emotionAfter"] == "scared"


def test_the_recorded_experience_encodes_causes_pain_for_the_model_to_learn():
    # The observed outcome flows into a derived training example (ADR 0012), so a
    # hot touch teaches the model `hot -> causes_pain`.
    examples = InMemoryTrainingExampleRepository()
    config = _config(room=_room("obj_hot"))
    sim = Simulation(config, training_repo=examples)

    sim.tick()

    encoder = FeatureEncoder.from_config(config)
    example = examples.all()[-1]
    labels = dict(zip(encoder.label_names(), example.output_labels))
    assert labels["causes_pain"] == 1.0


def test_acute_pain_recovers_as_it_decays_while_the_fear_can_linger():
    # Recovery only where it plausibly exists: the acute pain fades over ticks,
    # but felt safety stays low, so the being remains scared (no forced recovery).
    sim = _sim(room=_room("obj_hot"), actions=_REALISTIC, timing=_REALISTIC_TIMING)

    sim.tick()  # touch -> pain spike, then the being is scared and withdraws
    spike = sim.state()["needs"]["pain"]
    assert spike > 0

    for _ in range(30):
        sim.tick()

    assert sim.state()["needs"]["pain"] < spike      # the acute pain decayed
    assert sim.state()["emotion"] == "scared"        # but the fear lingers


def test_a_sim_breaking_action_stays_on_the_invariant_floor_but_the_split_is_config():
    # An invariant-floor rule still hard-blocks its action no matter the utility.
    floor = {"rules": [{"action": "touch", "blocked_property": "hot", "reason": "this would break the simulation"}]}
    blocked = _sim(room=_room("obj_hot"), safety=floor)
    for _ in range(5):
        blocked.tick()
    assert blocked.interactions()  # it still acted (the safe fallback)
    assert all(e["action"] != "touch" for e in blocked.interactions())  # never touched

    # The SAME action, with the floor empty, IS taken — so the invariant/risk
    # split is a config change, not a code one.
    allowed = _sim(room=_room("obj_hot"), safety={"rules": []})
    allowed.tick()
    assert any(e["action"] == "touch" for e in allowed.interactions())


def test_consequence_magnitudes_are_config_only():
    # Same code, same scenario; only the effect magnitudes differ — and the felt
    # pain differs. Retuning how much harm hurts is a config change.
    mild = {"effects": {"causes_pain": {"pain": 10}}}
    severe = {"effects": {"causes_pain": {"pain": 80}}}

    a = _sim(room=_room("obj_hot"), effects=mild).tick()
    b = _sim(room=_room("obj_hot"), effects=severe).tick()

    assert a["needs"]["pain"] < b["needs"]["pain"]

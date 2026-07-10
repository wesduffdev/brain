"""Behaviors: how the room's environmental conditions move the being's
*contextual* needs (safety, warmth), and therefore its emotion.

Every test asserts through the public surface only — `Simulation.tick()` and
`Simulation.state()`. A dark or loud room drives safety down over ticks until
`scared` (fear) becomes dominant; a comfortable room leaves the being calm.
The seam between conditions and needs is ADR 0006.
"""
from __future__ import annotations

from app.config_service import ConfigService
from app.simulation import Simulation

# Standard emotion table (fear checked first, as shipped).
_EMOTIONS = {
    "rules": [
        {"emotion": "scared", "need": "safety", "op": "<=", "value": 30},
        {"emotion": "hungry", "need": "hunger", "op": ">=", "value": 80},
        {"emotion": "curious", "need": "curiosity", "op": ">=", "value": 70},
    ],
    "default": "calm",
}

# Every environmental category maps to the per-application delta it applies to a
# contextual need. `every_ticks` is how often those deltas land.
_ENVIRONMENT = {
    "every_ticks": 10,
    "light": {
        "dark": {"safety": -6},
        "comfortable": {"safety": 0},
    },
    "sound": {
        "normal": {"safety": 0},
        "loud": {"safety": -6},
    },
    "temperature": {
        "cool": {"warmth": -4},
        "comfortable": {"warmth": 0},
    },
}


def _need(start):
    # Contextual: no autonomous drift, so only the environment can move it.
    return {"direction": "contextual", "amount": 0, "every_ticks": 1, "min": 0, "max": 100, "start": start}


_NEEDS = {
    "safety": _need(80),
    "warmth": _need(20),
    "hunger": _need(30),
    "sleep": _need(35),
    "comfort": _need(70),
    "curiosity": _need(40),
}


def _sim(*, room, environment=None, emotions=None, needs=None):
    tick_rates = {"tick": {"duration_ms": 1000}, "needs": needs or _NEEDS}
    return Simulation(
        ConfigService.from_dict(
            tick_rates,
            emotions or _EMOTIONS,
            rooms={"room": room},
            environment=environment if environment is not None else _ENVIRONMENT,
        )
    )


def _comfortable_room():
    return {"id": "room_001", "light": "comfortable", "sound": "normal", "temperature": "comfortable"}


def test_dark_room_lowers_safety_until_being_is_scared():
    sim = _sim(room={"id": "room_001", "light": "dark", "sound": "normal", "temperature": "comfortable"})
    assert sim.state()["emotion"] == "calm"  # safe at birth

    emotions_seen = {sim.state()["emotion"]}
    for _ in range(200):
        state = sim.tick()
        emotions_seen.add(state["emotion"])

    assert state["needs"]["safety"] < 80  # the dark room pushed safety down
    assert "scared" in emotions_seen
    assert sim.state()["emotion"] == "scared"


def test_loud_room_lowers_safety_until_being_is_scared():
    sim = _sim(room={"id": "room_001", "light": "comfortable", "sound": "loud", "temperature": "comfortable"})
    assert sim.state()["emotion"] == "calm"

    for _ in range(200):
        sim.tick()

    assert sim.state()["emotion"] == "scared"


def test_a_comfortable_room_leaves_the_being_calm():
    sim = _sim(room=_comfortable_room())
    for _ in range(200):
        sim.tick()

    assert sim.state()["needs"]["safety"] == 80  # nothing pushed it
    assert sim.state()["emotion"] == "calm"


def test_darkening_a_calm_beings_room_drives_it_to_fear():
    # The demo's story: a calm being whose room goes dark becomes scared —
    # same being, no reset. Changing the room is a world event, not an action.
    sim = _sim(room=_comfortable_room())
    for _ in range(50):
        sim.tick()
    assert sim.state()["emotion"] == "calm"

    sim.change_environment(light="dark")
    for _ in range(200):
        sim.tick()

    assert sim.state()["emotion"] == "scared"


def test_a_cool_room_lowers_the_warmth_need():
    # Temperature is the other contextual mover; it shifts warmth (no emotion
    # consequence yet, but the need honestly moves).
    sim = _sim(room={"id": "room_001", "light": "comfortable", "sound": "normal", "temperature": "cool"})
    for _ in range(100):
        sim.tick()

    assert sim.state()["needs"]["warmth"] < 20


def test_the_environmental_delta_is_config_only():
    # Same code, a harsher darkness: retuning the push lives in config alone.
    gentle_env = {"every_ticks": 10, "light": {"dark": {"safety": -1}},
                  "sound": {"normal": {"safety": 0}}, "temperature": {"comfortable": {"warmth": 0}}}
    harsh_env = {"every_ticks": 10, "light": {"dark": {"safety": -20}},
                 "sound": {"normal": {"safety": 0}}, "temperature": {"comfortable": {"warmth": 0}}}
    dark_room = {"id": "room_001", "light": "dark", "sound": "normal", "temperature": "comfortable"}

    gentle = _sim(room=dark_room, environment=gentle_env)
    harsh = _sim(room=dark_room, environment=harsh_env)
    for _ in range(30):
        gentle.tick()
        harsh.tick()

    assert harsh.state()["needs"]["safety"] < gentle.state()["needs"]["safety"]
    assert harsh.state()["emotion"] == "scared"
    assert gentle.state()["emotion"] != "scared"


def test_the_fear_threshold_is_config_only():
    # Identical dark room and environment; only the `scared` threshold differs.
    # After the same ticks safety is the same, but only the lenient line reads
    # it as fear — proof the threshold is a config change, not a code change.
    dark_room = {"id": "room_001", "light": "dark", "sound": "normal", "temperature": "comfortable"}
    lenient = {"rules": [{"emotion": "scared", "need": "safety", "op": "<=", "value": 30}], "default": "calm"}
    strict = {"rules": [{"emotion": "scared", "need": "safety", "op": "<=", "value": 10}], "default": "calm"}

    lenient_sim = _sim(room=dark_room, emotions=lenient)
    strict_sim = _sim(room=dark_room, emotions=strict)
    for _ in range(100):  # safety: 80 - 6*10 == 20
        lenient_sim.tick()
        strict_sim.tick()

    assert lenient_sim.state()["needs"]["safety"] == strict_sim.state()["needs"]["safety"]
    assert lenient_sim.state()["emotion"] == "scared"  # 20 <= 30
    assert strict_sim.state()["emotion"] != "scared"  # 20 > 10


def test_a_room_naming_an_unknown_condition_is_rejected():
    # Same discipline as the object-property vocabulary: a typo'd or invented
    # condition category fails loudly rather than silently doing nothing.
    bad_room = {"id": "room_001", "light": "drak", "sound": "normal", "temperature": "comfortable"}
    sim = _sim(room=bad_room)
    import pytest

    with pytest.raises(ValueError):
        sim.tick()

"""End-to-end behaviors of the whole engine core, on the SHIPPED config —
so the config files are exercised, not just hand-built dicts."""
from __future__ import annotations

import os

from app.config_service import ConfigService
from app.simulation import Simulation

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _fresh():
    return Simulation(ConfigService.from_files(_CONFIG_ROOT))


def test_state_reports_tick_needs_and_emotion():
    state = _fresh().state()
    assert state["tick"] == 0
    assert state["beingId"] == "being_001"
    assert {"hunger", "sleep", "comfort", "warmth", "curiosity", "safety", "hygiene"} <= set(state["needs"])
    assert isinstance(state["emotion"], str)


def test_a_fresh_being_is_born_calm():
    assert _fresh().state()["emotion"] == "calm"


def test_a_left_alone_being_grows_curious_as_curiosity_climbs():
    # Shipped config: curiosity starts 55, +1 every 15 ticks -> 70 by tick 225.
    sim = _fresh()
    assert sim.state()["emotion"] == "calm"

    seen = {sim.state()["emotion"]}
    for _ in range(260):
        seen.add(sim.tick()["emotion"])

    assert "curious" in seen


def test_a_snapshot_does_not_alias_internal_state():
    sim = _fresh()
    snapshot = sim.state()
    snapshot["needs"]["hunger"] = 999  # mutating the copy must not leak back
    assert sim.state()["needs"]["hunger"] != 999

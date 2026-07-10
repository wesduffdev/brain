"""Behaviors: the one dominant emotion the being reads as, given its needs."""
from __future__ import annotations

from app.config_service import ConfigService
from app.simulation import Simulation

# Priority order matters: fear is checked before hunger, hunger before curiosity.
_EMOTIONS = {
    "rules": [
        {"emotion": "scared", "need": "safety", "op": "<=", "value": 30},
        {"emotion": "hungry", "need": "hunger", "op": ">=", "value": 80},
        {"emotion": "curious", "need": "curiosity", "op": ">=", "value": 70},
    ],
    "default": "calm",
}


def _being_with(**needs):
    # All needs frozen at their start value (contextual, no drift), so the
    # birth emotion is exactly the derivation of these levels.
    needs_spec = {
        name: {"direction": "contextual", "amount": 0, "every_ticks": 1, "min": 0, "max": 100, "start": value}
        for name, value in needs.items()
    }
    tick_rates = {"tick": {"duration_ms": 1000}, "needs": needs_spec}
    return Simulation(ConfigService.from_dict(tick_rates, _EMOTIONS)).state()["emotion"]


def test_a_fed_safe_incurious_being_is_calm():
    assert _being_with(hunger=30, safety=80, curiosity=40) == "calm"


def test_curiosity_past_its_line_reads_as_curious():
    assert _being_with(hunger=30, safety=80, curiosity=75) == "curious"


def test_hunger_past_its_line_outranks_curiosity():
    assert _being_with(hunger=85, safety=80, curiosity=90) == "hungry"


def test_low_safety_reads_as_fear_over_everything_else():
    # `scared` is fear; it is the strongest pull and is checked first.
    assert _being_with(hunger=90, safety=20, curiosity=90) == "scared"

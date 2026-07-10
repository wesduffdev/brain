"""Behaviors: how a being's needs move over time, driven by config."""
from __future__ import annotations

from app.config_service import ConfigService
from app.simulation import Simulation


def _sim(needs_spec):
    tick_rates = {"tick": {"duration_ms": 1000}, "needs": needs_spec}
    return Simulation(ConfigService.from_dict(tick_rates, {"rules": [], "default": "calm"}))


def test_a_need_holds_until_its_interval_then_rises():
    sim = _sim(
        {"hunger": {"direction": "increase", "amount": 1, "every_ticks": 30, "min": 0, "max": 100, "start": 30}}
    )
    assert sim.state()["needs"]["hunger"] == 30  # birth value

    for _ in range(29):
        sim.tick()
    assert sim.state()["needs"]["hunger"] == 30  # unchanged before the interval

    sim.tick()  # the 30th tick
    assert sim.state()["needs"]["hunger"] == 31


def test_a_contextual_need_does_not_drift_on_its_own():
    sim = _sim(
        {"safety": {"direction": "contextual", "amount": 1, "every_ticks": 10, "min": 0, "max": 100, "start": 80}}
    )
    for _ in range(200):
        sim.tick()
    assert sim.state()["needs"]["safety"] == 80


def test_a_need_never_climbs_past_its_ceiling():
    sim = _sim(
        {"hunger": {"direction": "increase", "amount": 50, "every_ticks": 1, "min": 0, "max": 100, "start": 30}}
    )
    for _ in range(10):
        sim.tick()
    assert sim.state()["needs"]["hunger"] == 100


def test_a_decreasing_need_never_sinks_below_its_floor():
    sim = _sim(
        {"comfort": {"direction": "decrease", "amount": 40, "every_ticks": 1, "min": 0, "max": 100, "start": 70}}
    )
    for _ in range(10):
        sim.tick()
    assert sim.state()["needs"]["comfort"] == 0


def test_retuning_the_interval_is_a_config_change_only():
    # The same code, a faster drift: proof that tuning lives in config.
    fast = _sim(
        {"hunger": {"direction": "increase", "amount": 1, "every_ticks": 10, "min": 0, "max": 100, "start": 0}}
    )
    for _ in range(30):
        fast.tick()
    assert fast.state()["needs"]["hunger"] == 3  # rose at ticks 10, 20, 30

"""Behavior of the scenario/milestone harness (card V10a).

A single config-defined SCENARIO seeds the room with one object, runs N ticks,
and reports whether a LEARNING METRIC rose — the target concept's confidence,
before vs after the run. This is the repeatable, testable "watch it learn": a
regression scenario that FAILS if learning does not occur.

The scenario file (config/scenarios/rolling_object_intro.yaml) is a HARNESS
input the runner parses directly (PyYAML), never routed through ConfigService —
the being's own config (needs, actions, safety, the object catalog) still comes
from config/*.yaml via ConfigService. The metric is CONCEPT CONFIDENCE (card
v2): pushing a round object teaches "round things roll", and that concept's
confidence climbs from nothing.
"""
from __future__ import annotations

import os

from app.services.scenario_runner import ScenarioRunner

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")
_SCENARIO = os.path.join(_CONFIG_ROOT, "scenarios", "rolling_object_intro.yaml")


def _runner() -> ScenarioRunner:
    return ScenarioRunner(scenario_path=_SCENARIO, config_root=_CONFIG_ROOT)


def test_running_the_scenario_raises_the_target_confidence_past_its_threshold():
    result = _runner().run()

    # the being started knowing nothing about round things rolling ...
    assert result.before == 0.0
    # ... and after N ticks of pushing the round object, it has learned it
    assert result.after > result.before
    assert result.after > 0.0
    # the learning metric rose past the scenario's configured floor — the
    # regression signal a run must clear
    assert result.delta >= result.threshold
    assert result.passed
    # the verdict names the metric it measured (the documented before/after line)
    assert "round" in result.metric
    assert "->" in result.summary()


def test_a_run_with_no_interaction_does_not_meet_the_threshold():
    # zero ticks => no pushes => the concept never forms => the metric cannot
    # rise, so the SAME regression assertion FAILS. This proves the scenario
    # measures learning, not noise: no learning, no pass.
    result = _runner().run(ticks=0)

    assert result.before == result.after == 0.0
    assert result.delta == 0.0
    assert not result.passed

"""Behavior of the developmental scenario/milestone system (card v10).

Config-defined SCENARIOS seed a room, run N ticks, and track developmental
MILESTONES — named capabilities the being grows into as a learning metric climbs
a ladder of stages. The same scenarios double as REGRESSION checks: a scenario
PASSES when the expected learning occurs and FAILS when it does not.

These behaviors are observed end-to-end through the public services
(ScenarioService, MilestoneService, ScenarioRunner, RegressionEvaluationService)
and the value objects they return — never by reaching into the Simulation, which
is exercised only through its public concepts() surface (card v2). Milestone
thresholds and stage ladders live in config/milestones.yaml; scenarios in
config/scenarios/*.yaml.
"""
from __future__ import annotations

import os

from app.services.milestone_service import MilestoneService
from app.services.regression_evaluation_service import RegressionEvaluationService
from app.services.scenario_runner import ScenarioRunner
from app.services.scenario_service import ScenarioService

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")
_SCENARIOS_DIR = os.path.join(_CONFIG_ROOT, "scenarios")
_MILESTONES = os.path.join(_CONFIG_ROOT, "milestones.yaml")


def _scenario_service() -> ScenarioService:
    return ScenarioService(_SCENARIOS_DIR)


def _milestone_service() -> MilestoneService:
    return MilestoneService(_MILESTONES)


def _runner(name: str) -> ScenarioRunner:
    scenario = _scenario_service().load(name)
    return ScenarioRunner(
        scenario=scenario,
        config_root=_CONFIG_ROOT,
        milestone_service=_milestone_service(),
    )


def _regression() -> RegressionEvaluationService:
    return RegressionEvaluationService(
        scenario_service=_scenario_service(),
        milestone_service=_milestone_service(),
        config_root=_CONFIG_ROOT,
    )


def test_rolling_object_scenario_advances_the_round_objects_roll_milestone():
    # Living with a round object and repeatedly pushing it, the being crosses a
    # developmental stage: the round_objects_roll milestone moves off its floor.
    result = _runner("rolling_object_intro").run()

    progress = result.milestone("round_objects_roll")
    assert progress.stage_before == "unaware"
    assert progress.stage_after == "established"
    assert progress.stage_index_after > progress.stage_index_before
    assert progress.advanced


def test_a_run_with_no_interaction_leaves_the_milestone_on_its_floor():
    # Zero ticks => no pushes => the concept never forms => the being does not
    # develop: the milestone stays on its lowest stage and has not advanced.
    result = _runner("rolling_object_intro").run(ticks=0)

    progress = result.milestone("round_objects_roll")
    assert progress.stage_before == progress.stage_after == "unaware"
    assert not progress.advanced


def test_hard_object_scenario_advances_the_hard_objects_make_noise_milestone():
    # The system is not single-milestone: a different scenario drives a different
    # developmental milestone. Pushing a hard object teaches that it makes noise.
    result = _runner("hard_object_intro").run()

    progress = result.milestone("hard_objects_make_noise")
    assert progress.stage_before == "unaware"
    assert progress.advanced


def test_scenario_service_lists_all_configured_scenarios():
    # Config defines MULTIPLE scenarios; the service discovers and names them.
    names = _scenario_service().names()

    assert "rolling_object_intro" in names
    assert "hard_object_intro" in names
    assert len(names) >= 2


def test_a_regression_scenario_passes_when_the_expected_learning_occurs():
    # Run to completion, the scenario's expected learning happens: the metric
    # clears its floor and every tracked milestone reaches its expected stage.
    outcome = _regression().evaluate("rolling_object_intro")

    assert outcome.passed
    assert outcome.failures == ()
    # the verdict carries the run's metrics (the "watch it learn" reading)
    assert outcome.result.after > outcome.result.before
    assert outcome.result.milestone("round_objects_roll").advanced


def test_a_regression_scenario_fails_when_the_expected_learning_is_absent():
    # The SAME regression check, run with no interaction (the negative control),
    # FAILS: no learning, no pass — proving the check has teeth. The failures
    # name what did not happen (the metric floor and/or the milestone stage).
    outcome = _regression().evaluate("rolling_object_intro", ticks=0)

    assert not outcome.passed
    assert outcome.failures  # non-empty, names the unmet expectations
    assert any("round" in reason for reason in outcome.failures)


def test_a_run_produces_a_metrics_snapshot():
    # A run is inspectable: its snapshot carries the before/after metric and the
    # per-milestone stage progressions — the documented, serializable record.
    snapshot = _runner("rolling_object_intro").run().snapshot()

    assert snapshot["before"] == 0.0
    assert snapshot["after"] > 0.0
    assert snapshot["delta"] > 0.0
    milestones = snapshot["milestones"]
    assert any(m["milestone"] == "round_objects_roll" and m["advanced"] for m in milestones)

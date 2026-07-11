"""RegressionEvaluationService — turn a scenario into a pass/fail regression check.

A scenario doubles as a REGRESSION TEST: run it, then judge whether the expected
learning actually occurred. This service loads a scenario by name, runs it through
the `ScenarioRunner`, and checks two kinds of expectation:

  - the headline metric cleared its success floor (the concept confidence rose
    far enough), and
  - every developmental MILESTONE the scenario declares reached at least its
    expected stage.

The verdict is a `RegressionOutcome` — the run's result plus every unmet
expectation named in `failures`. It PASSES when nothing went unmet and FAILS the
moment expected learning is absent (e.g. a run with no interaction), which is
what makes the scenario a regression guard rather than a demo. See docs/BRIEF.md
§16.
"""
from __future__ import annotations

from typing import List, Optional

from app.domain.scenario_result import RegressionOutcome
from app.services.milestone_service import MilestoneService
from app.services.scenario_runner import ScenarioRunner
from app.services.scenario_service import ScenarioService


class RegressionEvaluationService:
    def __init__(
        self,
        *,
        scenario_service: ScenarioService,
        milestone_service: MilestoneService,
        config_root: str,
    ) -> None:
        self._scenarios = scenario_service
        self._milestones = milestone_service
        self._config_root = config_root

    def evaluate(
        self, scenario_name: str, ticks: Optional[int] = None
    ) -> RegressionOutcome:
        """Run the named scenario and judge whether its expected learning occurred.

        `ticks` overrides the scenario's own length — passing 0 is the negative
        control that makes a healthy regression check FAIL, proving it measures
        learning rather than noise."""
        scenario = self._scenarios.load(scenario_name)
        runner = ScenarioRunner(
            scenario=scenario,
            config_root=self._config_root,
            milestone_service=self._milestones,
        )
        result = runner.run(ticks)

        failures: List[str] = []
        if not result.passed:
            failures.append(
                f"metric {result.metric} rose {result.delta:+.3f}, "
                f"needs >= {result.threshold:.3f}"
            )
        for expectation in scenario.milestones:
            progress = result.milestone(expectation.milestone)
            expected_index = self._milestones.get(
                expectation.milestone
            ).stage_index(expectation.expect_stage)
            if progress.stage_index_after < expected_index:
                failures.append(
                    f"milestone {expectation.milestone} reached "
                    f"{progress.stage_after!r}, expected at least "
                    f"{expectation.expect_stage!r}"
                )

        return RegressionOutcome(
            scenario=scenario.name, result=result, failures=tuple(failures)
        )

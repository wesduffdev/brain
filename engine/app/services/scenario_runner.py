"""ScenarioRunner — seed a being from a scenario, run it, measure what it learned.

A SCENARIO is a small authored experiment (config/scenarios/*.yaml): a room of
objects, how many ticks to live, a headline LEARNING TARGET with a success floor,
and the developmental MILESTONES the run exercises. The runner is the harness that
turns that scenario into a reading — it seeds a `Simulation` with the scenario's
objects, runs N ticks, and reads two things off the being's public surface: the
target concept's confidence before vs after (card v2), and, for each milestone the
scenario declares, which developmental STAGE the being has reached (card v10). It
reports a `ScenarioResult` carrying the metric verdict and the milestone
progressions — the repeatable "watch it learn, watch it grow up".

The scenario is a HARNESS INPUT, not engine config: `ScenarioService` parses the
file directly (PyYAML) and never routes it through ConfigService — the being's own
config (needs, actions, safety, the object catalog) still comes from config/*.yaml
via ConfigService. The runner only uses ConfigService's existing public surface
(`from_files`, `resolve_object`, `with_room_contents`) to place the scenario's
objects, and reads all metrics through the Simulation's public `concepts()`
surface. Milestone stage ladders come from `MilestoneService`
(config/milestones.yaml), also a harness input. See docs/BRIEF.md §16 and §18.
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Tuple

from app.config_service import ConfigService
from app.domain.milestone import MilestoneProgress
from app.domain.scenario import Scenario
from app.domain.scenario_result import ScenarioResult
from app.repositories import InMemoryConceptRepository
from app.services.milestone_service import MilestoneService
from app.services.scenario_service import ScenarioService
from app.simulation import Simulation


class ScenarioRunner:
    def __init__(
        self,
        *,
        scenario: Optional[Scenario] = None,
        scenario_path: Optional[str] = None,
        config_root: str,
        milestone_service: Optional[MilestoneService] = None,
    ) -> None:
        if scenario is None:
            if scenario_path is None:
                raise ValueError(
                    "ScenarioRunner needs a `scenario` or a `scenario_path`"
                )
            scenario = ScenarioService.load_file(scenario_path)
        self._scenario = scenario
        self._config_root = config_root
        self._milestones = milestone_service

    def run(self, ticks: Optional[int] = None) -> ScenarioResult:
        """Seed the being from the scenario, run `ticks` (default: the scenario's
        own), and report how far the target concept's confidence moved and which
        developmental stages the tracked milestones crossed.

        Passing `ticks=0` runs no interactions — the metric cannot rise and no
        milestone can advance, so the result does not pass; that is the harness's
        negative control, proving the scenario measures learning rather than noise.
        """
        scenario = self._scenario
        run_ticks = int(scenario.ticks if ticks is None else ticks)

        config = ConfigService.from_files(self._config_root)
        object_ids = [
            config.resolve_object(sel) for sel in scenario.object_selectors
        ]
        # Inject a concept store so the being actually forms concepts and the
        # metrics have something to read; the scenario needs no database.
        sim = Simulation(
            config.with_room_contents(object_ids),
            concept_repository=InMemoryConceptRepository(),
        )

        before_concepts = sim.concepts()
        for _ in range(run_ticks):
            sim.tick()
        after_concepts = sim.concepts()

        before = self._confidence(before_concepts, scenario.target)
        after = self._confidence(after_concepts, scenario.target)
        progressions = self._milestone_progress(
            scenario, before_concepts, after_concepts
        )

        metric = (
            f"{scenario.target['feature']}+{scenario.target['action']}"
            f"->{scenario.target['outcome']} confidence"
        )
        return ScenarioResult(
            scenario=scenario.name,
            metric=metric,
            ticks=run_ticks,
            before=before,
            after=after,
            threshold=scenario.min_confidence_delta,
            milestones=progressions,
        )

    def _milestone_progress(
        self,
        scenario: Scenario,
        before_concepts: List[Dict],
        after_concepts: List[Dict],
    ) -> Tuple[MilestoneProgress, ...]:
        """The stage each declared milestone crossed, read from the concept
        confidence before vs after. Empty when the scenario declares none."""
        if not scenario.milestones:
            return ()
        milestones = self._milestones or MilestoneService.from_config_root(
            self._config_root
        )
        progressions = []
        for expectation in scenario.milestones:
            milestone = milestones.get(expectation.milestone)
            value_before = self._confidence(before_concepts, milestone.concept)
            value_after = self._confidence(after_concepts, milestone.concept)
            progressions.append(milestone.progress(value_before, value_after))
        return tuple(progressions)

    @staticmethod
    def _confidence(concepts: List[Dict], key: Mapping[str, str]) -> float:
        """The current confidence of the concept matching `key` (feature + action
        + outcome), from a `concepts()` snapshot — 0.0 until the being has formed
        it (keyed on a perceived property, ADR 0002)."""
        for concept in concepts:
            if (
                concept["feature"] == key["feature"]
                and concept["action"] == key["action"]
                and concept["outcome"] == key["outcome"]
            ):
                return float(concept["confidence"])
        return 0.0


def main() -> None:  # pragma: no cover - thin CLI wrapper over run()
    """Run the default scenario and print the before/after + milestone verdict — a
    runnable "watch it learn": `PYTHONPATH=. python -m app.services.scenario_runner`."""
    import os
    from pathlib import Path

    root = os.environ.get(
        "CONFIG_ROOT", str(Path(__file__).resolve().parents[3] / "config")
    )
    scenario = os.environ.get(
        "SCENARIO", str(Path(root) / "scenarios" / "rolling_object_intro.yaml")
    )
    result = ScenarioRunner(scenario_path=scenario, config_root=root).run()
    print(result.summary())


if __name__ == "__main__":  # pragma: no cover
    main()

"""ScenarioRunner — seed a being from a scenario, run it, measure what it learned.

A SCENARIO is a small authored experiment (config/scenarios/*.yaml): a room of
objects, how many ticks to live, and a LEARNING TARGET with a success floor. The
runner is the harness that turns that file into a verdict — it seeds a
`Simulation` with the scenario's objects, runs N ticks, reads ONE metric (the
target concept's confidence, card v2) before and after, and reports a
`ScenarioResult` whose `passed` is the regression signal: the metric rose past
the floor. This is the repeatable "watch it learn".

The scenario file is a HARNESS INPUT, not engine config: the runner parses it
directly with PyYAML and never routes it through ConfigService — the being's own
config (needs, actions, safety, the object catalog) still comes from
`config/*.yaml` via ConfigService. The runner only uses ConfigService's existing
public surface (`from_files`, `resolve_object`, `with_room_contents`) to place
the scenario's objects in the room, and reads the metric through the
Simulation's public `concepts()` surface. See docs/BRIEF.md §16 (Testing
Strategy) and §18 (v10 scenario system).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from app.config_service import ConfigService
from app.domain.scenario_result import ScenarioResult
from app.repositories import InMemoryConceptRepository
from app.simulation import Simulation


class ScenarioRunner:
    def __init__(self, *, scenario_path: str, config_root: str) -> None:
        self._scenario_path = Path(scenario_path)
        self._config_root = config_root

    def run(self, ticks: Optional[int] = None) -> ScenarioResult:
        """Seed the being from the scenario, run `ticks` (default: the scenario's
        own), and report how far the learning target's confidence moved.

        Passing `ticks=0` runs no interactions — the metric cannot rise, so the
        result does not pass; that is the harness's negative control, proving the
        scenario measures learning rather than noise.
        """
        scenario = self._load_scenario()
        target = scenario["learning_target"]
        floor = float(scenario["success_condition"]["min_confidence_delta"])
        run_ticks = int(scenario["ticks"] if ticks is None else ticks)

        config = ConfigService.from_files(self._config_root)
        object_ids = [config.resolve_object(sel) for sel in scenario["room"]["objects"]]
        # Inject a concept store so the being actually forms concepts and the
        # metric has something to read; the scenario needs no database.
        sim = Simulation(
            config.with_room_contents(object_ids),
            concept_repository=InMemoryConceptRepository(),
        )

        before = self._confidence(sim, target)
        for _ in range(run_ticks):
            sim.tick()
        after = self._confidence(sim, target)

        metric = (
            f"{target['feature']}+{target['action']}->{target['outcome']} confidence"
        )
        return ScenarioResult(
            scenario=str(scenario["name"]),
            metric=metric,
            ticks=run_ticks,
            before=before,
            after=after,
            threshold=floor,
        )

    def _load_scenario(self) -> Dict:
        import yaml  # noqa: PLC0415 — lazy, matching ConfigService.from_files

        return yaml.safe_load(self._scenario_path.read_text())

    @staticmethod
    def _confidence(sim: Simulation, target: Dict) -> float:
        """The current confidence of the target concept, read through the
        Simulation's public `concepts()` surface — 0.0 until the being has formed
        it (feature+action+outcome, keyed on a perceived property, ADR 0002)."""
        for concept in sim.concepts():
            if (
                concept["feature"] == target["feature"]
                and concept["action"] == target["action"]
                and concept["outcome"] == target["outcome"]
            ):
                return float(concept["confidence"])
        return 0.0


def main() -> None:  # pragma: no cover - thin CLI wrapper over run()
    """Run the default scenario and print the before/after verdict — a runnable
    "watch it learn": `PYTHONPATH=. python -m app.services.scenario_runner`."""
    import os

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

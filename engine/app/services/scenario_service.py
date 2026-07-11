"""ScenarioService — the registry of authored scenarios (card v10).

Discovers `config/scenarios/*.yaml`, parses each directly with PyYAML into a
`Scenario` value object, and hands them out by name. Reading the scenario file
shape lives here (with `Scenario.from_mapping`), in one place, so `ScenarioRunner`
and `RegressionEvaluationService` consume typed `Scenario`s rather than raw dicts.

Scenario files are HARNESS INPUTS, not engine config: this service parses them
directly and never routes them through ConfigService (the being's own config —
needs, actions, safety, the object catalog — still comes from config/*.yaml via
ConfigService). See docs/BRIEF.md §16.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from app.domain.scenario import Scenario


class ScenarioService:
    def __init__(self, scenarios_dir: str) -> None:
        self._dir = Path(scenarios_dir)
        self._scenarios: Dict[str, Scenario] | None = None

    @staticmethod
    def load_file(path: str) -> Scenario:
        """Parse a single scenario file into a `Scenario` — the seam the runner
        uses when handed one file directly (card V10a compatibility)."""
        import yaml  # noqa: PLC0415 — lazy, matching ConfigService.from_files

        mapping = yaml.safe_load(Path(path).read_text())
        return Scenario.from_mapping(mapping)

    def names(self) -> List[str]:
        """The names of every scenario in the directory, sorted."""
        return sorted(self._load().keys())

    def all(self) -> List[Scenario]:
        """Every configured scenario, by name order."""
        return [self._load()[name] for name in self.names()]

    def load(self, name: str) -> Scenario:
        """The scenario with this `name`. Fail-loud on an unknown name so a caller
        cannot run a scenario that isn't configured."""
        scenarios = self._load()
        if name not in scenarios:
            raise ValueError(
                f"unknown scenario {name!r}; known: {sorted(scenarios)}"
            )
        return scenarios[name]

    def _load(self) -> Dict[str, Scenario]:
        if self._scenarios is None:
            found: Dict[str, Scenario] = {}
            for path in sorted(self._dir.glob("*.yaml")):
                scenario = self.load_file(str(path))
                found[scenario.name] = scenario
            self._scenarios = found
        return self._scenarios

"""MilestoneService — the registry of developmental milestones (card v10).

Loads `config/milestones.yaml` directly with PyYAML into `Milestone` value
objects and hands them out by name. This service owns discovery, parsing, and
fail-loud lookup; the stage-ladder math (which stage a metric value sits on)
lives on `Milestone` itself, with the data it reasons over.

The milestones file is a HARNESS INPUT, not engine config — like
`config/scenarios/*.yaml`, it is parsed directly here and never routed through
ConfigService. Retuning a stage ladder is a change to that file, never code. See
docs/BRIEF.md §16.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from app.domain.milestone import Milestone


class MilestoneService:
    def __init__(self, milestones_path: str) -> None:
        self._path = Path(milestones_path)
        self._milestones: Dict[str, Milestone] | None = None

    @classmethod
    def from_config_root(cls, config_root: str) -> "MilestoneService":
        """The milestones file at its conventional home, `config/milestones.yaml`."""
        return cls(str(Path(config_root) / "milestones.yaml"))

    def names(self) -> List[str]:
        """The names of every configured milestone, sorted."""
        return sorted(self._load().keys())

    def milestones(self) -> List[Milestone]:
        """Every configured milestone, by name order."""
        return [self._load()[name] for name in self.names()]

    def get(self, name: str) -> Milestone:
        """The milestone with this `name`. Fail-loud on an unknown name so a
        scenario cannot track a milestone that isn't defined."""
        milestones = self._load()
        if name not in milestones:
            raise ValueError(
                f"unknown milestone {name!r}; known: {sorted(milestones)}"
            )
        return milestones[name]

    def _load(self) -> Dict[str, Milestone]:
        if self._milestones is None:
            import yaml  # noqa: PLC0415 — lazy, matching ConfigService.from_files

            raw = yaml.safe_load(self._path.read_text()) or {}
            entries = raw.get("milestones") or {}
            self._milestones = {
                name: Milestone.from_mapping(name, body)
                for name, body in entries.items()
            }
        return self._milestones

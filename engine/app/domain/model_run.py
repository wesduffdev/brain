"""ModelRun — the metadata of one training run of the outcome predictor.

The learned weights themselves live in a `.pt` artifact on disk (ADR 0008); this
is the record of *that run*: where the artifact was written (`artifact_path`),
how well it scored (`metrics` — the same dict the trainer returns), and when it
finished (`finished_at`). One row per `make train` / `ml-trainer` run, written
through the model-run repository port so the runs are queryable alongside the
interaction events and training examples they learned from (BRIEF §8, §11).

The timestamp is carried on the aggregate rather than stamped by the store, so a
run's moment is explicit and testable (no wall-clock in the persistence path).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict


@dataclass(frozen=True)
class ModelRun:
    artifact_path: str
    finished_at: datetime
    metrics: Dict[str, object] = field(default_factory=dict)

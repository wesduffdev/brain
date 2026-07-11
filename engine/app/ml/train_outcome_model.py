"""train_outcome_model — trains the outcome predictor and writes the artifact.

The v0 learning loop (BRIEF §11, "Shadow Mode First"): the being's rule layer is
the source of truth, and this small net learns to imitate it. Real stored
`training_examples` (persisted by V0-7b as the being interacts) are used when they
exist; when none are stored — no database, or an empty one — the trainer seeds
itself from a **synthetic seed set** derived from the config vocabulary, so the
whole loop (encode -> train -> evaluate -> persist) runs standalone, with no
database.

Public surface:
  - `synthetic_examples(config)` — the config-derived seed set (pure, no torch).
  - `train(...)` / `train_and_save(...)` — train a model and (optionally) persist
    it with metrics, given pre-`Example` interactions and an encoder.
  - `run_training(...)` — the orchestration used by `make train`: read stored
    examples through the injected `TrainingExampleRepository` (else synthetic),
    train, save the artifact, and record a `ModelRun` through the injected
    `ModelRunRepository`. Repositories and the timestamp are seams the caller
    supplies, so the whole thing is testable without a wall clock or a database.
  - `main()` — the `python -m app.ml.train_outcome_model` / `ml-trainer` entry.

PyTorch is imported lazily inside the training functions, so importing this
module (e.g. to reach `synthetic_examples`) never requires the training-only
dependency set.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from app.domain.model_run import ModelRun
from app.ml.encode_features import Example, FeatureEncoder

# One already-encoded training row: (feature vector, label vector). Both the
# synthetic seed set (encoded here) and stored TrainingExamples (encoded at write
# time, V0-7b) reduce to this shape, so the torch core trains on rows alone.
_EncodedRow = Tuple[Sequence[float], Sequence[float]]

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG_ROOT = _REPO_ROOT / "config"
_DEFAULT_MODEL_PATH = _REPO_ROOT / "models" / "outcome_predictor.pt"


# --- the synthetic seed set ------------------------------------------------
#
# Authored rules that stand in for the being's rule layer: given an object's
# properties, the action taken, and the surface it meets, what happens? These are
# the "ground truth" the net imitates in v0. They are config-derived (they read
# the real object catalog and context vocabulary), deterministic, and chosen so
# every outcome label appears in the seed set.


def _outcomes_for(properties: Set[str], action: str, context: str) -> List[str]:
    outcomes: List[str] = []
    if action in ("push", "drop") and "round" in properties:
        outcomes.append("rolls")
    if action == "drop":
        outcomes.append("falls")
    if action == "drop" and "rubbery" in properties and context == "surface_hard":
        outcomes.append("bounces")
    if action in ("push", "drop") and "heavy" in properties:
        outcomes.append("makes_noise")
    if action == "touch" and "hard" in properties and "heavy" in properties:
        outcomes.append("causes_pain")
    if action == "push" and "heavy" in properties and context == "surface_hard":
        outcomes.append("scary")
    pleasant_touch = action in ("touch", "grab") and ("soft" in properties or "warm" in properties)
    pleasant_sight = action == "look" and ("red" in properties or "blue" in properties)
    if pleasant_touch or pleasant_sight:
        outcomes.append("pleasant")
    return outcomes


def synthetic_examples(config) -> List[Example]:
    """A deterministic seed set: every real object, crossed with each action it
    affords and each surface context, labelled by the authored rules above."""
    contexts = config.outcome_context_features() or ("surface_hard",)
    examples: List[Example] = []
    for entity in config.object_catalog().values():
        props = set(entity.properties)
        for action in entity.affordances:
            for context in contexts:
                outcomes = _outcomes_for(props, action, context)
                examples.append(
                    Example(
                        properties=tuple(entity.properties),
                        action=action,
                        context=(context,),
                        outcomes=tuple(outcomes),
                    )
                )
    return examples


# --- training --------------------------------------------------------------


def _train_rows(
    *,
    rows: List[_EncodedRow],
    feature_size: int,
    label_size: int,
    label_names: Sequence[str],
    epochs: int,
    hidden_size: int,
    learning_rate: float,
    seed: int,
):
    """Train an OutcomeModel to green on already-encoded rows; returns
    (model, metrics). This is the torch core both `train` (synthetic Examples)
    and `run_training` (stored examples) reduce to. Torch is imported here so the
    module imports without the training deps."""
    import torch
    from torch import nn

    from app.ml.outcome_model import OutcomeModel

    torch.manual_seed(seed)

    features = torch.tensor([list(f) for f, _ in rows], dtype=torch.float32)
    labels = torch.tensor([list(l) for _, l in rows], dtype=torch.float32)

    model = OutcomeModel(feature_size, label_size, hidden_size)
    loss_fn = nn.BCEWithLogitsLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)

    final_loss = 0.0
    for _ in range(max(1, int(epochs))):
        optimizer.zero_grad()
        loss = loss_fn(model(features), labels)
        loss.backward()
        optimizer.step()
        final_loss = float(loss.item())

    metrics = _evaluate(model, features, labels, label_names)
    metrics.update(
        {"num_examples": len(rows), "epochs": int(epochs), "final_loss": final_loss}
    )
    return model, metrics


def train(
    *,
    encoder: FeatureEncoder,
    examples: List[Example],
    epochs: int,
    hidden_size: int,
    learning_rate: float = 0.05,
    seed: int = 0,
):
    """Train an OutcomeModel to green on `examples`; returns (model, metrics).
    The examples are encoded through the ADR 0008 contract before training."""
    rows = [
        (encoder.encode_features(ex), encoder.encode_labels(ex)) for ex in examples
    ]
    return _train_rows(
        rows=rows,
        feature_size=encoder.feature_size,
        label_size=encoder.label_size,
        label_names=encoder.label_names(),
        epochs=epochs,
        hidden_size=hidden_size,
        learning_rate=learning_rate,
        seed=seed,
    )


def _evaluate(model, features, labels, label_names) -> Dict:
    """Training-set fit at threshold 0.5: hamming (per-slot) and exact-match
    (whole-vector) accuracy, plus per-label accuracy. In v0 the model imitates
    rules, so this measures how well it reproduced them."""
    probabilities = model.predict(features)
    predictions = (probabilities >= 0.5).float()
    correct = (predictions == labels).float()
    return {
        "hamming_accuracy": float(correct.mean().item()) if correct.numel() else 0.0,
        "exact_match": float(correct.prod(dim=1).mean().item()) if correct.numel() else 0.0,
        "per_label": {
            name: float(correct[:, i].mean().item()) for i, name in enumerate(label_names)
        },
    }


def _save_artifact(model, encoder, metrics, output_path, metrics_path=None) -> None:
    """Persist the model (with its feature/label contract) to `output_path`, and
    write the metrics to `metrics_path` when given."""
    from app.ml.outcome_model import save_outcome_model

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    save_outcome_model(
        model,
        output_path,
        feature_names=encoder.feature_names(),
        label_names=encoder.label_names(),
        metrics=metrics,
    )

    if metrics_path:
        Path(metrics_path).parent.mkdir(parents=True, exist_ok=True)
        Path(metrics_path).write_text(json.dumps(metrics, indent=2, sort_keys=True))


def train_and_save(
    *,
    encoder: FeatureEncoder,
    examples: List[Example],
    output_path: str,
    metrics_path: Optional[str] = None,
    epochs: int = 300,
    hidden_size: int = 16,
    learning_rate: float = 0.05,
    seed: int = 0,
) -> Dict:
    """Train, persist the model (with its feature/label contract) to
    `output_path`, and return the metrics — writing them to `metrics_path` too
    when given."""
    model, metrics = train(
        encoder=encoder,
        examples=examples,
        epochs=epochs,
        hidden_size=hidden_size,
        learning_rate=learning_rate,
        seed=seed,
    )
    _save_artifact(model, encoder, metrics, output_path, metrics_path)
    return metrics


def run_training(
    *,
    config,
    output_path: str,
    training_repo=None,
    model_run_repo=None,
    unit_of_work=None,
    timestamp: datetime,
    metrics_path: Optional[str] = None,
    epochs: int = 300,
    hidden_size: int = 16,
    learning_rate: float = 0.05,
    seed: int = 0,
) -> Dict:
    """Train the outcome predictor and record the run (the `make train` path).

    Source of truth for the data: the stored `training_examples` read through
    `training_repo` (the V0-7b `TrainingExampleRepository`) when it holds any;
    otherwise the config-derived synthetic seed set, so a run needs no database.
    Trains, saves the artifact (+ optional metrics sidecar), and — when a
    `model_run_repo` is present — records one `ModelRun` (artifact path, metrics,
    and the injected `timestamp`; no wall clock here) in one unit of work (ADR
    0017), so the run row commits atomically; `unit_of_work` defaults to the no-op
    in-memory unit for the standalone/no-DB path. Returns the metrics with an
    added `source` key ("training_examples" or "synthetic")."""
    from app.db.unit_of_work import NullUnitOfWork

    unit_of_work = unit_of_work or NullUnitOfWork()
    encoder = FeatureEncoder.from_config(config)

    stored = list(training_repo.all()) if training_repo is not None else []
    if stored:
        rows: List[_EncodedRow] = [(ex.input_features, ex.output_labels) for ex in stored]
        source = "training_examples"
    else:
        rows = [
            (encoder.encode_features(ex), encoder.encode_labels(ex))
            for ex in synthetic_examples(config)
        ]
        source = "synthetic"

    model, metrics = _train_rows(
        rows=rows,
        feature_size=encoder.feature_size,
        label_size=encoder.label_size,
        label_names=encoder.label_names(),
        epochs=epochs,
        hidden_size=hidden_size,
        learning_rate=learning_rate,
        seed=seed,
    )
    metrics["source"] = source

    _save_artifact(model, encoder, metrics, output_path, metrics_path)

    if model_run_repo is not None:
        with unit_of_work.begin():
            model_run_repo.add(
                ModelRun(artifact_path=output_path, finished_at=timestamp, metrics=dict(metrics))
            )

    return metrics


def _open_repositories():
    """The Postgres-backed training-example + model-run repositories when
    `DATABASE_URL` is configured, else `(None, None, None)` so the synthetic path
    runs standalone with no database. Returns the open session too so `main` can
    close it. The connection string is env-only (ADR 0005), never guessed."""
    if not os.environ.get("DATABASE_URL"):
        return None, None, None

    from app.db.session import create_db_engine, session_factory
    from app.repositories import (
        PostgresModelRunRepository,
        PostgresTrainingExampleRepository,
    )

    session = session_factory(create_db_engine())()
    return (
        PostgresTrainingExampleRepository(session),
        PostgresModelRunRepository(session),
        session,
    )


def main() -> None:
    """Train on stored examples when a database holds them, else the synthetic
    seed set, write `models/outcome_predictor.pt` + a metrics sidecar, and record
    a `model_runs` row when a database is configured. Paths and tuning are
    config/env-driven so the container and local `make train` share this path."""
    from app.config_service import ConfigService

    config_root = os.environ.get("CONFIG_ROOT", str(_DEFAULT_CONFIG_ROOT))
    output_path = os.environ.get("MODEL_OUTPUT_PATH", str(_DEFAULT_MODEL_PATH))

    config = ConfigService.from_files(config_root)
    params = config.outcome_training_params()

    training_repo, model_run_repo, session = _open_repositories()
    unit_of_work = None
    if session is not None:
        from app.db.unit_of_work import SessionUnitOfWork

        unit_of_work = SessionUnitOfWork(session)
    try:
        metrics = run_training(
            config=config,
            output_path=output_path,
            training_repo=training_repo,
            model_run_repo=model_run_repo,
            unit_of_work=unit_of_work,
            timestamp=datetime.now(timezone.utc),
            metrics_path=output_path + ".metrics.json",
            epochs=params["epochs"],
            hidden_size=params["hidden_size"],
            learning_rate=params["learning_rate"],
            seed=params["seed"],
        )
    finally:
        if session is not None:
            session.close()

    print(
        "trained outcome predictor "
        f"(source={metrics['source']}, examples={metrics['num_examples']}, "
        f"epochs={metrics['epochs']})\n"
        f"  -> {output_path}\n"
        f"  final_loss={metrics['final_loss']:.4f} "
        f"hamming_accuracy={metrics['hamming_accuracy']:.3f} "
        f"exact_match={metrics['exact_match']:.3f}"
    )


if __name__ == "__main__":
    main()

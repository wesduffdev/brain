"""train_instinct_model — trains the instinct model and writes the artifact
(ADR 0026), mirroring `train_outcome_model` but with instinct's own contract,
seed data, and mixed classification+regression objective.

The v0 learning loop: the being's real stimulus->reaction pairs are the source of
truth once it has lived them. `run_training` reads the persisted
`instinct_training_examples` (EVT-PERSIST) through the repository port when the
table holds any and trains on THEM; with an empty table (or no database) it falls
back to a config-derived **synthetic seed set** of rule-labeled stimulus windows,
so the whole loop (encode -> train -> evaluate -> persist) still runs standalone.
This mirrors `train_outcome_model`, which already prefers stored `training_examples`
over its synthetic seed. The rule labels only *seed* the model — production
inference is neural; no rule table ships as the runtime path.

Public surface:
  - `LabeledStimulus` / `synthetic_examples(config)` — the rule-labeled seed set
    (pure, no torch).
  - `training_rows(config, training_repo)` — the dataset the trainer will learn
    from and where it came from: the persisted `instinct_training_examples` read
    through the port when present, else the synthetic seed. Pure (no torch), so
    the selection + fallback is testable offline.
  - `train(...)` / `train_and_save(...)` — train a model and (optionally) persist
    it with metrics, given pre-`LabeledStimulus` examples and an encoder.
  - `run_training(...)` — the orchestration used by the instinct trainer entry:
    choose the dataset (persisted examples else synthetic seed) via `training_rows`,
    train, save the artifact, and — when a `model_run_repo` is present — record one
    `ModelRun` in one unit of work (ADR 0017). Repositories and the timestamp are
    seams the caller supplies, so it is testable without a wall clock or a database.
  - `main()` — the `python -m app.ml.train_instinct_model` entry.

PyTorch is imported lazily inside the training functions, so importing this module
(e.g. to reach `synthetic_examples`) never requires the training-only deps.
"""
from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from app.domain.model_run import ModelRun
from app.ml.instinct_encoder import InstinctFeatureEncoder, Stimulus

# One already-encoded training row: (feature vector, reaction vector, intensity).
_EncodedRow = Tuple[Sequence[float], Sequence[float], float]

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG_ROOT = _REPO_ROOT / "config"
_DEFAULT_MODEL_PATH = _REPO_ROOT / "models" / "instinct.pt"

# A fixed seed for the synthetic data so the seed set is reproducible independent
# of the torch training seed.
_DATA_SEED = 20260711
_PER_ARCHETYPE = 24

# The explicit no-reaction label (ADR 0026): it names "nothing fired", so it is
# excluded when reading a persisted row's intensity target (see `_intensity_from_labels`)
# and, like the config's reaction thresholds, it never counts as a protective response.
_NO_REACTION_LABEL = "ignore"


@dataclass(frozen=True)
class LabeledStimulus:
    """One rule-labeled training sample: the perceived `stimulus`, the protective
    `reactions` it should trigger (multi-label), and its `intensity` in [0, 1]."""

    stimulus: Stimulus
    reactions: Tuple[str, ...]
    intensity: float


# --- the synthetic seed set ------------------------------------------------
#
# Authored rules that stand in for the being's pre-conceptual instinct layer:
# given the fast-sensory reading of a stimulus, which protective reaction(s) fire,
# and how intensely? These are the "ground truth" the net imitates in v0
# (ADR 0026): fast-toward-body -> flinch, loud-unknown -> freeze, unexpected-touch
# -> withdraw, a salient-but-unthreatening new stimulus -> orient, low signal ->
# ignore. Multi-label — a stimulus can fire several at once.


def _reactions_for(s: Stimulus) -> Tuple[Tuple[str, ...], float]:
    """The reactions a stimulus should trigger, and the reaction intensity."""
    reactions: List[str] = []
    strengths: List[float] = []

    flinch = s.velocity > 0.6 and s.trajectory_toward_body > 0.6 and s.time_to_contact < 0.35
    freeze = s.sound_spike_intensity > 0.6 and s.unexpectedness > 0.5 and s.visibility_confidence < 0.4
    withdraw = s.touch_intensity > 0.5 and s.unexpectedness > 0.5
    # A new/salient stimulus that is NOT threatening enough for a protective
    # reaction draws the being to turn and look.
    orient = s.unexpectedness > 0.5 and not (flinch or freeze or withdraw)

    if flinch:
        reactions.append("flinch")
        strengths.append(s.velocity * s.trajectory_toward_body * (1.0 - s.time_to_contact))
    if freeze:
        reactions.append("freeze")
        strengths.append(s.sound_spike_intensity * s.unexpectedness * (1.0 - s.visibility_confidence))
    if withdraw:
        reactions.append("withdraw")
        strengths.append(s.touch_intensity * s.unexpectedness)
    if orient:
        reactions.append("orient")
        strengths.append(0.4 * s.unexpectedness)

    if not reactions:  # low signal — nothing salient enough to react to
        return ("ignore",), 0.05

    intensity = max(0.0, min(1.0, max(strengths)))
    return tuple(reactions), intensity


def _archetype(rng: random.Random, kind: str) -> Stimulus:
    """A jittered stimulus sampled around one archetype so the tiny net has clean,
    separable examples of each reaction to imitate."""
    def lo() -> float:
        return rng.uniform(0.0, 0.3)

    base = dict(
        distance=lo(), velocity=lo(), acceleration=lo(), trajectory_toward_body=lo(),
        time_to_contact=rng.uniform(0.6, 1.0), object_size=rng.uniform(0.2, 0.6),
        size_change_rate=lo(), unexpectedness=lo(), visibility_confidence=rng.uniform(0.5, 1.0),
        sound_spike_intensity=lo(), touch_intensity=lo(),
        current_focus_level=rng.uniform(0.3, 0.7), current_stability=rng.uniform(0.3, 0.7),
        prior_prediction_error=lo(),
    )
    if kind == "flinch":  # a fast object rushing straight at the body
        base.update(velocity=rng.uniform(0.7, 1.0), trajectory_toward_body=rng.uniform(0.7, 1.0),
                    time_to_contact=rng.uniform(0.0, 0.3), acceleration=rng.uniform(0.5, 1.0),
                    size_change_rate=rng.uniform(0.5, 1.0), distance=rng.uniform(0.0, 0.4),
                    unexpectedness=rng.uniform(0.3, 0.7))
    elif kind == "freeze":  # a loud, unknown stimulus
        base.update(sound_spike_intensity=rng.uniform(0.7, 1.0), unexpectedness=rng.uniform(0.6, 1.0),
                    visibility_confidence=rng.uniform(0.0, 0.35))
    elif kind == "withdraw":  # an unexpected touch
        base.update(touch_intensity=rng.uniform(0.6, 1.0), unexpectedness=rng.uniform(0.6, 1.0),
                    visibility_confidence=rng.uniform(0.4, 0.9))
    elif kind == "orient":  # a salient new stimulus, not threatening
        base.update(unexpectedness=rng.uniform(0.6, 1.0), visibility_confidence=rng.uniform(0.4, 0.9),
                    velocity=rng.uniform(0.0, 0.4), trajectory_toward_body=rng.uniform(0.0, 0.4))
    # "ignore" keeps the all-low base.
    return Stimulus(**base)


def synthetic_examples(config) -> List[LabeledStimulus]:
    """A deterministic, rule-labeled seed set covering every reaction, so the tiny
    net imitates the instinct rules. `config` is accepted for signature symmetry
    with the outcome trainer (and future config-derived tuning); the archetypes
    are self-contained."""
    rng = random.Random(_DATA_SEED)
    examples: List[LabeledStimulus] = []
    for kind in ("flinch", "freeze", "withdraw", "orient", "ignore"):
        for _ in range(_PER_ARCHETYPE):
            stimulus = _archetype(rng, kind)
            reactions, intensity = _reactions_for(stimulus)
            examples.append(LabeledStimulus(stimulus, reactions, intensity))
    return examples


# --- dataset selection (pure, no torch) ------------------------------------


def _intensity_from_labels(labels: Sequence[float], label_names: Sequence[str]) -> float:
    """The intensity regression target for a PERSISTED row.

    `InstinctTrainingExample` stores only the multi-hot reaction labels — the
    scalar reaction intensity the model also predicts is not persisted (ADR 0026).
    So read the training target as the strength of the being's strongest
    PROTECTIVE reaction: the max label value across every slot except
    `ignore` (the explicit no-reaction outcome), and 0.0 when only `ignore` fired.
    Pure, so it is exercised offline with the rest of `training_rows`."""
    protective = [
        float(value)
        for name, value in zip(label_names, labels)
        if name != _NO_REACTION_LABEL
    ]
    return max(protective) if protective else 0.0


def training_rows(config, training_repo=None) -> Tuple[List[_EncodedRow], str]:
    """The dataset the instinct trainer will learn from, and where it came from.

    Source of truth: the persisted `instinct_training_examples` read through the
    injected repository (EVT-PERSIST) when the table holds any — already encoded to
    the frozen 14-feature / 5-label contract at write time, so they are used
    directly (the intensity target, which the row does not persist, is read from
    the labels via `_intensity_from_labels`). Otherwise the config-derived
    synthetic seed set, so a run needs no database. This mirrors
    `train_outcome_model`'s stored-else-synthetic selection. Pure — no torch — so
    the selection and byte-identical fallback are testable offline. Returns
    (encoded rows, source: ``"instinct_training_examples"`` | ``"synthetic"``)."""
    encoder = InstinctFeatureEncoder.from_config(config)

    stored = list(training_repo.all()) if training_repo is not None else []
    if stored:
        label_names = encoder.label_names()
        rows: List[_EncodedRow] = [
            (
                tuple(float(f) for f in ex.input_features),
                tuple(float(l) for l in ex.output_labels),
                _intensity_from_labels(ex.output_labels, label_names),
            )
            for ex in stored
        ]
        return rows, "instinct_training_examples"

    rows = [
        (encoder.encode_features(ex.stimulus), encoder.encode_labels(ex.reactions), float(ex.intensity))
        for ex in synthetic_examples(config)
    ]
    return rows, "synthetic"


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
    intensity_loss: str,
):
    """Train an InstinctModel to green on already-encoded rows; returns
    (model, metrics). Torch is imported here so the module imports without the
    training deps."""
    import torch
    from torch import nn

    from app.ml.instinct_model import InstinctModel

    torch.manual_seed(seed)

    features = torch.tensor([list(f) for f, _, _ in rows], dtype=torch.float32)
    labels = torch.tensor([list(l) for _, l, _ in rows], dtype=torch.float32)
    intensities = torch.tensor([[float(i)] for _, _, i in rows], dtype=torch.float32)

    model = InstinctModel(feature_size, label_size, hidden_size)
    label_loss_fn = nn.BCEWithLogitsLoss()
    use_mse = str(intensity_loss).lower() == "mse"
    intensity_loss_fn = nn.MSELoss() if use_mse else nn.BCEWithLogitsLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)

    final_loss = 0.0
    for _ in range(max(1, int(epochs))):
        optimizer.zero_grad()
        label_logits, intensity_logit = model(features)
        loss = label_loss_fn(label_logits, labels)
        if use_mse:
            loss = loss + intensity_loss_fn(torch.sigmoid(intensity_logit), intensities)
        else:
            loss = loss + intensity_loss_fn(intensity_logit, intensities)
        loss.backward()
        optimizer.step()
        final_loss = float(loss.item())

    metrics = _evaluate(model, features, labels, intensities, label_names)
    metrics.update(
        {"num_examples": len(rows), "epochs": int(epochs), "final_loss": final_loss}
    )
    return model, metrics


def train(
    *,
    encoder: InstinctFeatureEncoder,
    examples: List[LabeledStimulus],
    epochs: int,
    hidden_size: int,
    learning_rate: float = 0.05,
    seed: int = 0,
    intensity_loss: str = "bce",
):
    """Train an InstinctModel to green on `examples`; returns (model, metrics).
    The examples are encoded through the ADR 0026 contract before training."""
    rows: List[_EncodedRow] = [
        (encoder.encode_features(ex.stimulus), encoder.encode_labels(ex.reactions), float(ex.intensity))
        for ex in examples
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
        intensity_loss=intensity_loss,
    )


def _evaluate(model, features, labels, intensities, label_names) -> Dict:
    """Training-set fit: reaction hamming (per-slot) and exact-match accuracy at
    threshold 0.5, per-reaction accuracy, and the intensity mean-absolute-error.
    In v0 the model imitates rules, so this measures how well it reproduced them."""
    probabilities, intensity_pred = model.predict(features)
    predictions = (probabilities >= 0.5).float()
    correct = (predictions == labels).float()
    return {
        "hamming_accuracy": float(correct.mean().item()) if correct.numel() else 0.0,
        "exact_match": float(correct.prod(dim=1).mean().item()) if correct.numel() else 0.0,
        "per_label": {
            name: float(correct[:, i].mean().item()) for i, name in enumerate(label_names)
        },
        "intensity_mae": float((intensity_pred - intensities).abs().mean().item())
        if intensities.numel()
        else 0.0,
    }


def _save_artifact(model, encoder, metrics, output_path, metrics_path=None) -> None:
    """Persist the model (with its feature/label contract) to `output_path`, and
    write the metrics to `metrics_path` when given."""
    from app.ml.instinct_model import save_instinct_model

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    save_instinct_model(
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
    encoder: InstinctFeatureEncoder,
    examples: List[LabeledStimulus],
    output_path: str,
    metrics_path: Optional[str] = None,
    epochs: int = 400,
    hidden_size: int = 16,
    learning_rate: float = 0.05,
    seed: int = 0,
    intensity_loss: str = "bce",
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
        intensity_loss=intensity_loss,
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
    epochs: int = 400,
    hidden_size: int = 16,
    learning_rate: float = 0.05,
    seed: int = 0,
    intensity_loss: str = "bce",
) -> Dict:
    """Train the instinct model and record the run.

    Source of truth for the data (via `training_rows`): the persisted
    `instinct_training_examples` read through `training_repo` (the EVT-PERSIST
    `InstinctTrainingExampleRepository`) when it holds any; otherwise the
    config-derived synthetic seed set, so a run needs no database — mirroring
    `train_outcome_model`. Saves the artifact (+ optional metrics sidecar), and —
    when a `model_run_repo` is present — records one `ModelRun` (artifact path,
    metrics, injected `timestamp`; no wall clock here) in one unit of work (ADR
    0017), so the run row commits atomically. `unit_of_work` defaults to the no-op
    in-memory unit for the standalone/no-DB path. Returns the metrics with an added
    `source` key ("instinct_training_examples" or "synthetic")."""
    from app.db.unit_of_work import NullUnitOfWork

    unit_of_work = unit_of_work or NullUnitOfWork()
    encoder = InstinctFeatureEncoder.from_config(config)

    rows, source = training_rows(config, training_repo)
    model, metrics = _train_rows(
        rows=rows,
        feature_size=encoder.feature_size,
        label_size=encoder.label_size,
        label_names=encoder.label_names(),
        epochs=epochs,
        hidden_size=hidden_size,
        learning_rate=learning_rate,
        seed=seed,
        intensity_loss=intensity_loss,
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
    """The Postgres-backed instinct-training-example + model-run repositories when
    `DATABASE_URL` is configured, else `(None, None, None)` so the synthetic path
    runs standalone with no database. Returns the open session too so `main` can
    close it. The connection string is env-only (ADR 0005), never guessed."""
    if not os.environ.get("DATABASE_URL"):
        return None, None, None

    from app.db.session import create_db_engine, session_factory
    from app.repositories import (
        PostgresInstinctTrainingExampleRepository,
        PostgresModelRunRepository,
    )

    session = session_factory(create_db_engine())()
    return (
        PostgresInstinctTrainingExampleRepository(session),
        PostgresModelRunRepository(session),
        session,
    )


def main() -> None:
    """Train the instinct model on the persisted `instinct_training_examples` when a
    database holds them, else the synthetic seed set, write `models/instinct.pt` +
    a metrics sidecar, and record a `model_runs` row when a database is configured.
    Paths and tuning are config/env-driven so the container and local training
    share this path."""
    from app.config_service import ConfigService

    config_root = os.environ.get("CONFIG_ROOT", str(_DEFAULT_CONFIG_ROOT))
    output_path = os.environ.get("INSTINCT_MODEL_OUTPUT_PATH", str(_DEFAULT_MODEL_PATH))

    config = ConfigService.from_files(config_root)
    policy = config.instinct_model_policy()

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
            epochs=policy.epochs,
            hidden_size=policy.hidden_size,
            learning_rate=policy.learning_rate,
            seed=policy.seed,
            intensity_loss=policy.intensity_loss,
        )
    finally:
        if session is not None:
            session.close()

    print(
        "trained instinct model "
        f"(source={metrics['source']}, examples={metrics['num_examples']}, "
        f"epochs={metrics['epochs']})\n"
        f"  -> {output_path}\n"
        f"  final_loss={metrics['final_loss']:.4f} "
        f"hamming_accuracy={metrics['hamming_accuracy']:.3f} "
        f"exact_match={metrics['exact_match']:.3f} "
        f"intensity_mae={metrics['intensity_mae']:.3f}"
    )


if __name__ == "__main__":
    main()

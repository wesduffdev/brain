"""Behavior: training the outcome predictor on a tiny synthetic set writes a
model artifact that reloads with its feature/label contract intact and predicts a
probability per outcome (ADR 0008).

PyTorch is a training-only dependency (kept out of the lean runtime image), so
this behavior is skipped where torch is not installed — the encoding contract in
`test_encode_features.py` is covered without it. Kept fast: one mini-epoch on a
handful of examples with a tiny hidden layer, into a temp path.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

torch = pytest.importorskip("torch")  # noqa: F841 — training-only dep gate

from app.config_service import ConfigService
from app.db import models
from app.db.migrate import create_all, drop_all
from app.db.session import create_db_engine, session_factory
from app.domain.training_example import TrainingExample
from app.ml import train_outcome_model as trainer
from app.ml.encode_features import Example, FeatureEncoder, FeatureSpec
from app.ml.outcome_model import load_outcome_model
from app.repositories import (
    InMemoryModelRunRepository,
    InMemoryTrainingExampleRepository,
    PostgresModelRunRepository,
    PostgresTrainingExampleRepository,
)
from app.simulation import Simulation

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")
_FIXED_TIME = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)


def _tiny_encoder():
    return FeatureEncoder(
        FeatureSpec(
            property_vocab=("round", "rubbery", "heavy"),
            action_vocab=("push", "drop"),
            context_vocab=("surface_hard",),
            label_vocab=("rolls", "bounces", "falls"),
        )
    )


def _tiny_examples():
    return [
        Example(("round", "rubbery"), "drop", ("surface_hard",), ("falls", "bounces")),
        Example(("round",), "push", (), ("rolls",)),
        Example(("heavy",), "drop", ("surface_hard",), ("falls",)),
    ]


def test_training_writes_a_reloadable_artifact_with_its_contract(tmp_path):
    out = tmp_path / "outcome_predictor.pt"
    metrics = trainer.train_and_save(
        encoder=_tiny_encoder(),
        examples=_tiny_examples(),
        output_path=str(out),
        epochs=1,
        hidden_size=4,
    )

    assert out.exists()
    assert metrics["num_examples"] == 3
    assert "final_loss" in metrics

    model, contract = load_outcome_model(str(out))
    assert contract["label_names"] == ["rolls", "bounces", "falls"]
    assert contract["feature_names"] == list(_tiny_encoder().feature_names())


def test_reloaded_model_predicts_a_probability_per_outcome(tmp_path):
    out = tmp_path / "outcome_predictor.pt"
    encoder = _tiny_encoder()
    trainer.train_and_save(
        encoder=encoder,
        examples=_tiny_examples(),
        output_path=str(out),
        epochs=1,
        hidden_size=4,
    )

    model, _ = load_outcome_model(str(out))
    probs = model.predict_one(encoder.encode_features(_tiny_examples()[0]))

    assert len(probs) == encoder.label_size
    assert all(0.0 <= p <= 1.0 for p in probs)


def test_training_also_writes_a_metrics_sidecar(tmp_path):
    out = tmp_path / "outcome_predictor.pt"
    metrics_path = tmp_path / "outcome_predictor.pt.metrics.json"
    trainer.train_and_save(
        encoder=_tiny_encoder(),
        examples=_tiny_examples(),
        output_path=str(out),
        metrics_path=str(metrics_path),
        epochs=1,
        hidden_size=4,
    )

    assert metrics_path.exists()
    import json

    saved = json.loads(metrics_path.read_text())
    assert saved["num_examples"] == 3


# --- run_training: stored examples, synthetic fallback, model-run recording ---
#
# The V0-8b finisher: `run_training` reads persisted training examples through
# the TrainingExampleRepository port (falling back to the config-derived
# synthetic seed set when there are none), trains + saves the artifact, and
# records one model_runs row through the ModelRunRepository port. The timestamp
# is injected — no wall clock in tests. The behavior is driven through the
# in-memory fakes; a live Postgres round-trip covers the adapters below.


def _run_config():
    """A small but real config the encoder and synthetic seed set both read.
    The full label vocabulary is used so the synthetic seed set is always
    encodable regardless of which authored rule fires."""
    return ConfigService.from_dict(
        {"tick": {"duration_ms": 1000}, "needs": {}},
        {"rules": [], "default": "calm"},
        objects={
            "properties": ["round", "rubbery", "heavy", "soft"],
            "affordances": ["push", "drop", "touch"],
            "objects": {
                "ball": {
                    "developerLabel": "Ball",
                    "properties": ["round", "rubbery"],
                    "affordances": ["push", "drop"],
                },
                "block": {
                    "developerLabel": "Block",
                    "properties": ["heavy"],
                    "affordances": ["drop"],
                },
            },
        },
        outcome={
            "labels": ["rolls", "bounces", "falls", "causes_pain", "makes_noise", "pleasant", "scary"],
            "context_features": ["surface_hard", "surface_soft"],
        },
    )


def _store_examples(config, repo, examples):
    encoder = FeatureEncoder.from_config(config)
    for i, ex in enumerate(examples):
        repo.add(
            TrainingExample(
                event_id=f"being_001:{i}",
                input_features=encoder.encode_features(ex),
                output_labels=encoder.encode_labels(ex),
            )
        )


def test_run_training_trains_on_stored_examples_and_writes_a_reloadable_artifact(tmp_path):
    config = _run_config()
    stored = InMemoryTrainingExampleRepository()
    _store_examples(
        config,
        stored,
        [
            Example(("round", "rubbery"), "drop", ("surface_hard",), ("falls", "bounces")),
            Example(("round",), "push", ("surface_hard",), ("rolls",)),
            Example(("heavy",), "drop", ("surface_hard",), ("falls", "makes_noise")),
        ],
    )
    out = tmp_path / "outcome_predictor.pt"

    metrics = trainer.run_training(
        config=config,
        output_path=str(out),
        training_repo=stored,
        timestamp=_FIXED_TIME,
        epochs=1,
        hidden_size=4,
    )

    assert out.exists()
    assert metrics["source"] == "training_examples"
    assert metrics["num_examples"] == 3
    # the artifact reloads with the encoding contract of the config it trained on
    _model, contract = load_outcome_model(str(out))
    assert contract["label_names"] == list(FeatureEncoder.from_config(config).label_names())


def test_run_training_records_a_model_run_row_through_the_port(tmp_path):
    config = _run_config()
    stored = InMemoryTrainingExampleRepository()
    _store_examples(config, stored, [Example(("round",), "push", ("surface_hard",), ("rolls",))])
    runs = InMemoryModelRunRepository()
    out = tmp_path / "outcome_predictor.pt"

    trainer.run_training(
        config=config,
        output_path=str(out),
        training_repo=stored,
        model_run_repo=runs,
        timestamp=_FIXED_TIME,
        epochs=1,
        hidden_size=4,
    )

    recorded = runs.all()
    assert len(recorded) == 1
    run = recorded[0]
    assert run.artifact_path == str(out)
    assert run.finished_at == _FIXED_TIME
    assert run.metrics["num_examples"] == 1
    assert run.metrics["source"] == "training_examples"


def test_run_training_falls_back_to_the_synthetic_seed_when_no_stored_examples(tmp_path):
    config = _run_config()
    runs = InMemoryModelRunRepository()
    out = tmp_path / "outcome_predictor.pt"

    # an empty training repo (a configured but empty DB) -> synthetic seed set,
    # and the run is still recorded.
    metrics = trainer.run_training(
        config=config,
        output_path=str(out),
        training_repo=InMemoryTrainingExampleRepository(),
        model_run_repo=runs,
        timestamp=_FIXED_TIME,
        epochs=1,
        hidden_size=4,
    )

    assert out.exists()
    assert metrics["source"] == "synthetic"
    assert metrics["num_examples"] > 0
    assert len(runs.all()) == 1


def test_run_training_runs_standalone_with_no_repositories(tmp_path):
    # The standalone synthetic path must still work with no DB at all: no
    # training repo, no model-run repo -> synthetic seed set, no run recorded.
    config = _run_config()
    out = tmp_path / "outcome_predictor.pt"

    metrics = trainer.run_training(
        config=config,
        output_path=str(out),
        timestamp=_FIXED_TIME,
        epochs=1,
        hidden_size=4,
    )

    assert out.exists()
    assert metrics["source"] == "synthetic"


# --- live Postgres round-trip (skipped when unreachable, never faked) --------


def _reachable_postgres_or_skip():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — skipping live Postgres round-trip")
    try:
        engine = create_db_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
    except Exception as exc:  # noqa: BLE001 — any connect failure means "skip, don't fake"
        pytest.skip(f"Postgres not reachable at DATABASE_URL ({type(exc).__name__}) — skipping")
    return engine


@pytest.mark.integration
def test_training_on_real_persisted_examples_writes_an_artifact_and_a_model_run(tmp_path):
    engine = _reachable_postgres_or_skip()
    drop_all(engine)  # fresh schema so the trainer sees only this run's examples
    create_all(engine)
    session = session_factory(engine)()
    try:
        config = ConfigService.from_files(_CONFIG_ROOT)
        # seed the parent rows the schema's foreign keys require, then run the sim
        # so real interaction-derived training examples land in Postgres.
        session.add(models.Being(being_id="being_001", needs={}, emotion="calm"))
        for entity in config.object_catalog().values():
            session.add(
                models.ObjectRecord(
                    object_id=entity.object_id,
                    developer_label=entity.developer_label,
                    properties=list(entity.properties),
                    affordances=list(entity.affordances),
                )
            )
        session.commit()

        example_repo = PostgresTrainingExampleRepository(session)
        sim = Simulation(config, training_repo=example_repo)
        for _ in range(80):
            sim.tick()
        assert example_repo.all(), "the sim should have persisted at least one example"

        out = tmp_path / "outcome_predictor.pt"
        run_repo = PostgresModelRunRepository(session)
        metrics = trainer.run_training(
            config=config,
            output_path=str(out),
            training_repo=example_repo,
            model_run_repo=run_repo,
            timestamp=_FIXED_TIME,
            epochs=5,
            hidden_size=8,
        )

        # trained on the REAL persisted examples, not the synthetic seed
        assert metrics["source"] == "training_examples"
        assert metrics["num_examples"] == len(example_repo.all())
        assert out.exists()
        # and a model_runs row records where/when/how well
        recorded = run_repo.all()
        assert len(recorded) == 1
        assert recorded[0].artifact_path == str(out)
        assert recorded[0].metrics["num_examples"] == metrics["num_examples"]
    finally:
        session.close()
        engine.dispose()

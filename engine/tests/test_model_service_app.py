"""Behavior of the model-service sidecar app (v8, ADR 0043).

A small FastAPI app that serves BOTH learned models out-of-process:
`/predict/outcome`, `/predict/instinct`, a public `/health`, and `/models/active`.
It is the same seam the engine's `HttpPredictionClient` calls. Here it is driven
OFFLINE with FastAPI's `TestClient` and INJECTED fake predictors (no torch, no
artifact, no network) — the app's own `create_app(...)` injection surface, the
mirror of `app.main.create_app`. When a model is not loaded on the host the
predict endpoint returns 503, which is exactly what makes the client's Fallback
degrade to rules rather than serve a bogus score.

One live round-trip against a REAL running sidecar is `@pytest.mark.model_service`
and SKIPS unless `MODEL_SERVICE_URL` is reachable, so the default suite stays
hermetic and green with no service.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.config_service import ConfigService
from app.model_service import create_app
from app.ports.instinct import InstinctPrediction

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


class _FixedOutcome:
    def predict_outcomes(self, example):
        return {"causes_pain": 0.9, "pleasant": 0.1}


class _FixedInstinct:
    def predict_reactions(self, stimulus):
        return InstinctPrediction(reactions={"flinch": 0.8, "ignore": 0.05}, intensity=0.7)


def _client(**kw):
    config = ConfigService.from_files(_CONFIG_ROOT)
    return TestClient(create_app(config=config, **kw))


def test_health_is_public_and_ok():
    resp = _client(outcome_predictor=None, instinct_predictor=None).get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_models_active_reports_which_models_are_loaded():
    body = _client(
        outcome_predictor=_FixedOutcome(), instinct_predictor=None, outcome_version="v1",
    ).get("/models/active").json()
    assert body["outcome"]["loaded"] is True
    assert body["outcome"]["version"] == "v1"
    assert body["instinct"]["loaded"] is False


def test_predict_outcome_serves_probabilities():
    resp = _client(outcome_predictor=_FixedOutcome(), instinct_predictor=None).post(
        "/predict/outcome", json={"properties": ["hot"], "action": "touch", "context": []},
    )
    assert resp.status_code == 200
    assert resp.json()["outcomes"]["causes_pain"] == pytest.approx(0.9)


def test_predict_instinct_serves_reactions_and_intensity():
    resp = _client(outcome_predictor=None, instinct_predictor=_FixedInstinct()).post(
        "/predict/instinct", json={"stimulus": {"distance": 0.1, "velocity": 0.9}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["reactions"]["flinch"] == pytest.approx(0.8)
    assert body["intensity"] == pytest.approx(0.7)


def test_predict_outcome_is_unavailable_when_no_model_is_loaded():
    resp = _client(outcome_predictor=None, instinct_predictor=None).post(
        "/predict/outcome", json={"properties": [], "action": "touch", "context": []},
    )
    assert resp.status_code == 503


# --- live sidecar round-trip (gated; skips with no reachable service) --------


def _reachable_service_or_skip():
    url = os.environ.get("MODEL_SERVICE_URL")
    if not url:
        pytest.skip("MODEL_SERVICE_URL not set — skipping live model-service round-trip")
    try:
        import httpx  # noqa: PLC0415

        httpx.get(f"{url.rstrip('/')}/health", timeout=2).raise_for_status()
    except Exception as exc:  # noqa: BLE001 — any connect problem means skip, don't fake
        pytest.skip(f"model-service not reachable at {url} ({type(exc).__name__}) — skipping")
    return url.rstrip("/")


@pytest.mark.model_service
def test_live_model_service_serves_a_prediction_over_http():
    url = _reachable_service_or_skip()
    from app.adapters.http_prediction_client import HttpPredictionClient
    from app.ml.encode_features import Example

    client = HttpPredictionClient(base_url=url)
    probs = client.predict_outcomes(Example(properties=("hot",), action="touch", context=()))

    assert isinstance(probs, dict)

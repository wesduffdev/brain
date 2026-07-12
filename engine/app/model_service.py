"""model_service — the out-of-process model-service sidecar app (v8, ADR 0043).

A small FastAPI app that serves BOTH learned models over HTTP so inference can run
OUT-OF-PROCESS: `/predict/outcome` (an encoded interaction -> outcome
probabilities), `/predict/instinct` (a perceived stimulus -> reaction
probabilities + intensity), a PUBLIC `/health` probe, and `/models/active`
(which models are loaded and at what version). It is the server side of the
engine's `HttpPredictionClient`; the two speak the same JSON.

It owns no psychology — it loads the SAME artifacts the engine would (via
`app.ml.load_predictor` / `load_instinct_predictor`, torch imported lazily there)
and runs them behind the SAME ports, so a served score is identical to an
in-process one. Everything is injectable (mirroring `app.main.create_app`) so the
behavior suite drives it with fake predictors offline, no torch and no artifact.

A model that is not loaded on this host makes its predict endpoint return 503 —
the signal that makes the engine's `FallbackPredictionClient` degrade to the
rule/safe baseline rather than serve a bogus score. Run it:

    uvicorn app.model_service:app --host 0.0.0.0 --port 8500
"""
from __future__ import annotations

import os
from dataclasses import fields
from typing import Optional

from fastapi import Body, FastAPI, HTTPException

from app.config_service import ConfigService
from app.ml.encode_features import Example
from app.ml.inference import load_predictor
from app.ml.instinct_encoder import Stimulus
from app.ml.instinct_inference import load_instinct_predictor
from app.ports.instinct import InstinctPredictorPort
from app.ports.predictor import PredictorPort

_DEFAULT_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")
_DEFAULT_MODEL_PATH = os.path.join(_DEFAULT_CONFIG_ROOT, "..", "models", "outcome_predictor.pt")
_DEFAULT_INSTINCT_MODEL_PATH = os.path.join(_DEFAULT_CONFIG_ROOT, "..", "models", "instinct.pt")
_STIMULUS_FIELDS = frozenset(f.name for f in fields(Stimulus))


def create_app(
    *,
    config: Optional[ConfigService] = None,
    config_root: Optional[str] = None,
    outcome_predictor: Optional[PredictorPort] = None,
    instinct_predictor: Optional[InstinctPredictorPort] = None,
    outcome_version: Optional[str] = None,
    instinct_version: Optional[str] = None,
    env: Optional[dict] = None,
) -> FastAPI:
    """Build the sidecar app around the two learned models.

    Left to their defaults, config is loaded from `config_root` (or the env
    `CONFIG_ROOT` / the shipped config) and each predictor is loaded from its
    artifact (`MODEL_PATH` / `INSTINCT_MODEL_PATH`), gracefully ``None`` when torch
    or the artifact is absent. Tests inject fake predictors so the endpoints are
    exercised with no torch and no network."""
    env = os.environ if env is None else env
    if config is None:
        config = ConfigService.from_files(config_root or env.get("CONFIG_ROOT", _DEFAULT_CONFIG_ROOT))

    routing = config.models_policy()
    if outcome_predictor is None:
        outcome_predictor = load_predictor(
            config=config, model_path=env.get("MODEL_PATH", _DEFAULT_MODEL_PATH)
        )
    if instinct_predictor is None:
        instinct_predictor = load_instinct_predictor(
            config=config, model_path=env.get("INSTINCT_MODEL_PATH", _DEFAULT_INSTINCT_MODEL_PATH)
        )
    if outcome_version is None:
        outcome_version = routing.outcome.active_version
    if instinct_version is None:
        instinct_version = routing.instinct.active_version

    app = FastAPI(title="being model-service", version="0")

    @app.get("/health")
    async def health():
        # Public: the availability probe the compose healthcheck and the engine's
        # client hit; it never touches a model, so it is up before either loads.
        return {"status": "ok"}

    @app.get("/models/active")
    async def models_active():
        return {
            "outcome": {"loaded": outcome_predictor is not None, "version": outcome_version},
            "instinct": {"loaded": instinct_predictor is not None, "version": instinct_version},
        }

    @app.post("/predict/outcome")
    async def predict_outcome(payload: dict = Body(default={})):
        if outcome_predictor is None:
            # 503 -> the client's Fallback degrades to the rule baseline.
            raise HTTPException(status_code=503, detail="no outcome model loaded on this host")
        example = Example(
            properties=tuple(payload.get("properties", []) or []),
            action=str(payload.get("action", "") or ""),
            context=tuple(payload.get("context", []) or []),
        )
        return {"outcomes": {label: float(prob) for label, prob in outcome_predictor.predict_outcomes(example).items()}}

    @app.post("/predict/instinct")
    async def predict_instinct(payload: dict = Body(default={})):
        if instinct_predictor is None:
            raise HTTPException(status_code=503, detail="no instinct model loaded on this host")
        raw = payload.get("stimulus", {}) or {}
        stimulus = Stimulus(**{k: float(v) for k, v in raw.items() if k in _STIMULUS_FIELDS})
        prediction = instinct_predictor.predict_reactions(stimulus)
        return {
            "reactions": {label: float(prob) for label, prob in prediction.reactions.items()},
            "intensity": float(prediction.intensity),
        }

    return app


# Module-level app for `uvicorn app.model_service:app` (the container entrypoint).
app = create_app()

"""HttpPredictionClient — a `PredictionClient` backed by the `model-service`
sidecar (v8, ADR 0043; extends the predictor seam of ADR 0011/0015 + 0026).

Model inference without keeping torch (and a slow model load) in the engine
process: this adapter POSTs an encoded interaction to the sidecar's
`/predict/outcome` and a perceived stimulus to `/predict/instinct`, and parses the
served JSON back into the ports' own return types — a `{label: probability}` map
and an `InstinctPrediction`. It sits behind the SAME two ports as the in-process
predictors, so selecting it changes only WHERE inference runs, never what the
callers see.

Config vs. deploy, like every other network seam here (the local language model,
`DATABASE_URL`): the endpoint `base_url` is a default in `config/models.yaml`,
OVERRIDDEN by an environment variable (`MODEL_SERVICE_URL` by default) at deploy
time — so the same routing points at a local container in dev or a GPU host in
prod. With no resolved endpoint the adapter REFUSES to build a client rather than
blind-call (mirroring the Claude/local adapters' no-endpoint refusal); `httpx` is
imported lazily so it is never a test dependency, and a client may be injected for
offline isolation. It is wrapped in a `FallbackPredictionClient` so a service
outage degrades to the safe baseline rather than raising — the sidecar is an
upgrade, never a dependency.
"""
from __future__ import annotations

import os
from dataclasses import fields
from typing import Dict, Mapping, Optional

from app.ml.encode_features import Example
from app.ml.instinct_encoder import Stimulus
from app.ports.instinct import InstinctPrediction

_OUTCOME_PATH = "/predict/outcome"
_INSTINCT_PATH = "/predict/instinct"
_STIMULUS_FIELDS = tuple(f.name for f in fields(Stimulus))


class HttpPredictionClient:
    def __init__(
        self,
        *,
        base_url: str = "",
        base_url_env: str = "MODEL_SERVICE_URL",
        timeout: float = 5.0,
        outcome_version: str = "",
        instinct_version: str = "",
        env: Optional[Mapping[str, str]] = None,
        client=None,
    ) -> None:
        env = os.environ if env is None else env
        # The env var OVERRIDES the authored default (deploy config beats YAML),
        # exactly like DATABASE_URL / OLLAMA_BASE_URL.
        self._base_url = (env.get(base_url_env) or base_url or "").rstrip("/")
        self._timeout = timeout
        self._outcome_version = outcome_version
        self._instinct_version = instinct_version
        self._client = client

    def predict_outcomes(self, example: Example) -> Dict[str, float]:
        data = self._post(
            _OUTCOME_PATH,
            {
                "properties": list(example.properties),
                "action": example.action,
                "context": list(example.context),
                "version": self._outcome_version,
            },
        )
        outcomes = data.get("outcomes", data)
        return {str(label): float(prob) for label, prob in outcomes.items()}

    def predict_reactions(self, stimulus: Stimulus) -> InstinctPrediction:
        data = self._post(
            _INSTINCT_PATH,
            {
                "stimulus": {name: float(getattr(stimulus, name)) for name in _STIMULUS_FIELDS},
                "version": self._instinct_version,
            },
        )
        reactions = {str(label): float(prob) for label, prob in data.get("reactions", {}).items()}
        return InstinctPrediction(reactions=reactions, intensity=float(data.get("intensity", 0.0)))

    def _post(self, path: str, payload: dict) -> dict:
        client = self._client if self._client is not None else self._build_client()
        response = client.post(f"{self._base_url}{path}", json=payload)
        response.raise_for_status()
        return dict(response.json())

    def _build_client(self):
        # Refuse BEFORE importing httpx, so a missing endpoint is a clean refusal
        # (never a network call) and httpx stays out of the test import path. The
        # FallbackPredictionClient turns this refusal into a graceful degrade.
        if not self._base_url:
            raise RuntimeError(
                "the model-service client needs an endpoint; set MODEL_SERVICE_URL "
                "in the environment (or models.endpoint.base_url in config/models.yaml) "
                "and route the model to `http` in config/models.yaml."
            )
        import httpx  # imported lazily: not needed for tests or in-process mode

        self._client = httpx.Client(timeout=self._timeout)
        return self._client

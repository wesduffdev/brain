# 0043 — Model-service sidecar + PredictionClient seam for both models

## Status

Accepted

## Date

2026-07-11

## Context

The being now has **two** learned models behind stable ports: the outcome
predictor (`PredictorPort`, ADR 0011/0015) and the instinct model
(`InstinctPredictorPort`, ADR 0026). Both run **in-process** today —
`app.ml.inference.TorchOutcomePredictor` / `instinct_inference.TorchInstinctPredictor`,
with torch imported lazily and a `None`-safe graceful-absence path. As the models
grow (slower loads, larger deps, a future GPU host), keeping torch and model
weight inside the lean engine process stops being right: inference wants to run
**out-of-process**, on its own image and possibly its own hardware, without the
engine taking a hard dependency on either the model or the network to it.

Two forces have to hold together:

- **Where inference runs must be swappable behind the existing ports** —
  callers (`DecisionService`, `InstinctService`, `PredictionService`) depend only
  on `predict_outcomes` / `predict_reactions`; moving inference across a process
  boundary must not touch them (the `predictor` port is a coordination hotspot
  shared across V0-9, v3, v8 — pin the interface, swap the implementation).
- **A model outage must never stall the sim.** The being keeps deciding when the
  model service is unreachable; ML stays **fallback-safe** (BRIEF §6; the ADR 0011
  ensemble and ADR 0022/0033 narrator both already degrade to a safe baseline).

## Decision

Add a **`model-service` sidecar** and a **`PredictionClient` seam** that selects
where each model's inference runs, config-routed and fallback-safe.

1. **`PredictionClient` — one object covering BOTH ports.** A `PredictionClient`
   answers `predict_outcomes(example)` and `predict_reactions(stimulus)`, so a
   single client stands in wherever a `PredictorPort` **or** an
   `InstinctPredictorPort` is wanted. Three implementations vary across the seam:
   - `InProcessPredictionClient` — delegates to the in-process predictors (today's
     behavior). A missing model degrades to a **safe null**: all-zero outcome
     probabilities / a no-reaction `InstinctPrediction`. This doubles as the safe
     baseline the fallback wraps.
   - `HttpPredictionClient` (`app.adapters`) — POSTs to the sidecar's
     `/predict/outcome` and `/predict/instinct`, parsing the served JSON back into
     the ports' own return types. `httpx` is imported lazily; with no resolved
     endpoint it **refuses** rather than blind-calls (mirrors the local language
     adapter).
   - `FallbackPredictionClient` — a primary (usually the HTTP client) + a safe
     fallback; on **any** error from the primary it degrades to the fallback for
     that call. This mirrors `FallbackLanguageModel` (ADR 0022) and the ensemble's
     `fallback_to_rules_on_error` (ADR 0011).

2. **`model-service` — a small FastAPI sidecar.** `/predict/outcome`,
   `/predict/instinct`, a **public** `/health`, and `/models/active`. It loads the
   SAME `.pt` artifacts through the SAME `app.ml` code the engine uses (torch lazy;
   `None`-safe), so a served score is identical to an in-process one. The app lives
   in the engine package (`app.model_service`) so it is covered by the engine test
   suite; `model-service/` carries the container entrypoint, Dockerfile, and
   serving-only `requirements.txt` (torch/numpy) kept out of the lean engine image.
   A model not loaded on the host makes its predict endpoint return **503** — the
   signal that makes the client's `Fallback` degrade to the baseline. The default
   compose stack is unchanged: the service is **profile-gated** (`profiles:
   [models]`), exactly like the kafka `events` profile.

3. **`config/models.yaml` — per-model routing.** A `routing:` entry per model
   (`mode: inprocess | http`, `active_version`, `fallback: on`) plus the sidecar
   `endpoint:` defaults, exposed as a typed `ModelsPolicy` on `ConfigService`. The
   sidecar **base URL is deploy config** — read from the `MODEL_SERVICE_URL`
   environment variable, like `DATABASE_URL` — so the same routing points at a
   local container in dev or a GPU host in prod by an **endpoint swap**; only
   routing/flags live in YAML. **Default `mode` is `inprocess` for both models, so
   the shipped being is byte-identical to before v8.**

4. **Bootstrap selects the client; injection still wins.** `build_simulation`
   consults `models_policy()`: `inprocess` reproduces today's gating exactly (the
   outcome predictor loaded on the DB path only, `None`-able; the instinct
   predictor gated on `instinct_runtime_enabled()`), while `http` builds the
   fallback-safe client. An injected `predictor` / `instinct_predictor` always wins.

5. **Safety is untouched.** The predictor only feeds `DecisionService`'s
   anticipated cost, which runs **after** the `SafetyService` block check; a served
   score can no more buy a blocked action past the floor than an in-process one can
   (BRIEF §12; ADR 0009/0014). No new type is introduced for the outcome result —
   the port's existing `Dict[str, float]` and `InstinctPrediction` are the served
   contract, so callers are unchanged.

## Consequences

- Inference can move out-of-process **per model** with no change above the ports,
  and local-container ↔ prod-GPU is an endpoint (env) swap.
- A model-service outage degrades to the rule/safe baseline and the sim keeps
  running; the sidecar is an upgrade, never a dependency.
- The default remains fully in-process and byte-identical — the sidecar and its
  torch dependency ship only under the `models` profile, so the lean engine image
  and the default stack are unchanged.
- The sidecar's predict endpoints are **unauthenticated on the compose-internal
  network** (only `/health` is intentionally public elsewhere); it is not exposed
  to untrusted callers by default. Adding JWT/mTLS parity with the engine
  (`require_auth`, ADR 0005) is a deliberate follow-up when the service leaves the
  trusted network — noted here rather than silently assumed.
- Extends ADR 0011/0015 (outcome predictor seam + active blend) and ADR 0026
  (instinct model/port/artifact); reuses the fallback pattern of ADR 0022.

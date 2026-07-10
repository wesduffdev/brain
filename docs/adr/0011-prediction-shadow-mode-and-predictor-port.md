# 0011 — Prediction shadow mode and the predictor port

## Status

Accepted

## Date

2026-07-10

## Context

V0-8 trained the outcome predictor and saved `models/outcome_predictor.pt` with
its feature/label contract (ADR 0008). This slice (V0-9) is the other side of
that saved file: the engine loads the artifact and, for **each interaction**,
records what the model predicted next to what the rule layer expected and what
actually happened — the "Shadow Mode First" loop of BRIEF §11:

```text
Rule system predicts outcome. PyTorch predicts outcome. Actual outcome occurs.
Both predictions are stored. System compares prediction quality.
```

The load-bearing constraint is that the model must **not** influence behavior:
in v0 predictions are observed and compared only; they never feed the decision
(that is a later version, and even then safety is absolute — BRIEF §12). So the
being's action stream and state must be byte-identical whether the predictor is
on or off.

Two further forces shape the design:

- **The lean runtime must stay small.** torch is a training/inference-only
  dependency (`requirements-train.txt`), not in the runtime image. Inference
  must import torch lazily and degrade gracefully when it — or the artifact — is
  absent, exactly as the trainer does.
- **A stale artifact must never be silently used.** The trainer and inference sit
  on opposite sides of a saved file built at different times; if the artifact's
  vocabulary disagrees with the current config, every prediction is quietly
  garbage (ADR 0008). Present-but-mismatched is a different case from absent.

## Decision

### A predictor port seam (shadow-vs-real varies)

Add `app.ports.predictor.PredictorPort`: one method,
`predict_outcomes(example) -> {label: probability}`, multi-label independent
probabilities, **no action selection**. This is a genuine seam because two
implementations vary across it:

- **Real**: `app.ml.inference.TorchOutcomePredictor`, loaded by
  `load_predictor(config=…, model_path=…)`. It encodes with the *same*
  `FeatureEncoder` contract the trainer used (ADR 0008) and runs the net. torch
  is imported lazily inside `load_predictor`, so the module imports with zero
  training deps.
- **Fake**: the behavior suite drives a fake predictor, so all shadow-mode logic
  is testable without torch or an artifact.

**Graceful degradation is the point of the seam.** `load_predictor` returns
`None` when torch is not installed or the artifact does not exist — shadow mode
then records nothing and behavior is unchanged. A *present* artifact whose
feature/label contract disagrees with config is rejected **loudly**
(`ValueError`), not silently paired (ADR 0008).

### A PredictionService (the shadow-mode coordinator)

`app.services.prediction_service.PredictionService` (BRIEF §17) takes a
`PredictorPort` and a `PredictionRecordRepository`. For one interaction it
encodes the being's perception + the action + situational context, asks the
predictor for probabilities, thresholds them into a predicted outcome set
(threshold is config-driven — `outcome_labels.yaml: prediction.threshold`,
default 0.5), and writes a `PredictionRecord` holding **model prediction vs the
rule's expected outcome vs the actual observed outcome**, plus `correct`
(exact-match at threshold — BRIEF §16: predicts bounce, actual bounce → correct)
and `prediction_error` (mean |probability − actual| over labels, the continuous
signal a later version feeds into curiosity). It touches no being state — the
model observes, it does not drive.

### The encode-action is an affordance, not the action name

The being's action *names* (`observe`, `approach`, `withdraw`, …) are not the
model's action vocabulary; the model was trained on object *affordances*
(`look`, `touch`, `push`, `grab`, `drop` — the trainer crosses each object with
its affordances). So an interaction is encoded by its action's **affordance**
(`observe` → `look`); a free action (`approach`/`withdraw`) has none and encodes
with no action slot. The `Simulation` supplies the affordance; the record keeps
the real action name.

### Contract reconciliation

The artifact stores the *concatenated* `feature_names` and `label_names`, but the
`FeatureEncoder` needs the property/action/context *split* to encode — which only
config carries. So `load_predictor` builds the encoder from config and **accepts
the artifact only if its feature/label names equal the encoder's**. Since they
must be equal, the vocabulary used is exactly the artifact's (ADR 0008), with the
mismatch caught loudly.

### Wiring and persistence

`Simulation` gains optional `predictor` and `prediction_repository` parameters.
With no predictor there is no `PredictionService` and nothing is recorded.
`Simulation.predictions()` exposes the records as snapshots, mirroring
`interactions()`. Records are written through a new
`PredictionRecordRepository` port with an in-memory fake; the Postgres-backed
adapter onto the reserved `prediction_records` table follows with the
persistence wiring (V0-7).

## Consequences

- **Shadow mode is real and safe.** The engine loads the model and records model
  vs rule vs actual per interaction, with the being's behavior provably
  unchanged (the shadow-invariant test: identical state and interactions
  predictor-on vs -off).
- **The runtime stays lean.** torch is pulled in only by an actually-loaded
  predictor; the runtime path and the encoding contract are torch-free.
- **Config-driven tuning holds.** The shadow threshold lives in config; retuning
  sensitivity is a config change.
- **v0 correctness measures agreement, not skill.** The model imitates the
  trainer's synthetic rules, while the actual outcome comes from the
  `actions.yaml` rule layer, and shadow-mode inference currently passes no
  surface context (the sim models none) — so `correct` will often be `False`
  until those rule sources are unified and a real context is wired. Shadow mode
  records this faithfully; making correctness *meaningful* is the follow-up
  below, not a change to this seam.
- **Follow-ups:** unify the trainer's synthetic outcome rules with the
  `actions.yaml` rule layer so the model imitates the rules the being actually
  uses; wire a real situational context (surface) into interactions so inference
  is in-distribution; add the Postgres `PredictionRecordRepository` adapter with
  the persistence wiring (V0-7); feed `prediction_error` into curiosity (v1+).
```

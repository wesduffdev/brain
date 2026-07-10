# 0008 — Outcome predictor and the feature/label encoding contract

## Status

Accepted

## Date

2026-07-10

## Context

The being's first neural network (BRIEF §11) is an **outcome predictor**: given
an object's properties, the action taken on it, and a little situational
context, predict which **outcomes** occur. It is **multi-label** — one action can
produce several outcomes at once (drop a rubber ball → `falls` + `bounces` +
`rolls`) — so each outcome is an independent probability, not a softmax class.

V0-8 builds the training half of this in shadow mode (BRIEF §11, "Shadow Mode
First"): the trainer and an `ml-trainer` sidecar produce `models/outcome_predictor.pt`.
V0-9 will load that artifact and run inference alongside the rule layer, storing
both predictions for comparison. The two slices sit on opposite sides of a saved
file and are built at different times, so **the encoding must be pinned as a
contract**: if V0-9 encodes an interaction even slightly differently from how
V0-8 trained, every prediction is silently garbage. A sketch in the brief is not
enough; this ADR is the source of truth for the exact feature and label layout.

Two constraints shape the decision:

- **The lean runtime image must stay small.** The `engine` service never trains;
  PyTorch is large. So the torch-dependent code (model + trainer) must be
  separable from the pure encoding code that inference will also need.
- **The synthetic path must run standalone.** Persistence (V0-6) and the
  event→example wiring (V0-7) do not exist yet. The trainer must produce a real
  artifact today, from config alone, with no database.

## Decision

### The model

A small feed-forward net (`engine/app/ml/outcome_model.py`): `Linear →
ReLU → Linear`, one logit per outcome. Training uses `BCEWithLogitsLoss`;
`predict`/`predict_one` apply a sigmoid so each outcome is an independent
probability in `[0, 1]`. Deliberately tiny — in v0 it imitates the rule layer
that generated its data, so the goal is to exercise the full loop (encode →
train → evaluate → persist → later infer), not to be large.

### The feature/label encoding contract (the load-bearing part)

`engine/app/ml/encode_features.py` is **pure** (no torch, no file IO, no
config-file knowledge) so it lives in the lean runtime and inference shares it.
An interaction is an `Example(properties, action, context, outcomes)`.

**Feature vector** — a multi-hot vector, concatenated in this fixed order:

```
[ property_vocab ] ++ [ action_vocab ] ++ [ context_vocab ]
```

- `property_vocab` — the `properties` list in `config/object_properties.yaml`,
  in authored order (an object's perceived properties set their slots).
- `action_vocab` — the `affordances` list in `config/object_properties.yaml`,
  in authored order (the single action taken sets one slot).
- `context_vocab` — the `context_features` list in `config/outcome_labels.yaml`
  (v0: `surface_hard`, `surface_soft` — the surface the object meets).

**Label vector** — multi-hot over `labels` in `config/outcome_labels.yaml`, in
authored order: `rolls, bounces, falls, causes_pain, makes_noise, pleasant,
scary`.

**Rules of the contract:**

- **Config order is the contract.** Slot *i* is whatever term is at position *i*
  in the concatenated vocabularies. The YAML files are the single source of
  truth for both the vocabulary and its order; reordering or inserting a term is
  a contract change (retrain required).
- **`ConfigService` owns config.** The encoder is built via
  `FeatureEncoder.from_config(config)`, which reads typed vocab off
  `ConfigService` (`object_property_vocab`, `object_action_vocab`,
  `outcome_context_features`, `outcome_labels`). The ML package never opens a
  YAML file.
- **Unknown terms are rejected, not silently dropped.** Encoding a property /
  action / context / outcome outside its vocabulary raises `ValueError` — same
  discipline as the object catalog: a typo fails loudly rather than encoding to
  nothing.
- **The artifact carries its contract.** `save_outcome_model` stores
  `feature_names` and `label_names` (and metrics) alongside the weights;
  `load_outcome_model` returns the model plus that contract. V0-9 reads the
  vocabulary out of the file it loaded, so a stale artifact cannot be silently
  paired with a newer config.

### Training data: stored first, else a synthetic seed set

`train_outcome_model.py` prefers stored `training_examples` when they exist, and
otherwise derives a **synthetic seed set** from the config vocabulary
(`synthetic_examples(config)`): every object in the catalog, crossed with each
action it affords and each surface context, labelled by authored rules that
stand in for the being's rule layer. The rules are chosen so every outcome label
appears in the seed set. Torch is imported lazily inside the training functions,
so importing the module (e.g. to reach `synthetic_examples`) never requires the
training deps. `load_training_examples` returns `None` today — deliberately
un-wired to any database, so the synthetic path runs standalone.

### Dependency and service split

PyTorch/NumPy live in `engine/requirements-train.txt` (not the lean
`requirements.txt`). The `ml-trainer` docker service (`profiles: [training]`)
reuses the engine image, installs the training set on top, and runs the trainer;
it has **no `depends_on: postgres`** so `docker compose --profile training run
ml-trainer` works without a database. `make train` is the local equivalent.

## Consequences

- **V0-9 can build against a frozen shape.** It loads `outcome_predictor.pt`,
  reads `feature_names`/`label_names` from the artifact, and encodes inference
  inputs with the same pure `FeatureEncoder` — no re-derivation, no drift. If the
  encoding must change incompatibly, this ADR is **superseded** (and models
  retrained), not quietly edited.
- **The runtime image stays lean.** Encoding is torch-free and shared;
  torch is training-only. Inference in V0-9 needs torch to run the net, but the
  encoding contract it depends on does not.
- **Config-driven tuning holds.** Outcome labels, context features, and trainer
  hyperparameters live in `config/outcome_labels.yaml`; retuning is a config
  change. Adding a vocabulary term is a config edit that changes the vector
  width and requires a retrain — expected and visible.
- **v0 metrics measure imitation, not generalization.** The seed set is
  generated by rules and the model trains to fit it, so high training accuracy
  means "reproduced the rules," as BRIEF §11 intends. Genuine learning signal
  (held-out data, prediction error feeding curiosity) arrives in v1+.
- **Design boundary.** Outcomes such as `causes_pain` and `scary` are abstract
  labels/probabilities the being learns to anticipate so it can avoid harm; they
  are never depictions of real-world harm (see `docs/design_boundary.md`,
  BRIEF §2). Learned predictions never bypass safety (BRIEF §12) — that is a
  decision-layer concern for a later slice, not this model's.
- **Follow-ups:** train on real `training_examples` once V0-6 persistence +
  V0-7 event→example wiring (and the DB port) land; record a `model_runs` row per
  training run when that port exists; V0-9 wires shadow-mode inference +
  prediction/actual comparison.

## Extension — V0-8b (train on persisted examples; record model runs)

### Date

2026-07-10

### What changed

The two follow-ups above (train on real `training_examples`; record a
`model_runs` row per run) are now realized, without altering the encoding
contract this ADR pins. This section is additive — the Decision above stands.

- **Source selection moved into `run_training(...)`.** The old
  `load_training_examples` stub (which always returned `None`) is replaced by a
  single deep orchestration on the trainer: read stored examples through the
  V0-7b `TrainingExampleRepository` when it holds any, else fall back to the
  config-derived synthetic seed set. The standalone synthetic path is unchanged —
  no repository injected means synthetic, so `make train` still runs with no
  database. Stored `TrainingExample`s are already encoded (V0-7b encoded them
  through this ADR's `FeatureEncoder` at write time), so both sources reduce to
  the same `(features, labels)` rows the torch core trains on; the contract is
  identical across them by construction.
- **A `ModelRunRepository` records each run.** It follows the append-only
  port + in-memory/Postgres-adapter pattern established for events and examples
  (ADR 0012), so it does not warrant its own ADR by the 3-part test (it is not
  surprising, is easy to reverse, and carries no real trade-off). Its aggregate
  is `app.domain.model_run.ModelRun` (`artifact_path`, `metrics`, `finished_at`).
  The **timestamp is carried on the aggregate and injected by the caller**, never
  stamped inside the store — so a run's moment is explicit and the persistence
  path is testable with no wall clock. `run_training` records one row (the
  artifact path, the metrics dict incl. a `source` key, and the timestamp) when a
  `model_run_repo` is present; with no database, no row is written and the run
  still succeeds.
- **`make train` wiring.** `main()` opens the Postgres training-example and
  model-run adapters when `DATABASE_URL` is configured (env-only, ADR 0005) and
  passes them plus `datetime.now(...)` into `run_training`; unset → both `None` →
  synthetic, no run recorded. An empty-but-configured database falls back to
  synthetic and still records the run.

### Consequences

- **The learning loop trains on real data end-to-end.** Demonstrated: 80 sim
  ticks persisted 52 interaction-derived `training_examples`; `make train` then
  read them (`source=training_examples`, 52 examples), wrote the artifact, and
  recorded one `model_runs` row (artifact path, metrics, finished-at). The
  synthetic fallback (`source=synthetic`, no DB) still produces an artifact.
- **Testable without torch, a wall clock, or a database.** The real-training
  behaviour stays `torch`-gated (`pytest.importorskip`); the repository and
  timestamp are seams driven by in-memory fakes and an injected time; a live
  Postgres round-trip covers the adapters (`integration`, skipped when
  unreachable, never faked) — the ADR 0007/0012 discipline, now covering runs.

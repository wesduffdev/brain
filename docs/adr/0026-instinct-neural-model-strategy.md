# 0026 — Instinct neural model strategy: a separate model, port, and artifact

## Status

Accepted

## Date

2026-07-11

## Context

The event-instinct wave (see [`docs/event_instinct_execution_plan.md`](../event_instinct_execution_plan.md),
card `NN-STRAT`) adds an **instinct layer** — fast, pre-conceptual protective
reactions (flinch / freeze / orient / withdraw / ignore) that sit between
perception and decision-making and run per perception/approach event, not per
decision. The being already has **one** neural network. Before `INS-MODEL` can
build the instinct net, the wave needs a recorded decision: is instinct a second
**head on the existing model**, or a **separate model** with its own port and
artifact — and what exactly is its input/output contract? This ADR is a decision
spike (`NN-STRAT`); it writes no production code. It freezes the contract that
`INS-MODEL` (the model, encoder, seed data, trainer) and `WORLD-MOTION` (the
stimulus source that produces the features) build against.

### The existing neural network, as it actually is (2026-07-11)

The one existing net is an **outcome predictor**, not a reaction model. Grounded
in the code (not guessed):

- **Model** — `OutcomeModel` (`engine/app/ml/outcome_model.py`): a deliberately
  tiny feed-forward net, `Linear(input_size, 16) → ReLU → Linear(16, output_size)`.
  `forward` returns raw logits (trained with `BCEWithLogitsLoss`); `predict`
  applies a **sigmoid** so each output is an independent probability;
  `predict_one(features)` maps one feature vector → a probability per label. It
  is **multi-label, not softmax** — one action can produce several outcomes at
  once (a dropped rubber ball → `falls` *and* `bounces` *and* `rolls`).

- **I/O shape** — the input is a **multi-hot** vector over authored categorical
  vocabularies, concatenated in fixed config order
  `property_vocab ++ action_vocab ++ context_vocab`; the output is multi-hot over
  the outcome `label_vocab` (`rolls, bounces, falls, causes_pain, makes_noise,
  pleasant, scary`). The encoding contract is pinned by **ADR 0008**.

- **Feature encoding** — `FeatureEncoder`/`FeatureSpec`
  (`engine/app/ml/encode_features.py`) is **pure**: no torch, no file IO, no
  config-file knowledge. It is built via `FeatureEncoder.from_config(config)`
  (reading typed vocab off `ConfigService`), turns an `Example(properties,
  action, context, outcomes)` into plain float tuples, exposes
  `feature_names()`/`label_names()`, and **rejects unknown terms loudly**
  (`ValueError`). Purity is deliberate so the lean runtime can import it for
  inference without pulling in torch.

- **Predictor seam** — `PredictorPort`
  (`engine/app/ports/predictor.py`): `predict_outcomes(example) -> Dict[str,
  float]`. Implementations that vary across it justify the seam:
  `TorchOutcomePredictor` (the loaded neural model, `engine/app/ml/inference.py`),
  `RuleBasedPredictor` (the always-available zero-dependency baseline),
  `EnsemblePredictor` (blends neural + rule by config weight, degrades to rules on
  error — ADR 0015), and test fakes. The decision layer depends only on the port;
  a learned score never bypasses `SafetyService` (ADR 0009/0014).

- **Training pipeline** — `train_outcome_model.py`: `synthetic_examples(config)`
  (a config-derived seed set standing in for the rule layer), `train` /
  `train_and_save`, `run_training` (reads stored `training_examples` through a
  repository when present, else synthetic; records a `ModelRun` in one unit of
  work — ADR 0017), and a `main()` entrypoint used by `make train` and the
  profile-gated `ml-trainer` service. Torch is imported **lazily** inside the
  training functions.

- **Artifact & versioning** — `save_outcome_model`/`load_outcome_model` persist
  the weights **with their feature/label contract** (`state_dict`, `input_size`,
  `output_size`, `hidden_size`, `feature_names`, `label_names`, `metrics`) to
  `models/outcome_predictor.pt`. On load, inference **rejects a stale artifact
  loudly** when its contract disagrees with the current config vocabulary, rather
  than silently pairing mismatched vocab (ADR 0008). Shadow-mode `load_predictor`
  returns `None` gracefully when torch or the artifact is absent, so the being's
  behavior is unchanged. Torch lives in `requirements-train.txt`, out of the lean
  runtime image.

### Why the choice is not obvious

The existing structure (`OutcomeModel` / `FeatureEncoder` / `PredictorPort` /
`train_outcome_model` / a contract-carrying `.pt`) is a clean, proven template.
The temptation is to reuse it wholesale by bolting a second output head onto
`OutcomeModel`. The question is whether instinct's contract actually *fits* that
model, or only its file layout.

## Decision

**Add a separate instinct model — a new `InstinctModel` (small PyTorch net)
behind a new `InstinctPredictorPort`, with its own artifact `models/instinct.pt`
— mirroring the `OutcomeModel` / `PredictorPort` / `train_outcome_model`
*structure* while keeping its own contract, training data, and rollout.** Do
**not** add a second head to `OutcomeModel`.

### Why a separate model, not a second head on `OutcomeModel`

The two nets share only a *shape of implementation*, not a domain contract. A
second head would couple things that genuinely differ:

- **Disjoint inputs, disjoint encoders.** `OutcomeModel` consumes a **multi-hot
  categorical** vector over authored vocabularies (properties/actions/context).
  Instinct consumes **continuous, normalized sensory/kinematic scalars**
  (distance, velocity, acceleration, time-to-contact…). There is no shared
  feature space to exploit — the encoders share nothing, so a shared trunk would
  learn nothing joint. The only thing a shared model would share is the *file*,
  which the deletion test flags as a pass-through coupling with no benefit.

- **Mixed output objective.** Outcome prediction is pure multi-label sigmoid.
  Instinct is **multi-label reaction probabilities *plus* a scalar
  `reaction_intensity` regression** — a mixed classification+regression head with
  a different loss, awkward to graft onto the single `BCEWithLogitsLoss` path.

- **Different invocation cadence and latency budget.** `OutcomeModel` runs once
  per *interaction* inside the synchronous decision pipeline. Instinct runs per
  *perception/approach event*, on the event backbone, and is on a **low-latency**
  fast path (`ObjectApproached → predict → reaction` before the decision loop).
  A fast-reaction net does not want to share an artifact/version with a
  slower, per-decision predictor.

- **Independent training data & seed labeling.** Instinct trains on **stimulus
  windows** rule-labeled by different functions (fast-toward-face→flinch,
  loud-unknown→freeze, new-stimulus→orient, unexpected-touch→withdraw,
  low-signal→ignore) — a different dataset, generator, and eval from the
  object-action-context outcome data.

- **Independent, shadow-first rollout with low blast radius.** Instinct ships
  shadow → visual-only → controlled-interrupt (each a config flip, per the ADR
  0011 precedent). A separate model + port + artifact means instinct can be
  trained, versioned, rolled out, and rolled back **without retraining or
  risking the outcome predictor**, and vice versa. One combined artifact would
  force a retrain of both whenever either vocabulary changed and would widen the
  blast radius of every instinct iteration.

Reusing the *template* (a tiny torch net; a pure, config-vocab encoder; a
contract-carrying artifact; a lazy-torch trainer; a port with a fake for tests)
keeps the win of the proven structure without the coupling of a shared model.
This matches the wave plan's default recommendation and the deep-module rule that
a seam is justified only when something varies across it — here, two real
implementations (outcome vs. instinct) and a test fake vary across
`InstinctPredictorPort`.

### The frozen contract (the load-bearing part)

This is what `INS-MODEL` and `WORLD-MOTION` build to. `WORLD-MOTION` produces
these features from perceived kinematics; `INS-MODEL`'s `InstinctFeatureEncoder`
encodes exactly this vector and its model emits exactly these outputs. Config
order is the contract, exactly as in ADR 0008: reordering or inserting a feature
or label is a contract change (retrain required), and the artifact carries its
own `feature_names`/`label_names` so a stale `instinct.pt` is rejected loudly.

**Input feature vector (ordered — 14 continuous, normalized scalars):**

```
[  0] distance
[  1] velocity
[  2] acceleration
[  3] trajectory_toward_body
[  4] time_to_contact
[  5] object_size
[  6] size_change_rate
[  7] unexpectedness
[  8] visibility_confidence
[  9] sound_spike_intensity
[ 10] touch_intensity
[ 11] current_focus_level
[ 12] current_stability
[ 13] prior_prediction_error
```

These are the being's *perceived* fast-sensory features. They key on perceived
kinematics/stimulus, never on any `developer_label` (ADR 0002). Unlike the
outcome encoder's multi-hot slots, each slot here is a single scalar (expected in
a normalized range, e.g. `[0, 1]` or a signed rate) — the `InstinctFeatureEncoder`
owns the normalization and, like `FeatureEncoder`, stays pure and torch-free so
inference can import it in the lean runtime.

**Output (multi-label reaction probabilities + one scalar intensity):**

```
labels (independent sigmoid probabilities, in order):
  flinch, freeze, orient, withdraw, ignore
scalar:
  reaction_intensity  in [0, 1]
```

The five reaction labels are multi-label (independent probabilities, not a
softmax distribution — a stimulus can score high on both `flinch` and
`withdraw`). `reaction_intensity` is a separate scalar regression output in
`[0, 1]`. Reaction selection, thresholds, and cooldowns are a *consumer* concern
(`INS-RT`, `config/instinct.yaml`) — the model only *predicts*; it never selects
an action and never bypasses safety (ADR 0009/0014), exactly as `PredictorPort`
never chooses an action.

### Structure `INS-MODEL` mirrors

- `InstinctModel` (small feed-forward torch net) in `engine/app/ml/`, with
  `save_*`/`load_*` persisting weights **with** the frozen feature/label
  contract to `models/instinct.pt` (contract-mismatch rejected loudly).
- `InstinctFeatureEncoder` (pure, config-vocab-driven, torch-free), the single
  home of the input contract above — the instinct analogue of `FeatureEncoder`.
- `train_instinct_model.py` with a synthetic (rule-labeled) seed generator and
  eval, mirroring `train_outcome_model.py`; torch imported lazily; torch stays in
  the training/opt deps, not the lean runtime.
- `InstinctPredictorPort` in `engine/app/ports/instinct.py` — a torch-backed
  real impl, plus a test fake, so the instinct consumer (`INS-RT`) is testable
  with no torch and no artifact (graceful `None` when the artifact/torch is
  absent, as with the outcome predictor's shadow load).

## Consequences

- **`INS-MODEL` can start unambiguously.** The feature vector, its order, the
  reaction-label set, and the intensity scalar are frozen here; the encoder and
  model build to them, and `WORLD-MOTION`'s emitted `ObjectApproached` payload
  supplies them.
- **Instinct iterates without touching the outcome predictor.** Separate model,
  port, and artifact mean independent training, versioning, shadow-first
  rollout, and rollback — the outcome predictor is never retrained or
  destabilized by instinct work, and neither model's failure affects the other.
- **The lean runtime stays lean.** As with ADR 0008, the instinct encoder is
  torch-free and shared with inference; torch is loaded only by an
  actually-loaded instinct predictor and the trainer.
- **The safety floor is untouched.** Instinct predicts reaction probabilities;
  it proposes reactions/interruptions that still route through
  `SafetyService`/`DecisionService` (`INS-RT`/`INS-ACT`). A learned instinct
  score can never buy a blocked action past the floor (ADR 0009/0014).
- **One more artifact and inference path.** The cost of the decision: a second
  `.pt`, a second port, and a second trainer entrypoint. Accepted deliberately —
  the isolation and independent rollout are worth more than one fewer file, and
  the structure is a proven copy of the outcome path.
- **v0-style metrics measure imitation.** As with the outcome model, the first
  instinct model imitates its rule-derived seed labels; genuine adaptive signal
  (temperament, experience-driven sensitivity) arrives later in the instinct
  rollout, not in `INS-MODEL`.
- **Design boundary.** Reactions such as `flinch`/`freeze`/`withdraw` and the
  intensity scalar are abstract internal probabilities the being learns so it can
  protect itself; they are never depictions of real-world harm (`docs/design_boundary.md`,
  ADR 0013).

Supersedes nothing.

Relates-to: **ADR 0008** (outcome predictor + feature/label encoding contract —
the template this mirrors and the artifact-carries-its-contract discipline it
reuses); **ADR 0011** (prediction shadow mode + predictor-port seam — the
shadow-first rollout and graceful-degradation precedent instinct follows);
**ADR 0015** (active blended outcome prediction — the port-behind-decision pattern
and the rule that learned scores never bypass the safety floor).

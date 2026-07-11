# 0015 — Active (blended) outcome prediction in the decision

## Status

Accepted

## Date

2026-07-10

## Context

ADR 0011 loaded the outcome predictor and ran it in **shadow mode**: for each
interaction it recorded what the model predicted beside the rule layer's
expectation and the actual outcome, but the prediction never touched what the
being did (the shadow invariant — behavior byte-identical predictor on vs off).
BRIEF §12 and the v2 roadmap always intended prediction to eventually *shape* the
decision: "neural prediction contributes to utility scores; safety rules remain
hard guardrails." This slice (card v3) is that step — prediction becomes
**active** — without breaking the two load-bearing constraints:

- **Learned scores never bypass safety** (BRIEF §12–§13). The SafetyService floor
  is absolute; a confident prediction can raise or lower an action's appeal but
  can never buy a blocked action past the guardrail.
- **A model failure must never stop the being.** The neural model is optional
  (torch/artifact may be absent) and can fail at inference time; the being must
  keep deciding regardless.

## Decision

### The predictor seam gains two pure-Python implementations (no new interface)

Prediction stays behind the existing `app.ports.predictor.PredictorPort`
(ADR 0011). Two implementations join the torch-backed `TorchOutcomePredictor`,
both pure Python so the lean runtime carries them:

- **`RuleBasedPredictor`** — the being's own action rules (`actions.yaml`, via
  `ActionPolicy.outcomes_for`) exposed as a `PredictorPort`: it returns the
  outcomes the rule layer says an action produces on an object, as certain
  (1.0) / not (0.0) probabilities. Always available, zero dependencies — the safe
  baseline the neural model is blended with and falls back to.
- **`EnsemblePredictor`** — blends a neural predictor with the rule-based one:
  per label, `neural_weight · P_neural + rule_weight · P_rule`. When the neural
  predictor is disabled or absent, the rule layer carries the call alone. When an
  *enabled* neural predictor raises, it degrades to the rule layer if
  `fallback_to_rules_on_error` is set (the sim keeps running), else it propagates.

No new port is introduced — the ensemble is itself a `PredictorPort`, so the
decision layer depends only on the seam, never on how a prediction was produced.

### The DecisionService consumes the blended prediction as an anticipated cost

`DecisionService` gains an optional `predictor` (the ensemble) and an
`OutcomeEffectPolicy`. For each **safe** candidate it builds the interaction
`Example` (perceived properties + the action's affordance), asks the predictor
for blended outcome probabilities, and subtracts the *anticipated aversive cost*
of those outcomes from the action's utility. Anticipated cost lives on
`OutcomeEffectPolicy.anticipated_cost(probabilities)`: each outcome's probability
weights how much that outcome is expected to erode the being's needs (the sum of
its need *drops*, from the same felt-consequence table that lands real harm in
ADR 0014). So the being penalizes an action it predicts will hurt — it can learn
to avoid the hot lamp by anticipation, not only by being burned.

**Penalize, not block, and safety first.** The cost is applied only to candidates
that already passed the SafetyService floor — blocked candidates are dropped
*before* prediction is consulted, so a learned score can never rescue a forbidden
action. The floor blocks; prediction merely reshuffles the safe options. This is
BRIEF §12's "block *or* penalize": genuinely simulation-breaking actions are
hard-blocked by the floor (ADR 0014), while recoverable-but-harmful ones are now
softly avoided through anticipation.

### Activation is a config flip (shadow → active)

The four knobs live in the existing `prediction:` block of
`outcome_labels.yaml` (typed as `PredictionBlendPolicy`): `neural_enabled`,
`neural_weight`, `rule_weight`, `fallback_to_rules_on_error`. `neural_enabled` is
the flip:

- **off (default)** — prediction is observational: shadow mode runs exactly as
  ADR 0011 (behavior byte-identical predictor on vs off).
- **on** — prediction is active: `Simulation` builds an `EnsemblePredictor`
  (rule baseline + the injected neural predictor, or rules only when the neural
  model is absent) and wires it into `DecisionService`; the decision consumes it
  directly and shadow recording steps aside. Retuning the blend, or turning the
  model off, is a config change only.

## Consequences

- **Prediction influences behavior, safely.** With `neural_enabled: true` the
  being's chosen action changes — it avoids an action it predicts will hurt —
  while an injected floor rule still blocks a prediction-endorsed action.
  Demonstrated by `engine/tests/test_blended_prediction.py`.
- **The runtime stays lean and robust.** Rule-based and ensemble predictors are
  torch-free; a neural inference error falls back to rules and the sim keeps
  running; an absent artifact degrades to the rule baseline.
- **No new interface.** Blending and rules reuse `PredictorPort`; the decision
  layer's dependency surface is a single seam.
- **Known limitation.** When a heavily-penalized action is the *only* selectable
  option, it is still chosen — there is no "prefer idle over predicted self-harm"
  threshold yet. And the anticipated cost is one-sided (it penalizes predicted
  need-drops; it grants no bonus for predicted need-gains, since pleasant carries
  no felt effect in v0 — ADR 0014). Both are v1+ follow-ups.
- **Follow-ups:** record active-mode predictions for the shadow comparison too
  (telemetry while active); a symmetric bonus for anticipated good outcomes once
  pleasant carries a felt effect; feed prediction uncertainty into curiosity
  (v1); exempt free actions from anticipated cost if neural blending proves to
  bias approach/withdraw.

# 0023 — One-shot aversive concept learning and the belief→decision feed

## Status

Accepted

## Date

2026-07-11

## Context

The being forms **concept schemas** and **beliefs** (ADR 0019, card v2) and can
anticipate/avoid harm when the neural predictor is *active* (ADR 0015, card v3).
A hot-lamp review exposed two gaps in the default configuration
(`neural_enabled=false`):

1. **Concept confidence was intensity-blind.** Every confirming interaction moved
   a concept's confidence by the same config step regardless of how *intensely*
   the being felt it. So the being touches the hot lamp once, is burned into fear,
   then fear-avoids — and `hot → touch → causes_pain` freezes at the seed
   confidence (0.30) on its single piece of evidence. A searing, once-in-a-lifetime
   burn produced the same timid generalization as one bland observation.

2. **Concepts/beliefs never reached the decision.** With the predictor off, the
   decision ran on raw utility (plus the v6 remembered-preference bias and the v4
   curiosity bonus). The concept-derived belief that touching a hot thing causes
   pain was *formed and stored* but never *consulted* when choosing an action, so a
   never-seen hot object could only be avoided once fear had already been induced —
   the being could not avoid it *cognitively*, from what it already understood.

We wanted both closed without a new port and without weakening the safety floor.

## Decision

**1. Emotional-intensity-weighted concept confidence (one-shot aversion).**
`ConceptLearningPolicy.reinforce` gains an `intensity` term. Confidence is
reinforced from its prior (0.0 before any evidence) toward certainty at an
*intensity-amplified* rate:

```
effective_rate = min(1, base_rate * (1 + intensity_gain * intensity))
confidence_next = prior + effective_rate * (1 - prior)
```

`intensity` is the interaction's **salience** — the same emotional-intensity +
prediction-error scalar that scores a memory's priority
(`MemoryPriorityPolicy`). The `Simulation` computes it once per interaction and
passes it into `ConceptService.observe(..., intensity=…)`. At `intensity_gain=2.0`
a single scared-level burn (salience ≈ 1.0) lifts `hot → causes_pain` from the
0.30 seed to ≈ 0.90 in one evidence (trauma-like one-shot learning), while
low-salience repetition keeps the ordinary slow, diminishing-returns curve.
`intensity_gain=0` (or `intensity=0`) is byte-identical to the pre-slice curve.

**2. Beliefs feed the default decision path via the existing `score_bias` seam.**
`BeliefService` gains a read-only query `anticipated(...) -> {outcome: confidence}`
(the being's current expectation for an (object, action), the strongest supporting
concept per outcome — `believe` now writes through the same query). Each tick the
`Simulation` turns those expectations into an **anticipated-discomfort** cost —
valued by the *same* `OutcomeEffectPolicy.anticipated_cost` the predictor path
uses, with the belief's confidence standing in for a predicted probability — scaled
by a new config `BeliefDecisionPolicy.discomfort_weight`. This belief bias is
**summed** with the v6 remembered-preference bias (`_sum_biases`) into the single
`score_bias` map the `DecisionService` already applies to **safe** candidates only.
No `DecisionService` logic changed.

Consequences of routing choice: the belief bias enters through `score_bias`
(alongside the memory bias), **not** through the `ExplorationPolicyService`'s
dormant `anticipated_discomfort` term. `score_bias` is applied strictly after the
safety block, so — like every learned signal — the belief can never buy a blocked
action past a guardrail (BRIEF §12); and both learned pathways compose in one
place. The two biases are **distinct cognitive pathways** (episodic recall vs.
semantic belief) and compose by addition, not double-counting.

All magnitudes are config (`config/learning_rates.yaml`: `concept.learning.
intensity_gain`, `belief.decision.discomfort_weight`); both default to the
pre-slice behaviour, so the feed is opt-in.

## Consequences

- One emotionally-intense burn now produces a strong, durable aversive concept in
  a single evidence; ordinary repetition is unchanged.
- With the predictor off, a never-seen hot object is avoided **cognitively** —
  demonstrated with fear held constant (the being calm, not scared), isolating the
  belief from the emotion.
- The safety floor is untouched: belief/memory scores only ever reshape candidates
  the floor has already cleared. Covered by a test that keeps a hard-blocked touch
  blocked with a strong aversive belief present.
- No new port or seam: this extends `ConceptLearningPolicy` and `BeliefService`,
  reuses `OutcomeEffectPolicy.anticipated_cost` and the v6 `score_bias` channel.
- **Known duplication (follow-up):** interaction *salience* is now computed twice
  per interaction — in `MemoryService` (for the memory's priority) and in the
  `Simulation` (for concept intensity). Identical inputs, identical result; a
  future slice could give salience a single home and hand it to both.
- **Shallow-boundary follow-up:** the belief→bias map is built inline in the
  `Simulation` (`_belief_bias`), whereas the memory bias is hidden behind
  `PreferenceService.biases`. A small `BeliefDecisionService.biases(...)` mirroring
  `PreferenceService` would restore symmetry and depth; deferred (one
  implementation, no variation yet).
- When the predictor is *active* (neural on) the belief bias and the predictor's
  anticipated cost both fire; the shipped config keeps the predictor off, so in
  practice only the belief fires. Composing belief with an active predictor is a
  future consideration.

Supersedes nothing. Extends ADR 0019 (concepts/beliefs), ADR 0014 (outcome
effects / anticipated cost), and the v6 preference bias; obeys ADR 0009/0013's
invariant floor.

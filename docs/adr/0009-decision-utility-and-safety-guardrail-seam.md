# 0009 — Decision (utility) + safety-guardrail seam

## Status

Accepted

## Date

2026-07-10

## Context

Until now the being only *drifted*: needs moved with time (ADR 0001), the
environment moved contextual needs (ADR 0006), and an emotion was derived — but
the being never *did* anything. It perceived objects (ADR 0002) and could not act
on them. The brief calls for a **hybrid decision system** — "rules + utility
scoring + neural prediction + safety guardrails" — that each tick chooses one
action toward an object, and is explicit that **"learned predictions never bypass
safety"** (`docs/BRIEF.md` §12), with a hot object whose touch predicts pain as
the canonical case: safety blocks touch and the being observes / withdraws
instead. The runtime flow (§13) sequences `DecisionService` scoring then
`SafetyService` blocking then action selection, and every meaningful action must
become an `InteractionEvent` carrying expected vs observed outcomes (§9), the
record all learning is later derived from.

This slice (V0-4) adds that action loop. The learned outcome predictor is not yet
in the loop (it runs in shadow mode from V0-9, ADR 0008), so the decision here is
**rules + utility + safety** — the rule layer the net will later imitate and be
compared against.

## Decision

Introduce a **decision seam** and a separate, absolute **safety seam**, and the
two domain records the action loop produces.

- **`DecisionService` scores and chooses; it never overrides safety.** Given the
  being's needs, dominant emotion, perceived objects, and which actions are
  resting on cooldown, it scores every valid `(action, object)` pair by utility
  and returns the best as a `Decision` (`action`, `targetId`, `emotion`,
  `reason`), or `None` when nothing is selectable. It holds no numbers; all
  weights come from config.
- **`SafetyService` is a hard, independent guardrail.** It answers only "is this
  action forbidden on an object with these properties?" and is **injected into**
  `DecisionService`, which drops every blocked candidate *before* ranking. A high
  utility (and, later, a confident learned prediction) therefore can never buy an
  action past a guardrail — the invariant is structural, not a matter of tuning.
  When a would-be top choice was blocked, the chosen action's `reason` says so,
  making the guardrail visible.
- **Config split, decided here: `actions.yaml` for *what/how-much*, `tick_rates.yaml`
  for *timing*.** `config/actions.yaml` holds each action's affordance (or `free`
  for self-directed movement), its utility weights (`base` + per-need
  coefficients + per-emotion bonuses), its outcome rules, and its reason.
  Action **timing** (`duration_ticks`, `cooldown_ticks`) extends
  `config/tick_rates.yaml` under an `actions` block, because that file is the
  single tuning surface for time (BRIEF §10 places action timing there and the
  file reserved the spot). `ConfigService` merges the two into one typed
  `ActionPolicy` — the one place that knows config is split.
- **Cooldown gate = `tick_taken + duration_ticks + cooldown_ticks`.** Both timing
  knobs are used: an action occupies the being for its duration, then rests for
  its cooldown, and is selectable again only past their sum. The being still acts
  every tick — cooldown governs when the *same* action may repeat, so it simply
  picks its next-best action meanwhile.
- **`outcome_labels.yaml` is reused as the outcome vocabulary.** Expected and
  observed outcomes are drawn from the existing V0-8 label set (ADR 0008); an
  action naming an outcome outside it is rejected at load, the same fail-loud
  discipline as the object catalog. The **rule layer** lives on `ActionPolicy`:
  `expected_outcomes` are always anticipated and each `property_outcomes` entry
  adds outcomes when its property is present. `Simulation` computes an
  InteractionEvent's **expected** outcome from the being's *perceived* properties
  and its **observed** outcome from the object's *true* properties — so the two
  diverge exactly where perception is imperfect, which is where the learned
  predictor will earn its keep.
- **Two new domain records.** `Decision` (the being's choice) and
  `InteractionEvent` (`objectId`, `action`, `expectedOutcome`, `observedOutcome`,
  `emotionBefore`/`emotionAfter`). InteractionEvents are produced **in memory
  only**, read via `Simulation.interactions()`; persisting them to Postgres is
  V0-7.
- **`state()` gains `currentAction` (`{type, targetId, reason}`)** when the being
  acted this tick, absent at birth and on idle ticks. The V0-10
  `RenderStateService` already passes unknown/future fields through, so this
  reaches the render frame with **no transport change** (forward-compatible; that
  service is not edited).
- **Self-/world-directed actions only — no caregiver.** The action vocabulary is
  observe / approach / withdraw / touch / grab / push; `free` actions target a
  perceived object (move toward/away), never an external actor. There is no
  caregiver-directed action, consistent with `CONTEXT.md`.

Two new services (not extensions) because "choose the best action" and "is this
action permitted" are distinct responsibilities, and keeping them separate is
precisely what makes the safety invariant enforceable and independently testable
(the deletion test passes: their logic would not vanish, it would tangle inside
`Simulation` and put scoring and safety in one place). No predictor **port** is
introduced — nothing varies across it yet (the learned model arrives in shadow
mode later); the deep-module rule from ADR 0001/0002 holds.

Per the design boundary, a harmful path (a hot surface) has a **visible
consequence** (the action is blocked, with an abstract feeling-level reason) and
a **recovery path** (the being takes a safe action instead) — never any depiction
of harm.

## Consequences

- The being now acts: each tick it takes one scored action toward an object with
  a stated reason, observable through `state()["currentAction"]` and the
  `interactions()` log; the demo shows a curious explorer that turns fearful and
  withdraws when its room darkens.
- Safety is absolute and demonstrated: a tailored test gives `touch` by far the
  highest utility on a hot object and it is still never chosen; the shipped demo
  interacts with a hot lamp many times via safe actions but never touches or
  grabs it.
- Retuning temperament is config-only: the same code, different utility weights,
  makes the being observe vs approach; timing lives in `tick_rates.yaml`, safety
  in `safety_rules.yaml` — proven by tests.
- The state shape grows by an optional `currentAction`; existing consumers are
  unaffected (it is absent until the being acts and flows through the render
  frame with no transport change).
- InteractionEvents exist and carry expected vs observed outcomes, ready for
  V0-7 to persist and V0-9 to compare against the learned predictor. In this
  slice actions do not yet move needs, so `emotionBefore == emotionAfter`; the
  field is captured honestly and will diverge once action effects land.
- New vocabulary: a `hot` property and an `obj_hot_lamp` object were added, plus
  safety rules blocking `touch`/`grab` on `hot`. Adding `hot` extends the ML
  feature vocabulary by one slot; the encoding contract (ADR 0008) absorbs it
  without change (its tests assert membership, not exact size).
- Deferred (documented, not silently dropped): learned prediction into the
  decision (shadow mode, later), action effects on needs/emotion, and
  per-`(action, target)` cooldowns (per-action for now).

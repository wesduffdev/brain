# 0014 — Invariant floor + outcome→state effects: harm is suffered, not blocked

## Status

Accepted

## Date

2026-07-10

## Context

[ADR 0013](0013-reframed-design-boundary.md) reframed the design boundary:
consequences are honest and may be lasting, the being *may* take harmful actions
and suffer for them (that experience is how cause→effect is learned), and the
safety guardrail should narrow from "blocks harmful actions" to a minimal
**invariant floor** that blocks only actions which would break the *simulation
itself*. It left the implementation to ticket **V0-SAFE**.

At the start of this slice the code still embodied the pre-0013 stance:

- `SafetyService` (ADR 0009) hard-blocked `touch`/`grab` on a `hot` object;
  `DecisionService` dropped every blocked candidate before ranking, so the being
  could never touch the hot lamp and could only ever "know" hot = bad from the
  rule we authored — never from experience.
- **Actions had no effect on the being's state.** `Simulation._act` re-derived
  the after-emotion from *unchanged* needs (ADR 0009 deferred this). There was no
  path from an action's outcome to a felt consequence, so nothing negative could
  ever land.

To make cause→effect real we need two things the codebase did not have: harmful
actions must be *allowed* (not blocked), and taking one must *cost* the being
something — abstract internal state, per the design boundary. This is an
interface decision (a new state dimension, a new need-application entry point, a
new config surface, and a narrowed meaning for the safety seam), so it is
recorded here.

## Decision

**1. `SafetyService` becomes a minimal invariant floor (semantic narrowing; no
code/interface change).** Its one method — "is this action forbidden on an object
with these properties?" — is unchanged, and `DecisionService` still drops blocked
candidates before ranking, so no utility (or later, learned) score can buy an
action past it. What narrows is *what belongs in `safety_rules.yaml`*: only
genuinely simulation-breaking actions. Recoverable-but-harmful actions (touching
something hot) are removed from the floor. In v0 there are no simulation-breaking
actions, so **the shipped floor is empty** (`rules: []`) and the being may touch
the hot lamp. The seam is kept deliberately: adding a rule reinstates a hard
block, proven by a test — the invariant/risk split is thus a **config** decision,
not a code one.

**2. An outcome→state-effect path lands the harm as abstract deltas (the new
capability).** An action's **observed outcome** (already computed from the
object's true properties, ADR 0009) now drives a felt consequence on the being's
needs. A new typed policy `OutcomeEffectPolicy` maps each outcome label to per-
need deltas (`config/outcome_effects.yaml`, read only through `ConfigService`).
`NeedService` — the one module that owns how needs change and stay in band — is
**deepened** with `apply_outcomes(needs, outcomes)`: event-driven (not tick-
gated), pure, clamped to each need's own band. `Simulation._act` applies it after
the outcome is known and re-derives the after-emotion from the *changed* needs,
so `emotionBefore`/`emotionAfter` now diverge exactly when an action mattered
(closing the ADR 0009 deferral). No new service: a standalone one would be a
shallow pass-through (the band/clamp logic lives on `NeedService`), failing the
deletion test.

**3. A new `pain` need is the abstract representation of felt harm.** Needs were
hunger/sleep/comfort/warmth/curiosity/safety; **`pain`** is added (0–100, born at
0, `decrease` drift so it decays back toward 0 on its own). A harmful outcome
(`causes_pain`) spikes `pain` upward, lowers `safety` (which reads as `scared`
once it crosses the emotion threshold — this is the "fear" spike) and lowers
`comfort` (distress). Recovery is modeled **only where it plausibly exists**:
acute pain decays over ticks; felt safety is *not* auto-restored, so fear from a
bad experience can linger (no forced recovery — ADR 0013). `trust` is **not**
added: there is no caregiver/other agent in v0 to trust (`CONTEXT.md`), so it has
nothing to attach to yet — deferred, not dropped.

**4. Harm stays abstract and non-instructional (ADR 0013's one line).** Every
consequence is a numeric delta on an internal need and the emotion/behavior that
follows — never a depiction of, or instruction for, harm. `outcome_effects.yaml`
and `safety_rules.yaml` say so and validate their keys against the outcome-label
and object-property vocabularies (fail-loud, like the object catalog).

## Consequences

- The being now **suffers recoverable harm and learns from it**: it touches the
  hot lamp, `pain` spikes, felt `safety` crashes so it reads as `scared`,
  `comfort` drops, and it then keeps its distance — visible in the demo
  (`make demo`, default hot lamp) and pinned by
  `engine/tests/test_harmful_action_consequences.py`.
- The harmful experience flows into the learning record unchanged: the touch's
  observed outcome carries `causes_pain`, which the ADR 0012 wiring encodes into
  a `training_example` — so a later slice can learn `hot → pain` from lived
  experience rather than from an authored rule.
- **Retuning is config-only, proven by tests:** how much an outcome hurts lives
  in `outcome_effects.yaml`; whether an action is on the invariant floor lives in
  `safety_rules.yaml`; the `pain` need's band and decay live in `tick_rates.yaml`.
- State shape grows by one need (`pain`) in `state()["needs"]`; consumers reading
  needs generically are unaffected (subset checks still hold). Needs are not ML
  features, so the ADR 0008 encoding contract is untouched.
- The `emotionBefore`/`emotionAfter` divergence deferred by ADR 0009 is closed;
  `Simulation` now updates the being's dominant emotion to reflect the action it
  just took.
- *Refines* ADR 0009 (the safety seam and decision flow are unchanged; only what
  the floor blocks narrows) and *implements* ADR 0013. A being left in a room
  containing a hot object will now be hurt and turn scared rather than idly grow
  curious — an intended behavior change (see the reworked
  `test_a_left_alone_being_grows_curious`, now isolated in an empty room).
- Deferred (documented, not dropped): a `trust` dimension (needs a caregiver/
  other agent); positive outcome effects (e.g. `pleasant → comfort`, and comfort
  as a second recovery path); a distinct `hurt`/`in-pain` emotion; and — the
  payoff this slice sets up — **learned avoidance** (v3), where the being stops
  re-touching what hurt it instead of only being emotionally deterred.

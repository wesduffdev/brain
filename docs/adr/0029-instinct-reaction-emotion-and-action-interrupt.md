# 0029 — Instinct reaction → emotion bias & safe action interruption (staged, config-gated)

## Status

Accepted. The decision that `EmotionBiasApplied` / `ActionInterrupted` are **transient** and "published straight through, not staged in a persistence unit of work" (Decision steps 1 & 2 and the final Consequence) is **superseded by [ADR 0042](0042-persist-reaction-events-via-transactional-outbox.md)** — those events are now staged through the transactional outbox (ADR 0028) and projected into the idempotent event log. The reaction → emotion/interrupt *behaviour* and the inviolable safety floor below are unchanged.

## Date

2026-07-11

## Context

The event-instinct wave built the instinct layer as a **shadow** (see
[`docs/event_instinct_execution_plan.md`](../event_instinct_execution_plan.md),
cards `NN-STRAT`/`INS-MODEL`/`INS-RT`): `InstinctService` consumes an approach
stimulus, runs the instinct model, selects a protective reaction against config
thresholds/cooldowns, and **publishes** `being.instinct.reactions` — a reaction
`label` (flinch / freeze / orient / withdraw) plus a scalar `reaction_intensity`
in `[0, 1]` — while changing **no** simulation behavior (ADR 0011's shadow
precedent, extended to instinct by [ADR 0026](0026-instinct-neural-model-strategy.md)).

`INS-ACT` is the step where a triggered reaction is finally *allowed to matter*:
it must be able to **bias the being's emotion** and **interrupt the being's
current action**. Two hard constraints frame the decision:

- **The invariant floor is inviolable.** The decision/safety seam
  ([ADR 0009](0009-decision-utility-and-safety-guardrail-seam.md), narrowed by
  [ADR 0014](0014-invariant-floor-and-outcome-state-effects.md)) says no
  utility, no learned prediction — and now no instinct — can buy an action past
  the `SafetyService`. Instinct must *propose*; safety must *dispose*.
- **Emotion is DERIVED, never assigned.** `EmotionService.derive(needs)` is the
  single source of the being's dominant emotion. Instinct is a *reaction*, not an
  emotion, and must not be stored as one; it may only reshape the *inputs* the
  emotion is derived from.

The rollout (queue §"Rollout Strategy", plan §6) further requires that each step
ship as a **config flip whose default is the prior behavior** — shadow → visual
→ active — so no behavior change lands without its own green suite.

## Decision

Add a `ReactionResponseService` (`engine/app/services/reaction_response_service.py`)
— the **active** counterpart to the shadow `InstinctService` — that subscribes to
`being.instinct.reactions` and turns a **triggered** reaction into two staged,
config-gated effects on the being, wired into `Simulation` through the existing
`SafetyService`/emotion-derivation seam. Two flags in the `reaction:` block of
`config/instinct.yaml`, both defaulting to the prior behavior, gate it (read into
a typed `ReactionResponsePolicy` via `ConfigService.reaction_response_policy()`):

1. **`visual_only` (step 1) — emotion bias + render surface, no interruption.**
   - The reaction is exposed in the being's state as a `reaction` field —
     `{type, intensity}` — the render contract `RENDER-RX` consumes.
   - The reaction feeds a **transient affect signal** into the being's
     needs→emotion **derivation**: `bias_needs(needs)` returns a copy of the needs
     overlaid with the label's `emotion_bias` (`label → {need: delta}`, e.g. a
     flinch drops the felt `safety` used for derivation below the `scared`
     threshold). The stored needs are **untouched**; only the derivation input is
     nudged, and the being's *displayed* emotion is re-derived from it — never
     assigned. The emotion fed to the `DecisionService` stays the unbiased one, so
     step 1 leaves the being's **actions** byte-identical (a true "visual only"
     step, mirroring the shadow philosophy: show it, don't let it drive).
   - An `EmotionBiasApplied` event is published on `being.state.events`.

2. **`allow_interrupt` (step 2) — safety-gated cancellation.**
   - A reaction at or above `interrupt.intensity_threshold`, whose label targets an
     action in `interrupt.interruptible_actions`, may **cancel** the current action.
   - The cancellation is **validated through the `SafetyService`**: instinct's
     interruption implies adopting a `protective_action` (default `withdraw`); the
     floor is asked whether that response is permitted on the target's perceived
     properties. If the floor **forbids** it, the interruption is **SUPPRESSED**,
     not forced — the being completes its (floor-permitted) action. The floor is
     never bypassed.
   - When permitted, the current action is cancelled (its outcomes never land) and
     an `ActionInterrupted` event is published on `being.action.events`.

Lifecycle: reactions arrive on the bus **between** ticks; `Simulation.tick()` calls
`begin_tick()` to latch the most recent one as the reaction in effect for that tick,
and a tick with no new reaction clears it — a reaction lingers exactly one tick,
then fades. The service subscribes only when an `event_consumer` is wired into
`Simulation`/`build_simulation`; with **both flags off** it is inert (no bias, no
`reaction` field, no interruption), so the pre-INS-ACT being is byte-identical and
activation is purely a config change.

This **extends** [ADR 0011](0011-prediction-shadow-mode-and-predictor-port.md)'s
shadow→active precedent to the instinct layer, **relates to**
[ADR 0009](0009-decision-utility-and-safety-guardrail-seam.md) /
[ADR 0014](0014-invariant-floor-and-outcome-state-effects.md) (the invariant floor
stays the sole arbiter — instinct only reshapes/interrupts already-safe
candidates), builds on [ADR 0024](0024-event-backbone-and-eventbus-port.md)'s
event backbone and the `being.action.events` / `being.state.events` topic
catalogue, and consumes the reaction contract published under
[ADR 0026](0026-instinct-neural-model-strategy.md).

## Consequences

- **The being finally reacts.** A learned protective reaction can make the being
  read as `scared` and break off a reach — but only within the floor, and only
  when a human flips the config. The staged flags let visual confirmation
  (`RENDER-RX`) ship before any behavior change.
- **The safety floor is provably not bypassed.** Interruption routes through the
  same `SafetyService.block_reason` the decision uses; a floor-forbidden
  protective response yields suppression, covered by a red-first test
  (`test_an_unsafe_interruption_is_suppressed_not_forced`).
- **Emotion stays derived.** The bias is a transient overlay on the derivation
  inputs; the stored needs and the emotion vocabulary are unchanged, and instinct
  is never stored as an emotion. A test pins that the stored `safety` need is
  untouched while the derived emotion flips to `scared`.
- **Byte-identical default.** Both flags default off and the 272 pre-INS-ACT tests
  pass unchanged; a compare-two-beings test pins that a reaction has zero
  observable effect while the flags are off.
- **Runtime wiring is deferred, not free.** End-to-end activation in the running
  app also needs the shadow `InstinctService`'s published reactions routed to the
  `Simulation`'s `event_consumer` (an integration owned by the broker/observability
  work, `EVT-VALID`). Until then the seam is exercised through the bus in tests;
  the config flip alone does not yet make the deployed being react.
- **New `being.*` producers.** `Simulation` now publishes `EmotionBiasApplied`
  (state topic) and `ActionInterrupted` (action topic) as transient runtime
  signals (published straight through, like `ObjectApproached`, not staged in a
  persistence unit of work).

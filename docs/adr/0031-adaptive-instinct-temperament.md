# 0031 — Adaptive instinct temperament: habituation & sensitization of reaction sensitivity

## Status

Accepted

## Date

2026-07-11

## Context

The instinct layer selects a protective reaction when the model's per-label
probability clears a **static** config threshold
([`InstinctRuntimePolicy.thresholds`](../../engine/app/policies.py), gated in
[`instinct_service.py`](../../engine/app/services/instinct_service.py),
[ADR 0026](0026-instinct-neural-model-strategy.md)/[0029](0029-instinct-reaction-emotion-and-action-interrupt.md)).
Those thresholds are the same for every being and never move — so identical stimuli
always provoke the identical reaction, no matter what the being has lived through.
A human-like being does not work that way: a startle it meets again and again with no
harm stops startling it (**habituation**), and a being that has been hurt becomes
jumpier (**sensitization**).

The being already has the two signals this needs. A slow **trait** system
([`TraitService`](../../engine/app/services/trait_service.py),
`config/traits.yaml`, v6) drifts a **caution** tendency up from harmful outcomes and
lets it amplify the being's aversion to bad *memories* in the **deliberate decision**.
And a **`pain`** need ([ADR 0014](0014-invariant-floor-and-outcome-state-effects.md)) spikes when a harmful outcome lands and
decays back toward 0 — the being's felt-harm cue. What was missing is adaptivity in
the **fast, pre-conceptual reaction layer** itself: the reaction *thresholds* were not
personalized.

This is the slice's outcome: make the effective reaction thresholds drift per-being
from experience, so the same stimulus provokes different reactions as the being learns
— habituation and sensitization — while the safety floor is never touched.

## Decision

Introduce a per-being **reaction sensitivity** that adjusts the **effective** instinct
thresholds, and drive it from the being's own harm cue.

1. **`ReactionTemperamentPolicy`** (a new frozen policy in `policies.py`) — the
   config-driven drift model. It holds one effective threshold per label and moves it
   on the **same saturating curve** the v6 trait drift and the ADR 0020 familiarity
   signal use:

   ```
   habituated = t + habituate_rate · (ceiling − t)      # a harmless startle → less reactive
   sensitized = t − sensitize_rate · (t − floor)        # a harmful outcome  → more reactive
   ```

   Both rates default `0.0` (no drift → the static thresholds, byte-identical to the
   pre-slice consumer). `floor`/`ceiling` bound the threshold in **probability space**;
   they are **not** the SafetyService invariant floor. Read from a new
   `reaction.temperament:` block of `config/instinct.yaml` by
   `ConfigService.reaction_temperament_policy()`.

2. **`TemperamentService`** (a new service, the instinct-layer sibling of
   `TraitService`) — holds the effective thresholds, seeded from the runtime baseline.
   - `record_reaction(label)` — a reaction *fired* this tick (a habituation candidate).
   - `settle(harm)` — folds the tick's verdict: **harm** (the being's `pain` rose)
     **sensitizes every** threshold and does *not* habituate that tick (harm takes
     precedence); a **harmless** tick **habituates whatever fired**.
   - `threshold(label)` — the current effective threshold the consumer gates on.

3. **`InstinctService`** consults `temperament.threshold(label)` instead of the raw
   config threshold when a temperament is wired, and reports firings via
   `record_reaction`. Selection is unchanged otherwise; it still never bypasses safety.

4. **`Simulation`** builds the `TemperamentService` alongside the instinct chain
   (only when an instinct predictor is present), injects it into the `InstinctService`,
   and each tick feeds it the harm cue — **the being's existing `pain` need rising**
   (`pain_after > pain_before`), *not* a parallel harm detector. The drifted thresholds
   are exposed via `Simulation.reaction_thresholds()` (kept **off** the `state()`
   snapshot so an un-wired being stays byte-identical).

**Transient in-process.** The drifted thresholds live in the service for the being's
lifetime, not persisted — matching the ADR 0020 familiarity precedent and the v6
traits (the demo shows it with no database).

**Relation to the caution trait (no double-counting).** Instinct sensitization and the
caution trait are **both harm-driven and reinforce** a hurt being's defensiveness, but
they act on **different layers** and touch **different numbers**:

| | Caution trait (v6) | Instinct sensitization (this slice) |
|---|---|---|
| Layer | Deliberate **decision** | Fast pre-conceptual **reaction** |
| Effect | Amplifies aversion to bad **memories** | Lowers the reaction **threshold** |
| Cue | Negative **valence** (net erosion) | Acute **pain** spike |

One harmful experience thus leaves the being both more **cautious in what it chooses**
and **jumpier in what startles it**, through two orthogonal mechanisms — reinforcing,
never the same quantity counted twice. They read complementary facets of the *same*
harmful outcome (valence vs. the acute pain spike).

**Safety floor untouched.** Temperament shifts only reaction **gating** (which reaction
fires). The reaction still only biases emotion and *proposes* an interrupt that the
`SafetyService` validates ([ADR 0029](0029-instinct-reaction-emotion-and-action-interrupt.md));
instinct still cannot buy a blocked action past the floor. `floor`/`ceiling` are
probability bounds, not safety.

## Consequences

- **Identical stimuli now provoke different reactions with experience.** Demonstrated
  torch-free (`python -m app.demo temperament`): a harmless approach (prob 0.70) that
  flinches the being on ticks 1–3 stops firing once its threshold climbs past 0.70
  (habituation); a mild approach (prob 0.45) it first *ignores* starts flinching once
  harm drops its threshold below 0.45 (sensitization).
- **Config-only tuning.** Retuning how fast a being habituates or sensitizes is a
  `config/instinct.yaml` change. Both rates `0` reproduce the static-threshold consumer
  exactly.
- **Byte-identical default preserved.** With no `models/instinct.pt` there is no
  predictor, no chain, no temperament, no drift — the whole prior suite is untouched.
- **Sensitization tracks *new* harm, not standing pain.** The cue is `pain` *rising*;
  a `pain` plateau stops sensitizing (and habituation may resume). This is a faithful
  consequence of using the acute felt-harm signal, and is visible in longer runs.
- Relates to [0026](0026-instinct-neural-model-strategy.md) (the model only predicts;
  selection/thresholds are the consumer's), [0029](0029-instinct-reaction-emotion-and-action-interrupt.md)
  (the reaction seam this personalizes), and the v6 trait drift (`config/traits.yaml`,
  the slow-drift precedent this matches and reinforces).

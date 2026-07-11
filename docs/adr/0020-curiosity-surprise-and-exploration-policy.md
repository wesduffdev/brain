# 0020 — Curiosity, surprise, and exploration policy

## Status

Accepted

## Date

2026-07-10

## Context

Until now the being decided on **utility alone** (ADR 0009), optionally shaded by
the anticipated cost of predicted harm when active prediction is on (ADR 0015). It
treated every object the same: a thing it had handled a hundred times and a thing
it had never seen scored identically if their utility matched. A being that is
"human-like in psychology — needs, emotions, **curiosity**" (project brief) should
instead be drawn to what it cannot yet predict, and lose interest in what it has
mastered.

Card v4 asks for that drive: a config-weighted **curiosity** that rises with an
object's novelty and uncertainty and how recently it *surprised* the being, and
falls with familiarity; a **surprise** signal computed from the gap between the
outcome the being expected and the one it observed; and an **exploration policy**
that lets curiosity shift action selection toward novel/uncertain objects — but
only *within* the safety floor (BRIEF §12: learned/exploration scores never bypass
safety).

Constraints are the established ones: config-driven tuning (no hard-coded weights),
deep modules behind small interfaces, and — critically — the change must be
observable through the **in-memory** demo (`make demo`), which runs with no
database and therefore no persisted concepts. So the curiosity signal cannot
depend on the ADR 0019 persistence stack being wired.

## Decision

**Three deep services behind a coordinating facade, a new `decision_weights`
config section, and one optional curiosity input threaded into the decision.**

Services (`engine/app/services/`):

- **`SurpriseService`** — `surprise(expected, observed)` is the symmetric
  difference of the two outcome sets over their union (Jaccard *distance*), in
  `[0, 1]`: an object that behaves exactly as predicted is unsurprising (0.0),
  computed straight from the `InteractionEvent`'s `expected_outcome` /
  `observed_outcome` (independent of whether the neural predictor recorded a
  prediction). It also owns a **decaying, per-object recent-surprise memory**:
  `record(...)` folds a shock into the object's trace; `recent(object, tick)` reads
  it faded by the config `decay` per tick elapsed.
- **`CuriosityService`** — composes the four config-weighted signals of
  `CuriosityWeights` into one curiosity per object:
  `curiosity = novelty + uncertainty + recent_surprise − familiarity`. It holds a
  per-**property** familiarity level in `[0, 1]` that rises as the being acts on
  objects showing that property (`learn`), on the same saturating curve concept
  confidence uses — so the being **generalizes** (a never-seen object sharing
  properties with handled ones is already partly familiar). `novelty` is the share
  of an object's properties never met; `uncertainty` is how unmastered the met ones
  are; `familiarity` is their mean level (pulls curiosity down).
- **`ExplorationPolicyService`** — the single facade the rest of the being uses for
  "everything exploration". It owns the `CuriosityService` and `SurpriseService`
  and the `ExplorationPolicy` weights, and offers `curiosity_map` / `surprise_map`
  (per perceived object, for the decision and the render frame), `adjustment`
  (the score delta the decision applies), and `observe_interaction` (fold a
  finished interaction's surprise + familiarity back in). Deleting it would scatter
  this orchestration across `Simulation._act` and `DecisionService`.

Signal composition and decay live in typed policies (`app/policies.py`):
`CuriosityWeights`, `SurprisePolicy`, `ExplorationPolicy`, all produced by
`ConfigService` from a new **`decision_weights.yaml`** section.

Decision integration (extends ADR 0009): `DecisionService.decide(...)` gains an
optional `curiosity: Mapping[objectId → float]`; for each **safe** candidate it
adds `ExplorationPolicyService.adjustment(action, curiosity)` —
`action_weight(action) · curiosity_weight · curiosity`. The bonus is applied
**after** the safety block and only to selectable candidates, so a curiosity bonus
can never rescue a blocked action past the floor (mirroring how the ADR 0015
anticipated cost is applied to safe candidates only). Epistemic, low-risk actions
(observe, approach) carry the highest action weight, so curiosity draws the being
to *look before it reaches out*.

**Inert by default.** `ExplorationPolicy.curiosity_weight` defaults to `0.0`, so a
config with no `decision_weights` section (every hand-built `from_dict` test)
yields a zero adjustment for every action — the being decides on pure utility,
byte-identical to the pre-v4 baseline. Only the shipped `decision_weights.yaml`
(and configs that opt in) turn the shift on.

**Curiosity is self-contained, not tied to persisted concepts.** Familiarity lives
in the always-on `CuriosityService`, fed by the being's own interactions, so the
signal works with or without the ADR 0019 persistence stack — the in-memory demo
shows it. Reading persisted concept *confidence* directly (unifying the two
familiarity models) is a possible refinement, deferred.

Wiring (`Simulation`): the exploration stack is **always** constructed (from config
defaults), curiosity/surprise are computed each tick from perception and exposed on
`state()` as `curiosity` / `surprise` maps (they flow onto the render frame
unchanged through `RenderStateService`'s pass-through), and after each action
`observe_interaction` records the surprise and grows familiarity for next tick.

Any neural curiosity predictor stays **shadow only** — none is added in this slice;
the exploration drive is rule/experience-based.

## Consequences

- **The being explores what it cannot predict.** With two objects it cannot both
  master, it alternates between them (demonstrated: `observe round → observe
  square → …` as each becomes familiar) instead of fixating on the tie-break
  winner; with `curiosity_weight` zeroed it fixates. Curiosity/surprise are exposed
  per object on the render frame.
- **Safety is untouched.** The bonus reshuffles only safe candidates; a maximally
  curious hot object is still never touched when a floor rule forbids it (pinned by
  a behavior test), and the existing safety/prediction suite is unchanged.
- **Config-only tuning.** Curiosity weights, surprise decay, and per-action
  exploration weights all live in `decision_weights.yaml`; retuning temperament —
  or turning exploration off — touches no Python (pinned by retuning-is-config-only
  tests). The default-inert weight keeps every prior `from_dict` behavior identical.
- **The demo still teaches cause and effect.** Exploration is active in the shipped
  config, yet the hot-lamp demo still reaches out and is hurt at tick 5 (cooldowns
  force a contact action), so the harm-learning story of ADR 0013/0014 is intact.
- **Deferred.** (1) The anticipated-**discomfort** push in `adjustment` is proven at
  the service level but wired to `0.0` in the decision this slice; feeding it from
  belief-anticipated discomfort is a follow-up (the ADR 0015 predictor already
  penalizes anticipated harm in the decision). (2) Curiosity/surprise are transient
  (in-process), not persisted. (3) Unifying `CuriosityService` familiarity with
  persisted concept confidence.
- **Coupling to watch.** `Simulation._act` gained the curiosity/surprise bookkeeping
  around the decision; it is bounded behind the `ExplorationPolicyService` facade
  rather than scattered, and the deep-module review flagged no new hotspot beyond
  the pre-existing `_act` size noted in ADR 0019.

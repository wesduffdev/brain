# TRAINING — Play Catch (motor-skill learning)

Status: Proposed · Date: 2026-07-11 · Owner: director + orchestrator

This is a **planning document to cut parallel tickets from** (not an ADR, not
code). It covers one training capability — **Play Catch** — as vertical slices
that fit the repo discipline (one-sentence outcome, TDD red-first, config-driven
tuning, deep modules, per-slice deep-module + domain-model gates, ADRs where
warranted). See [`CLAUDE.md`](../CLAUDE.md) and [`docs/BRIEF.md`](BRIEF.md).

> **The reading voicebox moved.** The other training idea — the being reading a
> document aloud, learning from it, and conversing about it with **our own LLM** —
> now has its own plan: [`docs/READING_VOICEBOX.md`](READING_VOICEBOX.md). The two
> are independent and can run as **parallel waves**.

---

## 0. Ground truth (what already exists vs. what is new)

Verified against the current tree so the slices below are honest.

| Thing the plan leans on | State today | Where |
|---|---|---|
| The being knows a **ball** | ✅ exists | `obj_red_ball` — `[round, rubbery, smooth, light, red]`, affordances `[look, touch, push, grab, drop]` (`config/object_properties.yaml`) |
| A **specific form of gravity** | ❌ **not built** — sketched only | BRIEF §9 describes `World.gravity {enabled, direction, strength}`; there is no `world.yaml`, no `velocity`/`motion`/`throw`/`catch` in `config/` or `engine/` |
| **Throw / catch** actions or motion | ❌ not built | affordances are a closed vocabulary; no timed/reactive skill exists |
| The learning loop (`_act()` → decide → perform → learn) | ✅ mature | `engine/app/simulation.py` (`tick()`, `_act()`, one unit-of-work per interaction) |
| Decision seam with `score_bias`, safety-gated | ✅ mature | `DecisionService.decide(...)` — learned pulls compose *after* the safety block |
| Outcome **predictor** pattern (PyTorch, encode → train → shadow → active) | ✅ mature, reusable | `engine/app/ml/` (`OutcomeModel`, `FeatureEncoder`/ADR 0008), `PredictorPort`/`EnsemblePredictor`, shadow (ADR 0011), active blend (ADR 0015) |
| **Scenario + milestone** harness (run N steps, emit a result/curve) | ✅ exists | `services/scenario_runner.py`, `milestone_service.py`, `config/scenarios/*` |
| Competence / trait drift, fear extinction machinery | ✅ exists | `TraitService`, one-shot aversive learning + belief→decision feed (ADR 0023) |

**Two invariants the track must respect (non-negotiable):**

1. **Nothing learned bypasses safety.** Every learned pull (a catch predictor)
   composes in `DecisionService` *after* `SafetyService` gates — the
   `score_bias`/invariant-floor discipline is the load-bearing seam (ADR 0009 /
   0014 / 0015).
2. New capabilities default to a **no-op config weight** so they are opt-in and
   byte-identical to the current baseline until turned on.

---

## 1. Play Catch

### Outcome (north star)

> You throw the ball to the being at a chosen speed under a specific form of
> gravity. It tries to **catch** it and to **throw it back accurately**. Early on
> it mostly fumbles — fast throws worst of all — but as you keep playing, its
> catch and throw success **climb a visible learning curve**, and it begins to
> *anticipate* fast balls (bracing/positioning) instead of being startled.

### Why this is a strong ML-training vehicle

A clean **supervised-learning-from-experience** loop with a **visible,
non-stationary learning curve** — exactly what this project exists to teach. It
reuses the outcome-predictor machinery (encode → train → shadow → active, ADR
0008/0011/0015) but with a twist the static outcome predictor doesn't have: the
training distribution **shifts as competence rises**, so the model must track the
being *getting better*. It also pre-stages the in-flight event-driven / instinct
direction (a thrown ball *is* the `ObjectApproached` stimulus that wave models —
see [§4](#4-relationship-to-the-in-flight-event--instinct-wave)).

### Design (grounded, minimal, honest)

1. **A specific form of gravity — config, not a physics engine.** Introduce
   `config/world.yaml` in the BRIEF §9 shape: `gravity {enabled, direction: down,
   strength}`. "Specific form" = one tunable constant. Gravity + throw speed →
   an **arc + arrival time → a catch window** (how long the ball is catchable).
   Faster throw = shorter window = harder. That is the entire "physics" needed.
2. **Throw as a world event / stimulus.** `throw_ball(speed[, distance])` puts the
   existing `obj_red_ball` **in flight** toward the being. New domain:
   `Throw` / `BallInFlight` (speed, trajectory, catch window) — designed
   **event-bus-ready** so it re-homes cleanly onto the instinct wave later.
3. **Catch is a *timed motor skill*, not a utility-scored action.** When a ball is
   in flight toward it, the being attempts a catch; success is **probabilistic**:
   `P(catch) = sigmoid(k · (catch_competence − difficulty(speed, gravity, distance)))`.
   Randomness lives **behind an injected RNG port** so tests stay deterministic
   (BRIEF: "deterministic unless randomness is injected behind an interface").
4. **Competence rises with practice — the learning curve.** Persisted
   `catch_competence` (and `throw_competence`) climb with attempts (more from
   successes, some from near-misses), with diminishing returns toward a mastery
   ceiling. Config: `practice_gain`, `mastery_ceiling`. Optional refinement:
   speed-banded competence so the being masters slow throws before fast ones and
   generalizes upward. Start scalar; add bands later.
5. **Throw-back accuracy + a rally.** The being throws the ball back;
   `throw_competence` sets `P(good throw)` (on-target). A "game of catch" is an
   alternating exchange; **rally length** is a delightful observable.
6. **Felt consequences + fear that extinguishes.** Good catch → `happy`/`excited`,
   competence + confidence up (reuse `NeedService.apply_outcomes`, ADR 0014). Drop
   → mild `frustrated`. A too-fast unexpected throw → `scared`/startle (this is the
   flinch idea). Over practice, **fear of fast balls extinguishes** as competence
   rises — reuse the trait-drift / aversive machinery already present (ADR 0023,
   `TraitService`).
7. **The model (teaching core).** `CatchPredictor` (tiny PyTorch, like
   `OutcomeModel`): features `[speed, gravity/arc, distance, catch_competence,
   focus, surprise, …]` → `P(catch)` (optionally `P(flinch)`, `P(good_throw)`).
   Trains on the being's **own accumulating** `catch_training_examples`. **Shadow
   first** (ADR 0011) → **active** (ADR 0015): predict "can I catch this?" → the
   being decides **attempt-catch vs. brace/flinch vs. let-it-bounce**. Genuine
   learning because the data is non-stationary.
8. **Decision integration via the existing seam.** Catch/brace/dodge candidates are
   scored in `DecisionService.decide(...)` with the predictor blended into
   `score_bias`; `SafetyService` still gates. Nothing new bypasses safety.
9. **Practice harness = the scenario runner.** Reuse `scenario_runner` +
   `milestone_service` (v10): a `catch_practice` scenario runs N throws at mixed
   speeds and emits a **success-rate-vs-throw curve** — the headline observable —
   plus a **regression scenario** guarding that the curve still climbs.

### Slices → tickets

| # | Slice (outcome) | New/changed seams | Observable | ADR? | Parallel |
|---|---|---|---|---|---|
| **B1** | **World gravity + throw kinematics** — a throw at speed S under gravity yields a catch window/difficulty | `config/world.yaml` (gravity), `domain/throw.py` (`Throw`/`BallInFlight`), minimal kinematics | test: faster S ⇒ shorter window / higher difficulty; gravity strength changes the arc | **Yes** — "World gravity + throw kinematics (a specific form of gravity)" | independent |
| **B2** | **Catch attempt + probabilistic outcome** — a single throw resolves to catch/drop with emotion | catch resolution + **RNG port**; emits an `InteractionEvent` → normal learning loop + felt consequence | test: low competence + fast ⇒ mostly drops; high + slow ⇒ mostly catches | maybe (folds into B1) | after B1 |
| **B3** | **Catch competence rises with practice (the learning curve)** ⭐ | persisted `catch_competence` (`motor_skill` store or reuse traits), config `practice_gain`, `mastery_ceiling` | **test: after N practice throws, success at a fixed speed is measurably higher than at the start** | **Yes** — motor-skill competence curve | after B2 |
| **B4** | **Throw-back accuracy + a rally** — the being throws back; rally length observable | `throw_competence`, `P(good_throw)`, exchange loop | test: throw accuracy climbs with practice; rallies lengthen | fold into B3's ADR | after B2 |
| **B5** | **CatchPredictor (PyTorch) in shadow mode** — predicts P(catch) beside actual | `ml/catch_model.py`, `ml/train_catch_model.py` (reuse ADR 0008 encoder + ml-trainer pattern), `catch_training_examples`, records predicted-vs-actual (ADR 0011) | `make train-catch` → model + metrics; shadow records accumulate | reuse 0008/0011 (note only) | after B2 (data), parallel with B3/B4 |
| **B6** | **Active catch prediction feeds the decision** — attempt vs. brace vs. dodge | blend predictor into `DecisionService` via `score_bias` (ADR 0015); safety gates | test: with the model on, the being stops attempting hopeless catches and braces on very fast throws | reuse 0015 (note) | after B5 |
| **B7** | **Fear of fast balls extinguishes with mastery** — startle on fast throws fades as skill grows | tie startle/fear to competence via `TraitService`/aversive path (ADR 0023) | test: fear response to a fixed fast speed declines across sessions | reuse 0023 (note) | after B3 |
| **B8** | **Catch-practice scenario + learning-curve milestone/regression** — a session prints a rising curve | reuse `scenario_runner`, `milestone_service`, `config/scenarios/catch_practice.yaml` | `make scenario catch_practice` prints success-rate-vs-throw; milestone "reliably catches a slow throw" fires; regression guards the curve | — | after B3 (B6 optional) |

**First-playable path:** **B1 → B2 → B3** = throw the ball, catch/drop, and *watch
the success rate climb*. That alone delivers the north star's core.

### Dependency sketch

```
B1 ─ B2 ─┬─ B3 ─┬─ B8
         │      └─ B7
         └─ B5 ─ B6
         └─ B4
```

---

## 2. Cross-cutting requirements

- **TDD red-first**, behavior-driven through the public surface (`Simulation` and
  the endpoints), named for behavior — e.g.
  `test_fast_throw_is_dropped_before_practice`,
  `test_catch_success_climbs_with_practice`.
- **Config-driven tuning**, no-op defaults: `config/world.yaml` and new keys in
  `learning_rates.yaml` / `traits.yaml` — all default to the current byte-identical
  baseline until turned on. Only `ConfigService` reads config.
- **Deep modules:** deepen `DecisionService` and reuse `scenario_runner` rather
  than sprawl new shallow services. Run `/legacy-deep-module-review` after each
  slice (per-slice gate) and update root `CONTEXT.md` glossary (add: *throw*,
  *catch window*, *catch competence*, *rally*).
- **Persistence** stays transactional (one unit of work per interaction, ADR 0017);
  new tables (`motor_skill`, `catch_training_examples`) stage in repos, commit with
  the interaction.
- **Auth** applies to every new endpoint (always-on JWT, ADR 0005).
- **Design boundary** (ADR 0013) unchanged — harm stays abstract internal state.

---

## 3. New ADRs to author (assign the next free `NNNN` at authoring time)

Only where the 3-part test holds (hard to reverse · surprising without context · a
real trade-off). Current highest ADR is 0023, so these take **0024+**.

- **World gravity + throw kinematics** (B1) — a config-driven "specific form of
  gravity" and the catch-window model.
- **Motor-skill competence + learning curve** (B3) — persisted competence, the
  practice curve, the RNG seam.
- The predictor (B5/B6) **reuses** ADR 0008/0011/0015 — note the reuse in those
  slices; no new ADR unless the encoding contract changes.

Update the ADR index (`docs/adr/README.md`), the roadmap, and the governance index
in `README.md` in the same slices that introduce these, per CLAUDE.md.

---

## 4. Relationship to the in-flight event / instinct wave

`docs/queue.md` captures an in-flight (unmerged) direction: an **event-driven
(Kafka) architecture + an "instinct" neural network** (flinch/freeze/orient on
`ObjectApproached`-style stimuli), running on **events instead of ticks**. Play
Catch overlaps that conceptually — **a thrown ball is exactly an approaching-object
stimulus**, and "brace/flinch vs. catch" is an instinct-vs-decision arbitration.

Guidance to avoid rework:
- Build B1/B2 on the **current tick loop now** (it is on `main`; the event wave is
  not), but shape `Throw`/`BallInFlight` as a **stimulus with speed/trajectory** so
  it maps onto `ObjectApproached` when that wave lands.
- Keep catch's decision integration on the existing `score_bias`/safety seam; if
  the instinct layer merges, "flinch on a very fast throw" becomes an instinct
  reaction that the catch decision defers to — a clean later integration, not a
  rewrite.

---

## 5. Open questions for the director

1. **Priority.** Run Play Catch first, in parallel with the reading voicebox, or
   after it?
2. **Catch generality.** Scalar competence to start, or speed-banded from the
   outset (masters slow before fast)?
3. **Cut cards?** Want the orchestrator to mint the Trello cards for B1→B3 next
   (intake gate), or keep planning first?

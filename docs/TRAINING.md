# TRAINING — two ways to train the being

Status: Proposed · Date: 2026-07-11 · Owner: director + orchestrator

This is a **planning document to cut parallel tickets from**, not an ADR and not
code. It defines two independent "training" capabilities the director asked for,
each as a set of vertical slices that fit this repo's discipline (one-sentence
outcome, TDD red-first, config-driven tuning, deep modules, per-slice
deep-module + domain-model gates, ADRs where warranted). See
[`CLAUDE.md`](../CLAUDE.md) for how work is done here and
[`docs/BRIEF.md`](BRIEF.md) for the target architecture.

The two tracks are:

- **Track A — Voicebox / Read-Aloud.** The being gets a *voice* (an open-source
  text-to-speech "voicebox"). You hand it a short document crafted for speech and
  it reads the document **aloud back to you**, and *how* it reads reflects its
  internal state and a fluency that improves with practice.
- **Track B — Play Catch.** You throw the ball to the being at a chosen speed
  under a specific form of gravity. It tries to **catch** (and throw back). At
  first it mostly fumbles — fast throws especially — but with **practice the
  success rate climbs a visible learning curve** and it starts anticipating fast
  balls instead of being surprised.

They are independent and can run as parallel waves. A short **"which first"**
recommendation is in [§4](#4-sequencing-how-the-tracks-relate-and-a-recommendation).

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
| **Language layer** (state → prose) | ⚠️ exists but **unwired to any surface** | `NarrationService`, `MemorySummaryService`, `LanguageCommandService`, `LanguageModelPort`, `ClaudeLanguageModel` — constructed only in tests; ADR 0022 explicitly defers the HTTP wiring |
| **Voice / TTS / audio** | ❌ nothing anywhere | new port + adapter |

**Two invariants both tracks must respect (non-negotiable):**

1. **Language and voice sit *on top* and never control the sim** (BRIEF rule #6,
   ADR 0022). The voicebox is *output*; if a read document is ever meant to
   *change* the being, it enters through the validated perception/command door,
   never through the language model.
2. **Nothing learned bypasses safety.** Every learned pull (a catch predictor, a
   fluency bias) composes in `DecisionService` *after* `SafetyService` gates — the
   `score_bias`/invariant-floor discipline is the load-bearing seam (ADR 0009 /
   0014 / 0015). New capabilities default to a **no-op config weight** so they are
   opt-in and byte-identical to the current baseline until turned on.

---

## 1. Track A — Voicebox / Read-Aloud

### Outcome (north star)

> You hand the being a short text document; it reads the document **aloud** in a
> synthesized voice, and how it reads (pace, steadiness, warmth, disfluency)
> reflects its dominant emotion and a **reading fluency that improves the more it
> practices** — a first read of a new passage is halting; a well-practiced one is
> smooth.

### Honest framing

TTS is deterministic — it does not "learn to speak." So Track A is primarily an
**expressive I/O capability** (the being gains a voice and can vocalize its state
and read text back), with a **modest learning curve** layered on: a *reading
fluency competence* that rises with practice and shapes delivery. If the
director's priority is heavier ML training, Track B is the meatier vehicle; if the
priority is a felt, interactive being, the voicebox is the higher-wow, and the two
compose (eventually the being can *say* "got it!" when it catches a ball).

### Open-source TTS recommendation

The voicebox lives behind a **`VoicePort`** so the engine never imports a TTS
library directly and we can swap engines by config (same shape as `PredictorPort`
with its rule-based baseline + neural implementation).

| Engine | Why | Role |
|---|---|---|
| **espeak-ng** | tiny, fully offline, zero model download, robotic | **always-available default / test fallback** (like `RuleBasedPredictor`); thematically fits a being *learning* to speak |
| **Piper** (`rhasspy/piper`) | fast, offline, neural, ONNX, CPU-friendly, MIT, packaged voice models | **recommended primary voice**; runs great as a Docker **sidecar** (mirrors `ml-trainer`/`requirements-train.txt` — keep heavy deps off the lean engine image) |
| **Kokoro** (82M, Apache) / **Coqui TTS** | higher quality, more voices, heavier | optional upgrade behind the same port |

Recommendation: ship **espeak-ng first** (guaranteed to run anywhere, deterministic
tests), then **Piper** as the real voice in a `voice` sidecar. A nice optional arc
ties voice quality to development (v10): the being "graduates" espeak → Piper as a
milestone.

### Delivery reflects state + fluency (the learning angle)

A `VoiceService` computes **voice params** (rate, pitch, pause length, clarity)
from two inputs:
- **Dominant emotion** (reuse the existing state): `scared` → faster/higher/clipped;
  `calm` → measured; `comforted` → warm/slow; `frustrated` → terse. This reuses the
  render-hints idea (ADR 0004) but for audio.
- **Reading fluency competence** (new, persisted): first read of a document is
  halting (slower, more pauses, lower clarity); repeated reads smooth out. Rises
  with practice on a config-driven curve. This is the felt "training."

### Document format ("crafted to work well for TTS")

Define a small **Reading Document** spec (the artifact you hand the being):

- Plain UTF-8 text or lightweight Markdown; **short declarative sentences**;
  explicit punctuation for prosody.
- Optional front-matter: `title`, intended `context`/`emotion`.
- Optional **SSML-lite** hints later (`[pause]`, phoneme/pronunciation overrides)
  that map onto the chosen engine's controls.
- v1 is deliberately minimal (plain sentences); the parser splits into ordered
  **utterance units**. Ship an example doc under `docs/reading/`.

### Slices → tickets (Track A)

Each is a card: one-sentence outcome, acceptance criteria, affected files/ADRs.
Parallelism noted.

| # | Slice (outcome) | New/changed seams | Observable | ADR? | Parallel |
|---|---|---|---|---|---|
| **A1** | **VoicePort + espeak-ng adapter** — the being can synthesize an utterance to audio | `ports/voice.py` (`VoicePort.synthesize`), `adapters/espeak_voice.py`, `FakeVoice` in tests; graceful no-op when the binary is absent (like `load_predictor`) | `make speak TEXT="hello"` writes a `.wav` | **Yes** — "Voice synthesis port + open-source TTS adapter" | independent |
| **A2** | **Reading Document format + parser** — a doc parses into ordered utterance units | `domain/reading_document.py`, `config/voice.yaml`, example `docs/reading/hello.md` | parse example doc → N utterance units in order | maybe (folds into A3) | after A1 spec agreed |
| **A3** | **VoiceService.read_aloud(document, snapshot)** — maps doc + emotion → voiced units; **wires the v9 language layer into `create_app`** (ADR 0022 follow-up) | deepen `NarrationService` or add `VoiceService`; construct it in `bootstrap.py`/`main.py` | test: `scared` state yields faster/higher params than `calm`; end-to-end a doc is voiced | update ADR 0022 (surface wiring) | after A1, A2 |
| **A4** | **Reading fluency competence (the learning curve)** — repeated reads get smoother | persisted `reading_competence` (new table/store), config `fluency_gain`, ceiling | test: re-reading the same doc measurably raises fluency / cuts pause count | small ADR if a new table/seam | after A3 |
| **A5** | **Piper adapter + `voice` sidecar** — a real neural voice, swapped by config, no engine code change | `adapters/piper_voice.py`, `requirements-voice.txt`, `docker-compose` `voice` service | `make up` includes voice; `/read` returns Piper audio | note in A1's ADR | after A1 |
| **A6** | **HTTP + renderer surface** — hand a doc via the UI, hear it read | `POST /read` (+ `/speak`), JWT-protected (ADR 0005); renderer plays audio + "speaking" pose/mouth | end-to-end: UI → audio out | — | after A3, A5 |
| **A7** *(later)* | **Reading comprehension → memory/concepts** — the document *changes* the being, via the **validated perception/command door, not the LLM** | route read passages through `PerceptionService`/`ActionValidationService` into the normal `_act()` learning loop | test: after reading, a memory/concept exists | **Yes** — comprehension-as-perception (keeps language non-authoritative) | after A3 |
| **A8** *(optional)* | **Voice development milestone** — espeak → Piper "graduation" tied to v10 progression | reuse `milestone_service` | milestone fires; voice upgrades | — | after A5 + v10 |

---

## 2. Track B — Play Catch

### Outcome (north star)

> You throw the ball to the being at a chosen speed under a specific form of
> gravity. It tries to **catch** it and to **throw it back accurately**. Early on
> it mostly fumbles — fast throws worst of all — but as you keep playing, its
> catch and throw success **climb a visible learning curve**, and it begins to
> *anticipate* fast balls (bracing/positioning) instead of being startled.

### Why this is the stronger ML-training vehicle

Track B is a clean **supervised-learning-from-experience** loop with a **visible,
non-stationary learning curve** — exactly what this project exists to teach. It
reuses the outcome-predictor machinery (encode → train → shadow → active, ADR
0008/0011/0015) but with a twist that the static outcome predictor doesn't have:
the training distribution **shifts as competence rises**, so the model must track
the being *getting better*. It also pre-stages the in-flight event-driven /
instinct direction (a thrown ball *is* the `ObjectApproached` stimulus that wave
models — see [§5](#5-relationship-to-the-in-flight-event--instinct-wave)).

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

### Slices → tickets (Track B)

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

---

## 3. Cross-cutting requirements (both tracks)

- **TDD red-first**, behavior-driven through the public surface (`Simulation` and
  the endpoints), named for behavior — e.g. `test_repeated_reads_grow_fluency`,
  `test_fast_throw_is_dropped_before_practice`,
  `test_catch_success_climbs_with_practice`.
- **Config-driven tuning**, no-op defaults: `config/voice.yaml`,
  `config/world.yaml`, and new keys in `learning_rates.yaml` /`traits.yaml` — all
  default to the current byte-identical baseline until turned on. Only
  `ConfigService` reads config.
- **Deep modules:** deepen `NarrationService` (Track A) and `DecisionService` +
  reuse `scenario_runner` (Track B) rather than sprawl new shallow services. Run
  `/legacy-deep-module-review` after each slice (per-slice gate) and update root
  `CONTEXT.md` glossary (add: *voicebox*, *utterance*, *reading fluency*, *throw*,
  *catch window*, *catch competence*, *rally*).
- **Persistence** stays transactional (one unit of work per interaction, ADR 0017);
  new tables (`reading_sessions`/`reading_competence`, `motor_skill`,
  `catch_training_examples`) stage in repos, commit with the interaction.
- **Auth** applies to every new endpoint (always-on JWT, ADR 0005).
- **Design boundary** (ADR 0013) unchanged — harm stays abstract internal state.

---

## 4. Sequencing: how the tracks relate, and a recommendation

- The tracks are **independent** — different files, different seams — so they can
  run as **parallel waves** (`wave/<n>` per the CLAUDE.md wave discipline), each
  slice in its own worktree.
- **Recommendation: start Track B (Play Catch).** It is the stronger answer to
  "we need more training": a real learn-from-experience loop with a visible
  learning curve, it reuses the ML machinery already in the repo, and it
  pre-stages the event/instinct direction the project is already moving toward.
  Track A (Voicebox) is a great parallel capability that gives the being a voice
  and a modest fluency curve — schedule it alongside if there's bandwidth, or as
  the next wave. They **compose** at the end: the being can *speak* its catch
  outcomes.
- **Minimal first-playable per track** (thin vertical slice to feel it working):
  - Track B: **B1 → B2 → B3** = throw the ball, catch/drop, and *watch the success
    rate climb*. That alone delivers the north star's core.
  - Track A: **A1 → A3** (with espeak) = hand a short doc, hear it read in a
    state-colored voice. A4 adds the fluency curve.

### Dependency sketch

```
Track A:  A1 ─┬─ A2 ─ A3 ─┬─ A4
              │           └─ A6 (needs A5)
              └─ A5 ───────┘         A7 (later)   A8 (optional)

Track B:  B1 ─ B2 ─┬─ B3 ─┬─ B8
                   │      └─ B7
                   └─ B5 ─ B6
                   └─ B4
```

---

## 5. Relationship to the in-flight event / instinct wave

`docs/queue.md` captures an in-flight (unmerged) direction: an **event-driven
(Kafka) architecture + an "instinct" neural network** (flinch/freeze/orient on
`ObjectApproached`-style stimuli), running on **events instead of ticks**. Track B
overlaps that conceptually — **a thrown ball is exactly an approaching-object
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

## 6. New ADRs to author (assign the next free `NNNN` at authoring time)

Only where the 3-part test holds (hard to reverse · surprising without context · a
real trade-off). Current highest ADR is 0023, so these take **0024+**.

- **Voice synthesis port + open-source TTS adapter** (Track A / A1) — introduces
  `VoicePort` and the espeak/Piper choice; the voice is output-only and
  non-authoritative (extends ADR 0022's "language on top").
- **Comprehension-as-perception** (Track A / A7, if built) — a read document
  changes the being only through the validated perception/command door.
- **World gravity + throw kinematics** (Track B / B1) — a config-driven "specific
  form of gravity" and the catch-window model.
- **Motor-skill competence + learning curve** (Track B / B3) — persisted
  competence, the practice curve, the RNG seam.
- Track B's predictor (B5/B6) **reuses** ADR 0008/0011/0015 — note the reuse in
  those slices; no new ADR unless the encoding contract changes.

Update the ADR index (`docs/adr/README.md`), the roadmap, and the governance index
in `README.md` in the same slices that introduce these, per CLAUDE.md.

---

## 7. Open questions for the director

1. **Priority / order.** Start with **Track B (Catch)** as recommended, Track A
   (Voicebox) in parallel, or a specific one first?
2. **Voice engine.** OK to ship **espeak-ng** first (guaranteed, robotic) and add
   **Piper** as the real voice in a sidecar — or go straight to Piper/Kokoro?
3. **Read fidelity.** Should the being read the document **faithfully** (verbatim,
   state-colored delivery), or is a **paraphrased/expressive** narration of it
   acceptable (uses the LLM more)? Faithful keeps language most clearly "on top."
4. **Does a read document change the being?** Is A7 (comprehension → memory/
   concepts) in scope, or is read-aloud purely output for now?
5. **Catch generality.** Scalar competence to start, or speed-banded from the
   outset (masters slow before fast)?
6. **These become cards.** Want the orchestrator to mint the Trello cards for the
   chosen slices next (intake gate), or keep planning first?

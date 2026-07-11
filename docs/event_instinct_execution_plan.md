# Event Backbone + Instinct — parallel-ticket wave plan

**Purpose.** Turn the raw augmentation source ([`docs/queue.md`](queue.md)) into a
set of **parallel, dependency-sequenced tickets** that add two capabilities to the
being: an **event backbone** (Kafka, behind a port) and a **new instinct neural
network** (fast, pre-conceptual protective reactions). Same fleet model as the v0
and post-v0 plans: an orchestrator sources cards and sequences them; sub-agents
each land one vertical slice in its own worktree and report completion.

This file follows the house pattern — it **reconciles the source against the repo
as it actually is today**, then cuts card→slice tickets. It does **not** restate
`queue.md`'s Kafka topic catalogue, event-envelope fields, or table sketches — it
links to them and adds only ticketing, sequencing, grounded file references, and
the adjustments needed to fit this repo's rules.

- Raw augmentation source (the design conversation that produced this):
  [`docs/queue.md`](queue.md). Treat it as a **source/archive**, not a spec — its
  first half is image-generation chat and it embeds the same plan twice; only the
  "NPC Brain Augmentation Plan" body is forward-looking, and its `npc.*`/`shell_001`
  naming is corrected to the repo's domain language here (**being**, not npc).
- How work is done here (slice discipline, TDD, board + worktree/PR guardrails):
  [`CLAUDE.md`](../CLAUDE.md). Decisions: [`docs/adr/`](adr/).
- Ordered roadmap (single source of truth): [`README.md`](../README.md); canonical
  `v1…v14` scheme in [ADR 0018](adr/0018-canonical-v1-v14-roadmap.md). This
  augmentation attaches to the **v8** (model-service / multi-model inference) and
  **v14** (production runtime split / observability) roadmap slots.
- The model this mirrors: [`docs/post_v0_execution_plan.md`](post_v0_execution_plan.md).

> **Snapshot date: 2026-07-11.** Board = intent, repo = truth. Re-read the board
> and re-plan each wave before dispatching — the wave table below is a
> point-in-time sequencing, not a standing instruction.

---

## 1. Reconciliation — the source vs. the repo

`queue.md` assumes an event-driven system that can be "augmented." **The repo is not
that system yet.** It is a single-writer, synchronous, in-process tick loop with no
messaging of any kind. So most of this augmentation is **greenfield seam work**, not
a refactor of existing plumbing. The map below is what a sub-agent will actually find.

### 1.1 What the repo has today (2026-07-11)

- **Tick model — one synchronous loop, no bus, no scheduler.** `TickService`
  (`engine/app/services/tick_service.py`) is a bare integer counter (`current_tick`
  + `advance()`). `Simulation.tick()` (`engine/app/simulation.py`) runs, in order:
  `clock.advance()` → need **drift** → environment → **emotion re-derived** (emotion
  is stateless-derived from needs; nothing "decays" except the `pain` need) →
  `_act()` → `state()`. `_act()` is the cognitive pipeline (perceive → curiosity/
  surprise → decide → apply outcome → re-derive emotion → build `InteractionEvent`
  → **one unit of work** persists event/example/prediction/memory/concepts/… →
  cooldown → observe). **There is no producer/consumer to extend.**
- **Perception is static.** `PerceptionService` (ADR 0002) returns
  `{objects:[{objectId, confidence, properties, affordances}]}` for one room; confidence
  is uniform and **there is no motion, velocity, trajectory, or stimulus/perception-frame
  type**. Objects live in `config/{rooms,object_properties,environment}.yaml`.
- **The existing NN is an outcome predictor, not an instinct model.** PyTorch
  `OutcomeModel` (`engine/app/ml/outcome_model.py`): multi-hot `property+action+context`
  → sigmoid multi-label `outcome_labels`. Trained by `train_outcome_model.py`
  (artifact `models/outcome_predictor.pt`), served behind `PredictorPort`
  (`engine/app/ports/predictor.py`) in **shadow** (ADR 0011) or **active blended**
  (ADR 0015, `EnsemblePredictor`) mode. Safety gates every candidate regardless.
- **Renderer — PixiJS 8 over WebSocket, static draw hints only.** Consumes the ADR 0004
  `being_state_update` frame; `RenderState.ts` **ignores unknown fields** (forward-
  compatible). Emotion→`visual` mapping is a config lookup (`config/render_hints.yaml`);
  `pose`/`action` are declared but always null. **No animation/timeline system.**
- **Persistence — 13 tables, strict unit-of-work, no event log.** `engine/app/db/models.py`;
  repository ports (`engine/app/ports/repositories.py`) are append-only `add()/all()`
  or `get()/save()`; `UnitOfWork` (ADR 0017) — repos stage, the caller commits one
  transaction per logical op. **No `event_log`/outbox table exists.**
- **Infra — no broker anywhere.** `docker-compose.yml`: `engine`, `postgres`,
  `renderer`, `ml-trainer` (profile-gated). Grep found **zero** Kafka/Redis/NATS/AMQP
  references. `engine/requirements.txt` has no messaging deps.
- **Config — one reader, typed policies.** `ConfigService` (`engine/app/config_service.py`)
  is the only code that knows YAML exists; services get dataclass policies from
  `engine/app/policies.py`. Adding a config section is a three-spot change. **Secrets
  and connection strings are env-only** (ADR 0005/0022) — so **Kafka broker URL →
  env; topic names / thresholds / enable-flags → config YAML + a typed policy.**

### 1.2 Adjustments folded into this plan (decisions, vetoable)

The source is sound in shape; these five changes fit it to the repo's own rules.
Each is called out again in the affected ticket.

1. **Kafka runs behind an `EventBus` port, not bound into the sim.** You chose Kafka
   over an in-process bus ("use Kafka and not a bus… best solution, no low-key
   first"). Honored. But two hard repo rules force a seam anyway: the suite must
   stay **hermetic** (`pytest` cannot require a live broker), and a port with a
   real second implementation (a test fake) is a *justified* seam, not a speculative
   one. So: `EventPublisher`/`EventConsumer` ports with an **in-memory fake** as the
   default test impl and **Kafka as the runtime impl** — exactly how `[postgres]`
   integration tests are gated apart from the fast suite. This also keeps the
   broker choice low-regret (see Open Questions on single-being scale).
2. **A motion/approach stimulus layer is a prerequisite, not a footnote.** The
   instinct model's features (velocity, trajectory-toward-body, time-to-contact,
   size-change-rate) have **no source in today's static world**. `WORLD-MOTION`
   below builds it; without it the instinct NN has nothing to consume.
3. **The tick→event refactor stays narrow.** `TICK-INV` is **classify-only**; wave 1
   migrates *only* the perception→instinct→reaction→render path. Need-drift and
   emotion re-derivation stay on the tick (classified "scheduled/keep") until later.
4. **Instinct routes through the existing safety/decision seam.** Learned scores
   never bypass `SafetyService` (ADR 0009/0014). Instinct reactions reshape/interrupt
   only already-safe candidates and bias emotion through the existing `EmotionService`
   derivation — no second, parallel gate.
5. **Atomic publish = transactional outbox.** Kafka+Postgres dual-write is solved by
   staging an outbox row in the *same* `uow.begin()` (ADR 0017 fits this exactly); a
   relay publishes to Kafka. Domain code never publishes inside the DB transaction.

Plus: **domain naming** — topics are `being.*`, ids are `being_001`, not `npc.*`/
`shell_001` (matches `CONTEXT.md`); **render reactions ship as hints** in
`render_hints.yaml`, not a new animation engine.

---

## 2. Standing constraints

Every ticket inherits the v0/post-v0 constraints verbatim (see
[`post_v0_execution_plan.md` §3](post_v0_execution_plan.md)): vertical slice →
observable outcome; **TDD red-first through the public surface**; config-driven
tuning; deep modules / no port until something varies; safety floor inviolable; ADR
in the same slice; deep-module-review + domain-model (`CONTEXT.md`) gates per slice.

This augmentation adds:

- **Messaging behind a port; the suite stays hermetic.** No ticket may make the
  default `pytest` run require a live Kafka broker. Kafka-touching tests carry a
  `[kafka]` marker and run separately (mirror the `[postgres]` split).
- **Instinct is a fast reaction, not an emotion or a decision.** It sits between
  perception and decision, biases emotion and *proposes* interruption; it never
  becomes a mood or bypasses safety.
- **Shadow-first for every new inference path.** Instinct ships in shadow (record
  only), then visual-only, then controlled interruption — each step a config flip
  with byte-identical prior behavior as the default (the ADR 0011 precedent).
- **Broker URL/credentials → env; everything tunable → config + typed policy.**

---

## 3. The tickets (→ Trello cards)

Copy-paste-ready card bodies carrying the `CLAUDE.md` card→slice contract. IDs use
`EVT-*` (event backbone / infra) and `INS-*` (instinct), plus the world prerequisite.
Each maps to a `queue.md` workstream (A–J) — noted in *Source*. Waves are
**indicative**; re-plan from the then-current board each time.

---

### Wave E1 — Foundation & decisions (4 parallel, no code interdependencies)

#### `EVT-BUS` — Event envelope + EventBus port + in-memory fake

- **Epic:** Infra · **Size:** M · **Depends on:** — · **Parallel-safe with:** all of E1 · **Wave E1**
- **Source:** queue Workstream B (+ the seam half of A).
- **Outcome:** Domain code can **publish and subscribe to versioned domain events**
  through a port, with an in-memory fake so the whole suite runs with no broker — a
  visible `being.*` event flows end-to-end in a test.
- **Acceptance criteria:**
  - `DomainEvent` envelope type (`event_id, event_type, event_version, occurred_at,
    produced_at, source_service, being_id, correlation_id, causation_id, payload`)
    with JSON-schema validation; `EventPublisher` / `EventConsumer` Protocol ports in
    `engine/app/ports/events.py`; an `InMemoryEventBus` fake in
    `engine/app/adapters/` used by tests.
  - Behavior tests (red first): publishing an event delivers it to a subscribed
    consumer; `correlation_id`/`causation_id` chain is preserved across a two-hop
    publish; an unknown/invalid envelope is rejected loudly.
  - **ADR 0024** records the event-backbone seam (envelope + port + fake default +
    Kafka runtime to follow); no broker required to run `pytest`.
- **Guardrails:** naming is `being.*` (not `npc.*`); the port is the only surface the
  sim binds to — no Kafka symbols above it.
- **Files/refs:** `engine/app/ports/events.py`, `engine/app/domain/event.py`,
  `engine/app/adapters/in_memory_event_bus.py`, `docs/adr/0024-*`, queue §"Event
  Schema Requirements".
- **Plan:** `docs/event_instinct_execution_plan.md` (EVT-BUS)

#### `EVT-KAFKA` — Kafka runtime impl + Compose + topics + DLQ

- **Epic:** Infra · **Size:** M · **Depends on:** `EVT-BUS` (port to implement) · **Parallel-safe with:** `TICK-INV`, `NN-STRAT` (Compose/infra half can scaffold before EVT-BUS lands) · **Wave E1→E2**
- **Source:** queue Workstream A / Epic 1.
- **Outcome:** The `EventBus` port has a **Kafka implementation** and the local stack
  brings up a broker + topics with one command; the same code paths run on the fake
  (tests) or Kafka (runtime).
- **Acceptance criteria:**
  - Kafka (KRaft, single broker) added to `docker-compose.yml` with a healthcheck; a
    **topic bootstrap** step creates the `being.*` topics + `.dlq` companions; new
    Makefile targets (`kafka-up`, topic-init) self-document.
  - `KafkaEventBus` implements the `EVT-BUS` ports; broker URL from **env**
    (`.env.example` updated), topic names from **config** (`config/events.yaml` + a
    typed `EventTopicsPolicy` on `ConfigService`).
  - A `[kafka]`-marked integration test publishes→consumes against a live broker;
    the **default suite still passes with no broker** (uses the fake).
  - Idempotent consume (dedupe on `event_id`) and DLQ-on-failure demonstrated.
- **Guardrails:** partition counts sized for a **single being** (start at 1; note in
  config, not code); no secret in `config/` or the repo.
- **Files/refs:** `docker-compose.yml`, `Makefile`, `engine/requirements.txt`,
  `engine/app/adapters/kafka_event_bus.py`, `config/events.yaml`,
  `engine/app/config_service.py`, `.env.example`, queue §"Kafka Topic Design" / §"Consumer Group Guidance".
- **Plan:** `docs/event_instinct_execution_plan.md` (EVT-KAFKA)

#### `TICK-INV` — Tick→event inventory & classification (classify-only) + ADR

- **Epic:** Reference · **Size:** S · **Depends on:** — · **Parallel-safe with:** all of E1 · **Wave E1**
- **Source:** queue Workstream C / Epic 3.
- **Outcome:** A written inventory of every tick-driven responsibility with a
  migration classification, and a decision on which stay time-driven vs. become
  events — enough to cut migration tickets safely **without changing behavior**.
- **Acceptance criteria:**
  - `docs/tick_to_event_inventory.md` (per item: owner module, what it reads/writes,
    cadence, side effects, classification: Event / Scheduled-event / Keep-loop /
    Renderer-only / Training) grounded in `simulation.py` + `tick_service.py` +
    `tick_rates.yaml`.
  - Migration order recommended (perception→instinct→render first; need-drift and
    emotion re-derivation classified **keep-as-scheduled** for now).
  - **ADR 0025** — scheduled events vs. real-time loop (no code, no behavior change).
- **Guardrails:** classify-only; this card writes **no** production code.
- **Files/refs:** `docs/tick_to_event_inventory.md`, `docs/adr/0025-*`,
  `engine/app/simulation.py`, `engine/app/services/tick_service.py`,
  `config/tick_rates.yaml`.
- **Plan:** `docs/event_instinct_execution_plan.md` (TICK-INV)

#### `NN-STRAT` — Instinct model strategy: extend vs. new (spike → ADR)

- **Epic:** ML · **Size:** S · **Depends on:** — · **Parallel-safe with:** all of E1 · **Wave E1**
- **Source:** queue Workstream D / Epic 4.
- **Outcome:** A recorded decision — **new instinct model + its own port/artifact**,
  or a second head on `OutcomeModel` — plus the frozen instinct feature-vector and
  reaction-label set, so `INS-MODEL` can start unambiguously.
- **Acceptance criteria:**
  - Assessment of the current `OutcomeModel` I/O shape, `PredictorPort`, training
    pipeline, and artifact/versioning (documented, not guessed).
  - **ADR 0026** — instinct neural strategy. Default recommendation per the map:
    **separate `InstinctModel` + `InstinctPredictorPort` + `models/instinct.pt`**,
    mirroring the `OutcomeModel`/`PredictorPort`/`train_outcome_model` structure
    (instinct's input/output contract differs from outcome prediction).
  - Frozen feature list (distance, velocity, trajectory-toward-body, time-to-contact,
    size-change-rate, unexpectedness, sound-spike, current focus/stability, prior
    prediction-error) and reaction labels (`flinch, freeze, orient, withdraw, ignore`
    + intensity) written into the ADR.
- **Guardrails:** no model built here — decision + contract only.
- **Files/refs:** `docs/adr/0026-*`, `engine/app/ml/outcome_model.py`,
  `engine/app/ports/predictor.py`, `engine/app/ml/encode_features.py`, queue
  §"Neural Network Strategy" / §"Instinct Model Definition".
- **Plan:** `docs/event_instinct_execution_plan.md` (NN-STRAT)

---

### Wave E2 — Instinct signal, model, and persistence (3 parallel, disjoint files)

#### `WORLD-MOTION` — Object motion + perception approach-stimulus events

- **Epic:** Psychology/World · **Size:** L · **Depends on:** `EVT-BUS` · **Parallel-safe with:** `INS-MODEL`, `EVT-PERSIST` · **Wave E2**
- **Source:** *new* — the prerequisite `queue.md` assumes but the repo lacks.
- **Outcome:** Objects can **move**, and perception derives an **approach stimulus**
  (distance/velocity/trajectory-toward-body/time-to-contact/size-change) and emits a
  `being.perception.events` `ObjectApproached` event — giving the instinct model
  real features to consume, visible in `state()` and on the event bus.
- **Acceptance criteria:**
  - A minimal kinematic layer (object position + velocity over ticks) in the world/
    perception path; `PerceptionService` (or a new `StimulusService` seam) computes
    the approach features and publishes `ObjectApproached` via the `EVT-BUS` port.
  - Config-driven motion (a new `config/motion.yaml` or an `environment.yaml` block +
    typed policy); no hard-coded speeds/thresholds.
  - Behavior tests (red first): a fast object on a body-intersecting trajectory →
    high `trajectory_toward_body` + low `time_to_contact` in the emitted event; a
    slow/away object → low scores; a static world → no `ObjectApproached`.
  - **ADR 0027** — perception motion / approach-stimulus seam (extends ADR 0002).
- **Guardrails:** stimulus keys on **perceived** properties/kinematics, never
  `developer_label`; motion stays a world/perception concern, not an instinct one.
- **Files/refs:** `engine/app/services/perception_service.py`,
  `engine/app/domain/{object_entity,room}.py`, `engine/app/simulation.py` (emit seam),
  `config/motion.yaml`, `docs/adr/0027-*`, queue §"Proposed New Brain Layer".
- **Plan:** `docs/event_instinct_execution_plan.md` (WORLD-MOTION)

#### `INS-MODEL` — Instinct PyTorch model, encoder, seed data, train/eval

- **Epic:** ML · **Size:** L · **Depends on:** `NN-STRAT` (contract), `EVT-BUS` (feature envelope) · **Parallel-safe with:** `WORLD-MOTION`, `EVT-PERSIST` · **Wave E2**
- **Source:** queue Workstream E / Epic 5.
- **Outcome:** A trained tiny instinct model that maps stimulus features → reaction
  probabilities + intensity, saved as a versioned artifact behind a port — testable
  in isolation with no sim or broker.
- **Acceptance criteria:**
  - `InstinctModel` (small PyTorch net), `InstinctFeatureEncoder` (pure, config-vocab
    driven — mirrors `FeatureEncoder`), a **synthetic seed dataset generator**
    (rule-labeled: fast-toward-face→flinch, loud-unknown→freeze, new-stimulus→orient,
    unexpected-touch→withdraw, low-signal→ignore), `train_instinct_model.py` +
    eval, artifact `models/instinct.pt` with its feature/label contract (rejected
    loudly on drift). `InstinctPredictorPort` in `engine/app/ports/instinct.py`.
  - Behavior tests (red first): features for a fast incoming object → `flinch` prob
    > `ignore` prob; trainer reproduces an artifact and records a `ModelRun`;
    encoder round-trips the frozen feature vector.
  - `torch` stays in the training/opt deps, not the lean runtime (mirror
    `requirements-train.txt`).
- **Guardrails:** rule labels only *seed* the model — production inference is neural;
  no rule table ships as the runtime path.
- **Files/refs:** `engine/app/ml/{instinct_model,instinct_encoder,train_instinct_model}.py`,
  `engine/app/ports/instinct.py`, `config/instinct.yaml`, `models/instinct.pt`,
  queue §"Instinct Model Definition" / §"Training data for instinct".
- **Plan:** `docs/event_instinct_execution_plan.md` (INS-MODEL)

#### `EVT-PERSIST` — Event log/outbox + instinct tables + training capture

- **Epic:** Data · **Size:** L · **Depends on:** `EVT-BUS` · **Parallel-safe with:** `WORLD-MOTION`, `INS-MODEL` · **Wave E2**
- **Source:** queue Workstream H / Epic 8.
- **Outcome:** Domain events are **published atomically with their DB writes**
  (transactional outbox) and projected into Postgres, and instinct predictions/
  reactions/training-examples are queryable — the audit + learning substrate.
- **Acceptance criteria:**
  - New tables (additive, via the ADR 0007 seam): `event_outbox`, `event_log`
    projection, `instinct_predictions`, `instinct_reactions`, `instinct_training_examples`;
    repository ports in the established append-only `add()/all()` shape.
  - **Outbox in the same `uow.begin()`** as the interaction write (ADR 0017); a relay/
    projection consumer moves outbox rows to the bus and into `event_log`.
  - Behavior tests (red first): an interaction that produces an event commits event +
    outbox row **atomically** (rollback drops both); a consumed event lands one
    `event_log` row keyed on `event_id` (idempotent on replay); an instinct
    prediction + observed outcome build one `instinct_training_examples` row.
  - **ADR 0028** — transactional outbox for atomic event publish (extends ADR 0017).
- **Guardrails:** repos stage only; no self-commit; no dual-write outside the outbox.
- **Files/refs:** `engine/app/db/models.py`, `engine/app/ports/repositories.py`,
  `engine/app/repositories.py`, `engine/app/db/unit_of_work.py`, `docs/adr/0028-*`,
  queue §"Data Storage Additions".
- **Plan:** `docs/event_instinct_execution_plan.md` (EVT-PERSIST)

---

### Wave E3 — Instinct inference on the bus (keystone, shadow mode)

#### `INS-RT` — Instinct inference consumer (perception→predict→reaction), shadow

- **Epic:** ML/Infra · **Size:** L · **Depends on:** `EVT-BUS`, `EVT-KAFKA`, `INS-MODEL`, `WORLD-MOTION`, `EVT-PERSIST` · **Parallel-safe with:** — (integration keystone) · **Wave E3**
- **Source:** queue Workstream F / Epic 6.
- **Outcome:** `ObjectApproached` events drive live instinct inference: the consumer
  encodes features, runs the model, and emits `InstinctPredictionMade` and (past
  thresholds) `InstinctReactionTriggered`/`Suppressed` — **in shadow: recorded and
  persisted, changing no behavior.**
- **Acceptance criteria:**
  - A consumer on `being.perception.events` → `InstinctFeatureEncoder` →
    `InstinctPredictorPort` → publishes `being.instinct.predictions`; applies
    config **thresholds + cooldowns** (`config/instinct.yaml` + typed policy) →
    publishes `being.instinct.reactions`. Idempotent (dedupe `event_id`), DLQ on
    failure.
  - **Shadow flag defaults on**: predictions/reactions are persisted (`EVT-PERSIST`)
    but the decision/action/render path is untouched — sim behavior byte-identical.
  - Behavior tests (red first, on the **in-memory bus**): a high-velocity body-bound
    `ObjectApproached` → an `InstinctReactionTriggered(flinch)` with intensity > a
    config threshold; a below-threshold stimulus → `Suppressed`; cooldown suppresses
    a rapid second trigger; duplicate `event_id` produces one reaction.
- **Guardrails:** shadow only — this card does **not** touch `DecisionService`,
  `EmotionService`, or the renderer.
- **Files/refs:** `engine/app/services/instinct_service.py`, `config/instinct.yaml`,
  `engine/app/ports/{events,instinct}.py`, queue §"Example Event Flow: Flinch" /
  §"Rollout Strategy → Phase 1".
- **Plan:** `docs/event_instinct_execution_plan.md` (INS-RT)

---

### Wave E4 — Behavior + visuals (staged activation, gated) + validation

#### `INS-ACT` — Instinct → decision/state integration (visual-only → controlled interrupt)

- **Epic:** Psychology · **Size:** L · **Depends on:** `INS-RT` · **Parallel-safe with:** `RENDER-RX` (disjoint: engine vs renderer files) · **Wave E4**
- **Source:** queue Workstream G / Epic 7.
- **Outcome:** A triggered instinct reaction can **bias emotion and interrupt the
  current action — through the existing safety/decision seam** — rolled out in two
  config steps: visual-only (emit reaction + emotion bias, no interrupt) then
  controlled interruption (cancel an interruptible action when the safety floor allows).
- **Acceptance criteria:**
  - Consumer on `being.instinct.reactions` → validates interruption via
    `DecisionService`/`SafetyService` (**never bypasses** the floor) → applies
    `emotion_bias` through the existing `EmotionService` derivation → on the interrupt
    step, cancels the current interruptible action and emits `ActionInterrupted` +
    state events.
  - Two config flags (`config/instinct.yaml`): `visual_only` and `allow_interrupt`,
    both default to the prior (byte-identical) behavior; activation is a config change.
  - Behavior tests (red first): a `flinch` reaction → `scared` emotion bias applied
    and current `reach` interrupted **only when** safety permits; a reaction whose
    interruption would produce an unsafe/invalid state is **suppressed, not forced**;
    with `visual_only`, emotion biases but no interruption occurs.
- **Guardrails:** the safety floor is inviolable; instinct proposes, safety disposes;
  instinct is never stored as an emotion.
- **Files/refs:** `engine/app/services/{instinct_service,decision_service,emotion_service}.py`,
  `engine/app/simulation.py`, `config/instinct.yaml`, queue §"Rollout → Phase 2/3".
- **Plan:** `docs/event_instinct_execution_plan.md` (INS-ACT)

#### `RENDER-RX` — Renderer reaction visuals (hints, not a timeline engine)

- **Epic:** Renderer · **Size:** M · **Depends on:** `EVT-BUS`/render events, `INS-RT` (shadow visuals) · **Parallel-safe with:** `INS-ACT` · **Wave E4**
- **Source:** queue Workstream I / Epic 9.
- **Outcome:** The renderer **shows** flinch / freeze / orient / withdraw via the
  existing render-state contract, with an optional debug overlay of reaction
  probability/intensity — visible confirmation the being reacts.
- **Acceptance criteria:**
  - Reaction draw hints added to `config/render_hints.yaml`; `RenderStateService`
    maps an active reaction into the `visual` block; `RenderState.ts`/`BeingView.ts`
    interpret the new hints (unknown-field tolerance keeps it forward-compatible).
  - A debug overlay (toggle) shows the latest reaction type + intensity.
  - Tests: renderer `Vitest` parses a frame carrying a reaction and selects the right
    hint; engine test asserts `RenderStateService` emits the reaction visual.
- **Guardrails:** static hints only — **no** animation/timeline system this slice;
  the renderer owns no psychology (ADR house rule).
- **Files/refs:** `config/render_hints.yaml`,
  `engine/app/services/render_state_service.py`,
  `renderer/src/{RenderState,BeingView}.ts`, queue §"Renderer Event Integration".
- **Plan:** `docs/event_instinct_execution_plan.md` (RENDER-RX)

#### `EVT-VALID` — Cross-service integration, idempotency & observability

- **Epic:** Infra/Observability (v14 slot) · **Size:** M · **Depends on:** `INS-RT`, `EVT-KAFKA` · **Parallel-safe with:** `RENDER-RX` · **Wave E4**
- **Source:** queue Workstream J / Epic 10.
- **Outcome:** The event path is trustworthy end-to-end: `[kafka]` integration tests,
  idempotency/DLQ tests, correlation-trace logging, and instinct model telemetry
  (prediction vs. observed outcome, consumer lag) — the observability foundation the
  v14 roadmap slot calls for.
- **Acceptance criteria:**
  - `[kafka]`-marked integration tests for the full `ObjectMoved→…→reaction` chain,
    consumer idempotency, and DLQ routing (default suite still broker-free).
  - Correlation-id trace logging across the chain; a `being.model.telemetry` stream
    records prediction accepted/rejected vs. observed outcome; consumer-lag metric
    exposed.
- **Guardrails:** telemetry is read-only; it never feeds back into the decision path.
- **Files/refs:** `engine/tests/` (`[kafka]` marker), `engine/app/services/instinct_service.py`,
  `engine/app/adapters/kafka_event_bus.py`, queue §"Preventing Too Many Listener Problems" / §"Epic 10".
- **Plan:** `docs/event_instinct_execution_plan.md` (EVT-VALID)

---

## 4. Dependency graph & parallel waves

Cards depend on the **public surface** of their predecessors; a card is dispatchable
when its deps are in Review/Done and it carries no `blocked`/overdue label.

```
Wave E1  ┌── EVT-BUS ──┬───────────────┐        (∥ TICK-INV ∥ NN-STRAT)
         │             │               │
         │        EVT-KAFKA        (port impl completes just after EVT-BUS)
         │             │               │
Wave E2  ├── WORLD-MOTION ── INS-MODEL ── EVT-PERSIST     (all ∥, disjoint files)
         │             │               │
Wave E3  │         INS-RT  (needs EVT-BUS+EVT-KAFKA+INS-MODEL+WORLD-MOTION+EVT-PERSIST)  ← shadow
         │             │
Wave E4  └── INS-ACT  ∥  RENDER-RX  ──►  EVT-VALID
              (visual-only → controlled interrupt, config flips)
```

| Wave | Runs in parallel | Width | Unblocks | Notes |
|------|------------------|-------|----------|-------|
| **E1** | `EVT-BUS` · `TICK-INV` · `NN-STRAT` (`EVT-KAFKA` infra scaffolds alongside) | **4** | all runtime work | The "4 parallel tracks" from queue §Recommended Next Action. |
| **E2** | `WORLD-MOTION` · `INS-MODEL` · `EVT-PERSIST` | **3** | `INS-RT` | Disjoint files; the widest real fan-out. |
| **E3** | `INS-RT` (shadow) | **1** | `INS-ACT`, `EVT-VALID` | Integration keystone; needs all of E2 + Kafka. |
| **E4** | `INS-ACT` ∥ `RENDER-RX` → `EVT-VALID` | **2** | staged activation + observability | Activation is a config flip, not new code. |

**File-overlap hotspots the orchestrator must serialize:**

| File / surface | Contended by |
|---|---|
| `engine/app/simulation.py` | `WORLD-MOTION` (emit seam), `INS-ACT` (interrupt/state), `EVT-BUS` (wiring) |
| `engine/app/services/perception_service.py` | `WORLD-MOTION` |
| `engine/app/services/decision_service.py` + safety | `INS-ACT` |
| `engine/app/db/models.py` + `repositories.py` | `EVT-PERSIST` (additive tables, ordered) |
| `engine/app/config_service.py` + `policies.py` | `EVT-KAFKA`, `WORLD-MOTION`, `INS-MODEL`, `INS-RT` (one new YAML each; keep `ConfigService` the only reader) |
| `docker-compose.yml` · `Makefile` · `requirements*.txt` | `EVT-KAFKA` |
| `config/render_hints.yaml` · `renderer/src/*` | `RENDER-RX` |
| `docs/adr/README.md` · `CONTEXT.md` | reconcile at roll-up (orchestrator, not a sub-agent) |

**Effective parallel width ≈ 3–4 early (foundation + E2), then 1–2** — the runtime
keystone (`INS-RT`) is inherently sequential.

---

## 5. ADRs & domain-model plan

New ADRs (next free number is **0024**; assign in merge order):

| ADR | Decision | From |
|---|---|---|
| **0024** | Event backbone: envelope + `EventBus` port + in-memory fake default + Kafka runtime | `EVT-BUS` |
| **0025** | Scheduled events vs. real-time loop (tick→event classification) | `TICK-INV` |
| **0026** | Instinct model strategy: separate `InstinctModel` + port + artifact | `NN-STRAT` |
| **0027** | Perception motion / approach-stimulus seam (extends 0002) | `WORLD-MOTION` |
| **0028** | Transactional outbox for atomic event publish (extends 0017) | `EVT-PERSIST` |

The instinct **shadow→visual→interrupt** rollout does *not* need a new ADR — it
extends the shadow-mode precedent (**ADR 0011**); note that in `INS-RT`/`INS-ACT`.

**`CONTEXT.md` glossary** (domain-model gate) gains: **event**, **event bus**,
**topic**, **outbox**, **stimulus**, **approach** (perceived kinematics), **instinct**
(fast pre-conceptual reaction — distinct from *emotion* and *decision*), **reaction**
(`flinch/freeze/orient/withdraw/ignore`), **shadow reaction**. Each with its
`_Avoid_` synonyms (e.g. instinct ≠ emotion; reaction ≠ action; event ≠ tick).

---

## 6. Rollout (maps queue §"Rollout Strategy" onto tickets)

| Phase | Behavior | Delivered by | Gate |
|---|---|---|---|
| **1 Shadow** | predict + persist, no behavior change | `INS-RT` | predictions/reactions persisted; traceable; suite green |
| **2 Visual-only** | reaction shown + emotion bias, no interrupt | `RENDER-RX` + `INS-ACT` (`visual_only=on`) | renderer reacts; no invalid state; cooldowns hold |
| **3 Controlled interrupt** | high-confidence reaction interrupts *interruptible, safe* actions | `INS-ACT` (`allow_interrupt=on`) | only allowed actions interrupted; safety floor holds; reaction persisted |
| **4 Adaptive** | event chains retrain the model | `EVT-PERSIST` capture + `train_instinct_model` | trainer reproduces artifact; metrics stored; versioned rollback possible |

Each phase is a **config flip**, default set to prior behavior — no phase ships a
behavior change without its own green suite and observed outcome.

---

## 7. Orchestration model — parallel tickets, a light orchestrator, workflow-capable sub-agents

Same fleet model as [`post_v0_execution_plan.md` §6](post_v0_execution_plan.md) and
[`CLAUDE.md`](../CLAUDE.md) ("Orchestrator delegates to sub-agents by default"), made
explicit for this wave.

**The orchestrator stays light on context.** It holds only the board state, the
dependency graph (§4), and each sub-agent's *verdict/report* — never raw file
contents, test logs, or search output. Everything delegable is delegated:
implementation, verification, shared-file reconciliation, doc authoring, and code
investigation (an `Explore` agent returns the conclusion, not file dumps). The
orchestrator's own inline acts are only those a sub-agent cannot do: create
worktrees/branches, merge a slice into the wave branch, open/roll up the wave PR,
delete merged branches, and all board/Trello writes. This keeps the long-lived
orchestrator session small across a multi-wave augmentation.

**The loop, per card.** Source from `Ready for Agent` → validate the card→slice
contract → compute the ready set from §4 (dispatchable when deps are in Review/Done,
no `blocked`/overdue label) → claim → dispatch **one implementer sub-agent per card**,
up to the wave's width (§4) **in parallel** → a **fresh** sub-agent (never the
implementer) runs the suite/demo and returns a pass/fail verdict → move the card one
state to Review → mirror every write to a commit/PR. Sub-agents work in
`slice/<ticket>` worktrees off `wave/<n>`, red-first TDD, run the deep-module-review +
domain-model gates, and never write to the board.

**Sub-agents may escalate to a workflow.** A slice large enough to warrant
decomposition (many independent files, a fan-out-then-verify shape) may spawn a
workflow or helper agents — staying inside its own worktree, **partitioning files so
nested agents never write the same file concurrently**, landing as commits on its
`slice/<ticket>` branch, and returning one completion report. **Workflow-eligible
here (all `L`):** `WORLD-MOTION` (world + perception + event-emit + ADR fan-out),
`INS-MODEL` (encoder ∥ model ∥ seed-gen ∥ train/eval), `EVT-PERSIST` (five tables +
outbox + projection consumer), `INS-RT` (consumer + thresholds + idempotency + DLQ),
`INS-ACT` (decision + emotion + interrupt + two rollout flags). Keep fan-out
proportional — the `S`/`M` cards (`TICK-INV`, `NN-STRAT`, `EVT-BUS`, `EVT-KAFKA`,
`RENDER-RX`, `EVT-VALID`) are single-agent slices.

**Roll-up.** The whole wave rolls into a single `wave/<n>` → `main` PR; defects found
in an open wave PR are ticketed and healed on `hotfix/<ticket>` so the PR stays
pristine and merge-ready. The orchestrator owns the shared-file reconciliation at
roll-up: `docker-compose.yml`, `Makefile`, `requirements*.txt`, the ADR index
(`docs/adr/README.md`), and `CONTEXT.md`.

---

## 8. Open questions (→ discovery tickets / ADR context)

1. **Broker choice — settled: Kafka (director, 2026-07-11).** The project is built
   to grow large and be enhanced long-term, which justifies a durable, replayable,
   partitioned log now rather than a bus swapped in later. Record in **ADR 0024**
   with alternatives-considered: **Redpanda** (Kafka-wire-compatible, single binary,
   no JVM/ZooKeeper — a lighter self-host that needs *zero* plan change since the
   `EVT-KAFKA` client is unchanged), **NATS JetStream** (simplest ops, subject-
   wildcard routing that fits `being.*`), **Pulsar** (queue+stream duality, tiered
   storage), and why **RabbitMQ/Redis Streams are not the backbone** (ack-delete /
   memory-bound retention — poor fit for replaying event history into ML training).
   The `EVT-BUS` port keeps the exact broker swappable. Note separately: the "10k
   items" scaling lever is a **perception-scan / spatial-index** problem, not a bus
   problem — track it on its own card, don't expect Kafka to solve it.
2. **Schema format:** JSON Schema (simpler, recommended first) vs. Avro + registry.
3. **Topic granularity / partitions** for a single being (start minimal: 1 partition,
   `being.{world,perception,instinct,action,state,render,training,telemetry}.events`).
4. **Instinct inference location:** in-process PyTorch behind the port now (like the
   outcome model) vs. riding the planned **v8 model-service sidecar** — align, don't
   fork the serving path.
5. **Acceptable instinct latency** end-to-end (perception event → reaction) — sets the
   consumer/poll design.
6. **Which further tick behaviors** (need drift, emotion) ever migrate — deferred to
   `TICK-INV`'s classification; not in this wave.

---

## 9. Loading onto Trello (board `NPC`, `qBaiErHa`)

- One card per ticket in §3, created in **`planned`** (a human stages it into
  `Ready for Agent` only when its deps are cleared — that move is the authorization).
- Card body = the ticket's **Outcome / Depends·Parallel·Wave·Epic·Size / Acceptance /
  Guardrails / Files·refs / Plan** blocks above. Title: `EVT-BUS — Event envelope +
  EventBus port  [infra·M·E1]`, etc.
- `EVT-BUS`, `TICK-INV`, `NN-STRAT` are the near-term (Wave E1) cards; the rest hold
  in `planned` until deps reach Review/Done. **`EVT-KAFKA` broker choice is settled
  (Kafka); the only sub-decision left is Kafka-proper vs. Redpanda for self-host,
  recorded in ADR 0024 — client code is identical either way.**
- All board writes go through the official `trello` MCP only, gated and mirrored to a
  commit/PR (`CLAUDE.md`). Board = intent, repo = truth.

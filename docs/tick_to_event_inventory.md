# Tick → event inventory & migration classification (TICK-INV)

**Purpose.** A grounded inventory of every responsibility the synchronous tick
loop drives today, each with a migration classification, so the event-backbone
wave can cut migration tickets **without changing behavior**. This is
**classify-only** — no production code changes with it. It is the evidence base
for [ADR 0025](adr/0025-scheduled-events-vs-real-time-loop.md) and for the
sequencing in [`event_instinct_execution_plan.md`](event_instinct_execution_plan.md).

**How the tick runs today (source of truth).** `Simulation.tick()`
(`engine/app/simulation.py`, lines ~277-287) advances the clock, drifts needs,
pushes contextual needs from the room, re-derives emotion, calls `_act(tick)`,
then returns `state()`. `_act()` (lines ~289-453) is the cognitive pipeline:
perceive → curiosity/surprise → decide → apply the outcome → re-derive emotion →
build the `InteractionEvent` → persist one unit of work (event / training example
/ shadow prediction / memory / concepts / beliefs / similarity / graph) → set the
cooldown → learn (exploration + traits). Time is a bare counter: `TickService`
(`engine/app/services/tick_service.py`) is `current_tick` + `advance()`, with
**no scheduler and no bus** — a real loop is expected to call `advance()` on a
timer (`config/tick_rates.yaml: tick.duration_ms = 1000`).

**Classification vocabulary** (per ADR 0025):

- **Event-driven** — a change *caused by something that happened* (a perception,
  an action, its consequence). Belongs on the event backbone: a producer emits a
  domain event, one or more consumers react. Migration target for this program's
  first path.
- **Scheduled-event** — a change *caused only by the passage of time* on a fixed
  cadence (`every_ticks`). Can later be driven by a scheduler/timer that emits a
  summarized event, but **need-drift and emotion re-derivation stay time-driven
  this program** (Keep-as-scheduled) — see the migration order below.
- **Keep-loop (real-time)** — genuinely real-time work whose correctness is the
  clock itself (the time source; action duration/cooldown timing). Keeps a local
  loop and emits *summarized* events rather than being decomposed onto the bus.
- **Renderer-only** — a read-model / projection assembled for the render-state
  frame (ADR 0004); no domain state changes. Migrates as a render event/frame.
- **Training/analytics** — a learning or audit side effect of an interaction,
  "never read back into this tick's decision" (per the code comments). Becomes an
  asynchronous consumer of the interaction event; not on the hot path.

---

## Inventory — one row per tick-driven responsibility

Line numbers are `engine/app/simulation.py` unless noted. "Pure" means the
service copies rather than mutates and has no external side effect.

### Phase A — `tick()` time-caused updates (before `_act`)

| # | Responsibility | Owner module / function | Reads | Writes | Cadence | Side effects | Classification |
|---|---|---|---|---|---|---|---|
| 1 | Advance time one step | `TickService.advance` (`services/tick_service.py`) | internal counter | `current_tick` | **every tick** | none (returns new tick) | **Keep-loop (real-time)** — the clock heartbeat / scheduler source |
| 2 | Autonomous need drift | `NeedService.apply` (`services/need_service.py:35`) | `being.needs`, `tick`, `NeedTickPolicy` set (`config/tick_rates.yaml: needs.*`) | `being.needs` | **`every_ticks` per need** (hunger 30, sleep 45, comfort 20, curiosity 15, pain 4; contextual needs skipped; tick 0 never drifts) | none (pure) | **Scheduled-event** (Keep-as-scheduled) |
| 3 | Environmental push on contextual needs | `EnvironmentService.apply` (`services/environment_service.py:36`) | `being.needs`, `Room.conditions()` (light/sound/temperature), `EnvironmentPolicy` (config), `tick` | `being.needs` (safety, warmth) | **`policy.every_ticks`** (tick 0 never moves; conditions re-resolved every tick to fail loud on a typo) | none (pure) | **Scheduled-event** (Keep-as-scheduled) — the room-change trigger (`change_environment`) is already event-shaped; only the per-tick application is scheduled |
| 4 | Emotion derivation (post-drift) | `EmotionService.derive` (`services/emotion_service.py:31`) | `being.needs`, `EmotionRule` set (`config/emotions.yaml`) | `being.emotion` | **every tick** | none (pure, stateless) | **Scheduled-event** (Keep-as-scheduled) — a pure projection of needs |

### Phase B — `_act()` cognitive pipeline

| # | Responsibility | Owner module / function | Reads | Writes | Cadence | Side effects | Classification |
|---|---|---|---|---|---|---|---|
| 5 | Perceive the room | `PerceptionService.perceive` (`services/perception_service.py:28`), called at `simulation.py:295` | `Room.contains`, object catalog (true defs) | — (returns perceived view) | **every tick** | none | **Event-driven — MIGRATE FIRST.** Becomes `being.perception.events` (`ObjectApproached` / motion frames) once `WORLD-MOTION` adds kinematics |
| 6 | Curiosity / surprise derivation + render view | `ExplorationPolicyService.curiosity_map` / `surprise_map` (`simulation.py:302-303`, refreshed at `:446`) wrapping `CuriosityService` + `SurpriseService` | `perceived`, `tick`, internal familiarity/recorded-surprise state, curiosity weights + surprise policy (config) | `_curiosity_view`, `_surprise_view` (transient view dicts) | **every tick** (surprise decays as a function of `tick`, computed on read) | transient in-memory views | **Renderer-only** (also the decision's curiosity input) — migrates alongside the perception→instinct→render path |
| 7 | Choose one action | `DecisionService.decide` (`services/decision_service.py:75`, +`SafetyService`, optional ensemble predictor, exploration, `score_bias`), called at `simulation.py:305` | `needs`, `emotion`, `perceived`, `on_cooldown`, `curiosity`, `score_bias` (memory + belief biases), action/safety policies, predictor | — (returns `Decision` or `None`) | **every tick** | none (pure decision; safety gates) | **Event-driven** — reaction to a perception (instinct will sit *before* it). Full integration is later (`INS-ACT`, wave E4), through the existing safety/decision seam — **not** wave 1 |
| 8 | Apply the action's felt consequence to needs | `NeedService.apply_outcomes` (`services/need_service.py:55`), called at `simulation.py:331` | `being.needs`, `observed_outcome`, `OutcomeEffectPolicy` (config) | `being.needs` (pain spike, safety/comfort drop) | **each acting tick — NOT tick-gated** ("lands the moment the action does", per docstring) | none (pure) | **Event-driven** — already an event-shaped consequence of the action |
| 9 | Emotion re-derivation (post-outcome) | `EmotionService.derive` (`simulation.py:332`) | `being.needs`, emotion rules | `being.emotion` (`emotion_after`) | **each acting tick** | none (pure) | **Scheduled-event** (Keep-as-scheduled) — same stateless derivation as #4; kept inline this program |
| 10 | Build the `InteractionEvent` + in-memory log | `Simulation._act` (`simulation.py:335-345`) | `decision`, outcomes, emotion before/after | `self._events` (in-memory log) | **each acting tick** | in-memory append | **Event-driven** — this *is* the domain event; the hook point for `EVT-BUS` publish |
| 11 | Persist the interaction event | `InteractionEventRepository.add` via `Simulation._record` (`simulation.py:510-519`) inside `self._uow.begin()` | `event` | `interaction_event` row | **each acting tick** (when repo injected) | **DB write** (unit of work) | **Event-driven** — becomes the transactional outbox → `event_log` (`EVT-PERSIST`, ADR 0028) |
| 12 | Derive the training example | `FeatureEncoder` + `TrainingExampleRepository.add` via `_record` (`simulation.py:520-534`) | `true_props`, affordance, observed outcomes | `training_example` row | **each acting tick with an affordance** (free actions derive none) | **DB write** | **Training/analytics** |
| 13 | Record the shadow prediction | `PredictionService.record` (`simulation.py:357-363`) | `event`, perceived props, action affordance, predictor | `prediction_record` row | **each acting tick** (shadow mode, predictor injected + neural off) | **DB write** | **Training/analytics** — observational only (ADR 0011) |
| 14 | Form the durable memory | `MemoryService.remember` (`simulation.py:364-367`) | `event`, perceived props, prediction, priority policy | `memory` row | **each acting tick** (memory port injected) | **DB write** | **Training/analytics** — learning substrate, "never read back into this tick's decision" |
| 15 | Concept-schema learning | `ConceptService.observe` (`simulation.py:380-392`) | object id, action, perceived props, observed outcomes, salience/intensity, learning policy | `concept` rows | **each acting tick** (concept port injected) | **DB write** | **Training/analytics** |
| 16 | Belief formation | `BeliefService.believe` (`simulation.py:393-400`) | object id, perceived props, action, concepts | `belief` rows | **each acting tick** (belief port injected) | **DB write** | **Training/analytics** |
| 17 | Similarity recording | `SimilarityService.record` (`simulation.py:401-415`) | object id, perceived props, peer objects | `similarity` rows | **each acting tick** (similarity port injected) | **DB write** | **Training/analytics** |
| 18 | Concept-graph projection | `KnowledgeGraphService.witness` (`simulation.py:419-429`) | concepts, object, observed outcomes, similarities, source memory ids, edge policy | graph node/edge rows | **each acting tick** (graph port injected) | **DB write** | **Training/analytics** |
| 19 | Action cooldown / timing gate | `Simulation._act` (`simulation.py:430-432`), timing from `config/tick_rates.yaml: actions.*` | chosen action policy (`duration_ticks`, `cooldown_ticks`) | `self._cooldown_until[action]` | **each acting tick** (consumed every tick as `on_cooldown`) | in-memory | **Keep-loop (real-time)** — action duration/rest timing keyed on the clock |
| 20 | Current-action projection | `Simulation._act` (`simulation.py:433`) | `decision.as_current_action()` | `self._current_action` | **each acting tick** (cleared on idle, `:314`) | in-memory | **Renderer-only** — surfaces as `currentAction` on the state frame |
| 21 | Exploration learning (surprise + familiarity) | `ExplorationPolicyService.observe_interaction` (`simulation.py:439-445`) | expected vs. observed outcomes, perceived props, tick | internal familiarity + recorded-surprise state | **each acting tick** | in-memory learning state | **Training/analytics** — feeds next tick's curiosity |
| 22 | Trait drift | `TraitService.observe_interaction` (`simulation.py:449-453`) | expected vs. observed outcomes, outcome effects, trait policy | internal caution/curiosity levels | **each acting tick** | in-memory state drift | **Training/analytics** — slow personality drift |

### Phase C — `state()` frame (end of `tick()`, and on demand)

| # | Responsibility | Owner module / function | Reads | Writes | Cadence | Side effects | Classification |
|---|---|---|---|---|---|---|---|
| 23 | Assemble the state / render snapshot | `Simulation.state` (`simulation.py:625-641`), re-calls `PerceptionService.perceive` | being state, room, `_curiosity_view`, `_surprise_view`, traits, `_current_action` | — (returns snapshot) | **every tick** + on demand | none | **Renderer-only** — the ADR 0004 `being_state_update` frame |

### Classification tally (23 responsibilities)

| Classification | Count | Rows |
|---|---|---|
| **Event-driven** | 5 | #5 perception, #7 decision, #8 outcome→need, #10 interaction event, #11 event persistence |
| **Scheduled-event** (Keep-as-scheduled this program) | 4 | #2 need drift, #3 environment push, #4 emotion (post-drift), #9 emotion (post-outcome) |
| **Keep-loop (real-time)** | 2 | #1 time advance, #19 action cooldown/timing |
| **Renderer-only** | 3 | #6 curiosity/surprise view, #20 current-action, #23 state frame |
| **Training/analytics** | 9 | #12 training example, #13 shadow prediction, #14 memory, #15 concept, #16 belief, #17 similarity, #18 graph, #21 exploration learning, #22 trait drift |

---

## Recommended migration order

The event backbone is introduced **narrowly and behavior-preservingly**. The
order below matches the wave plan (`event_instinct_execution_plan.md` §1.2 #3 and
§4) and stops well short of decomposing the whole tick onto the bus.

1. **FIRST: perception → instinct → render** (the only path migrated this program).
   - **Perception (#5)** becomes a producer of `being.perception.events` once
     `WORLD-MOTION` adds object kinematics and an approach stimulus
     (`ObjectApproached`). This is the pull-through that gives the instinct model
     real features.
   - **Instinct** is a *new* consumer between perception and decision (`INS-RT`,
     shadow mode) — it does not exist on the tick today, so nothing is "migrated,"
     it is added downstream of the perception event; it records and persists,
     changing no behavior.
   - **Render (#6, #20, #23)** consumes reaction events and shows flinch / freeze /
     orient / withdraw as static hints (`RENDER-RX`) — no animation engine.
   - **Decision (#7)** integrates *last* in this path (`INS-ACT`, wave E4), through
     the existing `DecisionService`/`SafetyService` seam — instinct proposes, safety
     disposes; it is not migrated in wave 1.

2. **Interaction event + persistence (#10, #11) onto the event backbone.** The
   `InteractionEvent` is published through the `EventBus` port (`EVT-BUS`) and
   persisted via a **transactional outbox** in the same unit of work (`EVT-PERSIST`,
   ADR 0028) — atomic with the DB write, no dual-write.

3. **Training/analytics side effects (#12-#18, #21, #22) become async consumers**
   of the interaction event — off the hot path. They stay as in-`uow` side effects
   for now and move to consumers only as needed; they are audit/learning, never
   read back into the same tick's decision.

4. **Keep-as-scheduled — do NOT migrate this program:**
   - **Need-drift (#2)** and **emotion re-derivation (#4, #9)** stay time-driven on
     the tick. They are cheap, deterministic, and already correct; converting them
     to scheduled events would add machinery with no behavior gain. Emotion in
     particular is a *pure projection of needs* — a candidate for future
     derive-on-read, but explicitly out of scope here.
   - **Environmental push (#3)** stays scheduled with need-drift (its world-change
     *trigger* is already event-shaped via `change_environment`).

5. **Keep-loop (real-time) — never decomposed onto the bus:**
   - **Time advance (#1)** is the clock/scheduler source itself.
   - **Action cooldown/timing (#19)** is duration/rest timing keyed on the clock; a
     local loop owns it and emits summarized action events, per ADR 0025.

**Net effect of wave 1:** only #5 (and the new instinct consumer) plus the render
projections change how they are driven; #2/#3/#4/#9 stay exactly as they are; the
rest keep their current in-`uow` behavior and migrate opportunistically later. No
behavior changes in the classify-only TICK-INV slice.

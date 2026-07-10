# v0 Execution Plan — orchestrated vertical slices

**Purpose.** Take the being from "slice 1 done" to the **v0 North Star** using a
fleet of agents: one **orchestrator** that sources work from the Trello board and
sequences it, and **sub-agents** that each land one vertical slice and report its
completion. This document is the source for the Trello cards; each ticket below
maps to one card.

- Architecture / target: [`docs/BRIEF.md`](BRIEF.md) (a.k.a. `approach_v1.md`).
- Ordered roadmap (single source of truth): [`README.md`](../README.md#roadmap-vertical-slices-in-order).
- How work is done here (slice discipline, TDD, board guardrails): [`CLAUDE.md`](../CLAUDE.md).
- Decisions: [`docs/adr/`](adr/). This plan does **not** restate the roadmap or
  the brief — it links to them and adds ticket-level detail + orchestration.

---

## 1. Where we are

**Slice 1 — minimal being state (done, ADR 0001).** A being whose needs drift
over ticks entirely from `config/tick_rates.yaml`, and whose one dominant emotion
is derived from those needs via `config/emotions.yaml`. Public surface:
`Simulation.tick()` / `Simulation.state()`, built from `ConfigService`. Pure
Python + PyYAML; no transport, DB, ML, renderer, objects, or actions.

**`scared`/fear is wired but cannot fire yet** — nothing lowers the contextual
`safety` need until the environment slice.

## 2. Definition of done for v0 (the North Star)

From [`BRIEF.md` §21](BRIEF.md): a Docker Compose project where the Python engine
runs the being in one room, with config-driven tick needs, a few objects and
environmental conditions (light/dark, sound, temperature), interaction events
logged to Postgres, a PyTorch outcome-predictor running in **shadow mode**, and a
PixiJS renderer showing the being's current emotion/action.

v0 is done when **every ticket below is in `Done`** and the North Star runs
end-to-end via `docker compose up` (plus the training profile).

## 3. Standing constraints (every ticket inherits these)

- **Vertical slice → observable outcome.** No model-only or transport-only work;
  each ticket ends in something a user can see or do. State the one-sentence
  outcome before writing code.
- **TDD, red first.** Behavior-driven tests through the public surface, observed
  failing, then green. `cd engine && python -m pytest` must be green to be
  review-ready. Never assert-only; demonstrate the observable outcome.
- **Config-driven tuning.** Rates, thresholds, timings, vocabularies live in
  `config/*.yaml`. `ConfigService` is the only config-aware code. Retuning is a
  config edit, proven by a test.
- **Deep modules / seams.** One public class per module; don't add a port until
  something varies across it (ADR-worthy when you do). Prefer deepening
  `Simulation` over adding shallow pass-throughs.
- **Self- and world-directed only.** The being acts on its own state and the
  world; there are no actions that summon or depend on an external actor. Actions
  are things like observe / approach / withdraw / touch / grasp / push.
- **Design boundary.** Harm stays abstract (state deltas + visible consequence +
  recovery path). See [`docs/design_boundary.md`](design_boundary.md).
- **ADR in the same slice.** Any ticket that adds or changes an interface
  adds/updates its ADR in the same slice, indexed in
  [`docs/adr/README.md`](adr/README.md).
- **Deep-module review gate.** After the slice is green and before it is called
  done, run `/legacy-deep-module-review` over the change; fold small fixes in,
  raise an ADR (or a next slice) for interface-level findings, never defer
  silently. A card is not review-ready until this has run (see `CLAUDE.md`).

---

## 4. The tickets (→ Trello cards)

Ten tickets, IDs `V0-2 … V0-11` (slice 1 = `V0-1`, done). Grouped by epic. Each
card body is copy-paste ready and carries the CLAUDE.md card→slice contract:
one-sentence **Outcome**, **Acceptance criteria**, and **links to files/ADRs**.

### Epic P — Psychology core (pure Python, extends `Simulation`)

---

#### `V0-2` — Objects, a room, and perception

- **Epic:** Psychology · **Size:** M · **Depends on:** V0-1 ✅ ·
  **Parallel-safe with:** V0-5, V0-6, V0-10a
- **Outcome:** The being perceives the objects near it in its one room — each
  with a confidence — and that perceived set appears in `Simulation.state()`.
- **Acceptance criteria:**
  - New config `config/rooms.yaml` (one room, contains a few object ids) and
    `config/object_properties.yaml` (property vocabulary + a handful of objects
    with `properties`, `affordances`, `developerLabel`), loaded via
    `ConfigService` only.
  - New domain: `Room`, `ObjectEntity`; new `PerceptionService` that turns world
    truth into a **perceived** view (confidence per object) — the being never
    reads true world state directly (BRIEF §17).
  - `state()` gains a `perceived` block (objects + confidence); existing keys
    unchanged.
  - Behavior tests through the public surface: e.g. `test_being_perceives_objects_in_its_room`,
    `test_perception_confidence_is_reported`. Red first, then green.
  - `python -m app.demo` shows perceived objects. ADR added (perceived-vs-true
    seam). `pytest` green.
- **Files/refs:** `engine/app/domain/{room,object_entity}.py`,
  `engine/app/services/perception_service.py`, `engine/app/simulation.py`,
  `config/rooms.yaml`, `config/object_properties.yaml`, BRIEF §9, §13, §17.
- **Coordination:** this changes the **shape of `state()`** — transport (V0-6)
  and render (V0-10) must serialize `state()` generically, not hard-code fields.

---

#### `V0-3` — Environmental conditions move contextual needs (fear can fire)

- **Epic:** Psychology · **Size:** M · **Depends on:** V0-2 ·
  **Parallel-safe with:** V0-6, V0-7(schema), V0-8(scaffold), V0-10
- **Outcome:** A dark or loud room drives the contextual `safety` need down and,
  when it crosses the threshold, the being's dominant emotion becomes `scared` —
  visible in the demo.
- **Acceptance criteria:**
  - New `config/environment.yaml`: light (`dark…too_bright`), sound
    (`silent…unknown_sound`), temperature (`cool/comfortable/warm`) categories
    with their impacts on `safety`/`warmth`. Room references a condition set.
  - `PerceptionService`/environment logic maps conditions → deltas on the
    contextual needs `safety` and `warmth` (which have `direction: contextual`
    and currently never move). No hard-coded numbers in service code.
  - Behavior test: dark/loud room → `safety` falls → emotion becomes `scared`
    (e.g. `test_dark_room_lowers_safety_until_being_is_scared`); a comfortable
    room keeps it calm. Retuning the threshold is a config-only change (test).
  - **No external-actor or "freeze" action** — this ticket only moves needs and
    lets emotion re-derive. `pytest` green; demo shows the shift.
- **Files/refs:** `engine/app/services/perception_service.py`,
  `config/environment.yaml`, `config/rooms.yaml`, `config/emotions.yaml`
  (existing `scared` rule), BRIEF §9 (Environmental Conditions), ADR 0001.

---

#### `V0-4` — Actions, rule/utility decision, and safety guardrails

- **Epic:** Psychology · **Size:** L · **Depends on:** V0-2, V0-3 ·
  **Parallel-safe with:** V0-8, V0-11(scaffold)
- **Outcome:** Each tick the being selects and performs one action toward an
  object via utility scoring (with a stated reason); safety rules hard-block
  unsafe actions, and each action produces an `InteractionEvent` with expected vs
  observed outcome.
- **Acceptance criteria:**
  - New config: `config/actions.yaml` (affordances, utility weights) and action
    **tick timing** (duration/cooldown) — decide in the ADR whether timing extends
    `tick_rates.yaml` or a new file; `config/safety_rules.yaml`;
    `config/outcome_labels.yaml` (the multi-label outcome vocabulary, e.g.
    `rolls/bounces/falls/causes_pain/makes_noise/pleasant/scary`).
  - New `DecisionService` (score valid actions from needs + emotion + perceived
    objects + cooldowns; output `{action, targetId, emotion, reason}`) and
    `SafetyService` (hard guardrails; **learned/utility scores never bypass
    safety**). New `InteractionEvent` domain with `expectedOutcome`,
    `observedOutcome`, `emotionBefore/After`.
  - Behavior tests: high curiosity + low risk → approach/observe; **hot object +
    touch predicts pain → touch blocked** and a safe action chosen instead;
    action respects cooldown. Red first.
  - `state()` gains `currentAction`; demo prints action + reason each tick.
    **Actions are self- and world-directed only.** ADR added. `pytest` green.
- **Files/refs:** `engine/app/services/{decision_service,safety_service}.py`,
  `engine/app/domain/{action,interaction_event}.py`,
  `config/{actions,safety_rules,outcome_labels}.yaml`, BRIEF §12, §13, §16.
- **Note:** this is the psychology capstone and the source of the events/labels
  that V0-7 stores and V0-8 learns from.

### Epic I — Transport & infrastructure

---

#### `V0-5` — Docker Compose skeleton + engine image

- **Epic:** Infra · **Size:** S · **Depends on:** V0-1 ✅ ·
  **Parallel-safe with:** V0-2, V0-6
- **Outcome:** `docker compose up` builds and starts the `engine` and `postgres`
  services and the engine runs (tick loop / demo) inside the container.
- **Acceptance criteria:**
  - `engine/Dockerfile` (installs `requirements.txt`), root `docker-compose.yml`
    with `engine` + `postgres` services and the env/volumes from BRIEF §6
    (`CONFIG_ROOT`, `DATABASE_URL`, `MODEL_PATH`). `.dockerignore` already exists.
  - `docker compose up` reaches a healthy state; engine container imports `app`
    and runs without error (demo or, once V0-6 lands, uvicorn). Postgres is up
    and reachable from engine (documented one-liner).
  - Observable: a documented `docker compose up` run in the ticket comment / PR.
    No app logic changes.
- **Files/refs:** `docker-compose.yml`, `engine/Dockerfile`, BRIEF §6.
- **Coordination:** owns the compose `command:` for engine jointly with V0-6
  (uvicorn) and V0-8 (`ml-trainer` under `profiles: [training]`).

---

#### `V0-6` — FastAPI engine: REST `/state` + WebSocket tick stream

- **Epic:** Infra · **Size:** M · **Depends on:** V0-1 ✅ ·
  **Parallel-safe with:** V0-2, V0-5
- **Outcome:** With the engine running, `GET /state` returns the current snapshot
  and a WebSocket endpoint streams one state frame per tick on a real clock.
- **Acceptance criteria:**
  - `engine/app/main.py` (FastAPI app) exposes `GET /state` → `Simulation.state()`
    and a WS endpoint that advances the sim on a timer and pushes each `state()`.
  - Introduce a `ClockPort` seam so wall-clock time is injectable (tests drive a
    fake clock; ADR 0001 anticipated this reassessment). Add ADR for the
    transport + clock seam.
  - Serializes **whatever `state()` returns** — no hard-coded field list — so it
    survives V0-2/V0-4 growing the snapshot.
  - Behavior tests via FastAPI `TestClient`: `/state` returns the snapshot; the WS
    emits N frames over N fake-clock ticks with monotonically increasing `tick`.
  - `fastapi` + `uvicorn` uncommented in `requirements.txt`. `pytest` green;
    documented `curl /state` + WS frame sample.
- **Files/refs:** `engine/app/main.py`, `engine/app/ports/clock.py`,
  `engine/requirements.txt`, BRIEF §5 (engine), §13, §14.

### Epic D — Data / persistence

---

#### `V0-7` — Postgres persistence: schema, repositories, event logging

- **Epic:** Data · **Size:** L · **Depends on:** V0-5 (postgres), V0-4 (events) ·
  **Parallel-safe with:** V0-3, V0-8, V0-10 *(schema + repo ports draftable in
  Wave 2; event-write wiring waits for V0-4)*
- **Outcome:** As the sim runs, interaction events are written to Postgres, and a
  query shows the rows.
- **Acceptance criteria:**
  - Repository **ports** + SQLAlchemy models + migrations for the v0 tables
    (BRIEF §15): `beings`, `objects`, `interaction_events`, `training_examples`,
    `prediction_records`, `model_runs`. Engine writes `InteractionEvent`s (from
    V0-4) via the repository port; `Simulation`/services depend on the port, not
    on SQLAlchemy.
  - A fake/in-memory repository is used in tests (seam), a real Postgres one in
    Compose. Behavior test: run the sim, events land; querying returns them.
  - `training_examples` are derived from interaction events (BRIEF §9,
    Training Strategy §16) and stored — this is the input V0-8 trains on.
  - `SQLAlchemy` + `psycopg` uncommented in `requirements.txt`. `pytest` green;
    documented `SELECT` showing rows after a Compose run.
- **Files/refs:** `engine/app/ports/repositories.py`, `engine/app/db/{models,session}.py`,
  `engine/app/db/migrations/`, `engine/app/services/learning_service.py`,
  BRIEF §8, §15, §16, §17.

### Epic M — Machine learning

---

#### `V0-8` — Outcome predictor + `ml-trainer` sidecar

- **Epic:** ML · **Size:** L · **Depends on:** outcome/feature vocab from V0-4;
  `training_examples` from V0-7 · **Parallel-safe with:** V0-3, V0-7, V0-10
  *(scaffold on synthetic examples in Wave 2; finalize on real data after V0-7)*
- **Outcome:** `docker compose --profile training run ml-trainer` reads training
  examples, trains a small multi-label PyTorch model, and writes
  `models/outcome_predictor.pt` plus metrics.
- **Acceptance criteria:**
  - `encode_features.py` maps (object properties + action + context) → a fixed
    feature vector; labels come from `config/outcome_labels.yaml` (multi-label).
    Feature/label contract documented in an ADR so V0-9 encodes identically.
  - `outcome_model.py` (simple feed-forward, `nn.Sigmoid` multi-label) +
    `train_outcome_model.py` (reads `training_examples`, or a **synthetic seed set**
    derived from the config vocab until V0-7 is wired) writes the `.pt` artifact
    and metrics (to `model_runs` or a metrics file).
  - `ml-trainer` service in `docker-compose.yml` under `profiles: [training]`
    (BRIEF §6). Tests: encoding is deterministic and round-trips the vocab;
    training runs one mini-epoch on a tiny fixture and produces an artifact.
  - `torch`/`numpy`/etc. added to a training requirements set (kept out of the
    lean runtime image where possible). `pytest` green; documented trainer run.
- **Files/refs:** `engine/app/ml/{encode_features,outcome_model,train_outcome_model,evaluate}.py`,
  `config/outcome_labels.yaml`, `models/`, `docker-compose.yml`, BRIEF §11, §16.

---

#### `V0-9` — Prediction shadow mode

- **Epic:** ML · **Size:** M · **Depends on:** V0-4, V0-7, V0-8 ·
  **Parallel-safe with:** V0-11(finish)
- **Outcome:** The engine loads the model and, for each interaction, records the
  model's predicted outcomes next to the rule's expectation and the actual
  outcome — **without influencing behavior**.
- **Acceptance criteria:**
  - `PredictionService` loads `models/outcome_predictor.pt` (if present), encodes
    the same features as V0-8, returns outcome probabilities; it **does not
    choose actions** (BRIEF §11, §17). Engine degrades gracefully with no artifact.
  - Each interaction writes a `prediction_records` row: model prediction vs rule
    expectation vs observed outcome, plus a correctness/error measure (BRIEF §16
    shadow-mode test).
  - Behavior test: model predicts bounce, actual is bounce → record marked
    correct; behavior is byte-identical with the model on vs off (shadow). ADR
    for the shadow-mode seam. `pytest` green; documented `prediction_records` rows.
- **Files/refs:** `engine/app/services/prediction_service.py`,
  `engine/app/ports/predictor.py`, `engine/app/ml/inference.py`, BRIEF §11, §13, §16.

### Epic R — Renderer

---

#### `V0-10` — Render-state contract + `RenderStateService`

- **Epic:** Renderer · **Size:** M · **Depends on:** V0-6 (transport); grows with
  V0-4 · **Parallel-safe with:** V0-3, V0-7, V0-8
- **Outcome:** The engine emits render frames matching the documented
  `being_state_update` contract and accepts a `player_command`; the contract is
  pinned in an ADR.
- **Acceptance criteria:**
  - **Sub-ticket `V0-10a` (doc-only, Wave 1):** author the render-state contract
    ADR from BRIEF §14 (`being_state_update` fields + `player_command`) so the
    renderer (V0-11) can be built against it in parallel.
  - `RenderStateService` maps domain `state()` → the contract frame (emotion,
    pose, action, intensity, needs, visual hints); makes **no psychology
    decisions** (BRIEF §17). WS endpoint (V0-6) emits these frames; a
    `player_command` (e.g. `present_object`) is validated and applied.
  - Contract test: a frame validates against the documented schema for a known
    state; an unknown command is rejected. `pytest` green.
- **Files/refs:** `engine/app/services/render_state_service.py`,
  `engine/app/services/command_service.py`, `docs/adr/…-render-state-contract.md`,
  BRIEF §14, §17.

---

#### `V0-11` — PixiJS renderer app

- **Epic:** Renderer · **Size:** L · **Depends on:** V0-10, V0-6 ·
  **Parallel-safe with:** V0-9 *(scaffold against the V0-10a contract in Wave 3;
  full correctness follows V0-4's action/pose + V0-10)*
- **Outcome:** A browser app connects over WebSocket and shows the being's current
  emotion/action/pose updating each tick, and can send one command back.
- **Acceptance criteria:**
  - `renderer/` Vite + PixiJS app (`main.ts`, `BeingView.ts`, `SocketClient.ts`,
    `RenderState.ts`, `CommandPanel.ts`) connects to the engine WS, renders the
    being reacting to `being_state_update` frames, and sends one `player_command`.
  - **The renderer owns no psychology/decision logic** (BRIEF §5, §17, rule #1).
  - `renderer` service added to `docker-compose.yml` (BRIEF §6). Observable: a
    documented run (screenshot / recording) of the being changing emotion/action
    as the engine ticks; a command round-trips.
  - Front-end test appropriate to the stack (e.g. `RenderState` parsing / socket
    client) where practical. Engine `pytest` remains green.
- **Files/refs:** `renderer/`, `docker-compose.yml`, BRIEF §5, §6, §14.

---

## 5. Dependency graph & parallel waves

Cards depend on the **public surface** of their predecessors, not their internals.
A card is dispatchable when its dependencies are in **Review** or **Done** and it
carries no `blocked`/overdue label.

```
V0-1 (done)
   │
   ├── V0-2 ─── V0-3 ─── V0-4 ──────────────┐
   │                          │             │
   ├── V0-5 ─── V0-7(schema) ─┴─ V0-7(wire) ┤
   │      │                                 ├── V0-9
   ├── V0-6 ─── V0-10 ─── V0-11             │
   │                                        │
   └── V0-8(scaffold) ───── V0-8(real) ─────┘
```

| Wave | Runs in parallel | Unblocks | Notes |
|------|------------------|----------|-------|
| **1** | `V0-2`, `V0-5`, `V0-6`, `V0-10a` (contract doc) | V0-3, V0-7, V0-10, V0-11 | All depend only on slice 1 / the frozen public surface. Disjoint files. |
| **2** | `V0-3`, `V0-7` (schema+ports), `V0-8` (scaffold on synthetic data), `V0-10` (service) | V0-4, V0-9, V0-11 | V0-3 needs V0-2; V0-7/V0-10 need V0-5/V0-6. |
| **3** | `V0-4` (psychology capstone), `V0-11` (renderer app) | V0-7 wire, V0-8 real, V0-9 | V0-4 unlocks events/labels; V0-11 needs V0-10. |
| **4** | `V0-7` (event wiring), `V0-8` (train on real examples), `V0-9` (shadow mode) | v0 done | Integration capstones. |

**Effective parallel width ≈ 3–4 sub-agents.** More than that starves on
dependencies. The critical path is `V0-2 → V0-3 → V0-4 → V0-7(wire) → V0-9`.

**Coordination hotspots the orchestrator must guard:**
- **`state()` shape** grows in V0-2 and V0-4. V0-6/V0-10 must serialize it
  generically. Orchestrator merges V0-2 before V0-6/V0-10 finalize.
- **`docker-compose.yml`** is touched by V0-5, V0-8, V0-11. V0-5 lands first and
  owns the file's shape; later cards append their service.
- **Feature/label contract** is shared by V0-8 and V0-9 — pinned in V0-8's ADR.
- **`requirements.txt`** is appended by V0-6, V0-7, V0-8 — keep the training-only
  deps (`torch`) out of the lean runtime image.

---

## 6. Orchestration model

**Execution mechanics (worktrees + wave PR).** Each wave runs on an integration
branch `wave/<n>` off `main`; each parallel slice runs in its own worktree on
`slice/<ticket>` under `.claude/worktrees/<ticket>/`. Sub-agents commit only in
their worktree; the orchestrator merges each finished slice into `wave/<n>` and,
once the whole wave is in, opens a **single PR** `wave/<n>` → `main` for a human
to merge. Defects found in review or in an open wave PR are ticketed and fixed by
a sub-agent on a `hotfix/<ticket>` branch that, once verified, merges back into
the wave branch (updating the PR in place) — the loop is **self-diagnosing**
(verification → bug ticket) and **self-healing** (ticket → sub-agent fix), and
nothing merges unless green, so the open PR stays **pristine and merge-ready to
`main` at all times**. See `CLAUDE.md` → "Parallel execution — git worktrees and
wave PRs" and "Bugs found during a wave".

### 6.1 Orchestrator agent (one long-lived session)

Sources work **only** from the board's `Ready for Agent` intake list (a human
moving a card there is the authorization to work it) and drives it to Review.

**Loop:**
1. **Read** `Ready for Agent` (read-only; official `trello` MCP only).
2. **Validate** each card against the card→slice contract (one-sentence outcome,
   acceptance criteria, file/ADR links). A card missing these is flagged back to
   a human, not started.
3. **Hard-stop** any card labeled `blocked` or past due — surface it in a triage
   report; never work around it.
4. **Compute the ready set** from the dependency graph (§5): dependencies in
   Review/Done, no blockers.
5. **Claim** each ready card (`claimed-by:<session>` marker) after checking no
   other claim exists; dispatch **one sub-agent per card**, up to the wave's
   width (~3–4).
6. **Collect** each sub-agent's vertical-slice completion report (§6.3).
7. On success: verify the report (suite green + observable outcome shown), then
   **move the card one state: `In Progress` → `Review`**, and comment the
   commit/PR ref. Never `Done`/archive — a human does that.
8. On failure: **release the claim**, comment the failure, leave the card in
   place, and record it in the run ledger.
9. Maintain a **run ledger** (card → agent → status → commit/PR) and re-run the
   loop as cards clear.

**The orchestrator never writes code.** It sequences, claims, verifies reports,
moves cards one adjacent state, and reports status. Every board write references
the git commit/PR (board = intent, repo = truth).

### 6.2 Sub-agent (implementer) — one card = one vertical slice

A sub-agent may spawn a workflow or helper agents when a slice is large enough to
warrant decomposition (see `CLAUDE.md` → "Parallel execution — git worktrees and
wave PRs"); the worktree, `slice/<ticket>` branch, and single-completion-report
contract still hold, and nested agents must not write the same files at once.

1. **Claim** confirmed by the orchestrator; work in the slice's worktree on
   `slice/<ticket>` (branched off the wave branch).
2. **Red first:** write behavior-driven tests through the public surface, run
   them, observe them **fail**.
3. **Green:** implement behind the module seam until the suite passes
   (`cd engine && python -m pytest`).
4. **Demonstrate** the observable outcome (demo output, `curl`, WS frame, SQL
   rows, screenshot) — assertion alone is not done.
5. **ADR** added/updated in the **same slice** if an interface changed; index it.
6. **Deep-module review:** run `/legacy-deep-module-review` over the change
   (required gate, §3); fold small fixes in, raise an ADR / next slice for
   interface-level findings, and carry the outcome into the report.
7. **Commit / open PR**; comment the card with the commit/PR ref.
8. **Report** the completion (§6.3) back to the orchestrator. Do **not** move the
   card yourself beyond what the flow allows; the orchestrator moves it to Review.
9. Honor every standing constraint (§3): config-driven, deep-module seams,
   self-/world-directed actions, design boundary.

### 6.3 Vertical-slice completion report (sub-agent → orchestrator)

Each sub-agent returns a structured report so the orchestrator can verify without
re-reading the whole diff:

```
card:            V0-N
outcome:         <the one sentence the user can now see/do>
tests_added:     [test_names…]   result: <N passed / 0 failed>
demo:            <command run>  →  <key output proving the outcome>
files_touched:   [paths…]
config_added:    [keys/files…]
adr:             <path, or "none — no interface change">
module_review:   <"/legacy-deep-module-review ran — findings + what was done">
state_shape:     <new state() keys, if changed — else "unchanged">
commit_or_pr:    <ref>
followups_risks: [<anything deferred / newly discovered>]
```

The orchestrator treats a card as review-ready **only** when `tests_added.result`
is all-green and `demo` shows the observable outcome (Done means verified).

---

## 7. Loading these onto Trello (board `NPC`, `qBaiErHa`)

- Create one card per ticket (§4). Put the **Outcome**, **Acceptance criteria**,
  **Depends on**, and **file/ADR links** in the card description (the contract).
- Suggested labels: epic (`psychology` / `infra` / `data` / `ml` / `renderer`),
  size (`S/M/L`), and `wave-1…4`.
- **Do not** dump every card into `Ready for Agent`. A human stages a card there
  only when its dependencies are cleared — that move is the authorization. Start
  Wave 1 (`V0-2`, `V0-5`, `V0-6`, `V0-10a`) in the intake list; hold the rest in a
  backlog list until their deps reach Review/Done.
- All board writes go through the official `trello` MCP only, gated and mirrored to
  a commit/PR, per [`CLAUDE.md`](../CLAUDE.md) guardrails.

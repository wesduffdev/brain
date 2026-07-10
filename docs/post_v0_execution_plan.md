# Post-v0 Execution Plan — canonical `v1…v14` roadmap, orchestrated in waves

**Purpose.** Take the being **beyond the v0 North Star** using the same fleet
model as [`docs/v0_execution_plan.md`](v0_execution_plan.md): an **orchestrator**
that sources work from the Trello board and sequences it, and **sub-agents** that
each land one vertical slice and report completion. This document is the source
for the *post-v0* Trello cards; each ticket below maps to one card. It does **not**
restate the version detail — it links to the archive and adds ticket-level detail,
wave sequencing, and the reconciliation between the planning archive and the repo.

- v0 plan (the model this mirrors): [`docs/v0_execution_plan.md`](v0_execution_plan.md).
- Architecture / target: [`docs/BRIEF.md`](BRIEF.md) — its §18 version path is
  **superseded by the canonical `v1…v14` scheme below** (rewrite tracked by the
  `CHORE-ROADMAP` card).
- Ordered roadmap (single source of truth): [`README.md`](../README.md).
- Raw source archive (the design conversation that produced the BRIEF and this
  roadmap): `planning/past_V0.md` (on the `planning` branch). Treat it as an
  **archive**, not a spec — its first half carries the earlier baby/caregiver/
  hygiene framing that the codebase deliberately stripped (see `CONTEXT.md`
  → "Not in the language"). Only its appended `v1…v14` roadmap is forward-looking.
- How work is done here: [`CLAUDE.md`](../CLAUDE.md). Decisions: [`docs/adr/`](adr/).

---

## 1. Reconciliation — the archive vs. the repo

The `planning/past_V0.md` roadmap **assumes "v0 is complete"** and defines v0 as a
full Dockerized stack (engine + Postgres + PixiJS renderer + tick loop + object
model + interaction-event logging + training-data pipeline + a first NN in shadow
mode + config-driven tuning). **That is a larger bucket than what is on `main`.**

### 1.1 What the repo actually has (2026-07-10)

- **Merged on `main`:** psychology core (needs drift → derived emotion →
  perceived room/objects), FastAPI `/state` + WS tick stream, **always-on JWT
  auth** (the archive never mentions auth), Docker Compose (`engine` + `postgres`),
  and the full governance/ADR scaffold. That is v0 slices **V0-1, V0-2, V0-5,
  V0-6, V0-10a (ADR)** + **V0-SEC**.
- **Written but unmerged (branches):** **V0-3** environment→contextual-needs
  (`slice/v0-3`) and **V0-7** Postgres persistence seam (`slice/v0-7`) — both
  complete with tests + an ADR, awaiting the Wave-2 PR.
- **Not started:** **V0-4** (actions / rule-utility decision / safety /
  `InteractionEvent`), **V0-8** (PyTorch outcome predictor + `ml-trainer`),
  **V0-9** (shadow mode), **V0-11** (PixiJS renderer).

So the archive's `v1` cannot start yet — roughly half of what the archive calls
"v0" is still unbuilt or unmerged. **Finishing v0 is Waves 1–4 (already carded in
`v0_execution_plan.md`); this document begins at Wave 5.**

### 1.2 Decisions taken (director, 2026-07-10)

1. **Canonical version scheme = the archive's `v1…v14`.** `BRIEF.md` §18's
   `v0…v6` path is rewritten to match (see `CHORE-ROADMAP`).
2. **Sequence by dependency, not by version number.** The archive's numbers are a
   *catalogue of capabilities*, not a build order. Two capabilities are already
   built out of numeric order and land as part of finishing v0:
   - Archive **v5 (Environment awareness)** ≈ **V0-3** — *delivered early* (it is
     what makes `scared`/fear fire, a visible v0 outcome). Recorded as "v5
     delivered early," not renumbered.
   - Persistence (archive v0/v3) ≈ **V0-7** — *delivered early*.
3. **Scenario/milestone harness pulled forward.** A minimal subset of archive
   `v10` (`V10a`) ships right after the shadow NN so we can *see* the model
   learning; the full scenario system stays at `v10`.
4. **Brain-epic order follows the archive:** rule-based **concepts/beliefs (`v2`)
   before the NN goes active (`v3`)**, and **curiosity (`v4`) after** both.

### 1.3 Archive version → build mapping

| Archive version | Delivered by | Status |
|---|---|---|
| `v1` stable cognitive loop | V0-2 (perception) + V0-4 (actions) + V0-8/V0-9 (shadow predict + error) + **`v1` card** (memory records) | in progress |
| `v5` environment awareness | **V0-3** | written, unmerged — *early* |
| persistence | **V0-7** | written, unmerged — *early* |
| `v2` object concepts / beliefs | **`v2` card** | not started |
| `v3` PyTorch active (blended) | **`v3` card** (built on V0-8/V0-9 shadow) | not started |
| `v4` curiosity / surprise / exploration | **`v4` card** | not started |
| `v6` memory retrieval + traits | **`v6` card** | not started |
| `v7` graph-like concept network | **`v7` card** | not started |
| `v8` model-service sidecar | **`v8` card** | not started |
| `v9` natural language layer | **`v9` card** | not started |
| `v10` developmental scenarios | **`V10a`** (minimal) + **`v10` card** (full) | not started |
| `v11`–`v14` (pgvector · RL · multi-shell · prod split) | **`BACKLOG-OPT` card** | optional |

### 1.4 Open drift to fix (surfaced, not silently reconciled)

- **ADR-0006 collision.** `slice/v0-3` and `slice/v0-7` *independently* created
  `docs/adr/0006-*.md`. At the Wave-2 merge, one keeps `0006` and the other
  becomes `0007`, and `docs/adr/README.md` is updated. Whatever number the
  canonical-roadmap ADR takes must follow both (likely `0008`).
- **Board ahead of repo.** The board shows **V0-8** and **V0-10** in *in review*,
  but their `slice/*` branches are empty (no code). Board = intent, repo = truth —
  this is flagged for the director; the cards are **not** moved by an agent.

---

## 2. Canonical version scheme (`v1…v14`)

Full goal / feature / exit-criteria detail for each version lives in the archive
(`planning/past_V0.md`). Summary (see §4 for the ticketed subset):

```
v1  Stable cognitive loop (perception→action→predict→error→memory)   ← V0-2/4/8/9 + v1 card
v2  Object concepts and belief formation
v3  PyTorch outcome prediction becomes active (blended into decision)
v4  Curiosity, surprise, and exploration policy
v5  Environment awareness                                            ← delivered early (V0-3)
v6  Memory retrieval and long-term trait drift
v7  Graph-like concept network (Postgres node/edge tables)
v8  Model-service sidecar and multi-model inference
v9  Natural language layer (interpret + narrate, never controls sim)
v10 Developmental progression and scenario system
v11 Optional — vector memory search (pgvector)
v12 Optional — reinforcement-learning sandbox
v13 Optional — multi-shell simulation
v14 Optional — production runtime split (observability)
```

---

## 3. Standing constraints

Every post-v0 ticket inherits the v0 constraints verbatim — see
[`docs/v0_execution_plan.md` §3](v0_execution_plan.md): vertical slice →
observable outcome; TDD red-first through the public surface; config-driven
tuning; deep modules / no port until something varies; **self- and
world-directed actions only**; design boundary (harm stays abstract); ADR in the
same slice; deep-module-review gate; domain-model (`CONTEXT.md`) update per slice.

Post-v0 adds two:

- **Sequence by dependency, not version number** (§1.2). A card is dispatchable
  when its dependencies are in Review/Done, regardless of its `vN` label.
- **ML stays narrow, testable, and fallback-safe.** Each model is a focused
  module with a typed interface, metrics, and a rule-based fallback; **learned
  scores never bypass `SafetyService`** (BRIEF §12–§13). Language (`v9`) sits on
  top of the sim and never controls it (BRIEF §17).

---

## 4. The post-v0 tickets (→ Trello cards)

Copy-paste-ready card bodies carrying the `CLAUDE.md` card→slice contract. IDs use
the canonical `vN` labels (post-v0 epics) to distinguish them from the v0 slice
IDs (`V0-N`). Waves 5+ are **indicative** — re-plan each wave from the then-current
state; several epics are larger than one slice and decompose when dispatched.

---

### `CHORE-ROADMAP` — Adopt the canonical `v1…v14` roadmap in the docs

- **Epic:** Reference · **Size:** S · **Depends on:** — · **Parallel-safe with:** all · **Wave 2**
- **Outcome:** `BRIEF.md` §18 and the `README.md` roadmap describe the single
  canonical `v1…v14` scheme (this doc), and the ADR-0006 collision is resolved so
  the ADR index is internally consistent.
- **Acceptance criteria:**
  - Rewrite `BRIEF.md` §18 to the `v1…v14` scheme (link to
    `docs/post_v0_execution_plan.md` for the wave breakdown; do not restate it).
  - Update the `README.md` roadmap to reference v0 (V0-N) + post-v0 (vN) with one
    numbering scheme; keep it the ordered single source of truth.
  - Resolve the **ADR-0006 collision** (env vs. persistence → 0006/0007) and add
    an ADR recording the canonical-roadmap decision (supersedes BRIEF §18); index
    all in `docs/adr/README.md`.
  - No code change; `pytest` still green. Governance index in README updated if any
    rule text moves.
- **Files/refs:** `docs/BRIEF.md`, `README.md`, `docs/adr/`, this plan.
- **Plan:** `docs/post_v0_execution_plan.md` (CHORE-ROADMAP)

---

### Wave 5 — Close the cognitive loop & first visible learning

#### `v1` — Cognitive-loop completion: persisted memory records

- **Epic:** Psychology · **Size:** M · **Depends on:** V0-4 (events), V0-7
  (persistence), V0-9 (prediction error) · **Parallel-safe with:** `V10a`
- **Outcome:** Every meaningful interaction writes a durable **memory** record
  (object snapshot, action, expected vs. observed outcome, emotion before/after,
  prediction error, tick) that is queryable from Postgres.
- **Acceptance criteria:**
  - New `memories` table + repository port (extends V0-7's seam); `MemoryService`
    creates one memory per interaction from the `InteractionEvent` + prediction
    record. `Simulation`/services depend on the port, not SQLAlchemy.
  - Memory carries a config-driven **priority** (high prediction error / high
    emotional intensity → higher priority). No hard-coded thresholds.
  - Behavior tests (red first): an interaction produces a memory; a high-
    prediction-error interaction is flagged higher priority; retuning the
    threshold is config-only.
  - `pytest` green; documented `SELECT` shows memory rows after a Compose run.
- **Guardrails:** memories key on **perceived** object properties, never
  `developerLabel`.
- **Files/refs:** `engine/app/services/memory_service.py`,
  `engine/app/domain/memory.py`, `engine/app/ports/repositories.py`,
  `engine/app/db/`, `config/learning_rates.yaml`, BRIEF §10, §15, §16.
- **Plan:** `docs/post_v0_execution_plan.md` (v1)

#### `V10a` — Minimal scenario/milestone harness (regression metric)

- **Epic:** ML · **Size:** M · **Depends on:** V0-8, V0-9 (shadow NN +
  `prediction_records`), V0-4 · **Parallel-safe with:** `v1`
- **Outcome:** A single config-defined scenario seeds the room, runs N ticks, and
  asserts a **learning metric** (roll-prediction confidence rose after repeated
  interactions) — a repeatable way to *see* the shadow NN learning, usable as a
  regression test.
- **Acceptance criteria:**
  - `config/scenarios/rolling_object_intro.yaml` (room + objects + one
    `learning_target` + a `success_condition`) and a minimal `ScenarioRunner`
    (seed → run ticks → collect one metric → report). No full milestone system.
  - A pytest regression scenario asserts the confidence delta exceeds a
    config-driven threshold after the run; failure if learning does not occur.
  - `pytest` green; documented runner output showing the metric before/after.
- **Files/refs:** `engine/app/services/scenario_runner.py`,
  `config/scenarios/`, BRIEF §16. Full system → `v10`.
- **Plan:** `docs/post_v0_execution_plan.md` (V10a)

---

### Wave 6 — Concepts, then the network goes active

#### `v2` — Object concepts and belief formation

- **Epic:** Psychology · **Size:** L · **Depends on:** `v1` (memories), V0-4 ·
  **Parallel-safe with:** `v3`, `v8`
- **Outcome:** Repeated interactions form and strengthen **concept schemas** so a
  never-seen object inherits expectations from its perceived properties, with a
  confidence that changes over time — all independent of English labels.
- **Acceptance criteria:**
  - `ConceptService` / `BeliefService` / `SimilarityService`; tables
    `concept_schemas`, `concept_evidence`, `beliefs`, `object_similarity_records`;
    seed/learning rates in config (no hard-coded numbers).
  - Behavior tests: repeated push of round objects → `round_objects_roll`
    confidence rises; a new round object → `roll` predicted with non-zero
    confidence; a round **heavy** object that does not move → strengthens
    `heavy_objects_resist_motion` **without erasing** the original concept.
  - Concepts key on perceived properties, never `developerLabel`; `pytest` green.
- **Files/refs:** `engine/app/services/{concept_service,belief_service,similarity_service}.py`,
  `config/learning_rates.yaml`, archive `v2`, BRIEF §17.
- **Plan:** `docs/post_v0_execution_plan.md` (v2)

#### `v3` — PyTorch outcome prediction becomes active (blended)

- **Epic:** ML · **Size:** L · **Depends on:** V0-8, V0-9 (shadow validated) ·
  **Parallel-safe with:** `v2`
- **Outcome:** The decision system **blends** the PyTorch predictor with the
  rule-based predictor by config weight, with safe fallback to rules on error —
  and behavior changes only *within* the safety guardrails.
- **Acceptance criteria:**
  - `OutcomePredictor` interface with `RuleBased`, `PyTorch`, and `Ensemble`
    implementations; `config/prediction.yaml` (`rule_weight`, `neural_weight`,
    `neural_enabled`, `fallback_to_rules_on_error`).
  - `DecisionService` consumes the blended prediction; **`SafetyService` still
    hard-blocks** (learned scores never bypass it).
  - Behavior tests: model active → outcome probabilities returned; model error →
    rule fallback used; a predicted-unsafe action is still blocked. Activation is
    a config flip (shadow → active).
- **Guardrails:** learned/neural scores **never** bypass safety (BRIEF §12–§13).
- **Files/refs:** `engine/app/ports/predictor.py`,
  `engine/app/services/prediction_service.py`, `config/prediction.yaml`,
  archive `v3`, BRIEF §11, §13.
- **Plan:** `docs/post_v0_execution_plan.md` (v3)

---

### Wave 7 — Curiosity-driven exploration

#### `v4` — Curiosity, surprise, and exploration policy

- **Epic:** Psychology · **Size:** L · **Depends on:** V0-9 (prediction error),
  `v2` (novelty/familiarity from concepts) · **Parallel-safe with:** `v8`
- **Outcome:** The being preferentially explores what it cannot yet predict —
  config-weighted curiosity and surprise shift action selection toward novel /
  uncertain objects rather than treating all objects equally.
- **Acceptance criteria:**
  - `CuriosityService` / `SurpriseService` / `ExplorationPolicyService`;
    `config/decision_weights.yaml` (curiosity = novelty + uncertainty +
    recent_surprise − familiarity; action-score weights). Optional neural
    curiosity predictor starts in **shadow** only.
  - Behavior tests: a new moving object → high curiosity; an object behaving
    exactly as predicted → low surprise; high predicted discomfort → `touch`
    penalized. All weights config-only.
  - Render state exposes curiosity/surprise; `pytest` green.
- **Files/refs:** `engine/app/services/{curiosity_service,surprise_service,exploration_policy_service}.py`,
  `config/decision_weights.yaml`, archive `v4`.
- **Plan:** `docs/post_v0_execution_plan.md` (v4)

---

### Wave 8 — Experience shapes the being

#### `v6` — Memory retrieval and long-term trait drift

- **Epic:** Psychology · **Size:** L · **Depends on:** `v1` (memories), `v2`
  (similarity), `v4` (curiosity) · **Parallel-safe with:** `v7`, `v8`
- **Outcome:** Prior experience changes current decisions — relevant memories are
  retrieved and bias action scores, and slow traits (caution / curiosity
  tendency) drift from repeated outcomes so the being develops individual
  tendencies.
- **Acceptance criteria:**
  - `MemoryRetrievalService` (SQL-based: same object / properties / action /
    similar outcome / high emotion / high error) + `TraitService` /
    `PreferenceService` / `PersonalityDriftService`; `config/traits.yaml`.
  - Behavior tests: a prior negative memory of a similar object → risky action
    scores drop; repeated positive exploration → curiosity trait rises slowly;
    repeated negative surprise → caution rises slowly. Trait drift is config-only
    and tested.
- **Files/refs:** `engine/app/services/{memory_retrieval_service,trait_service,preference_service,personality_drift_service}.py`,
  `config/traits.yaml`, archive `v6`.
- **Plan:** `docs/post_v0_execution_plan.md` (v6)

---

### Wave 9 — Explanation & serving

#### `v7` — Graph-like concept network

- **Epic:** Data · **Size:** L · **Depends on:** `v2` (concepts), `v6` (memory) ·
  **Parallel-safe with:** `v8`
- **Outcome:** Predictions come with an **explanation path**
  (`object → property → outcome`) drawn from a Postgres-backed concept graph, and
  edge confidence strengthens with evidence.
- **Acceptance criteria:**
  - Node/edge tables in Postgres (`HAS_PROPERTY`, `PREDICTS`, `PRODUCED`,
    `SIMILAR_TO`) with `confidence`, `evidence_count`, `last_updated_tick`,
    `source_memory_ids`; `KnowledgeGraphService` / `ConceptPathService` /
    `PredictionExplanationService`.
  - Behavior tests: round `PREDICTS` roll → explanation path includes
    `round → roll`; repeated evidence → edge confidence rises.
  - ADR **evaluates** (does not adopt) a graph DB — Postgres node/edge tables
    first.
- **Files/refs:** `engine/app/services/{knowledge_graph_service,concept_path_service,prediction_explanation_service}.py`,
  `engine/app/db/`, archive `v7`.
- **Plan:** `docs/post_v0_execution_plan.md` (v7)

#### `v8` — Model-service sidecar and multi-model inference

- **Epic:** Infra · **Size:** M · **Depends on:** `v3` (an active NN worth
  isolating) · **Parallel-safe with:** `v7`, `v9`
- **Outcome:** Model inference can run **out-of-process** behind a `model-service`
  sidecar, selected by config, and the engine falls back to rules if it is
  unavailable — the sim never stalls on a model outage.
- **Acceptance criteria:**
  - `model-service` Dockerfile + Compose service (`/predict/outcome`, `/health`,
    `/models/active`); `PredictionClient` interface with `InProcess`, `Http`, and
    `Fallback` implementations; `config/models.yaml` routing (mode / active_version
    / fallback).
  - Behavior tests: service down → fallback predictions, sim continues; service
    returns probabilities → converted to a `PredictionResult`.
  - **Only build when justified** (multiple/slow models, separate deps) — this
    card is gated on that trigger per the archive's "when needed."
- **Files/refs:** `model-service/`, `engine/app/ports/predictor.py`,
  `docker-compose.yml`, `config/models.yaml`, archive `v8`, BRIEF §6.
- **Plan:** `docs/post_v0_execution_plan.md` (v8)

---

### Wave 10 — Language & scenarios

#### `v9` — Natural language layer

- **Epic:** ML · **Size:** L · **Depends on:** V0-4 (allowed-action list), a
  stable state · **Parallel-safe with:** `v7`, `v8`
- **Outcome:** A natural-language command maps **only** to allowed actions, and
  narration describes events **without ever changing** simulation state — language
  sits on top, never in control.
- **Acceptance criteria:**
  - `LanguageCommandService` (NL → structured action, mapped to the allowed-action
    list only) / `NarrationService` (state → readable log, non-authoritative) /
    `MemorySummaryService` / `ActionValidationService`. The LLM sits behind an
    interface with a **deterministic fake** in tests (default provider: Claude —
    see the repo's `claude-api` guidance).
  - Behavior tests: an NL command referencing a visible object → allowed actions
    only, unknown/unsupported output rejected; narration does not mutate state.
- **Guardrails:** language **never** controls the sim (BRIEF §17); unsupported
  outputs are rejected.
- **Files/refs:** `engine/app/services/{language_command_service,narration_service,memory_summary_service,action_validation_service}.py`,
  archive `v9`.
- **Plan:** `docs/post_v0_execution_plan.md` (v9)

#### `v10` — Developmental progression and scenario system (full)

- **Epic:** ML · **Size:** L · **Depends on:** `V10a` + most of `v1`–`v6`
  (something to measure) · **Parallel-safe with:** `v9`
- **Outcome:** Config-defined scenarios seed a room, run N ticks, track
  developmental **milestones**, and double as **regression tests** that fail if
  expected learning does not occur.
- **Acceptance criteria:**
  - `ScenarioService` / `MilestoneService` / `ScenarioRunner` (extends `V10a`) /
    `RegressionEvaluationService`; scenarios + milestones in config.
  - Behavior tests: a rolling-object scenario → the `round_objects_roll` milestone
    progresses; a regression scenario **fails** when expected learning is absent;
    runs produce metrics.
- **Files/refs:** `engine/app/services/{scenario_service,milestone_service,scenario_runner,regression_evaluation_service}.py`,
  `config/scenarios/`, archive `v10`.
- **Plan:** `docs/post_v0_execution_plan.md` (v10)

---

### `BACKLOG-OPT` — Optional long-term versions (`v11`–`v14`)

- **Epic:** Mixed · **Size:** L · **Depends on:** a stable env + strong regression
  suite · **Wave:** backlog
- **Outcome (deferred, one card until pulled apart):** `v11` pgvector memory
  search (when property-SQL retrieval is not enough) · `v12` reinforcement-learning
  sandbox (only after env stable + rewards designed + safety constraints + strong
  regression suite) · `v13` multi-shell simulation · `v14` production runtime split
  (metrics / tracing / structured logs / model-drift monitoring).
- **Acceptance criteria:** each becomes its own card with the full contract when a
  concrete trigger exists; until then this card only holds intent and links.
- **Files/refs:** archive `v11`–`v14`.
- **Plan:** `docs/post_v0_execution_plan.md` (BACKLOG-OPT)

---

## 5. Dependency graph & parallel waves

Cards depend on the **public surface** of their predecessors. A card is
dispatchable when its dependencies are in Review/Done and it carries no
`blocked`/overdue label. Waves 1–4 (v0) are in [`v0_execution_plan.md` §5](v0_execution_plan.md).

```
[v0 Waves 1–4 complete: V0-2…V0-11 + V0-SEC]
        │
Wave 5  ├── v1 (memory records) ── V10a (min scenario harness)
        │        │
Wave 6  │        ├── v2 (concepts/beliefs) ─┐
        │        │                          │
        │        └── v3 (NN blended) ───────┤  (v2 ∥ v3)
        │                                   │
Wave 7  │            v4 (curiosity/surprise/exploration)
        │                     │
Wave 8  │            v6 (memory retrieval + trait drift)
        │                     │
Wave 9  │            v7 (concept graph)  ∥  v8 (model-service sidecar)
        │                                        │
Wave 10 │            v9 (NL layer)  ∥  v10 (full scenario system)
        │
Backlog └── v11 pgvector · v12 RL · v13 multi-shell · v14 prod split
```

| Wave | Runs in parallel | Unblocks | Notes |
|------|------------------|----------|-------|
| **2** | `CHORE-ROADMAP` (alongside landing V0-3/V0-7) | consistent docs/ADRs | Resolves the ADR-0006 collision. |
| **5** | `v1`, `V10a` | `v2`, `v6`, the learning metric | Needs v0 (V0-4/7/8/9) in Review/Done. |
| **6** | `v2`, `v3` | `v4`, `v7` | `v2` needs `v1`; `v3` needs the shadow NN. Disjoint files. |
| **7** | `v4` | `v6` | Needs prediction error + concepts. |
| **8** | `v6` | `v7` | Memory retrieval + traits. |
| **9** | `v7`, `v8` | `v10` | `v8` gated on the "multiple/slow models" trigger. |
| **10** | `v9`, `v10` | roadmap through archive `v10` | `v9`/`v10` are independent. |

**Effective parallel width post-v0 ≈ 1–2 sub-agents** — the cognitive epics are
more sequential than the v0 slices (each builds on the last's learned state). The
independent lanes worth parallelizing are `v8` (serving) and `v9` (language),
which do not touch the cognitive core.

**Coordination hotspots the orchestrator must guard:**
- **`config/` growth** — each epic adds a config file (`learning_rates`,
  `decision_weights`, `prediction`, `traits`, `models`, `scenarios`); keep
  `ConfigService` the only reader.
- **`db/` schema** — `v1`, `v2`, `v7` add tables via the V0-7 repository seam;
  migrations must be additive and ordered.
- **`predictor` port** — shared by V0-9, `v3`, `v8`; pin its interface in `v3`'s
  ADR so `v8` swaps the implementation without touching callers.
- **Safety invariant** — `v3`/`v4`/`v9` all feed the decision system; none may let
  learned/language output bypass `SafetyService`.

---

## 6. Orchestration model

Identical to [`v0_execution_plan.md` §6](v0_execution_plan.md): one long-lived
**orchestrator** sources cards only from the `Ready for Agent` intake list,
validates the card→slice contract, computes the ready set from §5, claims and
dispatches **one sub-agent per card** (≤ the wave's width), collects the
vertical-slice completion report (§6.3 there), verifies (suite green + observable
outcome), moves the card one state to Review, and mirrors every write to a
commit/PR. Sub-agents work in `slice/<ticket>` worktrees off the wave branch,
red-first TDD, run the deep-module-review + domain-model gates, and never write to
the board. Each wave rolls up into a single `wave/<n>` → `main` PR; defects found
in an open wave PR are ticketed and healed on `hotfix/<ticket>` so the PR stays
pristine and merge-ready.

---

## 7. Loading these onto Trello (board `NPC`, `qBaiErHa`)

- One card per ticket in §4, created in the **`planned`** list (not
  `Ready for Agent` — a human stages a card there only when its deps are cleared;
  that move is the authorization to work it).
- Card body = the ticket's **Outcome / Depends·Parallel·Wave·Epic·Size /
  Acceptance criteria / Guardrails / Files·refs / Plan** — the copy-paste blocks
  above. Title format matches v0: `vN — Title  [epic·size·wave]`.
- `CHORE-ROADMAP` is the near-term one (Wave 2); the rest hold in `planned` until
  their dependencies reach Review/Done.
- All board writes go through the official `trello` MCP only, gated and mirrored to
  a commit/PR, per [`CLAUDE.md`](../CLAUDE.md) guardrails. Board = intent, repo =
  truth.

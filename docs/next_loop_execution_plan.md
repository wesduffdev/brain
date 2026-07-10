# Next-Loop Execution Plan — live wave ledger (post-v0)

**Purpose.** A *living* orchestration ledger for the loop **after v0 core**. It
records the current board state, cross-references every post-v0 plan ticket
against its Trello card, sequences the v0-finisher cards that the canonical plan
predates, and gives a concrete parallel-wave table (with the file-overlap
hotspots) so the orchestrator can dispatch each wave from the *then-current*
state without re-deriving it.

This file **does not restate** the roadmap or the ticket bodies — it links to
the sources and adds only the live delta:

- Canonical post-v0 roadmap (`v1…v14`, waves, ticket bodies):
  [`docs/post_v0_execution_plan.md`](post_v0_execution_plan.md).
- v0 plan (the model this mirrors): [`docs/v0_execution_plan.md`](v0_execution_plan.md).
- How work is done here (slice discipline, TDD, board + worktree/PR guardrails):
  [`CLAUDE.md`](../CLAUDE.md). Decisions: [`docs/adr/`](adr/).
- Ordered roadmap single source of truth: [`README.md`](../README.md).

> **Snapshot date: 2026-07-10.** Board = intent, repo = truth. Re-read the board
> and re-plan each wave before dispatching — the "dispatch state" section below
> is a point-in-time record, not a standing instruction.

---

## 1. Board snapshot (NPC board, `qBaiErHa`)

- **done (16):** V0-2, V0-3, V0-4, V0-5, V0-6, V0-7, V0-7b, V0-8, V0-8b, V0-9,
  V0-10, V0-10a, V0-11, V0-SEC, DEV-INTAKE-GATE, DEMO-OBJ. → **all of v0 core is
  merged.**
- **in progress (1):** **V0-SAFE** (this loop's active slice — see §5).
- **Ready for Agent (0)** · **in review (0)**.
- **planned:** CHORE-ROADMAP, V0-DB, V0-RT, v1, V10a, v2, v3, v4, v6, v7, v8, v9,
  v10, BACKLOG-OPT, WAVE-PLAN (this card).

---

## 2. Cross-reference — post-v0 plan ticket → Trello card

Every ticket in [`post_v0_execution_plan.md` §4](post_v0_execution_plan.md)
**already has a card**. No plan part is missing a ticket.

| Plan ticket | Card | List |
|---|---|---|
| `CHORE-ROADMAP` | present | planned |
| `v1` (memory records) | present | planned |
| `V10a` (min scenario harness) | present | planned |
| `v2` (concepts/beliefs) | present | planned |
| `v3` (NN blended active) | present | planned |
| `v4` (curiosity/surprise) | present | planned |
| `v6` (memory retrieval + traits) | present | planned |
| `v7` (concept graph) | present | planned |
| `v8` (model-service sidecar) | present | planned |
| `v9` (NL layer) | present | planned |
| `v10` (full scenario system) | present | planned |
| `BACKLOG-OPT` (`v11`–`v14`) | present | planned |

---

## 3. v0-finisher cards the plan predates

Three executable cards exist on the board that `post_v0_execution_plan.md` (a
snapshot from earlier on 2026-07-10) does **not** sequence. They are the real
"finish v0" work and they gate the start of Wave 5:

| Card | What it does | Depends on (all done) | Gates |
|---|---|---|---|
| **V0-SAFE** | Reshape `SafetyService`: invariant floor + allowed recoverable harm with honest abstract state deltas → `observed_outcome` → training examples. | ADR 0013 (merged), V0-4, V0-9 | learned avoidance fully closes at `v3` |
| **V0-RT** | Wire the Postgres event/training/prediction repos into the **runtime** `Simulation` (behind `main.py`/bootstrap + demo) when `DATABASE_URL` is set. | V0-7b, V0-9 | **prerequisite for `v1`** (memories build on persisted interaction + prediction data) |
| **V0-DB** | DB connection hardening: retry-until-ready + `make db-up` + README recipe; V0-7 `[postgres]` integration tests green against a live DB. | V0-7 | robust Compose bring-up |

**Implication:** `v1` (Wave 5) should follow **V0-RT**, not just the merged
V0-7/V0-9 seams — otherwise "persisted memory records" run against an in-memory
runtime.

---

## 4. Plan-doc staleness found (deferred, not silently reconciled)

`post_v0_execution_plan.md` §1 reflects an early-2026-07-10 snapshot and is now
stale; do **not** trust its status lines:

- §1.1 lists V0-3/V0-7 as "written, unmerged" and V0-4/V0-8/V0-9/V0-11 as "not
  started" — **all are merged/done.**
- §1.4 warns of an "ADR-0006 collision" — it **never occurred**; the ADR index
  is clean and sequential through **0013** (0006 = environmental-conditions seam,
  0007 = persistence seam).

Rewriting `BRIEF.md` §18 + the `README.md` roadmap to the canonical `v1…v14`
scheme, adding the canonical-roadmap ADR (next free number is **0014**; note
V0-SAFE may also claim 0014 — whichever lands first wins, the other takes the
next number), and refreshing §1 here are owned by the existing **`CHORE-ROADMAP`**
card. This ledger does **not** duplicate that work — it only flags it.

---

## 5. Dispatch state & the parallel-wave table

### 5.1 What is dependency-cleared right now

All deps in Review/Done, no blockers: **V0-SAFE, V0-DB, V0-RT, CHORE-ROADMAP,
V10a, v3.** (`v1` after V0-RT.)

### 5.2 File-overlap hotspots (why width is limited)

The cognitive core is more sequential than the v0 slices — a card is only
parallel-safe with another if they don't write the same file:

| File / surface | Contended by |
|---|---|
| `engine/app/simulation.py` | V0-SAFE, V0-RT, `v1` |
| `engine/app/services/decision_service.py` | V0-SAFE, `v3` |
| `engine/app/ports/predictor.py` | V0-9 (done), `v3`, `v8` |
| `engine/app/db/` schema + migrations | V0-RT, V0-DB, `v1`, `v2`, `v7` (additive, ordered) |
| `README.md` | V0-DB, CHORE-ROADMAP |
| `config/` (one new file per epic) | keep `ConfigService` the only reader |

### 5.3 Indicative waves (re-plan from current state each time)

| Wave | Dispatch in parallel | Why grouped | Then unblocks |
|---|---|---|---|
| **A (now)** | **V0-SAFE** | cognitive-core anchor (safety + decision + sim); director scoped this loop to V0-SAFE only | — |
| **A′ (parallel-safe with A)** | **V0-DB** ∥ **V10a** | disjoint files (`db/session`+`migrate`+`Makefile`; all-new `scenario_runner`+`config/scenarios/`) — could run beside V0-SAFE with no conflict | live-DB confidence; visible learning metric |
| **B** | **V0-RT** → then **CHORE-ROADMAP** ∥ **v3** | V0-RT needs `simulation.py` after V0-SAFE; v3 needs `decision_service.py` after V0-SAFE; CHORE-ROADMAP needs `README.md` after V0-DB | `v1` |
| **C** | **v1** ∥ **v3** (if not in B) | v1 needs V0-RT (persisted runtime) + memories seam | `v2`, `v6` |
| **5–10** | per [`post_v0_execution_plan.md` §5](post_v0_execution_plan.md) | cognitive epics build on each other's learned state; effective width ≈ 1–2 (independent lanes: `v8` serving, `v9` language) | roadmap through archive `v10` |

### 5.4 Current decision (director, 2026-07-10)

> **"Just V0-SAFE for now."** Wave A is dispatched (V0-SAFE, `slice/v0-safe`
> worktree, sub-agent, TDD). V0-DB / V10a / V0-RT / CHORE-ROADMAP / v3 stay in
> `planned` until the director stages the next wave. The `planning` branch is
> left as-is.

---

## 6. Orchestration recap

Unchanged from [`v0_execution_plan.md` §6](v0_execution_plan.md) /
[`post_v0_execution_plan.md` §6](post_v0_execution_plan.md): one orchestrator
sources from `Ready for Agent`, validates the card→slice contract, claims,
dispatches **one sub-agent per card** (≤ the wave's width), collects the
completion report, verifies (suite green + observable outcome), moves the card
one state to `in review`, and mirrors every write to a commit/PR. Sub-agents work
in `slice/<ticket>` worktrees, red-first TDD, run the deep-module-review +
domain-model gates, and never write to the board. A sub-agent may escalate to a
workflow for a large slice (staying inside its worktree). Each slice/wave lands
via a reviewed PR to `main`; the human's merge is `done`.

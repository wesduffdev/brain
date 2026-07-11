# 0018 — Canonical `v1…v14` roadmap

## Status

Accepted

## Date

2026-07-11

## Context

The project carried **two competing version schemes** for what comes after the
v0 Minimal Learning Loop:

- **BRIEF §18 ("Version Path")** described a `v0 — Minimal Learning Loop`
  followed by a short `v1…v6` path (`v1` prediction→curiosity, `v2`
  prediction→decision, `v3` beliefs/concepts, `v4` memory retrieval, `v5` LLM,
  `v6` graph projection).
- The **design-conversation archive** (`planning/past_V0.md`) carried a longer
  `v1…v14` capability catalogue, which `docs/post_v0_execution_plan.md` adopted,
  sequenced into waves, and reconciled against what is actually on `main`.

These schemes are **not** a renumbering of the same milestones — the BRIEF's
`v1…v6` do not map one-to-one onto the archive's `v1…v14` (e.g. the BRIEF's `v5`
is the LLM layer, which is `v9` in the canonical scheme). Two source-of-truth
documents disagreeing on what "v2" means is exactly the drift the "one source of
truth per fact" rule exists to prevent, and the post-v0 Trello cards were already
being minted against the `v1…v14` labels. A single canonical scheme was needed so
the brief, the README roadmap, the execution plans, and the board all speak the
same version language.

The director's decision (recorded in `docs/post_v0_execution_plan.md` §1.2,
2026-07-10) already selected the archive's `v1…v14` as canonical; this ADR
records that decision as an architecturally significant one and pins where each
fact now lives.

## Decision

**The canonical version scheme is `v1…v14`**, as catalogued and sequenced in
[`docs/post_v0_execution_plan.md`](../post_v0_execution_plan.md). One numbering,
used everywhere:

- **v0** is the Minimal Learning Loop, delivered as slices `V0-1…V0-11` +
  `V0-SEC` (all merged). It is done, not a future version.
- **`v1…v14`** is the single post-v0 capability roadmap:

  ```
  v1  Stable cognitive loop (perception→action→predict→error→memory)
  v2  Object concepts and belief formation
  v3  PyTorch outcome prediction becomes active (blended into decision)
  v4  Curiosity, surprise, and exploration policy
  v5  Environment awareness (delivered early as V0-3)
  v6  Memory retrieval and long-term trait drift
  v7  Graph-like concept network (Postgres node/edge tables)
  v8  Model-service sidecar and multi-model inference
  v9  Natural language layer (interpret + narrate, never controls the sim)
  v10 Developmental progression and scenario system
  v11 Optional — vector memory search (pgvector)
  v12 Optional — reinforcement-learning sandbox
  v13 Optional — multi-shell simulation
  v14 Optional — production runtime split (observability)
  ```

**This supersedes BRIEF §18's old `v0 — Minimal Learning Loop / v1…v6` path.**
BRIEF §18 is rewritten to carry the canonical scheme and a superseded banner; it
links to the execution plan for the per-version detail rather than restating it.

**Where each fact lives (one source of truth per fact):**

- **Ordered, status-bearing roadmap** — [`README.md`](../../README.md). The
  brief and the plans link here for order and status.
- **Per-version goals, exit criteria, wave sequencing, archive-vs-repo
  reconciliation** — [`docs/post_v0_execution_plan.md`](../post_v0_execution_plan.md).
- **Live per-wave board/dispatch state** —
  [`docs/next_loop_execution_plan.md`](../next_loop_execution_plan.md).
- **Architecture / target** — [`docs/BRIEF.md`](../BRIEF.md); its §18 now points
  at the above rather than defining a rival scheme.

**Sequence by dependency, not version number.** The `v1…v14` numbers are a
*catalogue of capabilities*, not a strict build order — a card is dispatchable
when its dependencies are in Review/Done regardless of its `vN` label (which is
why archive `v5`, environment awareness, was delivered early as `V0-3`). The wave
sequencing lives in the execution plan.

## Consequences

- **One version language everywhere.** The brief, README roadmap, execution
  plans, and Trello cards all refer to the same `v1…v14` capabilities; "v2" means
  one thing (object concepts), not two.
- **BRIEF §18's old `v1…v6` path is retired.** It survives only as history behind
  a superseded banner; readers are routed to the canonical scheme. Per the ADR
  discipline, the old text is not silently deleted — it is marked superseded.
- **No code change.** This is a documentation/decision alignment only; the test
  suite is unaffected and stays green.
- **Numbers are a catalogue, not a schedule.** Because sequencing is by
  dependency, the roadmap's `vN` order is not a promise of build order; the
  authoritative order and status live in the README roadmap and the live ledger,
  which the plans link to.
- **Follow-up (roadmap hygiene):** as post-v0 slices land, keep the README
  roadmap's statuses and the live ledger current; the canonical scheme itself is
  stable and should change only by a superseding ADR.

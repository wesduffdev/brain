# 0021 — Graph-like concept network (explanation paths over Postgres node/edge tables)

## Status

Accepted

## Date

2026-07-11

## Context

The being already generalizes: repeated interactions form **concept schemas**
(`round → rolls`), per-object **beliefs**, and perceived-property **similarities**
(ADR 0019, card v2). But those live as flat rows. A prediction the being makes
arrives *bare* — "this thing will roll" — with no walkable account of *why*. Card
v7 asks for the next representation: the being's learning as a **graph** it can
traverse, so a prediction comes with the `object → property → outcome`
**explanation path** that justifies it, and so a relationship's confidence
strengthens as evidence accrues.

This raises a storage question the card names explicitly: **should the graph live
in a dedicated graph database (Neo4j, Memgraph, a property-graph engine), or in
node/edge tables in the Postgres the engine already runs?** The card requires this
ADR to *evaluate* that choice, not silently take one.

The established constraints still hold: config-driven tuning (no hard-coded
rates), the repository port as the only persistence seam (in-memory fake +
Postgres adapter), writes staged inside the interaction's unit of work (ADR 0017),
and nothing keyed on `developerLabel` (ADR 0002).

## Decision

### 1. A graph *projected over* the v2 concept layer, not a second source of truth

The concept graph is a **view** built from what the cognitive layer already
learns. Each interaction, the `Simulation` hands the graph the concepts it just
formed, the object it perceived, the outcomes it observed, and the similarities it
recorded (the return values of the v2 services — the concept services are read,
never edited). The graph projects those into:

- **Nodes** — `OBJECT`, `PROPERTY`, `OUTCOME`, keyed on perceived tokens
  (`being|kind|label`), upserted so a thing met again is the same node.
- **Edges** — typed and directed, upserted by `being|kind|source|target`:
  - `HAS_PROPERTY` (object → each perceived property),
  - `PREDICTS` (each concept's property → its outcome — the concept relationship
    in graph form),
  - `PRODUCED` (object → each observed outcome),
  - `SIMILAR_TO` (object → each peer found alike).

Each edge carries `confidence`, `evidence_count`, `last_updated_tick`, and
`source_memory_ids` — the interactions (`being:tick`) behind it, so an edge is
reconcilable to the v1 memories that formed it.

Three deep services:

- **`KnowledgeGraphService`** — `witness(...)` projects one interaction, *upserting*
  each edge in place: it reads the edge's current confidence, nudges it toward
  certainty by the config-driven `GraphEdgePolicy` (`c ← c + rate·(1−c)`, the same
  saturating curve concept confidence uses, tuned independently in
  `learning_rates.yaml` `graph.edge`), increments its evidence count, stamps the
  tick, and merges in the interaction's source-memory ids.
- **`ConceptPathService`** — pure graph traversal: given an ordered *template* of
  edge kinds (`HAS_PROPERTY` then `PREDICTS`), it walks the being's graph and
  returns every matching `object → property → outcome` path, optionally pinned to a
  start/end node. One method serves both "explain this prediction" and "every
  prediction the graph supports"; a path's confidence is its weakest edge.
- **`PredictionExplanationService`** — the bridge from a raw walk to a
  prediction's reason: it fixes the explanation template, asks the path service to
  walk it, and returns an `ExplanationPath` (object, mediating property, outcome,
  aggregate confidence). `explanations(being_id)` keeps the strongest walk per
  (object, outcome).

Ports/adapters: one `GraphRepository` (`save_node`/`save_edge` upsert,
`get_edge`, `nodes`, `edges`) with an in-memory fake and a `PostgresGraphRepository`.
Wiring: `Simulation` gains one optional `graph_repository` param; when injected,
`witness` runs inside the *same* `with self._uow.begin()` an interaction already
opens, so the graph updates atomically with the event it learned from. Observable
via `Simulation.explanations()`; with no graph port the being is unchanged (opt-in,
mirroring memory/concepts). `bootstrap.build_simulation` wires the Postgres adapter
on the DB path.

`graph_edges.source_id`/`target_id` are plain indexed links to `graph_nodes`, **not
DB foreign keys** — node and edge are staged together in one unit, and a natural-key
FK only forces a brittle intra-unit insert ordering without adding integrity the
unit already guarantees (the same reasoning as `concept_evidence.concept_id`, ADR
0019).

### 2. Postgres node/edge tables first — a dedicated graph DB is EVALUATED and DEFERRED, not adopted

We considered a dedicated property-graph database:

- **A dedicated graph DB (Neo4j / Memgraph / property-graph engine).** *For:*
  native traversal (Cypher), indexes tuned for multi-hop pathfinding, a natural fit
  for a graph that may later grow deep (transitive similarity, multi-hop
  inference). *Against:* a **whole second datastore** to run, back up, secure, and
  keep transactionally consistent with the Postgres that holds every other learned
  fact — the explanation edge and the `interaction_event`/`memory` it derives from
  could no longer commit in **one unit of work** (ADR 0017); the atomic-per-
  interaction invariant would break or need a distributed-transaction contortion.
  It adds an operational dependency and a query language for a graph that is, today,
  **two hops deep** (`object → property → outcome`) over a handful of objects.
- **Postgres node/edge tables (chosen).** Two ordinary tables behind the existing
  repository seam. *For:* the graph commits in the **same transaction** as the
  interaction that grew it; one datastore, one backup, one auth story; the two-hop
  walk this card needs is a trivial adjacency traversal in application code
  (`ConceptPathService`), needing no graph engine; retuning stays config-only.
  *Against:* deep/variable-length traversal in SQL is awkward, so if the graph
  later needs many-hop or transitive queries at scale, application-side BFS or
  recursive CTEs will strain.

**Decision: Postgres node/edge tables now.** The deep-module rule applies — *do not
introduce a tool until something varies across it.* A dedicated graph DB earns its
operational and atomicity cost only when traversal depth/scale actually demands it;
today's explanation is a fixed two-hop template. The `GraphRepository` port is the
seam that keeps the option open: if many-hop inference at scale arrives, a
graph-DB-backed adapter can be slotted behind the same port (a future ADR that
supersedes this one), without touching the services or the wire.

## Consequences

- **Predictions now come with a reason.** `Simulation.explanations()` returns, per
  prediction, the `object → property → outcome` path that justifies it — e.g.
  `obj_red_ball → round → rolls`. Demonstrated end-to-end over a 120-tick run (17
  explanations, each a well-formed path) and round-tripped through live Postgres.
- **Edges strengthen with evidence.** A `round PREDICTS rolls` edge's confidence
  rose 0.30 → 0.44 → 0.55 → 0.64 → 0.71 over five confirmations (pinned by a
  behavior test), and each edge links back to the memories (`being:tick`) that
  formed it — verified FK-consistent with real `interaction_events` on Postgres.
- **One datastore, one transaction.** The graph commits atomically with the
  interaction that grew it (ADR 0017); there is no second store to keep consistent.
- **Config-only tuning.** Edge seed/reinforcement live in `learning_rates.yaml`
  (`graph.edge`), tuned independently of concept confidence; retuning touches no
  Python (pinned by a retuning-is-config-only test).
- **The port stays the only seam; the ORM never leaks.** The behavior suite drives
  the whole layer with in-memory fakes and no database; the live-Postgres round-trip
  (skipped, never faked, when unreachable) proves the two tables land, all four edge
  kinds form, and evidence links back to interactions.
- **Coupling to watch.** `Simulation` now carries eight optional repository params
  and `_act` gates seven persistence side effects. This continues the pattern ADR
  0019 already flagged; a future slice should still consider aggregating the
  cognitive services (concepts + beliefs + similarity + graph) behind one
  `witness(interaction)` facade and bundling their repository params — an
  interface-level change, its own ADR.
- **`source_memory_ids` growth.** An edge accumulates the distinct interactions
  behind it; over a very long run its id list grows unbounded. Acceptable at v7's
  scale; a windowing/cap policy is a followup if a long-lived being bloats the row.
- **The graph-DB option is preserved, not taken.** If deep/transitive traversal at
  scale ever justifies it, a graph-DB adapter slots behind `GraphRepository` under a
  superseding ADR.

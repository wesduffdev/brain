# 0019 — Object concepts and belief formation

## Status

Accepted

## Date

2026-07-10

## Context

The being already records what it lived through: an `InteractionEvent` per action
and a durable `Memory` per interaction (ADR 0012, card v1). But memory is a log of
particulars — it does not let the being *generalize*. Card v2 asks for the next
cognitive layer: repeated interactions should form **concept schemas** so that a
never-seen object inherits expectations from its perceived properties, with a
confidence that changes over time — all independent of the developer's English
labels (ADR 0002).

This needs a place for three new pieces of behavior and their persistence:

- turning interactions into learned generalizations that strengthen with
  repetition (a concept's *confidence*),
- applying those generalizations to a specific perceived object (a *belief*),
- and scoring how alike two objects are by what the being perceives of them
  (*similarity*), the signal later slices (curiosity, generalization) will draw
  on.

The constraints are the established ones: config-driven tuning (no hard-coded
learning rates), the repository port as the only persistence seam with an
in-memory fake and a Postgres adapter, writes staged inside the interaction's
unit of work (ADR 0017), and nothing keyed on `developerLabel`.

## Decision

**A cognitive layer of three deep services over three new repository ports and
four tables, wired into the interaction's existing unit of work.**

Services (`engine/app/services/`):

- **`ConceptService`** — `observe(...)` distils one interaction into concept
  schemas keyed on `(perceived feature, action, observed outcome)`, one per
  `(property × outcome)` pair. Each is strengthened through the config-driven
  `ConceptLearningPolicy` and recorded with append-only `ConceptEvidence`.
  `concepts_for(...)` reads the concepts a set of perceived properties + an action
  bear on. Concepts for different features are distinct and coexist — learning
  that a heavy thing resists a push forms its own concept and never erases the
  belief that round things roll.
- **`BeliefService`** — `believe(...)` turns concepts into a per-object
  prediction: for a perceived object + action, it emits one `Belief` per foreseen
  outcome, at the strongest supporting concept's confidence, so a never-seen
  object inherits an expectation purely from what it looks like. It holds a
  `ConceptService` as a real collaborator below the seam.
- **`SimilarityService`** — `similarity(a, b)` is the Jaccard overlap of two
  perceived-property sets; `record(...)` lays down `ObjectSimilarityRecord`s for
  the object being acted on against the others perceived. Its signal is the
  deliverable here; its consumer arrives in a later slice.

Confidence model (`ConceptLearningPolicy`, config `learning_rates.yaml`
`concept.learning`): a concept starts at `seed_confidence` on first sighting and
each confirming interaction moves it a fraction `reinforce_rate` toward 1.0
(`c ← c + rate·(1−c)`) — monotonic rise, diminishing returns, retunable in config
only.

Ports (`engine/app/ports/repositories.py`) and adapters
(`engine/app/repositories.py`), each with an in-memory fake and a Postgres
adapter:

- **`ConceptRepository`** — `get`/`save` (upsert by `concept_id`, so a concept
  *strengthens in place* rather than duplicating) + `add_evidence` + `all`. It
  owns both the `concept_schemas` and `concept_evidence` tables as one aggregate.
- **`BeliefRepository`** and **`SimilarityRepository`** — append-only `add`/`all`.

Tables (`engine/app/db/models.py`): `concept_schemas` (upserted),
`concept_evidence`, `beliefs`, `object_similarity_records`.

Wiring: `Simulation` gains three optional repository params; when injected, the
services run inside the *same* `with self._uow.begin()` an interaction already
opens (ADR 0017), so a concept strengthens, a belief forms, and similarities are
recorded atomically with the event they were learned from. Like memory, forming
concepts is a side effect of living — never read back into this tick's decision.
`bootstrap.build_simulation` wires the Postgres adapters on the DB path; with no
DB the being is unchanged (the layer is opt-in, mirroring memory). Observable via
`Simulation.concepts()`, `beliefs()`, `similarities()`.

**Keyed on perceived properties, never labels.** A concept's `feature` is a
perceived property token from the object vocabulary; there is deliberately no
`developerLabel` column or snapshot key anywhere in the layer (ADR 0002).

**Outcomes are the existing outcome vocabulary.** "Resists motion" is modeled with
the real labels — a heavy/hard object pushed produces `makes_noise` and does *not*
`roll` — rather than adding a `resists_motion` label, which would change the ML
encode contract (ADR 0008).

**`concept_evidence.concept_id` is a plain indexed link, not a DB foreign key.**
The concept and its evidence are staged together in one unit, and SQLAlchemy's
flush does not reliably order a natural-string-key parent before its child when
the two are written via `merge`/`add` without an ORM relationship. A DB-level FK
between them therefore forced a brittle intra-unit insert ordering (observed as a
`ForeignKeyViolation` under Postgres) without adding integrity the unit does not
already guarantee. The cross-aggregate FK that matters — `concept_evidence.event_id
→ interaction_events.event_id` — is kept and enforced, mirroring how `beliefs` and
`object_similarity_records` treat their perception-scoped object ids without a FK.

## Consequences

- **The being generalizes.** Repeated confirmation raises a concept's confidence
  (demonstrated on live Postgres: `round_objects_rolls` rose 0.3 → 0.99 over 20
  confirmations), and a never-seen round object is predicted to `roll` with a
  confidence that tracks the concept — expectations inherited from perceived
  properties, changing over time.
- **Multiple concepts coexist.** A heavy object that does not roll forms its own
  concept without erasing the round-rolls one, pinned by a behavior test.
- **Config-only tuning.** Seed and reinforcement live in `learning_rates.yaml`;
  retuning how fast the being commits to a pattern touches no Python (pinned by a
  retuning-is-config-only test).
- **The port stays the only seam; the ORM never leaks.** The behavior suite drives
  the whole layer with in-memory fakes and no database; the live-Postgres
  round-trip (skipped, never faked, when unreachable) proves the four tables land
  and the evidence is FK-linked to its interaction_event.
- **Coupling to watch.** `Simulation` now carries seven optional repository params
  and `_act` gates six persistence side effects. This mirrors the established
  memory/prediction pattern and is not worse than the status quo, but a future
  slice should consider aggregating the cognitive services behind one facade (a
  `witness(interaction)` call) and bundling the repository params — an
  interface-level change, its own ADR.
- **Similarity's consumer is deferred.** `SimilarityService` produces and persists
  a real signal now; blending it into belief formation (inheriting from *similar*,
  not just property-matching, objects) is a later slice.

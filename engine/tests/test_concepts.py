"""Behavior of object concepts and belief formation (card v2).

Repeated interactions turn into learned CONCEPT SCHEMAS — generalizations keyed
on the object's PERCEIVED properties (never a developer label, ADR 0002): "a
round thing, when pushed, rolls." A concept carries a CONFIDENCE that rises the
more the being sees it confirmed. From those concepts the being forms BELIEFS: a
never-seen object inherits an expected outcome purely from the properties it is
perceived to share with things the being already understands, with a non-zero
confidence. A SimilarityService scores how alike two objects are by their
perceived-property overlap, recording the signal later slices (curiosity,
generalization) will consume.

These pin the behavior through public surfaces:

- the `ConceptService` — repetition raises a concept's confidence; a heavy object
  that does not roll forms its OWN concept without erasing the round-rolls one;
- the `BeliefService` — a never-seen object inherits a prediction (>0 confidence)
  from its perceived properties;
- the `SimilarityService` — more shared perceived properties means higher
  similarity;
- the `ConfigService` — retuning the concept learning rate is config-only;
- the `Simulation` — a run forms concepts keyed on perceived properties (never a
  developer label), strengthens them, and records beliefs + similarities;
- a live-Postgres round-trip — concept/evidence/belief/similarity rows land, the
  evidence FK-linked to its interaction_event (skipped, never faked, when
  Postgres is unreachable).
"""
from __future__ import annotations

import os

import pytest

from app.bootstrap import build_simulation
from app.config_service import ConfigService
from app.db import models
from app.db.migrate import create_all, drop_all
from app.db.session import create_db_engine, session_factory
from app.repositories import (
    InMemoryBeliefRepository,
    InMemoryConceptRepository,
    InMemorySimilarityRepository,
)
from app.services.belief_service import BeliefService
from app.services.concept_service import ConceptService
from app.services.similarity_service import SimilarityService
from app.simulation import Simulation

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _concept_service(config: ConfigService = None) -> ConceptService:
    config = config or ConfigService.from_files(_CONFIG_ROOT)
    return ConceptService(InMemoryConceptRepository(), config.concept_learning_policy())


def _push_round(service: ConceptService, times: int) -> None:
    """Push a round object that rolls, `times` times — one distinct object each
    time, so the concept is built from repeated PERCEPTION, not one object."""
    for tick in range(1, times + 1):
        service.observe(
            being_id="being_001",
            tick=tick,
            object_id=f"obj_ball_{tick}",
            action="push",
            perceived_properties=("round",),
            observed_outcomes=("rolls",),
        )


def _round_rolls_confidence(service: ConceptService) -> float:
    concepts = service.concepts_for(
        being_id="being_001", perceived_properties=("round",), action="push"
    )
    return next(c for c in concepts if c.outcome == "rolls").confidence


def _cognitive_sim(config: ConfigService) -> Simulation:
    return Simulation(
        config,
        concept_repository=InMemoryConceptRepository(),
        belief_repository=InMemoryBeliefRepository(),
        similarity_repository=InMemorySimilarityRepository(),
    )


# --- ConceptService: repetition strengthens a concept ------------------------


def test_repeated_confirming_interactions_raise_a_concepts_confidence():
    service = _concept_service()
    confidences = []
    for tick in range(1, 6):
        concepts = service.observe(
            being_id="being_001",
            tick=tick,
            object_id=f"obj_ball_{tick}",
            action="push",
            perceived_properties=("round",),
            observed_outcomes=("rolls",),
        )
        roll = next(c for c in concepts if c.feature == "round" and c.outcome == "rolls")
        confidences.append(roll.confidence)

    # confidence rises monotonically with repetition and ends above one sighting
    assert confidences == sorted(confidences)
    assert confidences[-1] > confidences[0]


# --- BeliefService: a never-seen object inherits a prediction ----------------


def test_a_never_seen_object_inherits_a_prediction_from_perceived_properties():
    service = _concept_service()
    _push_round(service, times=5)

    beliefs = BeliefService(service, InMemoryBeliefRepository()).believe(
        being_id="being_001",
        tick=99,
        object_id="obj_never_seen",
        perceived_properties=("round", "blue"),  # shares only `round` with the seen balls
        action="push",
    )

    rolls = next((b for b in beliefs if b.outcome == "rolls"), None)
    assert rolls is not None, "a round object should be expected to roll"
    assert rolls.confidence > 0.0
    assert rolls.object_id == "obj_never_seen"


# --- a heavy object forms its own concept without erasing round-rolls --------


def test_a_heavy_object_forms_its_own_concept_without_erasing_round_rolls():
    service = _concept_service()
    _push_round(service, times=5)
    round_before = _round_rolls_confidence(service)

    # a round, HEAVY object that does NOT roll — it makes noise instead. ("resists
    # motion" is modeled with the real outcome vocab: it makes_noise and does not
    # roll; there is no `resists_motion` label — that would change the ML encode
    # contract.)
    service.observe(
        being_id="being_001",
        tick=6,
        object_id="obj_heavy_ball",
        action="push",
        perceived_properties=("round", "heavy"),
        observed_outcomes=("makes_noise",),
    )

    heavy = service.concepts_for(
        being_id="being_001", perceived_properties=("heavy",), action="push"
    )
    heavy_concept = next((c for c in heavy if c.outcome == "makes_noise"), None)
    assert heavy_concept is not None and heavy_concept.confidence > 0.0

    # the original round->rolls concept still stands, unchanged (not erased)
    assert _round_rolls_confidence(service) == round_before


# --- concepts key on perceived properties, never a developer label -----------


def test_a_run_forms_concepts_keyed_on_perceived_properties_never_a_label():
    config = ConfigService.from_files(_CONFIG_ROOT)
    sim = _cognitive_sim(config)
    for _ in range(80):
        sim.tick()

    concepts = sim.concepts()
    assert concepts, "a run should form at least one concept"
    property_vocab = set(config.object_property_vocab())
    for concept in concepts:
        # the object snapshot is what the being PERCEIVED, never the label
        assert "developerLabel" not in concept
        # a concept keys on a perceived property token from the vocabulary
        assert concept["feature"] in property_vocab


def test_a_run_strengthens_concepts_and_records_beliefs():
    config = ConfigService.from_files(_CONFIG_ROOT)
    sim = _cognitive_sim(config)
    for _ in range(120):
        sim.tick()

    concepts = sim.concepts()
    assert concepts
    # a concept the being met more than once has been reinforced past one sighting
    assert any(concept["evidenceCount"] > 1 for concept in concepts)

    beliefs = sim.beliefs()
    assert beliefs, "the being should form beliefs about the objects it perceives"
    assert all(belief["confidence"] >= 0.0 for belief in beliefs)


# --- retuning concept learning is config-only --------------------------------


def test_retuning_concept_learning_rate_is_config_only():
    slow = ConfigService.from_dict(
        tick_rates={},
        emotions={},
        learning_rates={"concept": {"learning": {"seed_confidence": 0.2, "reinforce_rate": 0.1}}},
    )
    fast = ConfigService.from_dict(
        tick_rates={},
        emotions={},
        learning_rates={"concept": {"learning": {"seed_confidence": 0.2, "reinforce_rate": 0.6}}},
    )

    def final_confidence(config: ConfigService) -> float:
        service = ConceptService(InMemoryConceptRepository(), config.concept_learning_policy())
        _push_round(service, times=5)
        return _round_rolls_confidence(service)

    # the SAME five interactions yield a higher confidence purely from config
    assert final_confidence(fast) > final_confidence(slow)


# --- SimilarityService -------------------------------------------------------


def test_more_shared_perceived_properties_means_higher_similarity():
    service = SimilarityService(InMemorySimilarityRepository())

    near = service.similarity(("round", "red", "smooth"), ("round", "red"))
    far = service.similarity(("round",), ("square", "heavy"))

    assert near > far
    assert far == 0.0


def test_a_run_records_object_similarities_between_perceived_objects():
    config = ConfigService.from_files(_CONFIG_ROOT)
    sim = _cognitive_sim(config)
    for _ in range(80):
        sim.tick()

    similarities = sim.similarities()
    assert similarities, "with several objects in the room, similarities are recorded"
    for record in similarities:
        assert 0.0 <= record["similarity"] <= 1.0


# --- live Postgres round-trip (skipped when unreachable, never faked) --------


def _reachable_postgres_or_skip():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — skipping live Postgres round-trip")
    try:
        engine = create_db_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
    except Exception as exc:  # noqa: BLE001 — any connect failure means "skip, don't fake"
        pytest.skip(f"Postgres not reachable at DATABASE_URL ({type(exc).__name__}) — skipping")
    return engine


@pytest.mark.integration
def test_concept_evidence_belief_and_similarity_rows_land_via_postgres():
    engine = _reachable_postgres_or_skip()
    drop_all(engine)  # fresh schema so the counts below see only this run
    create_all(engine)

    config = ConfigService.from_files(_CONFIG_ROOT)
    built = build_simulation(config, env={"DATABASE_URL": os.environ["DATABASE_URL"]})
    sim = built.simulation
    try:
        for _ in range(80):
            sim.tick()

        session = session_factory(engine)()
        try:
            assert session.query(models.ConceptSchema).count() > 0
            assert session.query(models.ConceptEvidence).count() > 0
            assert session.query(models.Belief).count() > 0
            assert session.query(models.ObjectSimilarityRecord).count() > 0

            # every piece of concept evidence is FK-linked to a real interaction_event
            event_ids = {row.event_id for row in session.query(models.InteractionEvent).all()}
            for row in session.query(models.ConceptEvidence).all():
                assert row.event_id in event_ids

            # concepts key on perceived property tokens, never a developer label
            labels = {obj.developer_label for obj in session.query(models.ObjectRecord).all()}
            for concept in session.query(models.ConceptSchema).all():
                assert concept.feature not in labels
        finally:
            session.close()
    finally:
        built.close()
        engine.dispose()

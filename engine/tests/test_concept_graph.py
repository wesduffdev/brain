"""Behavior of the graph-like concept network (card v7).

The being's learned concepts, beliefs, and similarities are projected into a
GRAPH: object / property / outcome NODES joined by EDGES (`HAS_PROPERTY`,
`PREDICTS`, `PRODUCED`, `SIMILAR_TO`). Every EDGE carries a CONFIDENCE that
strengthens the more evidence the being accrues, an `evidence_count`, the tick it
was last updated, and the `source_memory_ids` linking it back to the interactions
that produced it (card v1). The payoff is an EXPLANATION PATH: a prediction the
being makes about an object comes with the `object → property → outcome` path
through the graph that justifies it, drawn from a Postgres-backed node/edge store.

These pin the behavior through public surfaces:

- the `KnowledgeGraphService` — repeated confirming evidence raises an edge's
  confidence; witnessing links the edge back to its source memories;
- the `ConceptPathService` — a `HAS_PROPERTY` then `PREDICTS` traversal finds the
  `object → property → outcome` path;
- the `PredictionExplanationService` — a `round PREDICTS rolls` graph yields an
  explanation whose path is `object → round → rolls`;
- the `ConfigService` — retuning the edge reinforcement rate is config-only;
- the `Simulation` — a run projects its concepts into a graph and exposes each
  prediction's explanation path; without a graph port there are no explanations;
- a live-Postgres round-trip — graph node/edge rows land, edges carry evidence
  and source_memory_ids that FK-link to real interaction_events (skipped, never
  faked, when Postgres is unreachable).
"""
from __future__ import annotations

import os

import pytest

from app.bootstrap import build_simulation
from app.config_service import ConfigService
from app.db import models
from app.db.migrate import create_all, drop_all
from app.db.session import create_db_engine, session_factory
from app.domain.concept import ConceptSchema
from app.domain.concept_graph import (
    HAS_PROPERTY,
    OBJECT,
    OUTCOME,
    PREDICTS,
    PRODUCED,
    SIMILAR_TO,
)
from app.domain.similarity import ObjectSimilarityRecord
from app.policies import GraphEdgePolicy
from app.repositories import (
    InMemoryBeliefRepository,
    InMemoryConceptRepository,
    InMemoryGraphRepository,
    InMemorySimilarityRepository,
)
from app.services.concept_path_service import ConceptPathService
from app.services.knowledge_graph_service import KnowledgeGraphService
from app.services.prediction_explanation_service import PredictionExplanationService
from app.simulation import Simulation

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")

BEING = "being_001"


def _graph_service(policy: GraphEdgePolicy = None) -> KnowledgeGraphService:
    policy = policy or GraphEdgePolicy(seed_confidence=0.3, reinforce_rate=0.2)
    return KnowledgeGraphService(InMemoryGraphRepository(), policy)


def _witness_round_rolls(service: KnowledgeGraphService, times: int) -> None:
    """Witness a round object that rolls, `times` times — a distinct object each
    time, so the PREDICTS edge is built from repeated evidence, not one object."""
    concept = ConceptSchema(being_id=BEING, feature="round", action="push", outcome="rolls")
    for tick in range(1, times + 1):
        service.witness(
            being_id=BEING,
            tick=tick,
            object_id=f"obj_ball_{tick}",
            perceived_properties=("round",),
            observed_outcomes=("rolls",),
            concepts=(concept,),
            similarities=(),
            source_memory_ids=(f"{BEING}:{tick}",),
        )


def _graph_sim(config: ConfigService) -> Simulation:
    return Simulation(
        config,
        concept_repository=InMemoryConceptRepository(),
        belief_repository=InMemoryBeliefRepository(),
        similarity_repository=InMemorySimilarityRepository(),
        graph_repository=InMemoryGraphRepository(),
    )


# --- KnowledgeGraphService: repeated evidence strengthens an edge ------------


def test_repeated_confirming_evidence_raises_an_edges_confidence():
    repo = InMemoryGraphRepository()
    service = KnowledgeGraphService(repo, GraphEdgePolicy(seed_confidence=0.3, reinforce_rate=0.2))
    paths = ConceptPathService(repo)

    confidences = []
    concept = ConceptSchema(being_id=BEING, feature="round", action="push", outcome="rolls")
    for tick in range(1, 6):
        service.witness(
            being_id=BEING,
            tick=tick,
            object_id=f"obj_ball_{tick}",
            perceived_properties=("round",),
            observed_outcomes=("rolls",),
            concepts=(concept,),
            similarities=(),
            source_memory_ids=(f"{BEING}:{tick}",),
        )
        predicts = next(
            p for p in paths.paths(being_id=BEING, via_kinds=(PREDICTS,)) if p.labels == ("round", "rolls")
        )
        confidences.append(predicts.confidence)

    # confidence rises monotonically with repetition and ends above one sighting
    assert confidences == sorted(confidences)
    assert confidences[-1] > confidences[0]


def test_an_edge_links_back_to_the_memories_that_produced_it():
    repo = InMemoryGraphRepository()
    _witness_round_rolls(KnowledgeGraphService(repo, GraphEdgePolicy()), times=3)

    predicts = next(
        e for e in repo.edges() if e.kind == PREDICTS
    )
    # every source memory id names a real interaction (being:tick), traceable to v1 memory
    assert predicts.source_memory_ids
    assert all(mem_id.startswith(f"{BEING}:") for mem_id in predicts.source_memory_ids)
    assert predicts.evidence_count == 3


# --- ConceptPathService: the object -> property -> outcome traversal ----------


def test_a_traversal_finds_the_object_property_outcome_path():
    repo = InMemoryGraphRepository()
    _witness_round_rolls(KnowledgeGraphService(repo, GraphEdgePolicy()), times=2)

    paths = ConceptPathService(repo).paths(
        being_id=BEING,
        via_kinds=(HAS_PROPERTY, PREDICTS),
        source_kind=OBJECT,
        target_kind=OUTCOME,
    )
    assert paths, "a round object that rolls should yield an object -> round -> rolls path"
    a_path = paths[0]
    assert a_path.labels[1] == "round"  # the mediating property
    assert a_path.labels[-1] == "rolls"


# --- PredictionExplanationService: a round PREDICTS rolls explanation ---------


def test_a_round_predicts_rolls_graph_yields_a_round_to_rolls_explanation():
    repo = InMemoryGraphRepository()
    _witness_round_rolls(KnowledgeGraphService(repo, GraphEdgePolicy()), times=4)

    explain = PredictionExplanationService(ConceptPathService(repo))
    explanation = explain.explain(being_id=BEING, object_id="obj_ball_4", outcome="rolls")

    assert explanation is not None, "the prediction should carry an explanation path"
    assert explanation.path == ("obj_ball_4", "round", "rolls")
    assert "round" in explanation.path
    assert explanation.confidence > 0.0


# --- Simulation: a run projects concepts into a graph with explanation paths --


def test_a_run_exposes_predictions_with_their_explanation_paths():
    config = ConfigService.from_files(_CONFIG_ROOT)
    sim = _graph_sim(config)
    for _ in range(120):
        sim.tick()

    explanations = sim.explanations()
    assert explanations, "a run should support at least one explained prediction"

    concept_pairs = {(c["feature"], c["outcome"]) for c in sim.concepts()}
    for exp in explanations:
        # each explanation is an object -> property -> outcome path
        assert exp["path"] == [exp["objectId"], exp["property"], exp["outcome"]]
        assert 0.0 <= exp["confidence"] <= 1.0
        # the property -> outcome step corresponds to a concept the being holds
        assert (exp["property"], exp["outcome"]) in concept_pairs


def test_a_being_with_no_graph_port_exposes_no_explanations():
    config = ConfigService.from_files(_CONFIG_ROOT)
    sim = Simulation(config)
    for _ in range(20):
        sim.tick()
    assert sim.explanations() == []


# --- retuning edge reinforcement is config-only ------------------------------


def test_retuning_edge_reinforcement_rate_is_config_only():
    slow = ConfigService.from_dict(
        tick_rates={},
        emotions={},
        learning_rates={"graph": {"edge": {"seed_confidence": 0.2, "reinforce_rate": 0.1}}},
    )
    fast = ConfigService.from_dict(
        tick_rates={},
        emotions={},
        learning_rates={"graph": {"edge": {"seed_confidence": 0.2, "reinforce_rate": 0.6}}},
    )

    def final_confidence(config: ConfigService) -> float:
        repo = InMemoryGraphRepository()
        service = KnowledgeGraphService(repo, config.graph_edge_policy())
        _witness_round_rolls(service, times=5)
        predicts = next(e for e in repo.edges() if e.kind == PREDICTS)
        return predicts.confidence

    # the SAME five witnessings yield a higher edge confidence purely from config
    assert final_confidence(fast) > final_confidence(slow)


# --- live Postgres round-trip (skipped when unreachable, never faked) ---------


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
def test_graph_node_and_edge_rows_land_via_postgres():
    engine = _reachable_postgres_or_skip()
    drop_all(engine)  # fresh schema so the counts below see only this run
    create_all(engine)

    config = ConfigService.from_files(_CONFIG_ROOT)
    built = build_simulation(config, env={"DATABASE_URL": os.environ["DATABASE_URL"]})
    sim = built.simulation
    try:
        for _ in range(120):
            sim.tick()

        # the observable payoff round-trips through Postgres
        explanations = sim.explanations()
        assert explanations
        assert all(exp["path"] == [exp["objectId"], exp["property"], exp["outcome"]] for exp in explanations)

        session = session_factory(engine)()
        try:
            assert session.query(models.GraphNode).count() > 0
            assert session.query(models.GraphEdge).count() > 0

            edges = session.query(models.GraphEdge).all()
            # every edge kind reached and every edge carries strengthening evidence
            kinds = {edge.kind for edge in edges}
            assert {HAS_PROPERTY, PREDICTS, PRODUCED, SIMILAR_TO} <= kinds
            assert all(edge.evidence_count > 0 for edge in edges)

            # source_memory_ids link edges back to real interaction_events (being:tick)
            event_ids = {row.event_id for row in session.query(models.InteractionEvent).all()}
            linked = [edge for edge in edges if edge.source_memory_ids]
            assert linked, "edges should carry the memories that produced them"
            for edge in linked:
                assert all(mem_id in event_ids for mem_id in edge.source_memory_ids)
        finally:
            session.close()
    finally:
        built.close()
        engine.dispose()

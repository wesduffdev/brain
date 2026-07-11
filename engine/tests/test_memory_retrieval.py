"""Behavior: prior experience biases current decisions (card v6).

The being does not decide from the present alone. Before it acts it RETRIEVES the
memories relevant to what it now perceives — by the same object, by similar
perceived properties (the SimilarityService's Jaccard overlap, ADR 0019), by the
same action, and weighted by how salient (emotional / surprising) each memory was
— and lets what it remembers bias the score of each *safe* candidate action. A
prior NEGATIVE memory of a SIMILAR object makes a risky action less appealing on a
new-but-alike object: the hot-lamp generalization — a burn remembered from one hot
thing makes a *new* hot thing less touchable.

The bias only ever reshuffles the SAFE candidates (it is applied after the safety
floor drops any blocked action), so neither a negative memory nor a tempting
positive one can push the being past a guardrail (BRIEF §12).

Every test asserts through a public surface: `Simulation.tick()` /
`Simulation.state()`, the `MemoryRetrievalService`, and the `PreferenceService`.
"""
from __future__ import annotations

import os
from dataclasses import replace

import pytest

from app.config_service import ConfigService
from app.db import models
from app.db.migrate import create_all, drop_all
from app.db.session import create_db_engine, session_factory
from app.db.unit_of_work import SessionUnitOfWork
from app.domain.memory import Memory
from app.repositories import InMemoryMemoryRepository, PostgresMemoryRepository
from app.services.memory_retrieval_service import MemoryRetrievalService
from app.services.preference_service import PreferenceService
from app.services.similarity_service import SimilarityService
from app.simulation import Simulation

# --- a small world: a stove (hot, previously burned) and a kettle (hot, alike) ---

_OBJECTS = {
    "properties": ["hot", "hard", "metal", "round", "soft"],
    "affordances": ["look", "touch"],
    "objects": {
        "obj_stove": {
            "developerLabel": "Stove",
            "properties": ["hot", "hard", "metal"],
            "affordances": ["look", "touch"],
        },
        "obj_kettle": {
            "developerLabel": "Kettle",
            "properties": ["hot", "hard", "round"],
            "affordances": ["look", "touch"],
        },
        "obj_pillow": {
            "developerLabel": "Pillow",
            "properties": ["soft", "round"],
            "affordances": ["look", "touch"],
        },
    },
}

# touch is by far the highest-utility action, so a being with no memory reaches out;
# observe is the safe fallback. touching something hot causes pain (aversive).
_ACTIONS = {
    "actions": {
        "observe": {
            "affordance": "look",
            "utility": {"base": 1.0, "needs": {}, "emotions": {}},
            "expected_outcomes": ["pleasant"],
            "reason": "taking a careful look",
        },
        "touch": {
            "affordance": "touch",
            "utility": {"base": 5.0, "needs": {}, "emotions": {}},
            "expected_outcomes": ["pleasant"],
            "property_outcomes": {"hot": ["causes_pain", "scary"], "soft": ["pleasant"]},
            "reason": "reaching out to touch",
        },
    }
}

_OUTCOME = {"labels": ["pleasant", "causes_pain", "scary"]}
_OUTCOME_EFFECTS = {
    "effects": {
        "causes_pain": {"safety": -40, "comfort": -20},
        "scary": {"safety": -10},
        "pleasant": {"comfort": 5},
    }
}
_EMOTIONS = {
    "rules": [{"emotion": "scared", "need": "safety", "op": "<=", "value": 30}],
    "default": "calm",
}

# preference is switched ON here (a non-zero weight) so a remembered burn biases the
# decision; the shipped default is inert unless config opts in.
_TRAITS = {
    "traits": {
        "caution": {"start": 0.5, "drift_rate": 0.02, "decision_gain": 1.0, "min": 0.0, "max": 1.0},
        "curiosity": {"start": 0.3, "drift_rate": 0.02, "decision_gain": 0.0, "min": 0.0, "max": 1.0},
    },
    "preference": {
        "weight": 1.0,
        "similarity_weight": 1.0,
        "same_object_weight": 1.0,
        "same_action_floor": 0.0,
        "salience_weight": 0.5,
    },
}


def _needs(**overrides):
    levels = {"curiosity": 40, "safety": 80, "comfort": 70}
    levels.update(overrides)
    return {
        name: {"direction": "contextual", "amount": 0, "every_ticks": 1, "min": 0, "max": 100, "start": val}
        for name, val in levels.items()
    }


def _config(*, contains, safety=None, traits=_TRAITS):
    return ConfigService.from_dict(
        {"tick": {"duration_ms": 1000}, "needs": _needs()},
        _EMOTIONS,
        rooms={"room": {"id": "room_001", "contains": list(contains)}},
        objects=_OBJECTS,
        actions=_ACTIONS,
        safety=safety or {"rules": []},
        outcome=_OUTCOME,
        outcome_effects=_OUTCOME_EFFECTS,
        traits=traits,
    )


def _burn_memory(object_id="obj_stove", properties=("hot", "hard", "metal")):
    return Memory(
        being_id="being_001",
        tick=1,
        object_id=object_id,
        action="touch",
        perceived_properties=tuple(properties),
        expected_outcome=("pleasant",),
        observed_outcome=("causes_pain", "scary"),
        emotion_before="calm",
        emotion_after="scared",
        prediction_error=0.9,
        priority=2.0,
    )


def _pleasant_memory(object_id="obj_pillow", properties=("soft", "round")):
    return Memory(
        being_id="being_001",
        tick=1,
        object_id=object_id,
        action="touch",
        perceived_properties=tuple(properties),
        expected_outcome=("pleasant",),
        observed_outcome=("pleasant",),
        emotion_before="calm",
        emotion_after="calm",
        prediction_error=0.1,
        priority=1.0,
    )


# --- the headline: a burn remembered generalizes to a new, similar hot object ---


def test_a_prior_negative_memory_of_a_similar_object_lowers_a_risky_actions_score():
    # With no memory, the being reaches out and touches the new hot object — touch
    # simply out-scores a careful look.
    naive = Simulation(_config(contains=["obj_kettle"]), memory_repository=InMemoryMemoryRepository())
    assert naive.tick()["currentAction"]["type"] == "touch"

    # But a being that remembers being burned by a SIMILAR hot thing (the stove)
    # holds back from the new one (the kettle): the memory drops touch's score
    # below the safe look. This is the hot-lamp generalization.
    scarred_store = InMemoryMemoryRepository()
    scarred_store.add(_burn_memory())
    scarred = Simulation(_config(contains=["obj_kettle"]), memory_repository=scarred_store)
    assert scarred.tick()["currentAction"]["type"] == "observe"


def test_an_unrelated_memory_leaves_the_decision_unchanged():
    # A memory of a wholly-unalike object (a soft pillow, touched pleasantly) shares
    # nothing with the hot kettle, so retrieval finds it irrelevant and the being
    # still reaches out — retrieval biases by RELEVANCE, not by merely having a past.
    store = InMemoryMemoryRepository()
    store.add(_pleasant_memory())
    sim = Simulation(_config(contains=["obj_kettle"]), memory_repository=store)
    assert sim.tick()["currentAction"]["type"] == "touch"


def test_memory_bias_never_lets_the_being_bypass_the_safety_floor():
    # touch on a hot object is hard-blocked here, and the being carries a strongly
    # POSITIVE memory of touching a similar hot object — yet the tempting memory can
    # never buy touch past the floor: the being takes the safe look instead.
    tempting = InMemoryMemoryRepository()
    tempting.add(
        Memory(
            being_id="being_001",
            tick=1,
            object_id="obj_stove",
            action="touch",
            perceived_properties=("hot", "hard", "metal"),
            expected_outcome=("pleasant",),
            observed_outcome=("pleasant",),
            emotion_before="calm",
            emotion_after="calm",
            priority=2.0,
        )
    )
    safety = {"rules": [{"action": "touch", "blocked_property": "hot", "reason": "a hot surface burns"}]}
    sim = Simulation(_config(contains=["obj_kettle"], safety=safety), memory_repository=tempting)

    state = sim.tick()

    assert state["currentAction"]["type"] == "observe"
    assert all(e["action"] != "touch" for e in sim.interactions())


# --- MemoryRetrievalService: relevance rises with similarity, action, salience ---


def test_a_more_similar_object_retrieves_a_memory_more_strongly():
    retrieval = MemoryRetrievalService(SimilarityService(InMemoryMemoryRepository()), _retrieval_policy())
    memories = [_burn_memory()]  # a burn of a (hot, hard, metal) stove

    alike = retrieval.retrieve(
        object_id="obj_kettle", perceived_properties=("hot", "hard", "round"), action="touch", memories=memories
    )
    unalike = retrieval.retrieve(
        object_id="obj_pillow", perceived_properties=("soft", "round"), action="touch", memories=memories
    )

    assert alike and alike[0].relevance > 0.0
    # a pillow shares nothing with the stove, so the burn is not retrieved for it
    assert all(rm.relevance == 0.0 for rm in unalike)


def test_a_memory_of_a_different_action_is_not_retrieved_for_this_action():
    retrieval = MemoryRetrievalService(SimilarityService(InMemoryMemoryRepository()), _retrieval_policy())
    memories = [_burn_memory()]  # remembered while TOUCHING

    # deciding whether to LOOK at a similar object: the touch-burn does not weigh in
    looking = retrieval.retrieve(
        object_id="obj_kettle", perceived_properties=("hot", "hard", "round"), action="observe", memories=memories
    )

    assert all(rm.relevance == 0.0 for rm in looking)


# --- PreferenceService: a bad memory reads negative, a good one positive ---------


def test_a_negative_memory_yields_a_negative_preference_and_a_positive_one_positive():
    preference = _preference_service()
    memories_bad = [_burn_memory()]
    memories_good = [replace(_burn_memory(), observed_outcome=("pleasant",))]

    bad = preference.valence(
        object_id="obj_kettle", perceived_properties=("hot", "hard", "round"), action="touch", memories=memories_bad
    )
    good = preference.valence(
        object_id="obj_kettle", perceived_properties=("hot", "hard", "round"), action="touch", memories=memories_good
    )

    assert bad < 0.0 < good


# --- retuning how strongly memory biases the decision is config-only -------------


def test_retuning_preference_weight_is_config_only():
    store_a = InMemoryMemoryRepository()
    store_a.add(_burn_memory())
    store_b = InMemoryMemoryRepository()
    store_b.add(_burn_memory())

    off = dict(_TRAITS, preference=dict(_TRAITS["preference"], weight=0.0))
    on = dict(_TRAITS, preference=dict(_TRAITS["preference"], weight=1.0))

    # weight 0.0: the burn is remembered but does not steer the decision → touch.
    ignored = Simulation(_config(contains=["obj_kettle"], traits=off), memory_repository=store_a)
    # weight 1.0: the same burn now holds the being back → observe. Only config changed.
    heeded = Simulation(_config(contains=["obj_kettle"], traits=on), memory_repository=store_b)

    assert ignored.tick()["currentAction"]["type"] == "touch"
    assert heeded.tick()["currentAction"]["type"] == "observe"


# --- live Postgres round-trip: a persisted memory biases the decision ------------


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
def test_a_memory_persisted_in_postgres_biases_the_decision():
    engine = _reachable_postgres_or_skip()
    drop_all(engine)
    create_all(engine)

    config = _config(contains=["obj_kettle"])
    session = session_factory(engine)()
    uow = SessionUnitOfWork(session)
    try:
        # seed the parent rows the memory's foreign keys need, then persist one burn.
        with uow.begin():
            session.merge(models.Being(being_id="being_001", needs={}, emotion="calm"))
            for entity in config.object_catalog().values():
                session.merge(
                    models.ObjectRecord(
                        object_id=entity.object_id,
                        developer_label=entity.developer_label,
                        properties=list(entity.properties),
                        affordances=list(entity.affordances),
                    )
                )
            session.merge(
                models.InteractionEvent(
                    event_id="being_001:1",
                    being_id="being_001",
                    object_id="obj_stove",
                    action="touch",
                    expected_outcome=["pleasant"],
                    observed_outcome=["causes_pain", "scary"],
                    emotion_before="calm",
                    emotion_after="scared",
                    tick=1,
                )
            )
        repo = PostgresMemoryRepository(session)
        with uow.begin():
            repo.add(_burn_memory())

        # a being reading its memory from Postgres holds back from the similar kettle
        sim = Simulation(config, memory_repository=repo, unit_of_work=uow)
        assert sim.tick()["currentAction"]["type"] == "observe"
    finally:
        session.close()
        engine.dispose()


# --- helpers -------------------------------------------------------------------


def _retrieval_policy():
    return _config(contains=["obj_kettle"]).retrieval_policy()


def _preference_service():
    config = _config(contains=["obj_kettle"])
    retrieval = MemoryRetrievalService(
        SimilarityService(InMemoryMemoryRepository()), config.retrieval_policy()
    )
    return PreferenceService(retrieval, config.outcome_effects(), config.preference_policy())

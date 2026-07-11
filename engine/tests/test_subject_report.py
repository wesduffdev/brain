"""Behaviors of the SUBJECT-QUERY surface (S3, ADR 0034): ask the being what it
KNOWS or how it FEELS about a subject, and it answers from its own learned
concepts / beliefs / explanations — grounded, keyed on PERCEIVED properties, and
honest about what it has never encountered.

Two invariants carry over from the self-report surface (S1/S2, ADR 0032) and are
pinned here:

- GROUNDING: a subject answer is built only from what the being LEARNED (its
  concepts, beliefs, graph explanations, and the emotions its memories recorded).
  It never invents a property, outcome, or feeling — and a subject it has no
  learned concept for is answered with an HONEST no-knowledge line, never a made-up
  one.
- PERCEPTION, NOT LABELS: the subject is resolved to the being's PERCEIVED
  property tokens ("hot things" -> `hot`), never a developer label or object id
  (ADR 0002).

Language sits on TOP and mutates nothing (ADR 0022): asking about a subject reads
snapshot dicts and leaves the being exactly as it was.
"""
from __future__ import annotations

import copy
import os

from fastapi.testclient import TestClient

from app.config_service import ConfigService
from app.main import create_app
from app.services.memory_summary_service import MemorySummaryService
from app.services.narration_service import NarrationService
from app.services.self_report_service import SelfReportService
from app.services.subject_report_service import SubjectReportService
from app.services.subject_resolver import SubjectResolver
from app.adapters.narrator import build_narrator

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _config() -> ConfigService:
    return ConfigService.from_files(_CONFIG_ROOT)


def _self_report(config: ConfigService) -> SelfReportService:
    """A SelfReportService WITH the S3 subject path wired, from real config —
    mirrors what `app.main` builds for `/ask`."""
    narrator = build_narrator(config)
    subject = SubjectReportService(
        narrator,
        SubjectResolver(config.object_property_vocab()),
        policy=config.subject_query_policy(),
    )
    policy = config.self_report_policy()
    return SelfReportService(
        MemorySummaryService(narrator),
        NarrationService(narrator),
        recent_count=policy.recent_count,
        subject=subject,
    )


# A being that has LEARNED about hot things: a concept (hot,touch -> causes_pain),
# the memory that taught it (touched a hot,hard thing; it hurt; felt scared), and
# the graph explanation that justifies the prediction.
def _hot_concepts():
    return [
        {
            "conceptId": "b|hot|touch|causes_pain",
            "beingId": "b",
            "feature": "hot",
            "action": "touch",
            "outcome": "causes_pain",
            "name": "hot_objects_causes_pain",
            "confidence": 0.82,
            "evidenceCount": 1,
        }
    ]


def _hot_memories():
    return [
        {
            "objectId": "obj_hot_lamp",
            "action": "touch",
            "perceivedProperties": ["hot", "hard"],
            "observedOutcome": ["causes_pain", "scary"],
            "emotionAfter": "scared",
            "priority": 1.4,
        }
    ]


def _hot_explanations():
    return [
        {
            "beingId": "b",
            "objectId": "obj_hot_lamp",
            "property": "hot",
            "outcome": "causes_pain",
            "confidence": 0.82,
            "path": ["obj_hot_lamp", "hot", "causes_pain"],
        }
    ]


# --- the subject resolver: term -> PERCEIVED property tokens -----------------


def test_resolver_maps_a_subject_term_to_perceived_property_tokens():
    resolver = SubjectResolver(_config().object_property_vocab())

    assert resolver.resolve("hot things") == ["hot"]
    assert resolver.resolve("the round red thing") == ["round", "red"]
    # a term with no perceived-property token resolves to nothing (it is unknown)
    assert resolver.resolve("dragons") == []


# --- a subject answer grounded in a learned concept --------------------------


def test_being_answers_what_it_knows_about_hot_things_from_a_learned_concept():
    report = _self_report(_config()).report(
        "what do you know about hot things?",
        memories=_hot_memories(),
        state={},
        concepts=_hot_concepts(),
        beliefs=[],
        explanations=_hot_explanations(),
    )

    assert isinstance(report, str) and report.strip()
    # keyed on the PERCEIVED property, cites the concept's property -> outcome,
    # and carries the felt emotion the memory recorded
    assert "hot" in report
    assert ("hurt" in report or "pain" in report)
    assert "scared" in report


def test_how_do_you_feel_about_also_routes_to_the_subject_path():
    report = _self_report(_config()).report(
        "how do you feel about hot things?",
        memories=_hot_memories(),
        state={},
        concepts=_hot_concepts(),
        beliefs=[],
        explanations=_hot_explanations(),
    )

    assert "hot" in report
    assert "scared" in report


def test_subject_answer_names_perceived_properties_not_the_developer_label():
    report = _self_report(_config()).report(
        "what do you know about hot things?",
        memories=_hot_memories(),
        state={},
        concepts=_hot_concepts(),
        beliefs=[],
        explanations=_hot_explanations(),
    )

    assert "hot" in report  # the perceived property
    assert "Hot Lamp" not in report  # never the developer label (ADR 0002)
    assert "obj_hot_lamp" not in report  # never the internal id


# --- grounding: honest about the unknown, never an invention -----------------


def test_a_never_encountered_subject_is_answered_honestly():
    report = _self_report(_config()).report(
        "what do you know about dragons?",
        memories=[],
        state={},
        concepts=[],
        beliefs=[],
        explanations=[],
    )

    lowered = report.lower()
    # an honest no-knowledge answer, referencing the subject
    assert "dragons" in lowered
    assert ("don't know" in lowered or "haven't" in lowered or "not encountered" in lowered)
    # and it invents no properties/outcomes/feelings
    for invented in ("hot", "round", "hurt", "pain", "scared", "rolled", "bounced"):
        assert invented not in lowered


def test_a_valid_property_never_learned_is_still_honest():
    # `square` is a real perceived property, but the being has learned nothing
    # about square things — it must NOT borrow the hot lesson or invent one.
    report = _self_report(_config()).report(
        "what do you know about square things?",
        memories=_hot_memories(),
        state={},
        concepts=_hot_concepts(),
        beliefs=[],
        explanations=_hot_explanations(),
    )

    lowered = report.lower()
    assert "square" in lowered
    assert ("don't know" in lowered or "haven't" in lowered or "not encountered" in lowered)
    assert "hurt" not in lowered and "pain" not in lowered


# --- routing: the S1 recent-experience path is untouched ---------------------


def test_a_recent_experience_query_still_uses_the_memory_path():
    report = _self_report(_config()).report(
        "what have you done recently?",
        memories=[
            {
                "objectId": "obj_x",
                "action": "push",
                "perceivedProperties": ["round", "red"],
                "observedOutcome": ["rolls"],
                "emotionAfter": "calm",
                "priority": 0.0,
            }
        ],
        state={},
        concepts=_hot_concepts(),
        beliefs=[],
        explanations=_hot_explanations(),
    )

    # the recent path renders the memory it lived, not the hot concept
    assert "round" in report
    assert "rolled" in report
    assert "hurt" not in report


# --- language mutates nothing (ADR 0022) -------------------------------------


def test_a_subject_report_mutates_nothing():
    concepts = _hot_concepts()
    memories = _hot_memories()
    explanations = _hot_explanations()
    before = copy.deepcopy((concepts, memories, explanations))

    _self_report(_config()).report(
        "what do you know about hot things?",
        memories=memories,
        state={},
        concepts=concepts,
        beliefs=[],
        explanations=explanations,
    )

    assert (concepts, memories, explanations) == before


# --- POST /ask: the subject query over the wire, behind the JWT guard --------


class _CognitiveSim:
    """A being at the Simulation seam exposing just the read-backs /ask needs for
    a subject query — its learned concepts, beliefs, graph explanations, memories,
    and present state."""

    def memories(self):
        return _hot_memories()

    def concepts(self):
        return _hot_concepts()

    def beliefs(self):
        return []

    def explanations(self):
        return _hot_explanations()

    def state(self):
        return {"emotion": "calm", "perceived": {"objects": []}}


def _client() -> TestClient:
    return TestClient(create_app(simulation=_CognitiveSim(), tick_interval_seconds=0))


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_ask_a_subject_query_returns_a_grounded_answer(mint):
    resp = _client().post(
        "/ask",
        json={"query": "what do you know about hot things?"},
        headers=_bearer(mint()),
    )

    assert resp.status_code == 200
    report = resp.json()["report"]
    assert "hot" in report
    assert ("hurt" in report or "pain" in report)


def test_ask_an_unknown_subject_is_answered_honestly_over_the_wire(mint):
    resp = _client().post(
        "/ask",
        json={"query": "what do you know about dragons?"},
        headers=_bearer(mint()),
    )

    assert resp.status_code == 200
    lowered = resp.json()["report"].lower()
    assert "dragons" in lowered
    assert ("don't know" in lowered or "haven't" in lowered)

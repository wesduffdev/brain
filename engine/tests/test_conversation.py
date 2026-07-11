"""Behaviors of a MULTI-TURN grounded conversation about what the being has READ
(reading R6, extends ADR 0039). Built on the R4 ReadingQAService + the R3 knowledge
store, so every turn keeps R4's guarantees: grounded in the retrieved passages,
CITING the source document, and honest about the unread — never fabricating.

Two things R6 adds over single-turn reading QA are pinned here:

- HISTORY-AWARE: a follow-up that names no subject of its own ("tell me more about
  that", "what else?") resolves to the subject established in earlier turns and
  stays grounded + cited — the SAME message on a fresh conversation, with no history
  to lean on, declines honestly, which proves the earlier turns are what carry it.
- STILL HONEST MID-CONVERSATION: a NEW topic the being has not read about is
  declined honestly even in the middle of a grounded conversation, never dragged
  onto a prior topic and never given a fabricated citation.

Offline: the deterministic hashing embedder + the in-memory R3 store + the in-memory
FakeLanguageModel + an in-memory turn repository, so the whole slice runs with no
model and no network.
"""
from __future__ import annotations

import copy
import os

from fastapi.testclient import TestClient

from app.config_service import ConfigService
from app.db.migrate import create_all
from app.db.unit_of_work import NullUnitOfWork, SessionUnitOfWork
from app.language.embedding import HashingEmbedder
from app.language.ingest import ingest_text
from app.language.knowledge_store import KnowledgeStore, index_document
from app.main import create_app
from app.policies import ConversationPolicy, ReadingQAPolicy
from app.ports.language_model import FakeLanguageModel
from app.repositories import (
    InMemoryConversationTurnRepository,
    InMemoryKnowledgeChunkRepository,
    PostgresConversationTurnRepository,
)
from app.services.conversation_service import ConversationService
from app.services.reading_qa_service import ReadingQAService

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")

_CATS = (
    "The cat is a small domesticated feline. Cats purr when they are content "
    "and hunt small prey at night."
)
_VOLCANO = (
    "A volcano erupts molten lava from deep underground. Volcanoes build "
    "mountains over many eruptions."
)


def _store(dim: int = 1024) -> KnowledgeStore:
    return KnowledgeStore(
        embedder=HashingEmbedder(dim=dim),
        repository=InMemoryKnowledgeChunkRepository(),
        unit_of_work=NullUnitOfWork(),
    )


def _read_cats_and_volcano() -> KnowledgeStore:
    store = _store()
    index_document(ingest_text(_CATS, source="cats.txt"), store)
    index_document(ingest_text(_VOLCANO, source="volcano.txt"), store)
    return store


def _conversation(model=None) -> ConversationService:
    """A conversation over the cats+volcano corpus. The fake model, when present,
    echoes the retrieved passage back (so a grounded answer reads naturally); with
    no model the grounded answer is EXTRACTIVE (R4). Citation comes from retrieval
    either way, so grounding holds without a model."""
    qa = ReadingQAService(_read_cats_and_volcano(), model=model, policy=ReadingQAPolicy())
    return ConversationService(
        qa,
        InMemoryConversationTurnRepository(),
        policy=ConversationPolicy(),
    )


# --- grounded + cited across turns --------------------------------------------


def test_a_multi_turn_dialogue_stays_grounded_and_cites_sources():
    convo = _conversation()

    first = convo.reply("c1", "What do you know about cats?")
    assert "From what I read" in first
    assert "cats.txt" in first and "volcano.txt" not in first

    second = convo.reply("c1", "Now tell me about volcanoes and their lava.")
    assert "From what I read" in second
    assert "volcano.txt" in second and "cats.txt" not in second


# --- a follow-up resolves to the earlier topic (history is what carries it) ----


def test_a_followup_with_no_subject_resolves_to_the_earlier_topic():
    convo = _conversation()
    convo.reply("c1", "Tell me about cats.")

    # "that" names nothing on its own — it resolves only via the earlier turn.
    followup = convo.reply("c1", "Tell me more about that.")

    assert "From what I read" in followup
    assert "cats.txt" in followup            # resolved to the cats topic
    assert "haven't read" not in followup.lower()


def test_the_same_followup_declines_without_a_conversation_to_lean_on():
    # Proof that HISTORY is what grounds the follow-up: with no prior turn the very
    # same referential message has no subject to reach and is declined honestly.
    convo = _conversation()

    cold = convo.reply("fresh", "Tell me more about that.")

    assert "haven't read" in cold.lower() or "have not read" in cold.lower()
    assert "(source:" not in cold


# --- still honest about a new unread topic mid-conversation --------------------


def test_an_unread_topic_mid_conversation_is_declined_honestly():
    convo = _conversation()
    convo.reply("c1", "Tell me about cats.")

    answer = convo.reply("c1", "What do you know about dinosaurs?").lower()

    assert "dinosaurs" in answer
    assert "haven't read" in answer or "have not read" in answer
    assert "(source:" not in answer          # no fabricated citation
    assert "cats.txt" not in answer          # not dragged onto the prior topic


# --- turns persist through the repository seam (ADR 0017) ----------------------


def test_conversation_turns_are_kept_per_conversation():
    repo = InMemoryConversationTurnRepository()
    qa = ReadingQAService(_read_cats_and_volcano(), model=None, policy=ReadingQAPolicy())
    convo = ConversationService(qa, repo, policy=ConversationPolicy())

    convo.reply("a", "Tell me about cats.")
    convo.reply("a", "What else?")
    convo.reply("b", "Tell me about volcanoes.")

    history_a = repo.history("a")
    assert [turn.user_message for turn in history_a] == [
        "Tell me about cats.",
        "What else?",
    ]
    assert all(turn.answer for turn in history_a)     # each turn kept its answer
    assert len(repo.history("b")) == 1                # conversations are independent


def test_conversation_turns_persist_and_round_trip_through_the_postgres_repo():
    # Persistence round-trip (ADR 0017): converse through a SQLAlchemy-backed turn
    # store — each reply staged in one unit of work — then reload the history with a
    # FRESH session over the SAME database. The follow-up in the SECOND turn resolves
    # via the FIRST turn read back from the store, and both turns survive the
    # round-trip, ordered. SQLite stands in for Postgres here; the live-Postgres path
    # is the @integration suite.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    Session = sessionmaker(bind=engine)

    write_session = Session()
    try:
        convo = ConversationService(
            ReadingQAService(_read_cats_and_volcano(), model=None, policy=ReadingQAPolicy()),
            PostgresConversationTurnRepository(write_session),
            policy=ConversationPolicy(),
            unit_of_work=SessionUnitOfWork(write_session),
        )
        convo.reply("c1", "Tell me about cats.")
        followup = convo.reply("c1", "Tell me more about that.")
        assert "cats.txt" in followup   # resolved via the just-persisted first turn
    finally:
        write_session.close()

    read_session = Session()
    try:
        history = PostgresConversationTurnRepository(read_session).history("c1")
        assert [turn.user_message for turn in history] == [
            "Tell me about cats.",
            "Tell me more about that.",
        ]
    finally:
        read_session.close()
        engine.dispose()


# --- config-driven -------------------------------------------------------------


def test_conversation_policy_is_read_from_config():
    policy = ConfigService.from_files(_CONFIG_ROOT).conversation_policy()
    assert policy.history_window >= 1
    assert len(policy.followup_cues) >= 1
    assert policy.is_followup("tell me more about that")
    assert not policy.is_followup("what do you know about dinosaurs")


# --- POST /chat: behind the always-on JWT guard, mutates nothing ---------------


class _Sim:
    """A being at the Simulation seam. Conversing never touches it (it reads the
    knowledge + turn stores, not the sim), so this proves /chat leaves the sim
    exactly as it was and never advances it (ADR 0022)."""

    def __init__(self) -> None:
        self.ticked = False
        self._state = {"emotion": "calm", "perceived": {"objects": []}}

    def state(self) -> dict:
        return copy.deepcopy(self._state)

    def tick(self) -> dict:
        self.ticked = True
        self._state = {"emotion": "excited", "perceived": {"objects": []}}
        return self.state()

    def memories(self):
        return []


def _chat_client(sim=None):
    convo = ConversationService(
        ReadingQAService(
            _read_cats_and_volcano(),
            model=FakeLanguageModel("Cats purr when they are content."),
            policy=ReadingQAPolicy(),
        ),
        InMemoryConversationTurnRepository(),
        policy=ConversationPolicy(),
    )
    return TestClient(
        create_app(
            simulation=sim if sim is not None else _Sim(),
            tick_interval_seconds=0,
            conversation_service=convo,
        )
    )


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_chat_without_a_token_is_rejected():
    resp = _chat_client().post(
        "/chat", json={"conversationId": "c1", "message": "about cats"}
    )
    assert resp.status_code == 401


def test_chat_with_a_bad_token_is_rejected():
    resp = _chat_client().post(
        "/chat",
        json={"conversationId": "c1", "message": "about cats"},
        headers=_bearer("nope"),
    )
    assert resp.status_code == 401


def test_chat_holds_a_grounded_cited_multi_turn_dialogue_over_the_wire(mint):
    client = _chat_client()
    headers = _bearer(mint())

    first = client.post(
        "/chat",
        json={"conversationId": "c1", "message": "What do you know about cats?"},
        headers=headers,
    )
    assert first.status_code == 200
    assert "cats.txt" in first.json()["answer"]
    assert "From what I read" in first.json()["answer"]

    # a follow-up on the SAME conversation resolves to the earlier topic
    followup = client.post(
        "/chat",
        json={"conversationId": "c1", "message": "Tell me more about that."},
        headers=headers,
    )
    assert followup.status_code == 200
    assert "cats.txt" in followup.json()["answer"]


def test_chat_about_an_unread_topic_declines_honestly_over_the_wire(mint):
    resp = _chat_client().post(
        "/chat",
        json={"conversationId": "c1", "message": "What do you know about dinosaurs?"},
        headers=_bearer(mint()),
    )
    assert resp.status_code == 200
    answer = resp.json()["answer"].lower()
    assert "dinosaurs" in answer
    assert "haven't read" in answer or "have not read" in answer
    assert "(source:" not in answer


def test_chat_leaves_the_sim_unchanged(mint):
    sim = _Sim()
    before = sim.state()

    _chat_client(sim).post(
        "/chat",
        json={"conversationId": "c1", "message": "What do you know about cats?"},
        headers=_bearer(mint()),
    )

    assert sim.state() == before   # read-only (ADR 0022)
    assert sim.ticked is False     # conversing never advances the being

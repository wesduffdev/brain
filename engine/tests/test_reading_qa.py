"""Behaviors of GROUNDED, CITED reading answers (reading R4, ADR 0039; reuses the
R3 knowledge store ADR 0038 + the language seam ADR 0022).

Ask about a document the being has READ and it answers grounded in the retrieved
passages, CITING the source document. Ask about something it has NOT read and it
says so honestly — and never fabricates a citation — optionally reasoning from
base knowledge, clearly labelled as "what I already knew" vs "what I read".

Two invariants are pinned here, exactly as the self-report/subject surfaces pin
theirs (ADR 0032/0034):

- GROUNDING BY CONSTRUCTION: the model only ever sees the RETRIEVED passages + the
  question (never the whole store), so it cannot invent grounding; and the
  citation is taken from the retrieval result, never from the model — so an unread
  topic can never carry a made-up source.
- READ vs BASE is transparent: a grounded answer is labelled as read + cites its
  source; a base-knowledge answer (when blended) is labelled distinctly.

Offline: driven by the deterministic hashing embedder + the in-memory R3 store and
the in-memory FakeLanguageModel, so the whole slice runs with no model + no network.
"""
from __future__ import annotations

import copy
import os

from fastapi.testclient import TestClient

from app.config_service import ConfigService
from app.db.unit_of_work import NullUnitOfWork
from app.language.embedding import HashingEmbedder
from app.language.ingest import ingest_text
from app.language.knowledge_store import KnowledgeStore, index_document
from app.main import create_app
from app.policies import ReadingQAPolicy
from app.ports.language_model import FakeLanguageModel
from app.repositories import InMemoryKnowledgeChunkRepository
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
    """A knowledge store on the R3 in-memory seam — the deterministic hashing
    embedder + in-memory chunk repository, no database, no network."""
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


# --- grounded + cited ---------------------------------------------------------


def test_answers_cite_the_document_they_came_from():
    store = _read_cats_and_volcano()
    model = FakeLanguageModel("Cats purr when they are content.")
    qa = ReadingQAService(store, model=model, policy=ReadingQAPolicy())

    answer = qa.answer("what do you know about cats and how they purr?")

    # grounded in the read passage, and CITES the document it came from
    assert "cats.txt" in answer
    assert "From what I read" in answer
    # it does not cite (or leak) the unrelated document
    assert "volcano.txt" not in answer
    # ...and a volcano question cites the OTHER document
    volcano = qa.answer("tell me about a volcano and its molten lava eruptions")
    assert "volcano.txt" in volcano
    assert "cats.txt" not in volcano


def test_the_grounded_prompt_contains_only_the_retrieved_passages():
    # The model must never see the whole store — only the retrieved (relevant)
    # passages + the question. An echoing fake lets us read exactly what it saw.
    store = _read_cats_and_volcano()
    fake = FakeLanguageModel(echo=True)
    qa = ReadingQAService(store, model=fake, policy=ReadingQAPolicy())

    qa.answer("what do you know about cats and how they purr?")
    prompt = fake.prompts[-1]

    assert "cat" in prompt.lower()                 # the retrieved passage is present
    assert "purr" in prompt.lower()
    assert "cats" in prompt.lower() and "how they purr" in prompt.lower()  # the question
    # the unrelated document is NOT in the prompt — retrieval, not the whole store
    assert "volcano" not in prompt.lower()
    assert "lava" not in prompt.lower()


def test_offline_default_answers_grounded_and_cited_without_a_model():
    # The default deploy narrator is the offline template (no generative model);
    # reading QA then answers EXTRACTIVELY — it quotes what it read and cites it,
    # so grounding holds with no model call at all.
    store = _read_cats_and_volcano()
    qa = ReadingQAService(store, model=None, policy=ReadingQAPolicy())

    answer = qa.answer("what do you know about cats and how they purr?")

    assert "cats.txt" in answer
    assert "purr" in answer.lower()
    assert "volcano" not in answer.lower()


# --- honest about the unread, never a fabricated citation ---------------------


def test_unread_topic_is_flagged_as_unlearned():
    store = _read_cats_and_volcano()
    qa = ReadingQAService(store, model=None, policy=ReadingQAPolicy())

    answer = qa.answer("what do you know about dinosaurs?").lower()

    assert "dinosaurs" in answer
    assert "haven't read" in answer or "have not read" in answer
    # it invents NO citation and leaks no source
    assert "(source:" not in answer
    assert "cats.txt" not in answer
    assert "volcano.txt" not in answer


def test_an_empty_store_answers_every_question_honestly():
    qa = ReadingQAService(_store(), model=None, policy=ReadingQAPolicy())

    answer = qa.answer("what do you know about cats?").lower()

    assert "haven't read" in answer or "have not read" in answer
    assert "(source:" not in answer


# --- read vs base knowledge, clearly distinguished ----------------------------


def test_base_knowledge_answer_is_labelled_distinct_from_the_read_answer():
    store = _read_cats_and_volcano()
    # A fake that answers with a recognisable base-knowledge sentence.
    model = FakeLanguageModel("Dinosaurs were large reptiles that lived long ago.")
    policy = ReadingQAPolicy(blend_base_knowledge=True)
    qa = ReadingQAService(store, model=model, policy=policy)

    answer = qa.answer("what do you know about dinosaurs?")

    # honest that it has not READ about it...
    assert "haven't read" in answer.lower() or "have not read" in answer.lower()
    # ...but offers a base-knowledge answer, clearly labelled and NOT cited as read
    assert "From what I already knew" in answer
    assert "Dinosaurs were large reptiles" in answer
    assert "From what I read" not in answer
    assert "(source:" not in answer


def test_base_knowledge_blend_can_be_turned_off():
    store = _read_cats_and_volcano()
    model = FakeLanguageModel("Dinosaurs were large reptiles that lived long ago.")
    policy = ReadingQAPolicy(blend_base_knowledge=False)
    qa = ReadingQAService(store, model=model, policy=policy)

    answer = qa.answer("what do you know about dinosaurs?")

    assert "haven't read" in answer.lower() or "have not read" in answer.lower()
    assert "From what I already knew" not in answer
    assert "Dinosaurs were large reptiles" not in answer


def test_a_grounded_answer_never_carries_the_base_knowledge_label():
    store = _read_cats_and_volcano()
    model = FakeLanguageModel("Cats purr when content.")
    qa = ReadingQAService(store, model=model, policy=ReadingQAPolicy(blend_base_knowledge=True))

    answer = qa.answer("what do you know about cats and how they purr?")

    assert "From what I read" in answer
    assert "From what I already knew" not in answer


# --- config-driven ------------------------------------------------------------


def test_reading_qa_policy_is_read_from_config():
    policy = ConfigService.from_files(_CONFIG_ROOT).reading_qa_policy()
    assert policy.k >= 1
    assert 0.0 <= policy.min_relevance <= 1.0
    assert "{topic}" in policy.unread_response
    assert isinstance(policy.blend_base_knowledge, bool)
    assert policy.read_label and policy.base_label


# --- POST /ask/reading: behind the always-on JWT guard, mutates nothing -------


class _Sim:
    """A being at the Simulation seam. Reading QA never touches it (it reads the
    knowledge store, not the sim), so this just proves the route leaves the sim
    exactly as it was (ADR 0022) and never advances it."""

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


def _reading_client(sim=None):
    store = _read_cats_and_volcano()
    qa = ReadingQAService(
        store,
        model=FakeLanguageModel("Cats purr when they are content."),
        policy=ReadingQAPolicy(),
    )
    return TestClient(
        create_app(
            simulation=sim if sim is not None else _Sim(),
            tick_interval_seconds=0,
            reading_qa_service=qa,
        )
    )


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_ask_reading_without_a_token_is_rejected():
    resp = _reading_client().post("/ask/reading", json={"query": "about cats"})
    assert resp.status_code == 401


def test_ask_reading_with_a_bad_token_is_rejected():
    resp = _reading_client().post(
        "/ask/reading", json={"query": "about cats"}, headers=_bearer("nope")
    )
    assert resp.status_code == 401


def test_ask_reading_returns_a_grounded_cited_answer_over_the_wire(mint):
    resp = _reading_client().post(
        "/ask/reading",
        json={"query": "what do you know about cats and how they purr?"},
        headers=_bearer(mint()),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert "cats.txt" in body["answer"]
    assert "From what I read" in body["answer"]


def test_ask_reading_about_an_unread_topic_declines_honestly_over_the_wire(mint):
    resp = _reading_client().post(
        "/ask/reading",
        json={"query": "what do you know about dinosaurs?"},
        headers=_bearer(mint()),
    )

    assert resp.status_code == 200
    answer = resp.json()["answer"].lower()
    assert "dinosaurs" in answer
    assert "haven't read" in answer or "have not read" in answer
    assert "(source:" not in answer


def test_ask_reading_leaves_the_sim_unchanged(mint):
    sim = _Sim()
    before = sim.state()

    _reading_client(sim).post(
        "/ask/reading",
        json={"query": "what do you know about cats?"},
        headers=_bearer(mint()),
    )

    assert sim.state() == before  # read-only (ADR 0022)
    assert sim.ticked is False    # asking never advances the being

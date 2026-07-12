"""Behaviors of the runtime DOCUMENT-INGEST endpoint (INGEST-ENDPOINT).

`POST /ingest` lets an operator hand the being a document to READ at runtime. One
call does two things at once, both through paths validated by earlier slices:

- it INDEXES the document into the being's SHARED knowledge store (the R3 store,
  ADR 0038), so `/ask/reading` and `/chat` then answer about it GROUNDED + CITED
  (reading R4/R6, ADR 0039) — where the same question was declined before; and
- it routes the document through the VALIDATED reading-as-perception door (R7,
  ADR 0040) via `Simulation.read`, so the being forms memories/concepts — the
  language model NEVER writes state (language-on-top, ADR 0022).

Offline throughout: the deterministic hashing embedder + in-memory stores + the
offline template narrator (extractive answers), so the whole slice runs with no
model and no network. Behind the always-on JWT guard (ADR 0005), like every other
protected route.
"""
from __future__ import annotations

import os

from fastapi.testclient import TestClient

from app.config_service import ConfigService
from app.main import create_app
from app.repositories import InMemoryConceptRepository, InMemoryMemoryRepository
from app.simulation import Simulation

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")

# A multi-paragraph document. "dragons" recurs across paragraphs, so it is both a
# strong retrieval signal ("tell me about dragons") and a recurring token a concept
# forms from. It shares NO content word with the unread query ("volcanoes"), so an
# unread topic stays declined even after this is ingested.
_DRAGON = (
    "Dragons are enormous winged reptiles from old legends. Dragons breathe "
    "fire and hoard gold deep inside mountain caves.\n\n"
    "Knights feared dragons because dragons could burn a whole village. People "
    "wrote many stories about brave dragons and cruel dragons.\n\n"
    "A dragon guards its treasure fiercely, and dragons rarely trust strangers."
)


def _config() -> ConfigService:
    return ConfigService.from_files(_CONFIG_ROOT)


def _sim() -> Simulation:
    """A being wired with memory + concept stores, so reading through the validated
    door forms memories/concepts the test can read back through the public surface."""
    return Simulation(
        _config(),
        memory_repository=InMemoryMemoryRepository(),
        concept_repository=InMemoryConceptRepository(),
    )


def _client(sim: Simulation) -> TestClient:
    # Only the being is injected; create_app builds the ONE shared knowledge store
    # and threads it to /ingest, reading QA, and conversation — so indexing on
    # /ingest is what the reading surfaces later answer from.
    return TestClient(create_app(simulation=sim, tick_interval_seconds=0))


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- (a) grounded + cited answering after ingest ------------------------------


def test_ingesting_a_document_lets_the_being_answer_about_it_grounded_and_cited(mint):
    sim = _sim()
    client = _client(sim)
    token = mint()

    # BEFORE reading: the being honestly declines — it has read nothing.
    before = client.post(
        "/ask/reading", json={"query": "tell me about dragons"}, headers=_bearer(token)
    )
    assert before.status_code == 200
    declined = before.json()["answer"].lower()
    assert "haven't read" in declined or "have not read" in declined
    assert "(source:" not in declined

    # INGEST the dragon document at runtime.
    resp = client.post(
        "/ingest",
        json={"text": _DRAGON, "source": "dragons.txt"},
        headers=_bearer(token),
    )
    assert resp.status_code == 200

    # AFTER reading: the SAME question is now answered grounded + CITED.
    after = client.post(
        "/ask/reading", json={"query": "tell me about dragons"}, headers=_bearer(token)
    )
    assert after.status_code == 200
    answer = after.json()["answer"]
    assert "dragons.txt" in answer        # citation, taken from the source
    assert "From what I read" in answer   # the grounded read label
    assert "dragon" in answer.lower()     # grounded in the read content


# --- (b) reading forms memories/concepts through the validated door -----------


def test_reading_a_document_forms_memories_or_concepts(mint):
    sim = _sim()
    client = _client(sim)
    assert sim.memories() == []  # a fresh being has read nothing

    resp = client.post(
        "/ingest",
        json={"text": _DRAGON, "source": "dragons.txt"},
        headers=_bearer(mint()),
    )
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["source"] == "dragons.txt"
    assert summary["chunks"] >= 1
    assert summary["perceived"] >= 1

    # Reading walked the validated perception/cognition door: memories formed,
    # keyed on perceived tokens + the reading action (never a developer label).
    memories = sim.memories()
    assert memories, "reading through /ingest should form memories"
    assert all(m["action"] == "read" for m in memories)
    assert all(m["objectId"].startswith("read:") for m in memories)
    # ...and a recurring token distils at least one concept.
    assert sim.concepts(), "reading should distil at least one concept"


# --- honest about the still-unread ---------------------------------------------


def test_an_unread_topic_is_still_declined_after_ingest(mint):
    sim = _sim()
    client = _client(sim)
    token = mint()

    client.post(
        "/ingest",
        json={"text": _DRAGON, "source": "dragons.txt"},
        headers=_bearer(token),
    )

    resp = client.post(
        "/ask/reading", json={"query": "tell me about volcanoes"}, headers=_bearer(token)
    )
    assert resp.status_code == 200
    answer = resp.json()["answer"].lower()
    assert "volcanoes" in answer
    assert "haven't read" in answer or "have not read" in answer
    assert "(source:" not in answer  # nothing read on this topic to cite


# --- input validation + auth ---------------------------------------------------


def test_ingesting_empty_text_is_rejected(mint):
    resp = _client(_sim()).post("/ingest", json={"text": ""}, headers=_bearer(mint()))
    assert resp.status_code == 422


def test_ingest_without_a_token_is_rejected():
    resp = _client(_sim()).post("/ingest", json={"text": _DRAGON})
    assert resp.status_code == 401


# --- (c) /chat over the SAME shared store stays grounded -----------------------


def test_chat_about_the_ingested_topic_stays_grounded(mint):
    sim = _sim()
    client = _client(sim)
    token = mint()

    client.post(
        "/ingest",
        json={"text": _DRAGON, "source": "dragons.txt"},
        headers=_bearer(token),
    )

    resp = client.post(
        "/chat", json={"message": "tell me about dragons"}, headers=_bearer(token)
    )
    assert resp.status_code == 200
    answer = resp.json()["answer"]
    assert "dragons.txt" in answer
    assert "From what I read" in answer

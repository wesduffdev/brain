"""Behaviors of the VOICEBOX READING a document aloud + SPEAKING answers (reading
R8, reuses S4's `VoicePort`/`FakeVoice`/`voice_policy`, ADR 0035).

Two new observables sit on the SAME voice seam S4 established:

- `POST /read` voices a PROVIDED document aloud — cleaned + chunked into sensible
  utterances (reusing R1's `ingest`) and rendered to audio by the `VoicePort`. A
  host with no TTS engine still answers 200 with the text (voice is an upgrade,
  never a dependency), exactly like `/speak`.
- `POST /ask/reading` and `POST /chat` gain an opt-in `speak` flag: the grounded
  reading answer is voiced through the SAME `VoicePort`. Without the flag the text
  behavior is byte-for-byte unchanged.

Both surfaces run behind the always-on JWT guard (ADR 0005) and are READ-ONLY
(ADR 0022): reading a document aloud never advances or mutates the being.
"""
from __future__ import annotations

import os

from fastapi.testclient import TestClient

from app.adapters.template_language_model import TemplateLanguageModel
from app.config_service import ConfigService
from app.main import create_app
from app.policies import VoicePolicy
from app.ports.voice import FakeVoice
from app.services.memory_summary_service import MemorySummaryService
from app.services.narration_service import NarrationService
from app.services.self_report_service import SelfReportService

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")

_DOC = "The dinosaurs were very large.\n\nThey lived a very long time ago."


def _config() -> ConfigService:
    return ConfigService.from_files(_CONFIG_ROOT)


class _RememberingSim:
    """A being at the Simulation seam with just the read-backs these routes need;
    its `tick` FAILS so a read-only route that mutated the being would be caught."""

    def __init__(self) -> None:
        self.ticks = 0

    def memories(self) -> list:
        return [
            {
                "objectId": "obj_red_ball",
                "action": "push",
                "perceivedProperties": ["round", "red"],
                "observedOutcome": ["rolls"],
                "emotionAfter": "calm",
                "priority": 0.0,
            }
        ]

    def state(self) -> dict:
        return {"emotion": "calm", "perceived": {"objects": []}}

    def tick(self) -> dict:  # pragma: no cover - a read route must never call it
        self.ticks += 1
        raise AssertionError("a read-only voice route must not advance the being")


class _FixedReadingQA:
    def __init__(self, answer: str) -> None:
        self._answer = answer

    def answer(self, question: str) -> str:
        return self._answer


class _FixedConversation:
    def __init__(self, reply: str) -> None:
        self._reply = reply

    def reply(self, conversation_id: str, message: str) -> str:
        return self._reply


def _self_report_service() -> SelfReportService:
    config = _config()
    policy = config.self_report_policy()
    narrator = TemplateLanguageModel(
        phrasing=config.narration_phrasing(),
        salience_emphasis_threshold=policy.salience_emphasis_threshold,
        neutral_emotion=config.default_emotion(),
    )
    return SelfReportService(
        MemorySummaryService(narrator),
        NarrationService(narrator),
        recent_count=policy.recent_count,
    )


def _client(voice, *, voice_policy=None, reading_qa=None, conversation=None, sim=None):
    return TestClient(
        create_app(
            simulation=sim if sim is not None else _RememberingSim(),
            tick_interval_seconds=0,
            self_report_service=_self_report_service(),
            reading_qa_service=reading_qa,
            conversation_service=conversation,
            voice=voice,
            voice_policy=voice_policy,
        )
    )


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- POST /read: voice a provided document aloud ----------------------------


def test_read_without_a_token_is_rejected():
    resp = _client(FakeVoice()).post("/read", json={"text": _DOC})

    assert resp.status_code == 401


def test_read_voices_the_provided_document_aloud(mint):
    voice = FakeVoice()

    resp = _client(voice).post("/read", json={"text": _DOC}, headers=_bearer(mint()))

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("audio/wav")
    assert resp.content  # audio bytes crossed the wire
    # the document's OWN text reached the voice (cleaned by ingest, R1 reuse)
    spoken = " ".join(voice.spoken)
    assert "dinosaurs" in spoken and "long time ago" in spoken


def test_read_chunks_a_long_document_into_several_utterances(mint):
    voice = FakeVoice()
    # a small per-utterance budget forces the document to be read in pieces
    policy = VoicePolicy(read_aloud_max_chars=40)
    long_doc = (
        "Alpha beta gamma delta epsilon.\n\n"
        "Zeta eta theta iota kappa.\n\n"
        "Lambda mu nu xi omicron pi rho sigma."
    )

    resp = _client(voice, voice_policy=policy).post(
        "/read", json={"text": long_doc}, headers=_bearer(mint())
    )

    assert resp.status_code == 200
    # it was read aloud as MORE THAN ONE utterance (chunked sensibly)...
    assert len(voice.spoken) > 1
    # ...and every part of the document was voiced, first word to last
    joined = " ".join(voice.spoken)
    assert "Alpha" in joined and "sigma" in joined


def test_read_returns_text_when_synthesis_is_a_noop(mint):
    # a host with no TTS engine (silent voice) still answers 200 with the text,
    # so the document is never left unread — voice is an upgrade, not a dependency.
    voice = FakeVoice(silent=True)

    resp = _client(voice).post("/read", json={"text": _DOC}, headers=_bearer(mint()))

    assert resp.status_code == 200
    body = resp.json()
    assert body["spoken"] is False
    assert "dinosaurs" in body["text"]
    assert body["detail"]
    # it still recorded the utterance it would have spoken
    assert voice.spoken


def test_read_rejects_an_empty_document(mint):
    resp = _client(FakeVoice()).post("/read", json={"text": "   "}, headers=_bearer(mint()))

    assert resp.status_code == 422


def test_read_is_read_only_and_never_advances_the_being(mint):
    sim = _RememberingSim()

    resp = _client(FakeVoice(), sim=sim).post(
        "/read", json={"text": _DOC}, headers=_bearer(mint())
    )

    assert resp.status_code == 200
    assert sim.ticks == 0  # the being was never advanced


# --- speaking answers: /ask/reading + /chat gain an opt-in `speak` flag -----


def test_ask_reading_speaks_the_answer_when_requested(mint):
    voice = FakeVoice()
    qa = _FixedReadingQA("From what I read: the sky is blue. (source: sky.txt)")

    resp = _client(voice, reading_qa=qa).post(
        "/ask/reading", json={"query": "why is the sky blue?", "speak": True},
        headers=_bearer(mint()),
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("audio/wav")
    assert resp.content
    assert voice.spoken[-1] == "From what I read: the sky is blue. (source: sky.txt)"


def test_ask_reading_stays_text_only_without_the_speak_flag(mint):
    voice = FakeVoice()
    qa = _FixedReadingQA("From what I read: the sky is blue. (source: sky.txt)")

    resp = _client(voice, reading_qa=qa).post(
        "/ask/reading", json={"query": "why is the sky blue?"}, headers=_bearer(mint())
    )

    assert resp.status_code == 200
    assert resp.json()["answer"].startswith("From what I read")
    assert voice.spoken == []  # the voice was never asked to speak


def test_chat_speaks_the_answer_when_requested(mint):
    voice = FakeVoice()
    chat = _FixedConversation("From what I read: it grew back. (source: lizards.txt)")

    resp = _client(voice, conversation=chat).post(
        "/chat", json={"message": "tell me more about that", "speak": True},
        headers=_bearer(mint()),
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("audio/wav")
    assert voice.spoken[-1] == "From what I read: it grew back. (source: lizards.txt)"


def test_chat_stays_text_only_without_the_speak_flag(mint):
    voice = FakeVoice()
    chat = _FixedConversation("From what I read: it grew back. (source: lizards.txt)")

    resp = _client(voice, conversation=chat).post(
        "/chat", json={"message": "tell me more about that"}, headers=_bearer(mint())
    )

    assert resp.status_code == 200
    assert resp.json()["answer"].startswith("From what I read")
    assert voice.spoken == []

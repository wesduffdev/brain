"""Behaviors of the VOICEBOX (S4, ADR 0034 = reading R8): the being SPEAKS its
grounded self-report aloud through a small `VoicePort`.

Two invariants are pinned here, mirroring the graceful-degradation precedent of
the outcome predictor (`load_predictor` returns None when torch/artifact absent):

- VOICE IS AN UPGRADE, NEVER A DEPENDENCY: the real `espeak-ng` adapter degrades
  to a clear no-op (returns ``None``) when the binary is not installed, and the
  suite never requires espeak-ng to be present.
- IT SPEAKS ONLY WHAT IT REPORTS: `/speak` voices the SAME grounded self-report
  the S1 `SelfReportService` produces; the voice adds sound, never words.

`/speak` runs behind the always-on JWT guard (ADR 0005), same contract as `/ask`.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.espeak_voice import EspeakVoice
from app.adapters.template_language_model import TemplateLanguageModel
from app.adapters.voice import build_voice
from app.config_service import ConfigService
from app.main import create_app
from app.ports.voice import FakeVoice, VoiceParams
from app.services.memory_summary_service import MemorySummaryService
from app.services.narration_service import NarrationService
from app.services.self_report_service import SelfReportService

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")

_QUERY = "what have you done recently?"


def _config() -> ConfigService:
    return ConfigService.from_files(_CONFIG_ROOT)


# --- the VoicePort + FakeVoice (the test seam) ------------------------------


def test_fake_voice_returns_audio_bytes_and_records_the_utterance():
    voice = FakeVoice()

    params = VoiceParams(voice="en", rate=170, pitch=60)
    audio = voice.synthesize("the round red thing rolled", params)

    # deterministic, non-empty audio bytes
    assert isinstance(audio, bytes) and audio
    # it recorded exactly what it was asked to speak, and with which params
    assert voice.spoken == ["the round red thing rolled"]
    assert voice.utterances[-1] == ("the round red thing rolled", params)


def test_fake_voice_can_simulate_a_silent_noop():
    voice = FakeVoice(silent=True)

    # a silent voice still records the utterance but produces no audio (None) —
    # the fake stand-in for a host with no TTS engine.
    assert voice.synthesize("anything", None) is None
    assert voice.spoken == ["anything"]


# --- the espeak-ng adapter: graceful when the binary is absent --------------


def test_espeak_degrades_to_a_noop_when_the_binary_is_absent():
    # simulate espeak-ng not installed at the lookup seam — no crash, a clean None
    voice = EspeakVoice(locate=lambda name: None)

    assert voice.synthesize("hello", VoiceParams(voice="en")) is None


def test_espeak_produces_wav_bytes_when_the_binary_is_present():
    # simulate a present binary at the seam: the injected runner writes the WAV
    # espeak was told to produce, so the present-path is exercised with no install.
    calls = []

    def run(argv):
        calls.append(argv)
        wav = argv[argv.index("-w") + 1]
        Path(wav).write_bytes(b"RIFF0000WAVEfake-audio")

    voice = EspeakVoice(
        binary="espeak-ng", locate=lambda name: "/usr/bin/espeak-ng", run=run
    )

    audio = voice.synthesize(
        "the round red thing bounced", VoiceParams(voice="en", rate=170, pitch=60)
    )

    assert audio == b"RIFF0000WAVEfake-audio"
    argv = calls[0]
    # the requested voice params became espeak flags, and the text is the payload
    assert "-v" in argv and "-s" in argv and "-p" in argv and "-w" in argv
    assert argv[-1] == "the round red thing bounced"


@pytest.mark.skipif(
    shutil.which("espeak-ng") is None, reason="espeak-ng not installed on this host"
)
def test_espeak_synthesizes_real_audio_when_installed():
    audio = EspeakVoice().synthesize("hello there", VoiceParams(voice="en"))

    assert audio and audio[:4] == b"RIFF"  # a real WAV header


# --- config: engine selection + emotion -> params (config-driven) -----------


def test_voice_policy_selects_engine_and_maps_emotion_to_params():
    policy = _config().voice_policy()

    assert policy.engine  # an engine is selected in config, not code
    scared = policy.params_for("scared")
    calm = policy.params_for("calm")
    # a config-authored emotion mapping makes a scared voice differ from a calm one
    assert (scared.rate, scared.pitch) != (calm.rate, calm.pitch)


def test_build_voice_selects_the_configured_espeak_engine():
    voice = build_voice(_config())  # config engine: espeak-ng

    assert isinstance(voice, EspeakVoice)


def test_build_voice_rejects_an_unknown_engine():
    config = ConfigService.from_dict(
        tick_rates={"tick": {"duration_ms": 1000}, "needs": {}},
        emotions={},
        voice={"engine": "nope"},
    )

    with pytest.raises(ValueError):
        build_voice(config)


# --- POST /speak: voices the grounded self-report, behind the JWT guard -----


class _RememberingSim:
    """A being at the Simulation seam with just the read-backs /speak needs."""

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


def _client(voice) -> TestClient:
    return TestClient(
        create_app(
            simulation=_RememberingSim(),
            tick_interval_seconds=0,
            self_report_service=_self_report_service(),
            voice=voice,
        )
    )


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_speak_without_a_token_is_rejected():
    resp = _client(FakeVoice()).post("/speak", json={"query": _QUERY})

    assert resp.status_code == 401


def test_speak_with_a_valid_token_voices_the_self_report(mint):
    voice = FakeVoice()

    resp = _client(voice).post("/speak", json={"query": _QUERY}, headers=_bearer(mint()))

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("audio/wav")
    # it voiced the being's OWN grounded self-report (names a perceived property)
    assert voice.spoken, "the voice should have been asked to speak"
    assert "round" in voice.spoken[-1]
    assert resp.content  # audio bytes crossed the wire


def test_speak_returns_a_clear_body_when_synthesis_is_a_noop(mint):
    # a host with no TTS engine (silent voice) still answers 200 with the words,
    # so the being is never left mute — voice is an upgrade, not a dependency.
    resp = _client(FakeVoice(silent=True)).post(
        "/speak", json={"query": _QUERY}, headers=_bearer(mint())
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["spoken"] is False
    assert "round" in body["report"]  # the grounded text is still returned
    assert body["detail"]

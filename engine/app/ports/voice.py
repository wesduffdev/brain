"""VoicePort — the seam the being's self-report is turned into SPEECH through
(S4, ADR 0034; the voicebox reading R8 reuses).

A voice here does one thing: hand it the text the being would say and it returns
synthesized audio — WAV bytes — or ``None`` when it cannot speak. That thin
surface is all the language layer needs to give the being a voice, and keeping
synthesis behind this one method is what lets the voicebox sit *on top* of the
sim exactly as narration does (ADR 0022): it only ever renders words the being
already produced into sound; nothing it returns can reach back into the being's
psychology.

The seam is genuine because implementations vary across it:

- `FakeVoice` (below) — deterministic, in-memory, zero dependencies: returns
  known bytes and records the text/params it was asked to speak, so the whole
  behavior suite drives the voicebox without any TTS engine installed;
- `app.adapters.espeak_voice.EspeakVoice` — the real, open-source adapter that
  shells out to `espeak-ng` (and, later, Piper for reading R8), env/host-gated:
  when the binary is absent it degrades to a clean no-op (``None``), mirroring
  the outcome predictor's graceful absence (`app.ml.inference.load_predictor`).

Voice is an UPGRADE, never a dependency: with no engine the being still answers
in text (the `/speak` endpoint's no-op body), it just cannot be heard.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol, Tuple


@dataclass(frozen=True)
class VoiceParams:
    """How an utterance should SOUND, resolved from config (`VoicePolicy`): the
    engine `voice` name and the `rate` (words/min) and `pitch` the being speaks
    with. Any field left ``None`` means "the engine's own default" — the adapter
    only passes a flag for a field that is set, so a bare `VoiceParams()` speaks
    in the engine's neutral voice."""

    voice: Optional[str] = None
    rate: Optional[int] = None
    pitch: Optional[int] = None


class VoicePort(Protocol):
    """Synthesizes speech from text. The only thing the voicebox needs a TTS
    engine to do; which voice/rate/pitch is a `VoiceParams` decided by config
    around this seam, and whether an engine even exists is the adapter's own
    graceful concern (it returns ``None`` rather than raise)."""

    def synthesize(self, text: str, params: Optional[VoiceParams] = None) -> Optional[bytes]:
        """Return synthesized audio (WAV bytes) for ``text``, or ``None`` when
        synthesis is unavailable (no engine on this host) — never raise."""
        ...


class FakeVoice:
    """A deterministic `VoicePort` for tests — never shells out and needs no TTS
    engine installed.

    It returns known, non-empty bytes for any text (``b"fake-wav:" + text`` by
    default, or a fixed `audio` payload) and records every utterance on
    ``utterances`` (and the plain text on ``spoken``) so a test can assert the
    being voiced exactly what it reported, with which params. Construct it with
    ``silent=True`` to model a host with NO engine — it still records the
    utterance but returns ``None``, the faithful stand-in for the espeak adapter's
    graceful no-op.
    """

    def __init__(self, *, audio: Optional[bytes] = None, silent: bool = False) -> None:
        self._audio = audio
        self._silent = silent
        self.utterances: List[Tuple[str, Optional[VoiceParams]]] = []

    @property
    def spoken(self) -> List[str]:
        """Just the text of each utterance, in the order it was asked to speak."""
        return [text for text, _ in self.utterances]

    def synthesize(self, text: str, params: Optional[VoiceParams] = None) -> Optional[bytes]:
        self.utterances.append((text, params))
        if self._silent:
            return None
        if self._audio is not None:
            return self._audio
        return b"fake-wav:" + text.encode("utf-8")

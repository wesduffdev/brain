"""voice — assemble the being's voicebox (a `VoicePort`) from config (S4, ADR
0034; the shared wiring the voicebox reading R8 reuses).

One function, `build_voice`, is the seam between "which engine the being speaks
with" and everything above the `VoicePort`. It reads `voice.engine` and
constructs the selected ENGINE — the open-source `espeak-ng` adapter (default),
or the in-memory `fake` (demo/tests). It mirrors `build_narrator`'s provider
selection: the engine is chosen in config, never in service code, so retuning the
voice — and, at reading R8, adding Piper as another branch — is a config change.

Construction never probes the host binary (that is `synthesize`'s graceful
concern), so building the voicebox is safe even on a host with no TTS engine.
"""
from __future__ import annotations

from typing import Optional

from app.config_service import ConfigService
from app.ports.voice import FakeVoice, VoicePort

# espeak-ng is the default open-source engine; `espeak` is its plain alias.
# (Piper joins here at reading R8 — a new branch, not a new port.)
_ESPEAK_ENGINES = frozenset({"espeak-ng", "espeak"})


def build_voice(config: ConfigService, *, fake: Optional[VoicePort] = None) -> VoicePort:
    """The `VoicePort` the being speaks through, engine-selected from config.
    `voice.engine` chooses the engine; the espeak-ng adapter is host-gated and
    degrades to a no-op when the binary is absent. The `fake` injection lets a
    demo/test wire the deterministic voice with no engine installed."""
    engine = config.voice_policy().engine
    if engine in _ESPEAK_ENGINES:
        from app.adapters.espeak_voice import EspeakVoice

        return EspeakVoice(binary=engine)
    if engine == "fake":
        # A demo/test may select the fake; a bare one is a harmless deterministic voice.
        return fake if fake is not None else FakeVoice()
    raise ValueError(
        f"unknown voice engine {engine!r}; expected one of "
        "espeak-ng / espeak / fake (config/voice.yaml engine)"
    )

"""EspeakVoice — the real, open-source `VoicePort` backed by `espeak-ng`
(S4, ADR 0034; the voicebox reading R8 reuses, then adds Piper).

espeak-ng is a tiny, dependency-free, offline TTS engine: this adapter shells
out to it to render text into a WAV file (`espeak-ng -w out.wav [-v voice]
[-s rate] [-p pitch] "text"`) and returns the bytes. It sits behind the same
`synthesize(text, params) -> bytes | None` seam as the test `FakeVoice`, so
nothing above the port knows or cares which is wired in.

GRACEFUL ABSENCE is the point of the seam (mirroring `load_predictor`, which
returns ``None`` when torch/the artifact is absent): espeak-ng is a host binary,
not a Python dependency, and it may not be installed. When it is missing — or the
shell-out fails, or it writes nothing — this adapter returns ``None`` (a clean
no-op) rather than crash, so the being still answers in text (voice is an
upgrade, never a dependency). The binary lookup and the shell-out are injectable
seams (`locate` / `run`) so both the absent and the present paths are exercised
offline, with no espeak-ng installed in the suite.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from typing import Callable, List, Optional

from app.ports.voice import VoiceParams

_DEFAULT_BINARY = "espeak-ng"


def _default_run(argv: List[str]) -> None:
    """Run espeak-ng, raising on a non-zero exit (the adapter catches it and
    degrades to a no-op). Output is captured so espeak never writes to the
    server's stdout/stderr. Imported lazily so `subprocess` is off the hot path."""
    import subprocess  # noqa: PLC0415 — only the real shell-out needs it

    subprocess.run(argv, check=True, capture_output=True)


class EspeakVoice:
    def __init__(
        self,
        *,
        binary: str = _DEFAULT_BINARY,
        locate: Callable[[str], Optional[str]] = shutil.which,
        run: Optional[Callable[[List[str]], None]] = None,
    ) -> None:
        self._binary = binary
        self._locate = locate
        self._run = run if run is not None else _default_run

    def synthesize(self, text: str, params: Optional[VoiceParams] = None) -> Optional[bytes]:
        # No engine on this host, or nothing to say: a clean no-op, never a crash.
        resolved = self._locate(self._binary)
        if not resolved or not text or not text.strip():
            return None

        with tempfile.TemporaryDirectory() as workdir:
            wav_path = os.path.join(workdir, "utterance.wav")
            argv = [resolved, "-w", wav_path]
            if params is not None:
                if params.voice:
                    argv += ["-v", params.voice]
                if params.rate is not None:
                    argv += ["-s", str(params.rate)]
                if params.pitch is not None:
                    argv += ["-p", str(params.pitch)]
            argv.append(text)

            try:
                self._run(argv)
                with open(wav_path, "rb") as handle:
                    audio = handle.read()
            except Exception:
                # Any failure — binary error, permission, missing output — degrades
                # to a no-op, so a bad TTS host never takes the being's voice out
                # by crashing the request (the graceful-absence contract).
                return None

        return audio or None

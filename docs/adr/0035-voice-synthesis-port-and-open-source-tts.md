# 0035 — Voice synthesis port + open-source TTS

Status: Accepted · Date: 2026-07-11

## Context

The self-report surface (ADR 0032) lets the being tell you what it has done in
grounded first-person text, and ADR 0033 made the phrasing config-selectable. The
next language slice (S4 in [`docs/SELF_NARRATION.md`](../SELF_NARRATION.md) §5) is
to let the being SPEAK that report aloud — and this is the same "voicebox" the
reading track needs (R8 in [`docs/READING_VOICEBOX.md`](../READING_VOICEBOX.md)),
so it is built once here and reused there.

Two forces shaped the decision:

- **Voice must be an upgrade, never a dependency.** A synthesized voice needs a
  TTS engine (a host binary), which will not be present everywhere — the lean
  runtime, CI, a fresh dev box. The being must not go mute (or crash) when the
  engine is absent; it must fall back to answering in text. This is the same
  graceful-absence shape the outcome predictor already uses
  (`app.ml.inference.load_predictor` returns `None` when torch/the artifact is
  absent, ADR 0011).
- **The voice adds sound, not words.** Narration already sits ON TOP of the sim
  and controls nothing (ADR 0022); the voicebox must keep that invariant — it
  renders the words the being already produced into audio and can never reach
  back into its psychology.

## Decision

Add a **`VoicePort`** seam — `synthesize(text, params) -> bytes | None` — with two
implementations that genuinely vary across it (the test for a real seam):

- **`FakeVoice`** (in `app.ports.voice`, beside the port, as `FakeLanguageModel`
  is): deterministic, in-memory, zero dependencies; returns known bytes and
  records the text/params it was asked to speak, so the whole behavior suite
  drives the voicebox with no engine installed. A `silent=True` fake models a
  host with no engine (returns `None`).
- **`EspeakVoice`** (`app.adapters.espeak_voice`): shells out to the open-source,
  offline **`espeak-ng`** binary to render a WAV and returns the bytes. When the
  binary is absent — or the shell-out fails, or it writes nothing — it returns
  `None` (a clean no-op), never raising. The binary lookup and the shell-out are
  injectable seams so both the absent and the present paths are exercised offline.

Engine selection is **config-driven**: `config/voice.yaml` (`engine`, neutral
`voice`/`rate`/`pitch`, and an optional per-emotion `rate`/`pitch` override so the
voice tracks how the being feels) is read by `ConfigService.voice_policy()` into a
typed `VoicePolicy`; `app.adapters.voice.build_voice` selects the engine
(`espeak-ng` default; `fake` for demos/tests), mirroring `build_narrator`. Piper
joins at reading R8 as another `build_voice` branch — a new engine, not a new
port.

A new authenticated **`POST /speak`** endpoint voices the current self-report: it
reuses the S1 `SelfReportService` to produce the SAME grounded text `/ask`
returns, synthesizes it with the emotion-appropriate params, and returns
`audio/wav`. When synthesis is a no-op (no engine) it returns `200` with a clear
JSON body carrying the report text, so the being is never left mute. `/speak`
runs behind the always-on JWT guard (ADR 0005), same contract as `/ask`.

## Consequences

- The being can be HEARD, not just read — the observable S4 outcome — while
  staying grounded (it can only voice what it reported) and non-authoritative
  (voice sits on top, mutates nothing, ADR 0022).
- No new runtime dependency is forced: espeak-ng is optional; with no engine the
  suite, CI, and the lean runtime behave exactly as before, and `/speak` degrades
  to a text body. The `subprocess`/`tempfile`/`shutil` use stays hidden behind the
  port.
- The voicebox is shared with reading R8 by construction: R8 adds the Piper engine
  behind the same `VoicePort` and reuses `/speak`, so the reading track inherits a
  working voice rather than rebuilding one.
- `VoiceParams` lives in `app.ports.voice` (the port owns its interface type), so
  `app.policies` imports it; this introduces a `policies → ports.voice` import,
  which is acyclic (`ports.voice` imports nothing from `app`).
- The renderer "speaking" pose is deferred (a follow-up), tracked in
  `docs/READING_VOICEBOX.md` R8; it does not gate this slice.

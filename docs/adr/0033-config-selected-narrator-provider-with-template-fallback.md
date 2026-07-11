# 0033 — Config-selected narrator provider with template fallback

## Status

Accepted (extends [0022](0022-natural-language-layer-and-language-model-port.md)
and [0032](0032-self-report-narration-surface.md))

## Date

2026-07-11

## Context

ADR 0032 wired the being's self-report to `POST /ask` through the deterministic
template narrator behind the one `LanguageModelPort`, and noted that flipping
`narrator.kind` to a real model makes phrasing fluent while grounding is preserved
(the model only ever sees the structured-experience prompt). This is the S2 slice
of the self-narration plan (`docs/SELF_NARRATION.md`): make that swap real, and
make it safe.

Three forces shape it. First, the being should be able to speak with **any of
several voices** — the offline template, the in-memory `fake` (tests), the
env-gated Claude adapter, or a **locally-served** model — chosen by config, behind
the single seam (ADR 0022: no new port). Second, a real model is a network / key
/ endpoint dependency that **can fail**, and a mute being is worse than a terse
one — so a failure must degrade gracefully, exactly as the outcome predictor's
neural head falls back to the rule layer (`fallback_to_rules_on_error`, ADR 0011).
Third, the local adapter is **shared infrastructure the reading track reuses**
(the plan's S2 ≡ reading R2): the toolchain is inherited — Qwen2.5-3B-Instruct
served by Ollama on `:11434` (`docs/READING_VOICEBOX.md` §11) — but the model is
not served until reading R1/R2, so the adapter must be a client that stays inert
(and offline-testable) until then.

## Decision

**Provider selection behind the one port, resolved by config.**
`narrator.kind` selects the provider: `deterministic` (the ADR-0032 template,
default), `fake` (the in-memory test model), `claude` (the env-gated adapter;
`model` is the S1 back-compat alias), or `local` (a new Ollama-style adapter). A
small `build_narrator(config)` factory (in `app.adapters.narrator`) constructs the
selected provider and is the sole place that branches on kind; the default path
returns the template unchanged, so it is **byte-identical to S1**.

**Fallback-safe by default.** Unless `narrator.fallback_to_template` is turned
off, a real model is wrapped in `FallbackLanguageModel(primary, template)` — a
`LanguageModelPort` that returns the primary's completion but, on **any** error
from it (raised exception, unavailable endpoint, missing key), degrades to the
deterministic template over the **same prompt**. Fluency lost, grounding kept: the
being always answers, and the answer never leaves the logged experience. This
mirrors ADR 0011's predictor fallback.

**A client-only local adapter.** `LocalLanguageModel` POSTs the prompt to an
Ollama-style endpoint (`{base_url}/api/generate`) and returns the completion. Its
`base_url` + served `model` are authored config (`LocalModelPolicy`,
`config/language.yaml`); the base URL is overridable by an environment variable
(`OLLAMA_BASE_URL`, a deploy detail like `DATABASE_URL`), `httpx` is imported
lazily, and a client may be injected for tests. With no resolved endpoint it
**refuses** rather than blind-calls (mirroring the Claude adapter's no-key
refusal). It **activates once reading R1/R2 serve a model**; until then, selecting
`local` with nothing serving simply falls back to the template.

## Consequences

- **One grounded report, many voices — grounding unchanged.** Every provider is
  handed the same structured fact-line prompt the narration services build (ADR
  0032), so no provider — and no failure — can invent a fact the being never
  logged. Proven offline: a fake model phrases the same facts, and an echoing fake
  shows the model's whole input is the log.
- **A model outage never mutes the being.** A `local`/`claude` provider that
  errors degrades to the deterministic template, still grounded; the failure mode
  is a config-gated, deliberate trade-off (fluency vs. always-available grounding),
  not a crash.
- **The suite stays offline.** Tests drive `fake` and a stubbed HTTP client; no
  test makes a network call, needs a key, or imports `anthropic`/`httpx` on the
  hot path. The default (deterministic) runtime is byte-identical to S1.
- **Shared with reading R2.** `LocalLanguageModel` is the client the reading track
  reuses once it serves a local model; this slice builds it once, under the S
  series, and reading only has to point it at a served endpoint.
- **A retune, not a rebuild.** Switching voice, tuning the local endpoint, or
  turning fallback off is a `config/language.yaml` (or env) change only.

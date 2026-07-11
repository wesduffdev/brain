# 0022 — Natural-language layer and the language-model port

## Status

Accepted

## Date

2026-07-11

## Context

Card v9 adds the natural-language layer (BRIEF §17): a person can phrase a
command in natural language, and the being's state can be turned into readable
narration. The load-bearing constraint is BRIEF's Important Architectural Rule
#6 — **do not start with an LLM as the whole brain**. The being's psychology
(perception → decision → safety → learning) is the brain; language must sit *on
top of* it, never in control.

Two forces meet here. First, the layer needs a large language model, and the
default provider is Claude — but the behaviour suite must stay deterministic and
must never make a network call or need an API key. Second, an LLM is an
unbounded text generator: if its output could reach the being's decision or
mutate the world directly, language would silently become the brain and could
invent actions the being does not have.

## Decision

**A single LLM seam, `LanguageModelPort` (`complete(prompt) -> str`).** Every use
of a language model in the engine goes through this one method. Two
implementations vary across it — a genuine seam, not a speculative one:

- `FakeLanguageModel` — deterministic, in-memory, zero-dependency; the whole
  suite drives it, so the language layer is testable with no network and no key.
- `ClaudeLanguageModel` — the real, Claude-backed adapter (default model
  `claude-opus-4-8`, official Anthropic SDK). It is **env-gated on
  `ANTHROPIC_API_KEY`**, exactly like `DATABASE_URL`/`JWT_SECRET` (a deploy
  secret, so `ConfigService` never learns of it), imports `anthropic` lazily so
  it is not a test dependency, and is **never invoked by the suite**.

**Language is non-authoritative — it proposes, it never decides or mutates.**
The layer is four services, none of which touches the `Simulation`:

- `LanguageCommandService.interpret(text, visible_object_ids)` — asks the model
  to map free text onto the being's action vocabulary, then runs the model's
  proposal through `ActionValidationService`. It returns a validated
  `PlayerCommand` (a *request*) or raises `LanguageCommandError`.
- `ActionValidationService.validate(action, target_id, visible_object_ids)` —
  the guardrail. An action must be in the being's vocabulary
  (`config/actions.yaml`), a named target must be a currently-perceived object,
  and an object-directed action requires such a target. The model's output is
  **untrusted**; this validator, not the model's goodwill, is the guarantee that
  a language command can only ever be an allowed action.
- `NarrationService.narrate(snapshot)` — state → readable, non-authoritative
  text, built strictly from the passed-in snapshot. Read-only.
- `MemorySummaryService.summarize(memories)` — the memory log → readable
  summary. Read-only.

The validated `PlayerCommand` is the same domain type the player-command path
(ADR 0004) produces — language reaches the being through the same validated
door as any other input, never a back door, and applying that command remains
the sim's business (it does not reach into the being's decision).

## Consequences

- **Language sits on top, never in control.** An unknown or unsupported model
  output is rejected rather than passed through, and interpreting a command or
  narrating a state leaves the being's state exactly as it was — the sim only
  ever advances through `tick()`.
- **Deterministic tests, real default provider.** Because the model output is
  never trusted, a fixed-string fake is a faithful stand-in; the Claude adapter
  can back production without any test ever calling it.
- **Retuning is config/env, not code.** The allowed-action vocabulary comes from
  `config/actions.yaml` via `config.action_policies()`; the provider key is an
  environment secret. Neither is hard-coded in the language layer.
- **A known overlap to watch.** `ActionValidationService` and `CommandService`
  (ADR 0004) are two validation gates over two vocabularies (the being's action
  vocab vs the player-command vocab). They have different reasons to change and
  are kept separate for now; if the vocabularies ever converge, unifying them
  behind one gate is an interface-level change for a future ADR, not a silent
  merge.
- **No HTTP surface yet.** This slice lands the layer behind its service
  interfaces; exposing an NL endpoint on `main.py` (and a Claude-backed default
  wiring) is a follow-up.

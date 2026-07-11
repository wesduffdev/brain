"""narrator — assemble the being's narrator (a `LanguageModelPort`) from config
(S2, extends ADR 0022/0032; the shared wiring reading R2 reuses).

One function, `build_narrator`, is the seam between "which voice the being speaks
with" and everything above the `LanguageModelPort`. It reads `narrator.kind` and
constructs the selected PROVIDER — the offline deterministic template (default),
the in-memory `fake` (tests), the env-gated Claude adapter, or the Ollama-style
`local` endpoint — and, unless config turns it off, wraps a real model in the
FALLBACK-SAFE `FallbackLanguageModel` so a model that errors or is unavailable
degrades to the deterministic template rather than leaving the being mute.

Grounding is preserved by construction: every provider is handed the SAME
structured-experience prompt the narration services build, and the fallback
template renders that same prompt — so no provider (and no failure) can invent a
fact the being never logged (ADR 0032). Selecting `local`/`claude` is env-gated,
never touched by the suite; tests drive `fake` and inject stubbed clients.
"""
from __future__ import annotations

from typing import Mapping, Optional

from app.adapters.template_language_model import TemplateLanguageModel
from app.config_service import ConfigService
from app.ports.language_model import FakeLanguageModel, LanguageModelPort

# `deterministic` needs no fallback wrapper (it IS the fallback); `model` is the
# back-compat S1 alias for `claude`.
_TEMPLATE_KINDS = frozenset({"deterministic", "template"})
_CLAUDE_KINDS = frozenset({"claude", "model"})


class FallbackLanguageModel:
    """A `LanguageModelPort` that is TWO narrators: a `primary` model and a
    grounded `fallback` (the deterministic template). It returns the primary's
    completion, and on ANY error from the primary — a raised exception, an
    unavailable endpoint, a missing key — degrades to the fallback over the SAME
    prompt, so the being always answers and always stays grounded. This mirrors
    the predictor ensemble's `fallback_to_rules_on_error` (ADR 0011): the fluent
    voice is an upgrade, never a dependency.
    """

    def __init__(self, primary: LanguageModelPort, fallback: LanguageModelPort) -> None:
        self._primary = primary
        self._fallback = fallback

    def complete(self, prompt: str) -> str:
        try:
            return self._primary.complete(prompt)
        except Exception:
            # Degrade to the grounded template over the same structured prompt —
            # fluency lost, grounding kept. (Deliberately broad: any provider
            # failure — network, key, HTTP status — must fall back, never crash.)
            return self._fallback.complete(prompt)


def build_narrator(
    config: ConfigService,
    *,
    env: Optional[Mapping[str, str]] = None,
    fake: Optional[LanguageModelPort] = None,
    local_client=None,
    claude_client=None,
) -> LanguageModelPort:
    """The `LanguageModelPort` the being narrates through, provider-selected and
    fallback-safe. `narrator.kind` chooses the provider; a real model is wrapped in
    `FallbackLanguageModel` over the deterministic template unless
    `fallback_to_template` is off. Injection seams (`fake`, `local_client`,
    `claude_client`, `env`) let the suite drive every branch offline, with no
    network and no key; left to their defaults the deploy path reads the endpoint
    from config and the key/URL from the environment."""
    policy = config.self_report_policy()
    template = TemplateLanguageModel(
        phrasing=config.narration_phrasing(),
        salience_emphasis_threshold=policy.salience_emphasis_threshold,
        neutral_emotion=config.default_emotion(),
    )

    kind = policy.narrator_kind
    if kind in _TEMPLATE_KINDS:
        return template  # the default: byte-identical to S1, no wrapper needed

    primary = _build_primary(
        kind,
        config,
        env=env,
        fake=fake,
        local_client=local_client,
        claude_client=claude_client,
    )
    if policy.fallback_to_template:
        return FallbackLanguageModel(primary, template)
    return primary


def _build_primary(
    kind: str,
    config: ConfigService,
    *,
    env: Optional[Mapping[str, str]],
    fake: Optional[LanguageModelPort],
    local_client,
    claude_client,
) -> LanguageModelPort:
    if kind == "fake":
        # Tests inject a configured fake; a bare one is a harmless empty completer.
        return fake if fake is not None else FakeLanguageModel()
    if kind in _CLAUDE_KINDS:
        from app.adapters.claude_language_model import ClaudeLanguageModel

        return ClaudeLanguageModel(client=claude_client)
    if kind == "local":
        from app.adapters.local_language_model import LocalLanguageModel

        lp = config.local_model_policy()
        return LocalLanguageModel(
            base_url=lp.base_url,
            model=lp.model,
            base_url_env=lp.base_url_env,
            timeout=lp.timeout_seconds,
            env=env,
            client=local_client,
        )
    raise ValueError(
        f"unknown narrator provider {kind!r}; expected one of "
        "deterministic / fake / claude / local (config/language.yaml narrator.kind)"
    )

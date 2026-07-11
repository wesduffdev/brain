"""Behaviors of the CONFIG-SELECTED narrator provider (S2, extends ADR 0022/0032):
the SAME grounded self-report can be phrased by a config-selected language model
(Fake in tests, Claude/local in deploy) behind the ONE `LanguageModelPort`, while
the deterministic template narrator stays the FALLBACK when the model errors or is
unavailable.

Load-bearing invariants pinned here:

- SELECTION: `narrator.kind` chooses the provider (deterministic / fake / claude /
  local); `deterministic` is the default and is byte-identical to S1.
- FALLBACK-SAFE: a selected model that raises/erros degrades to the deterministic
  template (mirroring the predictor ensemble's rule fallback), and the fallback is
  config-gated (`fallback_to_template`).
- GROUNDING (unchanged): the model only ever sees the structured-experience prompt
  the narration services build, so it cannot invent facts beyond the memory log; a
  model error yields the grounded deterministic report.

Everything is exercised OFFLINE: the Fake model and a STUBBED HTTP client stand in
for Claude / a live local model, so no test makes a network call or needs a key.
"""
from __future__ import annotations

import pytest

from app.adapters.local_language_model import LocalLanguageModel
from app.adapters.narrator import FallbackLanguageModel, build_narrator
from app.adapters.template_language_model import TemplateLanguageModel
from app.config_service import ConfigService
from app.ports.language_model import FakeLanguageModel
from app.services.memory_summary_service import MemorySummaryService
from app.services.narration_service import NarrationService
from app.services.self_report_service import SelfReportService

_QUERY = "what have you done recently?"

# One hand-built memory: exactly one perceived-property set and one outcome, so
# everything the being says must trace back to it (the grounding fixture).
_LOG = [
    {
        "objectId": "obj_x",
        "action": "push",
        "perceivedProperties": ["round", "red"],
        "observedOutcome": ["rolls"],
        "emotionAfter": "calm",
        "priority": 0.0,
    }
]
_NOT_LOGGED = ("hot", "square", "blue", "bounced", "hurt", "frightened")

_TICK = {"tick": {"duration_ms": 100}, "needs": {}}
_EMO = {"rules": [], "default": "calm"}


def _provider_config(kind, *, local=None, fallback=True, phrasing=None) -> ConfigService:
    """A ConfigService whose language section selects `kind`, with the fallback flag
    and (for `local`) the endpoint block. Minimal required sections otherwise."""
    narrator = {"kind": kind, "fallback_to_template": fallback}
    if local is not None:
        narrator["local"] = local
    language = {
        "narrator": narrator,
        "report": {"recent_count": 5, "salience_emphasis_threshold": 1.0},
    }
    if phrasing:
        language["phrasing"] = phrasing
    return ConfigService.from_dict(tick_rates=_TICK, emotions=_EMO, language=language)


def _report_service(config: ConfigService, narrator) -> SelfReportService:
    policy = config.self_report_policy()
    return SelfReportService(
        MemorySummaryService(narrator),
        NarrationService(narrator),
        recent_count=policy.recent_count,
    )


def _template(config: ConfigService) -> TemplateLanguageModel:
    policy = config.self_report_policy()
    return TemplateLanguageModel(
        phrasing=config.narration_phrasing(),
        salience_emphasis_threshold=policy.salience_emphasis_threshold,
        neutral_emotion=config.default_emotion(),
    )


# --- a stubbed Ollama-style HTTP client (no network) ------------------------


class _StubResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _StubHttpClient:
    """The minimal `.post(url, json=...) -> response` surface LocalLanguageModel
    needs — records the last request so a test can assert what was sent."""

    def __init__(self, payload):
        self._payload = payload
        self.last_url = None
        self.last_json = None

    def post(self, url, json=None):
        self.last_url = url
        self.last_json = json
        return _StubResponse(self._payload)


class _BoomHttpClient:
    def post(self, url, json=None):
        raise ConnectionError("local endpoint is down")


class _BoomModel:
    def complete(self, prompt):
        raise RuntimeError("model unavailable")


# --- default / deterministic: byte-identical to S1 --------------------------


def test_the_default_narrator_is_the_deterministic_template():
    config = _provider_config("deterministic")
    built = build_narrator(config)
    assert isinstance(built, TemplateLanguageModel)  # no fallback wrapper on default

    got = _report_service(config, built).report(_QUERY, memories=_LOG, state={})
    want = _report_service(config, _template(config)).report(_QUERY, memories=_LOG, state={})
    assert got == want  # byte-identical to the S1 deterministic render


# --- fake / model path: same facts, phrased by the model --------------------


def test_a_config_selected_fake_model_phrases_the_report():
    fake = FakeLanguageModel(reply="I pushed the round red thing and it rolled.")
    config = _provider_config("fake")

    built = build_narrator(config, fake=fake)
    report = _report_service(config, built).report(_QUERY, memories=_LOG, state={})

    assert report == "I pushed the round red thing and it rolled."


def test_the_model_only_ever_sees_the_logged_facts():
    # An echoing fake returns exactly the prompt it was handed, so the report IS
    # the model's whole input: it contains the logged facts and nothing invented.
    fake = FakeLanguageModel(echo=True)
    config = _provider_config("fake")

    report = _report_service(config, build_narrator(config, fake=fake)).report(
        _QUERY, memories=_LOG, state={}
    )

    assert "round" in report and "red" in report and "rolls" in report
    for not_logged in _NOT_LOGGED:
        assert not_logged not in report
    # the model was handed the structured log only
    assert fake.prompts and "round" in fake.prompts[0]


# --- local adapter: client-only, tested with a stubbed endpoint -------------


def test_a_local_model_returns_the_endpoint_completion():
    client = _StubHttpClient({"response": "I pushed the round red thing."})
    model = LocalLanguageModel(
        base_url="http://localhost:11434", model="qwen2.5:3b-instruct", client=client, env={}
    )

    out = model.complete("a structured prompt")

    assert out == "I pushed the round red thing."
    assert client.last_url == "http://localhost:11434/api/generate"
    assert client.last_json["model"] == "qwen2.5:3b-instruct"
    assert client.last_json["prompt"] == "a structured prompt"
    assert client.last_json["stream"] is False


def test_a_local_model_without_an_endpoint_refuses_rather_than_calls_out():
    # No base_url and no injected client: it must refuse (never blind-call), exactly
    # like the Claude adapter with no key.
    model = LocalLanguageModel(base_url="", model="m", env={})
    with pytest.raises(RuntimeError):
        model.complete("prompt")


def test_a_config_selected_local_narrator_uses_the_endpoint():
    client = _StubHttpClient({"response": "fluent local phrasing"})
    config = _provider_config(
        "local", local={"base_url": "http://host:11434", "model": "qwen2.5:3b-instruct"}
    )

    built = build_narrator(config, local_client=client, env={})
    report = _report_service(config, built).report(_QUERY, memories=_LOG, state={})

    assert report == "fluent local phrasing"
    assert client.last_json["model"] == "qwen2.5:3b-instruct"


# --- fallback-safe: a model that errors degrades to the template ------------


def test_a_narrator_that_errors_falls_back_to_the_deterministic_template():
    config = _provider_config("local")
    fb = FallbackLanguageModel(_BoomModel(), _template(config))

    got = _report_service(config, fb).report(_QUERY, memories=_LOG, state={})
    want = _report_service(config, _template(config)).report(_QUERY, memories=_LOG, state={})

    assert got == want  # the grounded deterministic render


def test_a_config_local_narrator_falls_back_when_the_endpoint_errors():
    config = _provider_config(
        "local", local={"base_url": "http://host:11434", "model": "m"}
    )
    built = build_narrator(config, local_client=_BoomHttpClient(), env={})

    got = _report_service(config, built).report(_QUERY, memories=_LOG, state={})
    want = _report_service(config, _template(config)).report(_QUERY, memories=_LOG, state={})

    assert got == want
    # the fallback report is grounded: only what the being logged
    for not_logged in _NOT_LOGGED:
        assert not_logged not in got


def test_disabling_fallback_lets_the_model_error_surface():
    config = _provider_config(
        "local", local={"base_url": "http://host:11434", "model": "m"}, fallback=False
    )
    built = build_narrator(config, local_client=_BoomHttpClient(), env={})

    with pytest.raises(Exception):
        _report_service(config, built).report(_QUERY, memories=_LOG, state={})


# --- claude provider: env-gated, never called in tests ----------------------


def test_a_config_claude_narrator_with_no_key_falls_back_to_the_template(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = _provider_config("claude")  # fallback default on

    built = build_narrator(config)
    got = _report_service(config, built).report(_QUERY, memories=_LOG, state={})
    want = _report_service(config, _template(config)).report(_QUERY, memories=_LOG, state={})

    assert got == want  # no key => the being still speaks, grounded


def test_a_config_claude_narrator_is_env_gated_when_fallback_is_off(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = _provider_config("claude", fallback=False)

    built = build_narrator(config)
    with pytest.raises(RuntimeError):
        built.complete("say hello")

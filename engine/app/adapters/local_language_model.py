"""LocalLanguageModel — a `LanguageModelPort` backed by a LOCALLY-served model
(S2, extends ADR 0022/0032; the shared client reading R2 reuses).

The being's fluent voice without a cloud dependency: this adapter completes a
prompt against an **Ollama-style HTTP endpoint** (`POST {base_url}/api/generate`
with `{"model", "prompt", "stream": false}` → `{"response": ...}`), the toolchain
the reading track inherits (`docs/READING_VOICEBOX.md` §11 — Qwen2.5-3B-Instruct
served by Ollama on `:11434`). It sits behind the SAME `complete(prompt) -> str`
seam as the Claude adapter, the deterministic template, and the test
`FakeLanguageModel` (ADR 0022 — no new port), so selecting it changes only where
the words come from, never the grounding.

**Client-only here.** The model is NOT served yet — that is reading R1/R2. This
adapter is the HTTP CLIENT and is exercised OFFLINE with a stubbed client (no live
model, no network in the suite). It **activates once R1/R2 serve a model** on the
configured endpoint; until then, selecting `local` and calling out with nothing
serving simply errors, and the fallback-safe narrator (ADR 0022/0032) degrades to
the grounded deterministic template.

Config vs. deploy, like every other seam here: the `base_url` + `model` are
authored config (`LocalModelPolicy`, `config/language.yaml`), and the base URL is
**overridable by an environment variable** (`OLLAMA_BASE_URL` by default) — a
deploy detail, like `DATABASE_URL`, so `ConfigService` carries only the default.
With no resolved endpoint the adapter **refuses** to build a client rather than
blind-call (mirroring the Claude adapter's no-key refusal). `httpx` is imported
lazily so it is never a test dependency, and a client may be injected for
isolation.
"""
from __future__ import annotations

import os
from typing import Mapping, Optional

_GENERATE_PATH = "/api/generate"


class LocalLanguageModel:
    def __init__(
        self,
        *,
        base_url: str = "",
        model: str = "",
        base_url_env: str = "OLLAMA_BASE_URL",
        timeout: float = 30.0,
        env: Optional[Mapping[str, str]] = None,
        client=None,
    ) -> None:
        env = os.environ if env is None else env
        # The env var OVERRIDES the authored default (deploy config beats YAML),
        # exactly like DATABASE_URL/JWT_SECRET.
        self._base_url = (env.get(base_url_env) or base_url or "").rstrip("/")
        self._model = model
        self._timeout = timeout
        self._client = client

    def complete(self, prompt: str) -> str:
        client = self._client if self._client is not None else self._build_client()
        response = client.post(
            f"{self._base_url}{_GENERATE_PATH}",
            json={"model": self._model, "prompt": prompt, "stream": False},
        )
        response.raise_for_status()
        data = response.json()
        # Ollama's generate endpoint returns the completion under `response`.
        return str(data.get("response", ""))

    def _build_client(self):
        # Refuse BEFORE importing httpx, so a missing endpoint is a clean refusal
        # (never a network call) and `httpx` stays out of the test import path.
        if not self._base_url:
            raise RuntimeError(
                "the local language model needs an endpoint; set narrator.local.base_url "
                "in config/language.yaml (or OLLAMA_BASE_URL in the environment) — it "
                "activates once reading R1/R2 serve a model there."
            )
        import httpx  # imported lazily: not needed for tests or the fake

        self._client = httpx.Client(timeout=self._timeout)
        return self._client

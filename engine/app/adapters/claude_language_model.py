"""ClaudeLanguageModel — the real, Claude-backed `LanguageModelPort` (card v9).

The default provider for the natural-language layer. Claude sits behind the same
`complete(prompt) -> str` seam the deterministic `FakeLanguageModel` implements,
so nothing above the port knows or cares which is wired in. It is **env-gated**,
like `DATABASE_URL`/`JWT_SECRET`: the key is read from `ANTHROPIC_API_KEY` (a
deploy/secret, not authored config — so `ConfigService` never learns of it), and
with no key it refuses to build a client rather than call out. The behaviour
suite never uses this adapter — it drives the fake — so no real API call is made
in tests, and the `anthropic` package is imported lazily so it is not a test
dependency.

Model default per the `claude-api` guidance: `claude-opus-4-8` via the official
Anthropic SDK's `messages.create`. A client may be injected for isolation.
"""
from __future__ import annotations

import os
from typing import Optional

_DEFAULT_MODEL = "claude-opus-4-8"
_ENV_KEY = "ANTHROPIC_API_KEY"


class ClaudeLanguageModel:
    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: str = _DEFAULT_MODEL,
        max_tokens: int = 1024,
        client=None,
    ):
        self._api_key = api_key if api_key is not None else os.environ.get(_ENV_KEY)
        self._model = model
        self._max_tokens = max_tokens
        self._client = client

    def complete(self, prompt: str) -> str:
        client = self._client if self._client is not None else self._build_client()
        message = client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        # Concatenate the text blocks; a message may interleave other block types.
        return "".join(
            block.text
            for block in message.content
            if getattr(block, "type", None) == "text"
        )

    def _build_client(self):
        # Gate on the key BEFORE importing the SDK, so a missing key is a clean
        # refusal (never a network call) and the `anthropic` dep stays optional.
        if not self._api_key:
            raise RuntimeError(
                f"{_ENV_KEY} is not set; the Claude language model needs a key "
                "(set it in the environment, like DATABASE_URL/JWT_SECRET)."
            )
        import anthropic  # imported lazily: not needed for tests or the fake

        self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

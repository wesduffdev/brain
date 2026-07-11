"""LanguageModelPort — the seam the natural-language layer talks to an LLM
through (card v9, BRIEF §17).

A language model here is just a text completer: hand it a prompt, get back
text. That thin surface is enough for both jobs the language layer does —
turning a natural-language command into a proposed action (which is then
validated), and turning state into a readable narration or summary. Keeping the
LLM behind this one method is what lets language sit *on top* of the sim: the
model only ever produces text; nothing it returns can reach into the being's
decision or mutate the world.

The seam is genuine because two implementations vary across it:

- `FakeLanguageModel` (below) — deterministic, in-memory, zero dependencies:
  the whole behavior suite drives it, so the language layer is testable without
  a network call or an API key;
- `app.adapters.claude_language_model.ClaudeLanguageModel` — the real, Claude-
  backed adapter (the default provider), env-gated on `ANTHROPIC_API_KEY` and
  never touched by the tests.

Because the model's output is never trusted — `ActionValidationService` is the
guardrail, not the model's goodwill — a fake that returns a fixed string is a
faithful stand-in for the real thing.
"""
from __future__ import annotations

from typing import Callable, List, Optional, Protocol, Sequence, Union


class LanguageModelPort(Protocol):
    """Completes a prompt with text. The only thing the language layer needs an
    LLM to do; everything structural (which actions are allowed, whether a
    target is visible) is decided by services *around* this seam, never here."""

    def complete(self, prompt: str) -> str:
        """Return the model's text completion of ``prompt``."""
        ...


_Reply = Union[str, Sequence[str], Callable[[str], str], None]


class FakeLanguageModel:
    """A deterministic `LanguageModelPort` for tests — never makes a network
    call and needs no API key.

    Configure the reply one of three ways:

    - a fixed ``reply`` string, returned for every prompt;
    - a sequence of strings, returned one per call in order (a scripted
      conversation); or
    - a callable ``reply(prompt) -> str`` for prompt-dependent replies.

    ``echo=True`` returns the prompt verbatim instead — a faithful "the model
    rendered exactly the facts we gave it" stand-in, which lets a test assert
    that narration is built from the state it was handed rather than invented.
    Every prompt is recorded on ``prompts`` for inspection.
    """

    def __init__(self, reply: _Reply = None, *, echo: bool = False):
        self._echo = echo
        self._queue: Optional[List[str]] = None
        self._callable: Optional[Callable[[str], str]] = None
        self._constant = ""
        if callable(reply):
            self._callable = reply
        elif isinstance(reply, str):
            self._constant = reply
        elif reply is not None:
            self._queue = list(reply)
        self.prompts: List[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self._echo:
            return prompt
        if self._callable is not None:
            return self._callable(prompt)
        if self._queue is not None:
            return self._queue.pop(0) if self._queue else ""
        return self._constant

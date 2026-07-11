"""ConversationTurn — one exchange of a multi-turn conversation about read material
(reading R6, extends ADR 0039).

A conversation is a several-turn back-and-forth: the user asks, the being answers
grounded in what it has READ (retrieval + citation, reused from R4), and the turn
is kept so later turns can resolve references to earlier ones ("tell me more about
that"). One turn is one such exchange — the `user_message` the person typed and the
being's grounded `answer` — tagged with the `conversation_id` it belongs to so the
being can hold several independent conversations at once. Append-only and durable
like every other learned fact (ADR 0017): a turn is a self-contained, replayable
record, so it carries no DB foreign key.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConversationTurn:
    """One turn of a conversation: the `user_message` and the being's grounded
    `answer`, tagged with the `conversation_id` they belong to. Immutable — a turn,
    once lived, is never edited; a new turn is appended instead."""

    conversation_id: str
    user_message: str
    answer: str

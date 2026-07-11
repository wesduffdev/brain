"""ConversationService — a multi-turn, grounded conversation about what the being
has READ (reading R6, extends ADR 0039/0038/0022).

The single-turn `ReadingQAService` (R4) already answers ONE question grounded in
the retrieved passages and CITING the source, and declines honestly when it has
read nothing relevant. This service holds a several-turn BACK-AND-FORTH on top of
it, adding exactly two things and nothing more:

- HISTORY: every turn (the user's message + the being's grounded answer) is kept,
  per conversation, through the same repository + unit-of-work seam every learned
  fact persists through (ADR 0017) — so the conversation is durable and cumulative.
- HISTORY-AWARE GROUNDING: a FOLLOW-UP that refers back but names no subject of its
  own ("tell me more about that", "what else?") has the recent turns' questions
  folded into its RETRIEVAL query, so it reaches the subject established earlier and
  stays grounded + cited. A message that names its OWN subject stands alone, so a
  NEW topic — including one the being has NOT read about — is judged on its own
  words and declined honestly rather than dragged onto a prior topic.

Every turn's answer still comes from `ReadingQAService`, so the R4 guarantees carry
over unchanged: the model only ever sees the retrieved passages + the (folded)
question, and the citation is taken from retrieval — never the model — so a
conversation can no more fabricate grounding or a source than a single question
can. Like all of the language layer it reads and mutates nothing in the sim (ADR
0022): conversing touches the knowledge store, the model, and the turn store — never
the being or the world.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from app.domain.conversation import ConversationTurn
from app.policies import ConversationPolicy
from app.services.reading_qa_service import ReadingQAService


class ConversationService:
    def __init__(
        self,
        reading_qa: ReadingQAService,
        repository,
        *,
        policy: Optional[ConversationPolicy] = None,
        unit_of_work=None,
    ) -> None:
        self._qa = reading_qa
        self._repository = repository
        self._policy = policy if policy is not None else ConversationPolicy()
        if unit_of_work is None:
            from app.db.unit_of_work import NullUnitOfWork  # noqa: PLC0415 — in-memory default

            unit_of_work = NullUnitOfWork()
        self._unit_of_work = unit_of_work

    def reply(self, conversation_id: str, message: str) -> str:
        """The being's grounded, cited reply to `message` in conversation
        `conversation_id`, aware of the turns before it. Read-only w.r.t. the sim
        (ADR 0022); the turn is persisted transactionally (ADR 0017)."""
        history = self._repository.history(conversation_id)
        answer = self._qa.answer(self._effective_query(message, history))
        with self._unit_of_work.begin():
            self._repository.add(
                ConversationTurn(
                    conversation_id=conversation_id,
                    user_message=message,
                    answer=answer,
                )
            )
        return answer

    def _effective_query(self, message: str, history: Sequence[ConversationTurn]) -> str:
        """The retrieval query for this turn. A follow-up that refers back but names
        no subject of its own gets the recent turns' questions prepended, so it
        reaches the subject established earlier; anything else stands alone, so a new
        (possibly unread) topic is judged only on its own words."""
        if not history or not self._policy.is_followup(message):
            return message
        window = self._policy.recent(history)
        prior = " ".join(turn.user_message for turn in window).strip()
        return f"{prior} {message}".strip() if prior else message

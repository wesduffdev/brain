"""ReadingQAService — the being answers what it has READ, grounded in the retrieved
passages and CITING the source document (reading R4, ADR 0039).

The conversational half of the reading faculty, sitting on the SAME two seams the
rest of the language layer uses: the `RetrievalPort` (the R3 growing knowledge
store, ADR 0038) and the `LanguageModelPort` (ADR 0022). Ask a question and it
retrieves the top-k passages, keeps only those relevant enough, and:

- GROUNDED path (something read is relevant): it hands the model a prompt built
  from ONLY the retrieved passages + the question — never the whole store — so the
  model cannot invent grounding, and it prefixes the answer with the read label and
  appends the SOURCE document(s), taken from the retrieval result (never the model),
  so the citation can never be fabricated. With no generative model (the offline
  template deploy) it answers EXTRACTIVELY — quoting what it read — so grounding
  and citation hold with no model call at all.
- UNREAD path (nothing read is relevant): it says so honestly, naming the topic,
  and NEVER carries a citation. When `blend_base_knowledge` is on and a model is
  present, it also offers a base-knowledge answer — the model answering WITHOUT any
  retrieved context (so it can carry no source) — labelled distinctly, so what the
  being READ is always transparent from what it already KNEW.

Like all of the language layer it reads and mutates nothing (ADR 0022): asking
touches the knowledge store and the model, never the being or the world.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from app.policies import ReadingQAPolicy
from app.ports.language_model import LanguageModelPort
from app.ports.retrieval import RetrievalPort, RetrievedPassage


class ReadingQAService:
    def __init__(
        self,
        retrieval: RetrievalPort,
        *,
        model: Optional[LanguageModelPort] = None,
        policy: Optional[ReadingQAPolicy] = None,
    ) -> None:
        self._retrieval = retrieval
        # Optional by design: with no generative model the grounded answer is
        # EXTRACTIVE (quotes the passages), so the being still answers grounded and
        # cited offline — fluency is an upgrade, grounding is guaranteed.
        self._model = model
        self._policy = policy if policy is not None else ReadingQAPolicy()

    def answer(self, question: str) -> str:
        """A grounded, cited answer to ``question`` from what the being has read, or
        the honest unread line when nothing read is relevant. Read-only (ADR 0022)."""
        relevant = [
            passage
            for passage in self._retrieval.search(question, self._policy.k)
            if passage.score >= self._policy.min_relevance
        ]
        if relevant:
            return self._grounded(question, relevant)
        return self._unread(question)

    # --- the grounded, cited answer ---------------------------------------

    def _grounded(self, question: str, passages: Sequence[RetrievedPassage]) -> str:
        body = ""
        if self._model is not None:
            body = self._model.complete(self._grounded_prompt(question, passages)).strip()
        if not body:
            # No model (offline template deploy) or an empty completion: quote what
            # was read, so the answer is grounded in the passages either way.
            body = " ".join(passage.text.strip() for passage in passages).strip()
        sources = self._sources(passages)
        citation = self._policy.cite_template.format(sources=", ".join(sources))
        return f"{self._policy.read_label}: {body} {citation}".strip()

    @staticmethod
    def _grounded_prompt(question: str, passages: Sequence[RetrievedPassage]) -> str:
        """The model sees ONLY the retrieved passages (each tagged with its source)
        and the question — never the rest of the store — so it cannot ground its
        answer in anything the being has not read for this query."""
        lines = [
            "Answer the question in a few plain first-person sentences, using ONLY "
            "the passages below — things you have read. Do not use any outside "
            "knowledge; if the passages do not answer it, say so.",
            "Question: " + question,
            "Passages: " + str(len(passages)),
        ]
        for passage in passages:
            lines.append("- [" + passage.source + "] " + passage.text.strip())
        return "\n".join(lines)

    @staticmethod
    def _sources(passages: Sequence[RetrievedPassage]) -> List[str]:
        """The distinct source documents of the retrieved passages, best-first —
        the citation, taken from retrieval (never the model, so never fabricated)."""
        ordered: List[str] = []
        for passage in passages:
            if passage.source not in ordered:
                ordered.append(passage.source)
        return ordered

    # --- the honest unread answer (+ optional labelled base knowledge) ----

    def _unread(self, question: str) -> str:
        line = self._policy.unread_response.replace("{topic}", self._topic(question))
        if self._policy.blend_base_knowledge and self._model is not None:
            base = self._model.complete(self._base_prompt(question)).strip()
            if base:
                line = f"{line} {self._policy.base_label}: {base}"
        return line

    @staticmethod
    def _base_prompt(question: str) -> str:
        """A base-knowledge prompt: the question and NOTHING read — no passages, no
        source — so the answer draws only on the model's own knowledge and can carry
        no citation."""
        return (
            "Answer the question from your own general knowledge, in a few plain "
            "first-person sentences.\nQuestion: " + question
        )

    def _topic(self, question: str) -> str:
        """The topic a question asks about — the text after a `topic_markers`
        connective ("...about dinosaurs" -> "dinosaurs"), else the whole question,
        trimmed of surrounding whitespace and trailing sentence punctuation."""
        lowered = str(question).lower()
        for marker in self._policy.topic_markers:
            token = " " + marker + " "
            index = lowered.find(token)
            if index != -1:
                return question[index + len(token):].strip().rstrip("?!.,;: ") or question.strip()
        return question.strip().rstrip("?!.,;: ")

"""TemplateLanguageModel — a deterministic, fully-offline `LanguageModelPort`
(S1, ADR 0032; extends ADR 0022).

The FIRST real narrator: it turns the being's structured experience into plain
first-person prose with no external model, no network, and no key — a talking
being on day one. It sits behind the SAME `complete(prompt) -> str` seam the
Claude adapter and the test `FakeLanguageModel` implement (ADR 0022 — no new
port), so swapping it for a fluent model (S2) changes only phrasing, never the
grounding.

How it stays grounded. `MemorySummaryService` / `NarrationService` serialize the
being's memory / state snapshots into a small, documented FACT-LINE grammar and
pass it in as the prompt; this narrator PARSES those facts and renders them —
inventing nothing. Each memory fact-line is::

    - action=push object=obj_red_ball perceived=round,red observed=rolls felt=calm salience=0.00

and a present-state fact-line (no `action`) is::

    - felt=scared perceives=hot,hard objects=obj_hot_lamp

Lines that do not begin with ``-`` (the instruction preamble, the counts) are
ignored. A round-trip through a string is the price of keeping ONE language seam
(ADR 0032); parsing is lenient — unknown or missing tokens degrade to a safe
default rather than raise — so a format tweak upstream never crashes the being.

Rendering is config-driven (ADR-0022 discipline): the verbs, outcome clauses,
and feeling words all come from a `NarrationPhrasing` (`config/language.yaml`),
never hard-coded here; an unmapped label falls back to itself, so the report is
grounded even before a word is authored. Crucially it describes an object by its
PERCEIVED properties only — never the object id or a developer label (ADR 0002).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from app.policies import NarrationPhrasing


class TemplateLanguageModel:
    """A deterministic `LanguageModelPort`. Renders the fact-line prompt built by
    the narration services into grounded first-person prose."""

    def __init__(
        self,
        *,
        phrasing: Optional[NarrationPhrasing] = None,
        salience_emphasis_threshold: float = 1.0,
        neutral_emotion: str = "calm",
    ) -> None:
        self._phrasing = phrasing if phrasing is not None else NarrationPhrasing()
        self._salience_threshold = float(salience_emphasis_threshold)
        self._neutral_emotion = neutral_emotion

    def complete(self, prompt: str) -> str:
        """Render the fact-lines in ``prompt`` into a plain self-report. A subject
        fact (``kind=subject``, the S3 "what do you know about X" answer) takes
        precedence; else a memory fact (past tense); else a present-state fact
        describes the current moment; with none, a safe 'nothing yet' line."""
        facts = [self._parse(line) for line in prompt.splitlines() if line.lstrip().startswith("-")]

        subjects = [fact for fact in facts if fact.get("kind") == "subject"]
        if subjects:
            return self._render_subject(subjects)

        memories = [fact for fact in facts if fact.get("action")]
        if memories:
            return self._join_sentences(self._render_memory(fact) for fact in memories)

        present = next((fact for fact in facts if "felt" in fact or "perceives" in fact), None)
        if present is not None:
            return self._render_present(present)

        return "I haven't done anything I can tell you about yet."

    # --- rendering --------------------------------------------------------

    def _render_memory(self, fact: Dict[str, object]) -> str:
        verb = self._phrasing.action(str(fact.get("action", "")))
        subject = self._thing(self._list(fact, "perceived"))
        clause = self._outcome_clause(self._list(fact, "observed"))
        affect = self._affect(str(fact.get("felt", "")), self._salience(fact))
        return f"I {verb} {subject}{clause}{affect}."

    def _render_present(self, fact: Dict[str, object]) -> str:
        feeling = str(fact.get("felt", ""))
        props = self._list(fact, "perceives")
        if not feeling and not props:
            return "I haven't done anything I can tell you about yet."
        parts: List[str] = ["I haven't done anything I can tell you about yet."]
        if feeling:
            parts.append(f"Right now I feel {self._phrasing.feel(feeling)}.")
        if props:
            parts.append(f"I can see {self._thing(props)}.")
        return " ".join(parts)

    def _render_subject(self, facts: List[Dict[str, object]]) -> str:
        # The S3 subject answer: what the being KNOWS and FEELS about a property it
        # has learned about. Group the learned facts by (perceived property, action)
        # so one sentence carries a property's outcomes together, and colour it with
        # the strongest-felt emotion the being's memories recorded of that property.
        groups: "Dict[tuple, Dict[str, object]]" = {}
        order: List[tuple] = []
        for fact in facts:
            prop = str(fact.get("property", ""))
            action = str(fact.get("action", ""))
            key = (prop, action)
            group = groups.get(key)
            if group is None:
                group = {"outcomes": [], "felt": "", "salience": -1.0}
                groups[key] = group
                order.append(key)
            outcome = str(fact.get("outcome", ""))
            outcomes = group["outcomes"]
            if outcome and outcome not in outcomes:
                outcomes.append(outcome)
            felt = str(fact.get("felt", ""))
            salience = self._salience(fact)
            if felt and salience >= float(group["salience"]):
                group["felt"] = felt
                group["salience"] = salience
        return self._join_sentences(
            self._subject_sentence(prop, action, groups[(prop, action)])
            for (prop, action) in order
        )

    def _subject_sentence(self, prop: str, action: str, group: Dict[str, object]) -> str:
        clauses = self._join_list(
            [self._phrasing.outcome(o) for o in group["outcomes"]]
        )
        salience = float(group["salience"])
        affect = self._affect(str(group["felt"]), salience if salience > 0.0 else 0.0)
        thing = f"a {prop} thing"
        if action:
            return f"When I {self._phrasing.action(action)} {thing}, {clauses}{affect}."
        return f"A {prop} thing — {clauses}{affect}."

    def _outcome_clause(self, outcomes: Sequence[str]) -> str:
        if not outcomes:
            return ""
        return ", and " + self._join_list([self._phrasing.outcome(o) for o in outcomes])

    def _affect(self, feeling: str, salience: float) -> str:
        # emotion_after + priority => the felt tail (ADR 0032). A neutral feeling
        # is omitted (not invented away — just not worth saying); a high-salience
        # memory is emphasized, config-driven so retuning the bar is YAML-only.
        if not feeling or feeling == self._neutral_emotion:
            return ""
        adverb = "very " if salience >= self._salience_threshold else ""
        return f" -- afterwards I felt {adverb}{self._phrasing.feel(feeling)}"

    def _thing(self, properties: Sequence[str]) -> str:
        # An object is named by what the being PERCEIVED, never its id/label.
        if not properties:
            return "it"
        return f"the {self._join_list(list(properties))} thing"

    # --- parsing / small helpers -----------------------------------------

    @staticmethod
    def _parse(line: str) -> Dict[str, object]:
        """A ``- key=value key=value`` fact-line into a dict; comma-lists stay as
        the raw string (split lazily by `_list`). Tokens without `=` are ignored."""
        fields: Dict[str, object] = {}
        for token in line.lstrip().lstrip("-").split():
            if "=" in token:
                key, value = token.split("=", 1)
                fields[key] = value
        return fields

    @staticmethod
    def _list(fact: Dict[str, object], key: str) -> List[str]:
        raw = str(fact.get(key, "") or "")
        return [item for item in raw.split(",") if item]

    @staticmethod
    def _salience(fact: Dict[str, object]) -> float:
        try:
            return float(str(fact.get("salience", 0.0)))
        except ValueError:
            return 0.0

    @staticmethod
    def _join_list(items: Sequence[str]) -> str:
        """Oxford-free natural join: [a] -> 'a'; [a,b] -> 'a and b';
        [a,b,c] -> 'a, b and c'."""
        items = list(items)
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        return ", ".join(items[:-1]) + " and " + items[-1]

    @staticmethod
    def _join_sentences(sentences) -> str:
        # Collapse consecutive identical sentences so a run of the same idle act
        # reads once, not five times — dedup, never invent.
        out: List[str] = []
        for sentence in sentences:
            if not out or out[-1] != sentence:
                out.append(sentence)
        return " ".join(out)

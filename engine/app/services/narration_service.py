"""NarrationService — turns a state snapshot into a readable, NON-authoritative
narration (card v9, BRIEF §17).

This is the "narrate" half of the language layer. Given a `Simulation.state()`
snapshot, it builds a factual prompt from that snapshot (the being's emotion,
its needs, what it perceives, and the action it just took) and asks the language
model to phrase it. The narration is a description laid *on top* of the sim: it
is derived strictly from the snapshot it is handed, and it never feeds back —
nothing here mutates the being or the world. It reads a plain dict, so the
`Simulation` stays a black box; running narration over a state leaves that state
exactly as it was.

Because the prompt is built only from the passed-in facts, the narration
reflects state rather than inventing or overriding it — language sits on top,
never in control.
"""
from __future__ import annotations

from typing import Mapping

from app.ports.language_model import LanguageModelPort


class NarrationService:
    def __init__(self, model: LanguageModelPort):
        self._model = model

    def narrate(self, snapshot: Mapping) -> str:
        """Return a readable, non-authoritative narration of ``snapshot``.
        Read-only: derives its prompt from the snapshot and mutates nothing."""
        return self._model.complete(self._prompt(snapshot)).strip()

    @staticmethod
    def _prompt(snapshot: Mapping) -> str:
        emotion = snapshot.get("emotion", "unknown")
        needs = snapshot.get("needs", {}) or {}
        perceived = (snapshot.get("perceived", {}) or {}).get("objects", []) or []
        seen = ", ".join(str(obj.get("objectId")) for obj in perceived) or "nothing"
        needs_text = ", ".join(f"{name}={value}" for name, value in needs.items()) or "none"

        lines = [
            "Describe, in one or two plain sentences, what the being is "
            "experiencing right now. Narrate only these facts; do not invent "
            "actions or outcomes.",
            f"Emotion: {emotion}",
            f"Needs: {needs_text}",
            f"Perceives: {seen}",
        ]
        current = snapshot.get("currentAction")
        if current:
            lines.append(
                f"Just did: {current.get('type')} -> {current.get('targetId')}"
            )
        return "\n".join(lines)

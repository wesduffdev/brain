"""RenderStateService — maps the domain `state()` snapshot onto the renderer's
`being_state_update` frame (ADR 0004).

It is the one place that turns what the being *is* into what the renderer draws:
it copies the domain snapshot through unchanged (so a `perceived` block, the
`curiosity`/`surprise` maps card v4 adds to `state()`, and any field a later slice
adds, flow onto the wire without a change here), stamps the frame `type`, looks up
the emotion's `visual` draw hints from config, folds an ACTIVE instinct reaction
(INS-ACT's `state()["reaction"]`) into that `visual` block as `visual.reaction`
from the same config, and reports a neutral `intensity` until the emotion model
carries one (~V0-4).

It makes NO psychology decision — the emotion is already derived upstream; the
visual is a pure config lookup keyed by that emotion, and `pose`/`action` are
simply absent until the domain supplies them. Retuning how an emotion LOOKS is a
`config/render_hints.yaml` edit, never a code change.
"""
from __future__ import annotations

from typing import Dict, Mapping

from app.policies import RenderHintsPolicy

_FRAME_TYPE = "being_state_update"


class RenderStateService:
    def __init__(self, hints: RenderHintsPolicy):
        self._hints = hints

    def render(self, state: Mapping) -> Dict:
        """Map one domain `state()` snapshot to a `being_state_update` frame.

        Forward-compatible: every field the domain reports passes through, unknown
        or future fields included; absent optional fields (`pose`/`action`) stay
        absent. The service only adds the presentation envelope — the frame
        `type`, the `visual` draw hints, and a neutral `intensity` default."""
        frame: Dict = dict(state)
        frame["type"] = _FRAME_TYPE
        visual = self._visual_for(frame.get("emotion"))
        reaction_visual = self._reaction_visual(frame.get("reaction"))
        if reaction_visual is not None:
            visual["reaction"] = reaction_visual
        frame["visual"] = visual
        frame.setdefault("intensity", self._hints.intensity_default)
        return frame

    def _visual_for(self, emotion) -> Dict:
        hint = self._hints.by_emotion.get(emotion, self._hints.default)
        return dict(hint)

    def _reaction_visual(self, reaction):
        """Present an active instinct reaction as `visual.reaction` (RENDER-RX).

        `reaction` is INS-ACT's `state()["reaction"]` — `{type, intensity}` when a
        reaction is active, absent otherwise. Returns the config draw hints for that
        reaction label stamped with the engine-decided `type` + `intensity`, or
        ``None`` when no reaction is active (the frame is then unchanged from today).
        It makes NO psychology decision — the reaction is already selected upstream;
        this is a pure config lookup keyed by its label."""
        if not isinstance(reaction, Mapping):
            return None
        label = reaction.get("type")
        if not label:
            return None
        hint = self._hints.by_reaction.get(label, {})
        return {"type": label, "intensity": reaction.get("intensity"), **dict(hint)}

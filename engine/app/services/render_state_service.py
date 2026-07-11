"""RenderStateService — maps the domain `state()` snapshot onto the renderer's
`being_state_update` frame (ADR 0004).

It is the one place that turns what the being *is* into what the renderer draws:
it copies the domain snapshot through unchanged (so a `perceived` block, the
`curiosity`/`surprise` maps card v4 adds to `state()`, and any field a later slice
adds, flow onto the wire without a change here), stamps the frame `type`, looks up
the emotion's `visual` draw hints from config, and reports a neutral `intensity`
until the emotion model carries one (~V0-4).

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
        frame["visual"] = self._visual_for(frame.get("emotion"))
        frame.setdefault("intensity", self._hints.intensity_default)
        return frame

    def _visual_for(self, emotion) -> Dict:
        hint = self._hints.by_emotion.get(emotion, self._hints.default)
        return dict(hint)

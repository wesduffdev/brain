"""StimulusService — turns perceived object MOTION into an approach STIMULUS
(WORLD-MOTION, ADR 0027; extends the perception seam, ADR 0002).

Perception (ADR 0002) says *what* objects the being can make out; this service
adds *how they move relative to it*. It holds the world's live kinematic state
(one `Motion` per object, seeded from config), advances it one tick each time the
being acts, and — for every object that is actually closing on the body — derives
the frozen 14-feature approach vector (ADR 0026, via `MotionPolicy`) and publishes
it as a `being.perception.object_approached` domain event on
`being.perception.events`. It is the *only* producer of that stimulus, and the
single home of the motion state, so `Simulation` stays a thin wirer.

The publisher is a seam (ADR 0024): injected, it puts the stimulus on the bus for
the instinct model to consume; absent, motion still advances and the stimulus is
still exposed through `Simulation.state()` — the being's world moves whether or not
anything is listening. Motion is a world/perception concern only: this service
never touches the being's needs, emotion, or decision.
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional

from app.domain.event import DomainEvent
from app.domain.motion import Motion
from app.policies import MotionPolicy
from app.ports.events import EventPublisher

# The one topic the approach stimulus travels on, and how the event names itself
# (matches the EVT-BUS catalogue, ADR 0024).
PERCEPTION_TOPIC = "being.perception.events"
OBJECT_APPROACHED = "being.perception.object_approached"
_SOURCE_SERVICE = "perception-service"


class StimulusService:
    def __init__(
        self,
        policy: MotionPolicy,
        *,
        being_id: str,
        publisher: Optional[EventPublisher] = None,
    ) -> None:
        self._policy = policy
        self._being_id = being_id
        self._publisher = publisher
        # The live kinematic state (seeded from config) and last tick's, so
        # between-tick rates (acceleration, looming) have a `prior` to read.
        self._motions: Dict[str, Motion] = policy.initial_motions()
        self._prior: Dict[str, Motion] = {}
        self._stimuli: List[Dict] = []

    def observe(self, *, perceived: List[Mapping], tick: int) -> List[Dict]:
        """Advance every object one tick, and raise an approach stimulus for each
        that is now closing on the body. Publishes an `ObjectApproached` event per
        stimulus when a publisher is wired; always records the stimuli for
        `stimuli()`. `perceived` supplies each object's visibility confidence (ADR
        0002) — an object the being cannot make out contributes none."""
        confidence = {obj["objectId"]: obj.get("confidence", 0.0) for obj in perceived}
        advanced: Dict[str, Motion] = {}
        stimuli: List[Dict] = []
        for object_id, motion in self._motions.items():
            prior = self._prior.get(object_id, motion)
            stepped = motion.advanced()
            advanced[object_id] = stepped
            # World-truth motion advances for every object, but a stimulus is a
            # PERCEPTION: raise it only for an object the being can make out this
            # tick (in its room, ADR 0002) that is actually closing on the body.
            if object_id not in confidence:
                continue
            if not self._policy.is_approaching(stepped):
                continue
            features = self._policy.features(
                stepped, prior, visibility_confidence=confidence.get(object_id, 0.0)
            )
            stimuli.append({"objectId": object_id, "features": features})
            if self._publisher is not None:
                self._publisher.publish(
                    PERCEPTION_TOPIC,
                    DomainEvent.create(
                        event_type=OBJECT_APPROACHED,
                        event_version=1,
                        source_service=_SOURCE_SERVICE,
                        being_id=self._being_id,
                        payload={"objectId": object_id, "tick": tick, "features": features},
                    ),
                )
        self._prior = self._motions
        self._motions = advanced
        self._stimuli = stimuli
        return stimuli

    def stimuli(self) -> List[Dict]:
        """The current tick's approach stimuli, as plain copies — one per object
        closing on the body, each carrying the frozen 14-feature vector. Empty
        before the first tick and whenever nothing is approaching."""
        return [
            {"objectId": s["objectId"], "features": dict(s["features"])} for s in self._stimuli
        ]

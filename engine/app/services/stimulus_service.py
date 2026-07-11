"""StimulusService — turns the being's perceived SENSORY signals into instinct
STIMULI: object MOTION (an approach), a SUDDEN sound (a spike), and an object
reaching the body (a contact) (SENSORY-STIM; extends WORLD-MOTION / ADR 0027,
which extends the perception seam ADR 0002).

Perception (ADR 0002) says *what* objects the being can make out; this service
adds *how they move relative to it*, *what it suddenly hears*, and *what touches
it*. It holds the world's live kinematic state (one `Motion` per object, seeded
from config) plus the last sound category it heard, advances motion one tick each
time the being acts, and derives:

- for every object closing on the body, the frozen 14-feature APPROACH vector
  (ADR 0026, via `MotionPolicy.features`);
- for an object that has just crossed into the body, a CONTACT vector carrying a
  real `touch_intensity` (`MotionPolicy.contact_features`);
- for a sudden transition into a loud/unknown sound, a SOUND-SPIKE vector carrying
  a real `sound_spike_intensity` (`MotionPolicy.sound_features`).

Each is published as a domain event on `being.perception.events`; all three carry
the same frozen 14-feature payload, so the instinct consumer treats them
uniformly. This is the only producer of these stimuli and the single home of the
sensory world-state, so `Simulation` stays a thin wirer.

The publisher is a seam (ADR 0024): injected, it puts each stimulus on the bus
for the instinct model to consume; absent, the world still advances and the
stimuli are still exposed through `Simulation.state()`. Sound/touch are
world/perception concerns only, keyed on perceived signals (never a developer
label, ADR 0002): this service never touches the being's needs, emotion, or
decision.
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional

from app.domain.event import DomainEvent
from app.domain.motion import Motion
from app.policies import MotionPolicy
from app.ports.events import EventPublisher

# The one topic the stimuli travel on, and how each event names itself (matches
# the EVT-BUS catalogue, ADR 0024). Approach is WORLD-MOTION's; the sound spike
# and the contact are SENSORY-STIM's — the instinct consumer treats all three as
# stimuli, each carrying the frozen 14-feature payload.
PERCEPTION_TOPIC = "being.perception.events"
OBJECT_APPROACHED = "being.perception.object_approached"
SOUND_SPIKE = "being.perception.sound_spike"
OBJECT_CONTACTED = "being.perception.object_contacted"
_SOURCE_SERVICE = "perception-service"
# A sound is not tied to a catalogued object — this is the perceived SOURCE token
# a sound-spike stimulus keys on (a heard signal, not a developer label).
SOUND_SOURCE_ID = "ambient_sound"

# The first-observation sentinel for the heard sound: the being's BIRTH sound is a
# baseline, never itself a spike — only a later transition into a loud/unknown
# category is sudden.
_UNSET = object()


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
        # The last sound category heard — the baseline a spike is a transition from.
        self._sound = _UNSET
        self._stimuli: List[Dict] = []

    def observe(
        self, *, perceived: List[Mapping], tick: int, sound: Optional[str] = None
    ) -> List[Dict]:
        """Advance every object one tick and raise this tick's stimuli: an APPROACH
        for each object closing on the body, a CONTACT for each that has just
        reached it, and a SOUND SPIKE when the heard `sound` has just transitioned
        into a loud/unknown category. Publishes one event per stimulus when a
        publisher is wired; always records them for `stimuli()`. `perceived`
        supplies each object's visibility confidence (ADR 0002) — an object the
        being cannot make out contributes none."""
        confidence = {obj["objectId"]: obj.get("confidence", 0.0) for obj in perceived}
        advanced: Dict[str, Motion] = {}
        stimuli: List[Dict] = []

        # A sudden sound the being HEARS is raised first — it needs no object.
        sound_stimulus = self._sound_spike(sound)
        if sound_stimulus is not None:
            stimuli.append(sound_stimulus)
            self._publish(SOUND_SPIKE, sound_stimulus, tick)

        for object_id, motion in self._motions.items():
            prior = self._prior.get(object_id, motion)
            stepped = motion.advanced()
            advanced[object_id] = stepped
            # World-truth motion advances for every object, but a stimulus is a
            # PERCEPTION: raise it only for an object the being can make out this
            # tick (in its room, ADR 0002).
            if object_id not in confidence:
                continue
            base = self._policy.features(
                stepped, prior, visibility_confidence=confidence.get(object_id, 0.0)
            )
            if self._policy.is_approaching(stepped):
                stimulus = {"objectId": object_id, "features": base}
                stimuli.append(stimulus)
                self._publish(OBJECT_APPROACHED, stimulus, tick)
            # A CONTACT is the object CROSSING into the body this step — an
            # unexpected touch, distinct from (and possibly alongside) the approach.
            if self._policy.is_contact(motion.distance(), stepped.distance()):
                stimulus = {
                    "objectId": object_id,
                    "features": self._policy.contact_features(base, impact_speed=stepped.speed()),
                }
                stimuli.append(stimulus)
                self._publish(OBJECT_CONTACTED, stimulus, tick)

        self._prior = self._motions
        self._motions = advanced
        self._stimuli = stimuli
        return stimuli

    def stimuli(self) -> List[Dict]:
        """The current tick's stimuli, as plain copies — one per object closing on
        the body, per fresh contact, and per sudden sound, each carrying the frozen
        14-feature vector. Empty before the first tick and whenever nothing is
        approaching, touching, or newly heard."""
        return [
            {"objectId": s["objectId"], "features": dict(s["features"])} for s in self._stimuli
        ]

    # --- internals -------------------------------------------------------

    def _sound_spike(self, sound: Optional[str]) -> Optional[Dict]:
        """The sound-spike stimulus for a sudden transition into a loud/unknown
        sound, or None. The first observation only sets the baseline (birth is
        never a spike); thereafter a change INTO a configured spike category is the
        startle the being freezes at."""
        prior = self._sound
        self._sound = sound
        if prior is _UNSET or prior == sound:
            return None
        features = self._policy.sound_features(sound)
        if features is None:
            return None
        return {"objectId": SOUND_SOURCE_ID, "features": features}

    def _publish(self, event_type: str, stimulus: Dict, tick: int) -> None:
        if self._publisher is None:
            return
        self._publisher.publish(
            PERCEPTION_TOPIC,
            DomainEvent.create(
                event_type=event_type,
                event_version=1,
                source_service=_SOURCE_SERVICE,
                being_id=self._being_id,
                payload={
                    "objectId": stimulus["objectId"],
                    "tick": tick,
                    "features": stimulus["features"],
                },
            ),
        )

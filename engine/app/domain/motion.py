"""Motion — one object's kinematic state, as world-truth (ADR 0027).

The being lives at the origin (its *body*); an object's `position` and `velocity`
are measured relative to it, in a small 2-D plane, per tick. This is pure
geometry with no config and no perception: it answers "how far is it?", "how fast
is it moving?", "is it heading at the body, and how squarely?", and "how long
until it gets here?" — the raw quantities the approach stimulus is normalized
from (`MotionPolicy`). The being never reads a Motion directly (ADR 0002); the
StimulusService turns it into a *perceived* approach stimulus.

Keeping the trajectory in 2-D (not a signed 1-D distance) is deliberate: it lets
`trajectory_toward_body` be a genuine measure of *aim* — an object can be fast yet
sail past tangentially — distinct from raw speed, which is exactly the signal the
instinct model needs. `advanced()` integrates one tick of constant-velocity motion
into a fresh Motion (frozen: a step is a new value, never a mutation).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Tuple

# Below this distance the object is treated as "at the body" — guards the
# divide-by-zero in the direction math without a magic literal scattered around.
_EPSILON = 1e-9


@dataclass(frozen=True)
class Motion:
    """An object's position and velocity relative to the being's body at the
    origin, plus its physical `size`. Distances/velocities are in abstract world
    units per tick; `size` is an abstract extent used for the apparent-size (looming)
    signal."""

    object_id: str
    position: Tuple[float, float] = (0.0, 0.0)
    velocity: Tuple[float, float] = (0.0, 0.0)
    size: float = 0.0

    def advanced(self, dt: float = 1.0) -> "Motion":
        """This object one tick on: position integrated by its (constant) velocity."""
        (x, y), (vx, vy) = self.position, self.velocity
        return replace(self, position=(x + vx * dt, y + vy * dt))

    def distance(self) -> float:
        """How far the object is from the body."""
        return math.hypot(self.position[0], self.position[1])

    def speed(self) -> float:
        """The magnitude of the object's velocity (direction-agnostic)."""
        return math.hypot(self.velocity[0], self.velocity[1])

    def closing_speed(self) -> float:
        """The rate the object's distance is DECREASING — the component of its
        velocity aimed straight at the body. Positive means approaching, negative
        means receding, zero means holding range (or moving purely tangentially).
        At the body it is the full speed (it cannot get any closer honestly)."""
        d = self.distance()
        if d < _EPSILON:
            return self.speed()
        x, y = self.position
        vx, vy = self.velocity
        return -(vx * x + vy * y) / d

    def trajectory_toward_body(self) -> float:
        """How squarely the object is aimed at the body, in ``[0, 1]``: 1.0 dead-on,
        0.0 moving away or tangentially. This is the cosine of the angle between the
        velocity and the direction toward the body, floored at 0 — a *steering*
        signal independent of how fast the object moves."""
        s = self.speed()
        d = self.distance()
        if s < _EPSILON or d < _EPSILON:
            return 0.0
        x, y = self.position
        vx, vy = self.velocity
        alignment = -(vx * x + vy * y) / (s * d)
        return max(0.0, min(1.0, alignment))

    def is_approaching(self, min_closing_speed: float = 0.0) -> bool:
        """Whether the object is closing on the body faster than `min_closing_speed`
        — the gate on whether it is an *approach* worth raising a stimulus for."""
        return self.closing_speed() > min_closing_speed

    def time_to_contact(self) -> float:
        """Ticks until the object reaches the body at its current closing speed;
        ``inf`` when it is not closing (never arrives)."""
        closing = self.closing_speed()
        if closing <= 0.0:
            return math.inf
        return self.distance() / closing

    def apparent_size(self) -> float:
        """How large the object *looms* — its size over its distance, so a nearer
        object of the same size appears bigger. The change in this between ticks is
        the looming (size-change) signal."""
        d = self.distance()
        if d < _EPSILON:
            return self.size / _EPSILON
        return self.size / d

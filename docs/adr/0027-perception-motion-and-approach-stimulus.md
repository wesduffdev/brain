# 0027 — Perception motion and the approach stimulus seam

## Status

Accepted

## Date

2026-07-11

## Context

The event-instinct wave (see
[`docs/event_instinct_execution_plan.md`](../event_instinct_execution_plan.md),
card `WORLD-MOTION`) adds an instinct layer whose model consumes fast sensory/
kinematic features — velocity, trajectory-toward-body, time-to-contact,
size-change-rate. **Today's world has no source for any of them.** The perception
seam (ADR 0002) turns a static `Room` + `ObjectEntity` catalog into a *perceived*
view (`{objectId, confidence, properties, affordances}`); nothing in it moves, and
`state()` carries no motion, velocity, or stimulus. The instinct feature vector is
**frozen** in [ADR 0026](0026-instinct-neural-model-strategy.md) (14 ordered,
normalized scalars) — and that ADR names `WORLD-MOTION` as the producer of those
features. So before `INS-MODEL`/`INS-RT` can do anything, the world needs objects
that move and a perception step that derives an approach stimulus from that motion
and emits it as a domain event (the `EVT-BUS` backbone, ADR 0024).

This must land without disturbing the being: motion is a **world/perception**
fact, not a decision input, and the suite must stay hermetic (no broker). It also
must honor the perception invariant — a stimulus keys on *perceived* kinematics,
never on an object's human-only `developer_label` (ADR 0002).

## Decision

Extend the perception seam with a small kinematic layer and a dedicated stimulus
producer, all behind existing seams.

- **`Motion` (new domain value).** A frozen dataclass — `object_id`, `position`,
  `velocity` (2-D, relative to the being's body at the origin), and `size` — with
  pure geometry: `distance`, `speed`, `closing_speed`, `trajectory_toward_body`
  (the cosine of the velocity against the direction toward the body, floored at 0
  — a *steering* signal genuinely distinct from raw speed), `time_to_contact`,
  `apparent_size` (looming), and `advanced(dt)` (one tick of constant-velocity
  integration → a new value). No config, no perception, no torch. Keeping it 2-D
  is deliberate: it lets `trajectory_toward_body` mean *aim* — a fast object can
  sail past tangentially — which is exactly the signal instinct needs.

- **`MotionPolicy` (new typed policy).** Produced by `ConfigService` from
  `config/motion.yaml`. It bundles the normalization maxima (a raw quantity at its
  max reads as 1.0; acceleration/looming are signed `[-1, 1]` rates), the
  `min_closing_speed` gate on what counts as an *approach*, the `sensory_defaults`
  for features the world has no source for yet, and the authored per-object
  kinematic **seeds** — mirroring how `EnvironmentPolicy` bundles its impacts table
  with the constants that read it. Its `features(motion, prior, *, visibility_
  confidence)` builds the frozen ADR 0026 vector, in contract order, from one
  place (`MOTION_FEATURE_NAMES`). A motion seed naming an uncatalogued object is
  rejected loudly (the object-catalog vocabulary discipline).

- **`StimulusService` (new seam).** The single home of the live motion state and
  the only producer of the approach stimulus. Each time the being acts it advances
  every object one tick, and for each object the being can currently perceive
  (in its room, ADR 0002) that is closing on the body, it derives the 14-feature
  vector and publishes a `being.perception.object_approached` `DomainEvent` on
  `being.perception.events` through an injected `EventPublisher` (ADR 0024). World
  motion advances for every object; a *stimulus* is a perception, so it is raised
  only for perceived, approaching objects.

- **`Simulation` wires it, unchanged behavior.** A new `event_publisher` port
  (default `None`) is injected and handed to the `StimulusService`; `_act` calls
  `observe(...)` once per tick after perceiving, before deciding, and `state()`
  gains an additive `stimuli` block. With no publisher and no motion the being
  behaves byte-identically — motion feeds nothing into needs, emotion, or the
  decision (the guardrail: motion is a world/perception concern, not an instinct
  one).

### The frozen 14-feature payload (ADR 0026)

`features()` emits exactly, and in this order: `distance, velocity, acceleration,
trajectory_toward_body, time_to_contact, object_size, size_change_rate,
unexpectedness, visibility_confidence, sound_spike_intensity, touch_intensity,
current_focus_level, current_stability, prior_prediction_error`. Eight are sourced
now — the seven kinematics from `Motion`, and `visibility_confidence` from the
perceived confidence (ADR 0002). **Six are defaulted to `0.0`** because the world
has no source for them yet: `unexpectedness`, `sound_spike_intensity`,
`touch_intensity` (no sound/touch sensing exists), and `current_focus_level`,
`current_stability`, `prior_prediction_error` (the being's fast-loop internal
state, which the instinct consumer `INS-RT` folds in — not the world). The
defaults are config-overridable (`sensory_defaults`), never hard-coded, so a later
slice can supply a real source without a contract change.

## Consequences

- **Instinct has real features to consume.** `ObjectApproached` carries the exact
  frozen vector `INS-MODEL`'s encoder was built to, on the topic `INS-RT` will
  subscribe to — the prerequisite the instinct wave was blocked on.
- **The perception seam is extended, not broken.** Motion is a new perception-time
  side output; `state()` grows an additive `stimuli` block (consumers already
  serialize whatever `state()` returns and tolerate unknown fields, ADR 0002/0004).
- **The suite stays hermetic and behavior byte-identical.** The publisher is a
  port with the in-memory fake as the default; with no publisher and no motion the
  being is unchanged. Retuning motion, or moving an object, is a `config/motion.yaml`
  change only.
- **The perceived/true-world invariant holds.** A stimulus keys on perceived
  kinematics and confidence, never on `developer_label`, and is raised only for
  objects the being can perceive.
- **Cost.** One new domain value, one policy, one service, and one config file —
  accepted as the minimal honest source for the instinct features, kept small and
  deep behind the perception/event seams.

Extends: **ADR 0002** (the perceived-vs-true-world perception seam this adds motion
to). Builds on: **ADR 0024** (the event backbone the stimulus is published through)
and **ADR 0026** (the frozen instinct feature contract this produces). Supersedes
nothing.

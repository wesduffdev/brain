# jarvis — Situated Being

The ubiquitous language for the simulation: one situated **being** with
human-like psychology, existing in a room and stepped through time. This file is
a glossary only — no implementation detail. See [`docs/BRIEF.md`](docs/BRIEF.md)
for the architecture and [`docs/adr/`](docs/adr/) for decisions.

## Language

**Being**:
The situated agent the whole simulation is about — human-like in psychology
(needs, emotions, curiosity, memory), not tied to an age or life-stage.
_Avoid_: baby, child, person, character, NPC.

**Need**:
A drive the being has, held as a level in 0–100 that changes over time — hunger,
sleep, comfort, warmth, curiosity, safety.
_Avoid_: stat, attribute, meter.

**Contextual need**:
A need with no drift of its own; only the world (environment / perception) moves
it. Safety and warmth are contextual.
_Avoid_: passive need, external need.

**Emotion**:
The single dominant felt state, always *derived* from the being's needs and
never set directly (e.g. calm, curious, scared).
_Avoid_: mood, feeling, affect.

**Tick**:
One unit of simulated time; the being advances one tick at a time, tick 0 being
its birth state.
_Avoid_: frame, step, turn, cycle.

**Perception**:
The being's sensed view of what is near it, carrying a confidence per object.
The being acts on its perception, never on the true world directly.
_Avoid_: sensing, sight.

**Perceived object**:
An object as the being currently senses it — id, confidence, properties,
affordances — never the human-only label.
_Avoid_: seen object, visible object.

**Object**:
A targetable thing in the room, known to the being by its properties and
affordances rather than a human name. Its developer label is a human-only
convenience the being never knows.
_Avoid_: item, entity, thing.

**Room**:
The local place the being occupies and perceives; holds objects and its
environmental conditions.
_Avoid_: level, scene, map, area.

**Environment**:
The room's ambient conditions the being is situated in — its light, sound, and
temperature — distinct from the objects the room contains. The environment has
no drive of its own; it pushes the being's contextual needs (safety, warmth).
_Avoid_: surroundings, ambience, atmosphere, weather.

**Environmental condition**:
One category the environment currently holds along a single dimension — e.g.
light is `dark`, sound is `loud`, temperature is `cool`. Each condition carries
a per-tick push on a contextual need, and a dark or loud room can push safety
low enough that the being reads as scared.
_Avoid_: setting, status, modifier, effect.

**Light**:
The environment's illumination dimension, a category from `dark` to
`too_bright`; darkness lowers the being's safety.
_Avoid_: brightness, lighting, lux.

**Sound**:
The environment's auditory dimension, a category from `silent` through `normal`
to `loud`/`unknown_sound`; loud or unknown sound lowers safety.
_Avoid_: noise, audio, volume.

**Temperature**:
The environment's thermal dimension, a category (`cool`/`comfortable`/`warm`);
it shifts the being's warmth need. Temperature is the condition; warmth is the
need it moves — they are not the same term.
_Avoid_: heat, climate, warmth (that is the need, not the condition).

**Simulation**:
The being-in-its-world advanced through ticks — the single public surface over
the whole model.
_Avoid_: engine, game. (`World`, meaning global laws, is a future concept, not
this term.)

**Interaction event**:
A meaningful thing that happened — the being took an action on an object, with an
expected outcome, an observed outcome, and the emotion before and after. The
lasting record everything learned is derived from.
_Avoid_: log entry, action record, transaction.

**Training example**:
A model-ready row derived from interaction events: input features in, outcome
labels out. What the predictor learns from, not raw history.
_Avoid_: sample, datapoint, dataset row.

**Prediction record**:
A prediction the model made, kept so it can later be compared against the actual
observed outcome (shadow mode) and marked right or wrong.
_Avoid_: guess, inference log, prediction log.

**Model run**:
The metadata of one training run — when it ran, how it scored, and where its
weights artifact lives; the learned weights themselves live in a `.pt` file, not
here.
_Avoid_: training job, experiment, checkpoint.

## Not in the language

- **Caregiver** — there is no caregiver; the being acts on its own state and the
  world. No action summons or depends on an external actor.
- **Hygiene** — not a need here; the being's needs are the six listed above.

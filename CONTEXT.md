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
The local place the being occupies and perceives; holds objects and (later)
environmental conditions.
_Avoid_: level, scene, map, area.

**Simulation**:
The being-in-its-world advanced through ticks — the single public surface over
the whole model.
_Avoid_: engine, game. (`World`, meaning global laws, is a future concept, not
this term.)

**Outcome**:
What happens when the being acts on an object — e.g. it rolls, bounces, falls,
causes pain, makes noise, is pleasant, or is scary. Several outcomes can occur
from one action at once (multi-label); an outcome is a fact about the world, not
the being's feeling about it.
_Avoid_: result, effect, consequence, reaction.

**Outcome predictor**:
The being's first learned model: given an object's properties, the action taken,
and the situational context, it anticipates the likely outcomes. It only
predicts — it never chooses the action.
_Avoid_: the model, the AI, the brain, classifier.

**Training example**:
One learnable row pairing an encoded interaction (properties + action + context)
with its observed outcomes; what the outcome predictor learns from. Real ones are
derived from the being's interactions; until those are recorded, a synthetic seed
set is derived from the config vocabulary.
_Avoid_: sample, data point, record, row.

**Shadow mode**:
Running the outcome predictor alongside the being's rule layer so its predictions
are recorded and compared, but do **not** control what the being does. The model
observes; it never drives.
_Avoid_: dry run, test mode, passive mode.

## Not in the language

- **Caregiver** — there is no caregiver; the being acts on its own state and the
  world. No action summons or depends on an external actor.
- **Hygiene** — not a need here; the being's needs are the six listed above.

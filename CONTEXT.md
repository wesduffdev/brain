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
A drive or felt level the being has, held as 0–100 that changes over time —
hunger, sleep, comfort, warmth, curiosity, safety, and pain (felt harm).
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

**Affordance**:
What an object offers to be done to it — `look`, `touch`, `push`, `grab`,
`drop`. An action that manipulates an object is valid only if the object offers
its affordance; self-directed actions need none.
_Avoid_: capability, verb, interaction type.

**Action**:
One thing the being does toward an object in a tick — observe, approach,
withdraw, touch, grab, push. Always the being's own doing, self- and
world-directed only; there is no caregiver-directed action. Distinct from a
player command, which is the world's doing.
_Avoid_: move, behaviour, command, activity.

**Decision**:
The being's choice of a single action toward a single object this tick, made by
utility scoring over its needs, emotion, and what it perceives — carrying the
action, its target, the felt emotion, and a stated reason. A safety rule can
forbid a candidate, and no score ever overrides it.
_Avoid_: plan, policy, choice engine, AI move.

**Invariant floor**:
The minimal, absolute set of safety rules the being can never cross — it blocks
only actions that would break the *simulation itself*, not merely harmful ones. A
high utility, or a confident learned prediction, can never buy an action past it.
In v0 it is empty. Narrowed from the earlier "safety guardrails hard-block
harmful actions" stance.
_Avoid_: safety guardrail (now names the floor), hard block, safety net, sandbox.

**Safety rule**:
One rule of the invariant floor: it forbids an `action` on an object with a given
property, with an abstract reason. Absolute — no score bypasses it — but it
covers only simulation-breaking actions; recoverable harm is not blocked.
_Avoid_: constraint, penalty, filter, validation.

**Recoverable harm**:
A harmful-but-not-simulation-breaking action the being is allowed to take and
suffer — such as touching something hot. Its cost lands as an outcome effect (a
pain/fear spike), and being allowed to happen is how cause and effect is learned,
rather than being hard-blocked.
_Avoid_: safe harm, minor harm, permitted risk, sanctioned damage.

**Pain**:
The being's felt-harm need — 0–100, born at 0, spiking when a harmful outcome
lands and decaying back toward 0 on its own (acute pain fades; the plausible
recovery). Distinct from fear, which is the `scared` emotion derived from low
safety.
_Avoid_: damage, hurt, injury, health, hit points.

**Outcome effect**:
The abstract internal cost an action's outcome imposes on the being — the need
deltas (pain up, felt safety and comfort down) and the emotion and behavior that
follow. This is how harm is represented and *suffered*: felt state only, never a
depiction of harm. Distinct from the outcome, which is a fact about the world;
the effect is what the being feels from it.
_Avoid_: damage, penalty, result, reaction, consequence.

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

**Prediction record**:
A prediction the model made, kept so it can later be compared against the actual
observed outcome (shadow mode) and marked right or wrong. Holds the model's
predicted outcome beside the rule layer's expected outcome and the actual
observed outcome for one interaction.
_Avoid_: guess, inference log, prediction log.

**Prediction error**:
How wrong a prediction was — the gap between what the model predicted and what
actually happened, measured continuously (not just right/wrong). It is recorded
in shadow mode and, in later versions, is the signal that feeds curiosity: a
surprising outcome is one the model predicted poorly.
_Avoid_: loss, inaccuracy, mistake, residual.

**Model run**:
The metadata of one training run — when it ran, how it scored, and where its
weights artifact lives; the learned weights themselves live in a `.pt` file, not
here.
_Avoid_: training job, experiment, checkpoint.

**Render frame**:
The engine's outbound picture of the being for a renderer (the
`being_state_update` message, ADR 0004): the domain state mapped onto the shared
wire contract, carrying presentation-only additions (a visual hint block, an
emotion intensity) but no new psychology. One frame per emitted state.
_Avoid_: state update, packet, message.

**Visual hint**:
A presentation-only cue for how an emotion looks — mouth, eyes, effects, a
thought glyph — looked up from the being's already-derived emotion. It encodes
no decision; retuning it never changes what the being feels.
_Avoid_: sprite, animation, expression state.

**Renderer**:
The client that draws the being from the engine's render frames and forwards
player commands back. It owns no psychology and makes no decision — it presents
what the engine already decided and sends raw intent. In v0 it is a browser
PixiJS app; the term names the role, not the technology.
_Avoid_: frontend, UI, client, view, PixiJS app.

**Player command**:
A raw player intent aimed at the world — e.g. presenting an object into the room
— sent by a renderer and validated by the engine before it can matter. It never
decides what the being does; the being's own psychology responds to it, exactly
as if the object had appeared any other way.
_Avoid_: action (that is the being's own doing), input event, control.

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

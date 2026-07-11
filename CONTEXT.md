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

**Need band**:
The [floor, ceiling] range a need may sit within (its min/max, from
tick_rates.yaml). Every force that moves a need — drift, environmental push,
felt-consequence effect — is clamped to the need's band, so a need's limits have
one home.
_Avoid_: clamp, min/max, cap, bounds.

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
action, its target, the felt emotion, and a stated reason. When active prediction is on, the score also reflects the
anticipated cost of the action's predicted outcomes. A safety rule can forbid a
candidate, and no score — utility or predicted — ever overrides it.
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

**Unit of work**:
One logical operation whose repository writes commit atomically together, or roll
back together, inside a single caller-owned transaction.
_Avoid_: transaction (too low-level), batch.

**Stage (a write)**:
A repository records a write on the session without committing; the enclosing
unit of work commits it.
_Avoid_: save, persist (those imply an immediate commit).

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

**Memory**:
What the being keeps from one interaction — a durable, self-contained trace (the
object as perceived, the action, expected vs. observed outcome, emotion
before/after, prediction error, and a priority) that later learning attends to.
_Avoid_: log entry, cache, history.

**Priority (salience)**:
How strongly later learning should attend to a memory — a config-driven score
raised by surprise (prediction error) and emotional intensity.
_Avoid_: weight, importance, rank, score.

**Memory retrieval**:
Recalling the memories relevant to what the being now perceives — by same
object, similar perceived properties, same action, and salience — before it
decides.
_Avoid_: search, lookup, recall query.

**Preference**:
A learned like/dislike the being forms from its recalled memories — a signed
bias on an action toward an object; a remembered burn reads negative, a fond
memory positive.
_Avoid_: reward, valence (that is the raw outcome sign), affinity.

**Trait (Caution tendency / Curiosity tendency)**:
A slow personality level in [0,1] that drifts a little from every outcome —
caution rising from harm, curiosity from safe exploration — settling into an
individual temperament. Distinct from the `curious` emotion (momentary) and the
v4 curiosity drive (per-object).
_Avoid_: personality stat, mood, disposition score.

**Retrieved memory**:
A remembered interaction paired with how relevant it is to the present choice.
_Avoid_: match, hit, candidate.

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

**Language command**:
A person's natural-language request, interpreted onto a single allowed action
the being may take and validated before it becomes a player command; a request,
never an application.
_Avoid_: chat, prompt, instruction, order.

**Narration**:
Readable, non-authoritative text describing the being's current state, derived
from a state snapshot and never fed back into the sim.
_Avoid_: description, log, caption, commentary.

**Memory summary**:
Readable text summarising the being's memory log; read-only, non-authoritative.
_Avoid_: recap, digest, report.

**Language model**:
The LLM behind the language-model port that completes a prompt with text (Claude
by default); never the being's brain.
_Avoid_: LLM, AI, GPT, oracle.

**Non-authoritative**:
A description or request that sits on top of the sim and can never mutate state
or reach the being's decision.
_Avoid_: read-only (too narrow), advisory.

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

**Concept schema**:
A learned generalization keyed on one perceived property + an action + an
observed outcome ("round things roll when pushed"), carrying a confidence that
rises as interactions confirm it.
_Avoid_: rule, category, class, prototype.

**Belief**:
A concept applied to one perceived object — an expected outcome of an action on
it, at the supporting concept's confidence; lets a never-seen object be
anticipated. A belief now also *feeds the decision*: it raises an action's
anticipated-discomfort cost (never bypassing the safety floor), not only sitting
stored.
_Avoid_: prediction, guess, opinion.

**Concept confidence**:
How strongly the being holds a concept schema, 0..1, rising with confirming
repetition (diminishing returns).
_Avoid_: weight, probability, score, certainty.

**Object similarity**:
How alike two objects are by the overlap of their perceived properties (0 =
nothing shared, 1 = perceived identically).
_Avoid_: distance, closeness, match.

**Concept graph**:
The being's learned knowledge as a walkable network — object/property/outcome
nodes joined by typed, confidence-bearing edges — projected from its concepts,
beliefs, and similarities.
_Avoid_: knowledge base, ontology, semantic net, database.

**Graph node**:
One object, perceived property, or observed outcome in the concept graph, keyed
on a perceived token (never a developer label).
_Avoid_: vertex, entity, record.

**Graph edge**:
A typed, directed link between two nodes (HAS_PROPERTY, PREDICTS, PRODUCED,
SIMILAR_TO) carrying an edge confidence, an evidence count, and the memories
behind it.
_Avoid_: relation, link, connection, arc.

**Explanation path**:
The object → property → outcome walk through the graph that justifies a
prediction — the reason the being expects an outcome.
_Avoid_: trace, proof, chain, reasoning.

**Edge confidence**:
How strongly the being holds a graph edge, 0..1, rising with confirming evidence
on the same saturating curve as concept confidence but tuned independently.
_Avoid_: weight, probability, similarity, score.

**Shadow mode**:
Running the outcome predictor alongside the being's rule layer so its predictions
are recorded and compared, but do **not** control what the being does. The model
observes; it never drives.
_Avoid_: dry run, test mode, passive mode.

**Active prediction**:
Running the outcome predictor so its blended prediction *shapes* the being's
decision — penalizing actions it predicts will erode the being's needs — the
opposite of shadow mode. Off by default; a config flip turns it on, and the
safety floor still gates every choice.
_Avoid_: live mode, prediction-driven, model control.

**Blended prediction**:
One outcome probability per label formed by weighting the neural predictor and
the rule-based predictor together (an ensemble); the weights, and whether the
neural arm is enabled, are config.
_Avoid_: combined model, average, hybrid score.

**Rule-based predictor**:
The being's own action rules exposed as a predictor — the always-available
baseline the neural model blends with, and the safe fallback used when the
neural arm is disabled or errors.
_Avoid_: heuristic, fallback model, dummy predictor.

**Anticipated cost**:
How much a predicted set of outcomes is expected to erode the being's needs,
subtracted from an action's utility when active prediction is on, so the being
avoids harm it foresees rather than only harm it has already suffered.
_Avoid_: risk score, penalty, expected loss.

**One-shot aversion**:
A single high-salience aversive interaction lifting a concept's confidence toward
certainty in one evidence (trauma-like), versus the slow curve of low-salience
repetition.
_Avoid_: instant learning, trauma flag.

**Anticipated discomfort**:
The being's expected aversive cost of an action, derived from a belief (or the
predictor), that lowers the action's decision score without a hard block.
_Avoid_: fear penalty, predicted pain.

**Curiosity**:
The being's config-weighted drive to explore an object it cannot yet predict —
rises with novelty, uncertainty, and recent surprise; falls with familiarity.
_Avoid_: interest, drive, exploration bonus.

**Surprise**:
How far an action's observed outcome diverged from the expected outcome (Jaccard
distance of the two outcome sets); decays over ticks.
_Avoid_: error, shock, mismatch, prediction error (that is the model's).

**Novelty / Familiarity**:
Novelty = the share of an object's perceived properties never encountered;
familiarity = how mastered its properties are (rises as the being acts on them,
pulling curiosity down).
_Avoid_: newness, recognition.

**Exploration policy**:
How curiosity (and anticipated discomfort) adjust an action's decision score,
within the safety floor.
_Avoid_: exploration strategy, curiosity engine.

**Scenario**:
An authored experiment file that seeds the room with objects, runs the being N
ticks, and defines a learning target + success condition — a repeatable "watch
it learn".
_Avoid_: test fixture, level, episode.

**Learning target**:
The concept (perceived feature + action + observed outcome) whose confidence a
scenario tracks.
_Avoid_: goal, objective.

**Learning metric (regression metric)**:
The single measured quantity a scenario reports before vs after a run — here, a
concept's confidence.
_Avoid_: score, KPI.

**Success condition**:
The config-driven floor the metric's rise (delta) must meet for a run to pass.
_Avoid_: threshold (generic), assertion.

**Scenario result**:
The verdict of one run — before/after/delta/threshold and whether it passed.
_Avoid_: report, outcome.

**Milestone**:
A named developmental capability the being grows into, read via one learning
metric and defined as an ordered ladder of stages.
_Avoid_: level, achievement, badge.

**Milestone stage**:
One rung of a milestone, gated by a metric floor; the being sits on the highest
stage its metric has reached.
_Avoid_: tier, rank.

**Developmental progression**:
A run moving the being up at least one milestone stage — the observable "it grew
up a little".
_Avoid_: level-up, XP.

**Regression scenario**:
A scenario run judged pass/fail against its metric floor + expected milestone
stages; passes on learning, FAILS when it is absent.
_Avoid_: unit test, assertion.

**Domain event**:
A versioned fact something in the being's world produced, published on a named
topic for other services to react to — carrying its identity, type, version,
timestamps, the being it concerns, a correlation/causation trace, and a payload.
Distinct from an interaction event (the persisted learning record) and from a
tick (a unit of simulated time, not a message).
_Avoid_: message, signal, tick, notification, interaction event (that is the learning record).

**Event bus**:
The seam domain events travel through — a publisher puts an event on a topic and
every consumer subscribed to that topic receives it — behind a port so the
being's code never binds to the broker. Broker-free in-memory by default; Kafka
at runtime.
_Avoid_: broker, queue, Kafka (that is one runtime impl), message bus, pub/sub system.

**Topic**:
The named channel a domain event is published on and consumers subscribe to
(`being.perception.events`, `being.instinct.predictions`), always under the
`being.*` namespace. Groups related event types; it is the routing key, not the
event's type.
_Avoid_: channel, queue, stream, subject, event type (that is the specific fact).

**Correlation id / Causation id**:
The two ids that trace an event chain. The correlation id is shared by every
event in one causal chain (a root event correlates to itself); the causation id
names the single event that directly caused this one (a root event has none).
Together they reconstruct `A -> B -> C`.
_Avoid_: trace id (only correlation), parent id, request id, chain id.

**Scheduled event**:
A change caused only by time passing, emitted on a fixed cadence (e.g. a
need-drift tick) rather than by every service polling the clock. Distinct from a
tick (time itself) and from a domain event triggered by something happening.
_Avoid_: timer, cron, tick (that is time passing, not the emitted event).

**Keep-loop (real-time work)**:
Tick-driven work whose correctness *is* the clock (time advance, action
cooldown/timing) — it stays a local loop rather than becoming an event, emitting
only summarized events downstream.
_Avoid_: game loop, polling, busy-wait.

**Instinct**:
The being's fast, pre-conceptual protective layer between perception and
decision — a learned reaction predicted from short-window sensory/kinematic
features, before any deliberation. It biases emotion and proposes interruption
but never selects an action and never bypasses the safety floor.
_Avoid_: reflex-as-emotion, mood, feeling, gut, decision (that is the chosen action).

**Reaction**:
The discrete instinctive response the instinct model outputs — one of `flinch`,
`freeze`, `orient`, `withdraw`, `ignore`, carried with a `reaction_intensity` in
[0,1]. A proposed fast response to a stimulus, distinct from an action (a
deliberated behavior the decision layer chooses).
_Avoid_: action, behavior, move, response-as-action, animation (the render hint is downstream).

**Object motion**:
An object's position and velocity relative to the being's body over ticks —
world-truth the being never reads directly; perception derives an approach
stimulus from it.
_Avoid_: animation, movement hint (renderer), drift (a need's autonomous change).

**Velocity**:
An object's rate and direction of positional change per tick (2-D, relative to
the body at the origin). Its magnitude alone is speed.
_Avoid_: speed (magnitude only), drift rate.

**Approach**:
An object closing on the being's body faster than a configured threshold — the
condition under which an approach stimulus is raised.
_Avoid_: proximity (static nearness), collision.

**Stimulus (approach stimulus)**:
The being's perceived fast-sensory reading of an approaching object — the frozen
ordered 14-scalar kinematic feature vector (ADR 0026), published as an
`ObjectApproached` domain event. Pre-cognitive input, not a reaction or a
decision.
_Avoid_: percept / perceived object (the static properties view), event (the
transport envelope), reaction (what a later layer does with it).

**Instinct model**:
The being's second neural network — a tiny feed-forward net mapping an approach
stimulus's 14 features to the five reaction probabilities plus a reaction
intensity. Separate model/port/artifact from the outcome predictor (ADR 0026).
_Avoid_: reflex net, reaction classifier, the outcome predictor.

**Instinct encoder**:
The pure, torch-free, config-vocab-driven contract turning a stimulus into the
frozen ordered 14-scalar feature vector (the instinct analogue of the outcome
FeatureEncoder); config order is the contract.
_Avoid_: feature builder.

**Reaction intensity**:
A scalar in [0,1] for how strongly a stimulus provokes a protective reaction — a
separate regression head of the instinct model, distinct from a label
probability.
_Avoid_: confidence, salience, priority.

**Transactional outbox**:
Staging a domain event as a database row inside the SAME unit of work as the data
it accompanies, so event and data commit atomically; a separate relay later
publishes it and projects it into the event log. Solves the Postgres↔broker
dual-write problem without a cross-system transaction.
_Avoid_: dual-write, direct publish (publishing inside the DB transaction — the
thing the outbox prevents).

**Outbox**:
The append-only queue of domain events staged for publication (one entry = topic
+ envelope); a producer adds to it inside its unit of work, the relay drains it.
Distinct from the event log (the durable projection of what was published).
_Avoid_: message queue, broker (the outbox is a DB table, not the transport).

**Event log**:
The durable, queryable projection of every published domain event, keyed on
event_id so projection is idempotent (a replayed event stays one row) — audit
trail and replay source for training.
_Avoid_: outbox (the pre-publish queue), event bus / topic (the transport),
interaction event (the outcome-model learning record).

**Reaction threshold**:
The per-label probability at or above which a predicted reaction may fire; below
it the candidate is suppressed. Distinct from the outcome predictor's prediction
threshold.
_Avoid_: prediction threshold, confidence cutoff.

**Reaction cooldown**:
The ticks that must elapse after a reaction of a given label fires before that
same label may fire again — damping instinct spam.
_Avoid_: duration, refractory period, action cooldown (that gates deliberated actions).

**Suppressed reaction**:
The dominant candidate reaction that did not fire — below threshold, still
cooling down, or (at the interrupt step) unsafe to act on — recorded with
`triggered=False`.
_Avoid_: ignore (the model's no-reaction label), blocked (a safety-floor term).

**Emotion bias**:
A transient affect signal a triggered reaction feeds into the being's
needs→emotion derivation for one tick, nudging the displayed emotion (a flinch
reads as `scared`) without mutating stored needs or setting emotion directly.
_Avoid_: setting the emotion, emotion override, mood (emotion is always derived).

**Action interruption**:
Cancelling the being's current action mid-tick because a high-intensity reaction
fired — permitted only when the action is interruptible and the safety floor
allows the protective response; its outcomes never land and an `ActionInterrupted`
event is emitted.
_Avoid_: abort, block (the floor blocks; instinct interrupts an already-safe action).

**Visual-only mode**:
The first instinct-activation step (`visual_only`): a reaction is surfaced in
state and biases the displayed emotion, but actions stay byte-identical — show
it, don't let it drive. Distinct from shadow (record-only) and controlled
interruption.
_Avoid_: preview, dry run, shadow.

**Reaction visual**:
The presentation of an active reaction on the render frame — the config draw
hints for the reaction's label stamped with the engine-decided type and
intensity, carried under `visual.reaction`; present only while a reaction is
active and carrying no psychology.
_Avoid_: reaction animation (static hints only), reaction emotion.

**Model telemetry**:
A read-only observability record pairing an instinct prediction with its observed
outcome (accepted/suppressed) on the `being.model.telemetry` stream; never feeds
back into decision or reaction selection.
_Avoid_: metric, log, feedback signal.

**Consumer lag**:
How many predictions are still awaiting their reaction on the telemetry observer;
settles to zero as the chain drains.
_Avoid_: backlog, queue depth.

**Correlation trace**:
The structured per-hop log line carrying `correlation_id`/`causation_id` that
lets one stimulus→prediction→reaction chain be followed end to end.
_Avoid_: audit log, request log.

**Sound spike**:
A sudden transition into a loud/unknown sound category the being hears but
cannot see — raises a `being.perception.sound_spike` stimulus with high
`sound_spike_intensity`/`unexpectedness` and low visibility_confidence, which the
instinct model reads as **freeze**.
_Avoid_: loud room (that is the slow contextual-need push on safety), noise.

**Contact (touch stimulus)**:
An approaching object crossing into the being's body (distance ≤ the configured
contact distance) — raises a `being.perception.object_contacted` stimulus with a
real `touch_intensity`, which the instinct model reads as **withdraw**.
_Avoid_: collision, approach (approach is closing on the body; contact is touching it).

**Reaction sensitivity**:
The being's current, per-being reaction thresholds — the config baseline
reshaped by experience — that gate which instinct reaction fires. Held by the
TemperamentService and consulted instead of the static threshold. Distinct from
reaction intensity (how strong a fired reaction is).
_Avoid_: sensitivity-as-intensity, threshold override, gain.

**Habituation**:
The slow rise of a reaction's effective threshold when a startle fires and proves
harmless (the being's pain did not rise), so a repeated harmless stimulus
gradually stops triggering.
_Avoid_: fatigue, forgetting, cooldown (the per-firing timing gate).

**Sensitization**:
The slow fall of every reaction threshold after a harmful outcome (pain spiked),
so the being is jumpier — a previously sub-threshold stimulus may now fire.
Distinct from the caution trait (which reshapes the deliberate decision, not the
reaction threshold).
_Avoid_: panic, trauma-as-state, sensitivity.

**Instinct temperament**:
The being's adaptive instinct disposition — the drifting set of effective
reaction thresholds grown from a life of startles (habituation) and harms
(sensitization); the fast-layer sibling of the slow personality Trait, transient
in-process.
_Avoid_: mood, personality stat, the caution trait.

## Not in the language

- **Caregiver** — there is no caregiver; the being acts on its own state and the
  world. No action summons or depends on an external actor.
- **Hygiene** — not a need here; the being's needs are the six listed above.

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

**Prediction client**:
WHERE a learned model's inference runs, chosen behind the model ports without
touching any caller: in-process (torch or rules inside the engine), over HTTP to
the model service, or a fallback-safe wrapper that degrades to the rule/safe
baseline when the service is unavailable. One object covers both model ports
(outcome and instinct). It only decides where prediction happens — it never
predicts differently, and never chooses an action.
_Avoid_: the model, the predictor (what predicts, not where it runs), inference
engine, model client (the Ollama language adapter).

**Model service**:
The out-of-process sidecar that serves the being's two learned models (outcome +
instinct) over HTTP — an availability boundary, not a new brain. The engine
reaches it through the prediction client and degrades to the rule/safe baseline
when it is unavailable, so a model outage never stalls the sim; a local container
and a prod GPU host are the SAME service behind an endpoint swap. It serves
scores; it never decides anything.
_Avoid_: model server (the Ollama LLM host — a different thing), the model,
backend, inference API, sidecar (the deployment shape, not the thing).

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

**Instinct training example**:
One learnable row pairing the fast-sensory stimulus features the instinct model
saw with the reaction labels the being actually reacted with; what the instinct
model learns from (the instinct analogue of a training example). Real ones are
derived from lived perception events; until those are recorded, the synthetic
seed set stands in.
_Avoid_: instinct sample, reaction record, stimulus row.

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

**Self-report**:
The being's first-person account of its own experience, produced on request
(`/ask`) and grounded ONLY in its logged memories — it can say what it has lived,
never what it has not. It names objects by their perceived properties ("the round
red thing"), never a developer label, and it describes; it never acts.
_Avoid_: introspection, confession, status, log dump, self-awareness.

**Narration**:
Readable, non-authoritative text laid ON TOP of the being's state and memories,
derived from a state snapshot. Narration reflects the being; it is read-only — it
never controls the sim, feeds back into a decision, or mutates state.
_Avoid_: description, log, caption, commentary, narrative, story, voice-over,
dialogue; self-report (that names the narration OF the being's own first-person
experience — a distinct term); and any implication that narration writes state.

**Narrator provider**:
Which voice phrases the being's self-report behind the one language-model seam,
chosen by config: the offline deterministic template (default), the in-memory
fake (tests), Claude (env-gated), or a locally-served model. A provider only
changes where the words come from — it is always handed the same structured
experience, so it can never change what the being is allowed to say.
_Avoid_: LLM-as-brain, backend, engine, model (bare).

**Narrator fallback**:
The fallback-safe rule that a self-report always lands, grounded: when the
selected narrator provider errors or is unavailable, the being degrades to the
deterministic template over the same experience — fluency lost, grounding kept.
The fluent voice is an upgrade, never a dependency (the sibling of the predictor
ensemble's rule fallback).
_Avoid_: retry, failover (as infra), silent error, default model.

**Subject query**:
A question that asks the being what it KNOWS or how it FEELS *about* something —
"what do you know about hot things?", "how do you feel about round things?" —
answered from what it has LEARNED (its concepts, beliefs, graph explanations, and
the emotions its memories recorded), keyed on the PERCEIVED property the subject
resolves to. A subject it has never encountered is declined honestly, never
invented. Distinct from a self-report of what it has DONE (the recent-experience
question).
_Avoid_: topic, search query, question intent, knowledge lookup, FAQ.

**Subject resolver**:
The step that turns a subject term into the being's PERCEIVED-property tokens
("hot things" -> `hot`; "the round red thing" -> `round`, `red`), drawn from the
perceived-property vocabulary — never a developer label or object id (the being
has no name for a thing, only how it perceives it). A term with no perceptual
handle ("dragons") resolves to nothing and is answered as unknown; resolving to a
real property is not the same as having learned about it.
_Avoid_: parser, intent classifier, entity linker, name lookup, keyword match.

**Salience**:
How strongly a memory stands out — its priority, raised by surprise (prediction
error) and emotional intensity, so the moments the being was most wrong or most
affected are held hardest. In a self-report, higher salience emphasizes the felt
affect ("afterwards I felt VERY scared").
_Avoid_: priority-as-queue-order, importance, weight, relevance (the recall
signal).

**Voicebox**:
The faculty that turns the being's words into audible SPEECH — a voice port behind
which an open-source TTS engine (espeak-ng) renders text to audio. It voices the
being's self-report (`/speak`), reads a document you hand it aloud (`/read`), and
speaks a grounded reading answer on request (an opt-in `speak` on `/ask/reading`
and `/chat`) — one voicebox, one port, reused across all three (reading R8). Like
narration it sits ON TOP of the simulation: it gives words sound, never new words,
and controls nothing. Voice is an upgrade, not a dependency — a host with no engine
degrades to a clear no-op and the being still answers in text.
_Avoid_: voice assistant, speech agent, TTS-as-feature, speaker, mouth.

**Utterance**:
One thing the being is asked to speak — the text handed to the voicebox (its
self-report, a grounded reading answer, or one chunk of a document being read
aloud), together with the voice parameters (rate, pitch, voice) it is spoken with.
The being can only utter what it can report, read, or answer, so an utterance is as
grounded as the text behind it.
_Avoid_: message, phrase, line, dialogue, sound clip.

**Synthesize**:
To render an utterance into audio through the voice port — deterministic given the
text and parameters, producing WAV bytes, or nothing when no engine is available on
the host. Synthesis adds sound to words the being already produced; it never
produces the words.
_Avoid_: speak (the act itself), generate, narrate/render (the narrator's words),
TTS (as a verb).

**Read aloud**:
To voice a whole DOCUMENT through the voicebox — the document is cleaned and chunked
into utterances (reusing ingest, at a config-driven read-aloud size) and each is
synthesized in turn, so a long file is spoken in sensible pieces rather than one
enormous synthesis call (`/read`, reading R8). Distinct from reading-as-perception
(which CHANGES the being) and Reading QA (which ANSWERS a question): reading aloud
only speaks the document's own words and mutates nothing.
_Avoid_: narrate, recite, playback, dictate, text-to-speech (the mechanism).

**Reading**:
The faculty by which the being takes in a document you hand it and LEARNS from
it — growing its knowledge from what you give it. Reading sits ON TOP of the
simulation like narration and voice: it adds to what the being knows, it does not
drive its needs, emotion, or decisions.
_Avoid_: parsing, loading, importing, scanning.

**Reading-as-perception**:
How reading CHANGES the being's cognition — the doctrine that a read document
forms memories and concepts (and moves curiosity) ONLY through the same validated
perception/cognition door a lived interaction uses, never by letting the language
model write state. Each section of a document is perceived as its salient content
tokens (deterministic, model-free), validated as a reading action on a perceived
thing, and handed to the SAME memory/concept/curiosity machinery an interaction
feeds. The tokens are what the being perceives — never the document's title or
file name (a developer label). Distinct from Reading QA and Conversation, which
read the knowledge store and only speak; reading-as-perception is the write path,
and the language model is absent from it.
_Avoid_: learning from text, the model remembering, importing knowledge, indexing
(the knowledge store), text-to-memory.

**Ingest**:
To turn a document the being reads into cleaned, chunked, training-ready text —
reading it, normalising it (uniform whitespace and line endings), and chunking it
into ordered passages. Ingest is pure and deterministic (no model, no GPU); the
same document always ingests the same way. It is the shared FRONT of reading: the
same ingested text feeds the fine-tune corpus, the growing knowledge store, and
reading-as-perception. Handing the being a document to READ at runtime ingests it
live, so it becomes answerable+cited and remembered at once.
_Avoid_: parse, tokenize, preprocess, load, index (the retrieval store).

**Chunk**:
An ordered slice of a document's cleaned text — the unit reading works in. Ingest
splits a document into chunks; each chunk is embedded and folded into the
knowledge store as one retrievable passage, tagged with its source document.
_Avoid_: token, segment, fragment, shard, paragraph.

**Embedding**:
A fixed-dimension vector that stands for a chunk's (or a query's) meaning, so
similarity is a distance between vectors. The default embedder is deterministic
and offline (a bag-of-words hash); a real semantic embedder is an optional, gated
alternative. Distinct from the outcome/instinct models' feature vectors.
_Avoid_: encoding, feature vector, representation, token.

**Knowledge store**:
The being's persistent, CUMULATIVE store of embedded chunks, spanning every
document it has ever read. A newly read document ADDS to it and never replaces
what came before, so knowledge grows over time. It is retrieved from to ground
answers; it sits on top of the simulation and drives nothing. Distinct from the
being's memories (its lived interactions).
_Avoid_: memory, database, index, cache, vector DB, corpus.

**Retrieval**:
Finding the chunks in the knowledge store most relevant to a query — the top-k
passages by embedding similarity, each carrying its source document. It is how a
question reaches what the being has read (grounded, cited answering builds on it).
Distinct from memory retrieval (recalling a lived interaction).
_Avoid_: search, recall, lookup, query, ranking.

**Citation**:
The source document a retrieved passage came from, carried with it so an answer
can say WHERE a fact was read. Every retrieved passage is attributable to the
document that was ingested.
_Avoid_: reference, provenance, footnote, source (bare).

**Reading QA**:
The being answering a question about what it has READ — retrieving the relevant
passages, grounding its answer in them, and citing the source — and declining
honestly when it has read nothing relevant, optionally adding a clearly-labelled
base-knowledge answer. Distinct from a subject query (what it KNOWS/FEELS about a
perceived property, from learned concepts) and from self-report (what it has DONE).
_Avoid_: search, retrieval (the store step), Q&A bot; it is a SINGLE-turn reading answer — the multi-turn back-and-forth is a Conversation.

**Grounded answer**:
An answer built ONLY from the passages the being actually retrieved from what it
has read, plus the question — never the model's free invention — and carrying the
source document it drew on. When nothing read is relevant the being says so rather
than forcing one. Distinct from a self-report, which is grounded in the being's own
lived memories rather than read documents.
_Avoid_: response, generation, completion, RAG answer, hallucination.

**Base knowledge**:
What the being knows from its underlying language model itself, independent of any
document you have given it to read. A reading answer keeps base knowledge separate
from — and labelled distinctly from — what the being READ, so the two are never
conflated (the learn-and-grow stance: transparent, not blinded).
_Avoid_: general knowledge (bare), prior, training data, world knowledge, the base model (the artifact).

**Conversation**:
A multi-turn back-and-forth about what the being has READ. Each turn is answered by
reading QA — grounded in the retrieved passages, citing the source — and the turns
are KEPT so a later turn can resolve a reference to an earlier one ("tell me more
about that") and stay grounded. A follow-up that names no subject of its own leans
on the conversation's history to reach the earlier subject; a message that names a
NEW topic — even one the being has not read about — is judged on its own words and
declined honestly, never dragged onto the prior topic. Held per conversation id, it
sits on top of the simulation and drives nothing.
_Avoid_: chat session, thread, dialogue (bare), context window, memory (the being's lived interactions).

**Conversation turn**:
One exchange of a conversation — the user's message and the being's grounded answer —
kept, in order, so later turns can build on it. Turns accumulate per conversation and
are never edited; they are the durable record a follow-up resolves against. Distinct
from a being's memory (a lived interaction) and from a reading chunk (a passage of a
read document).
_Avoid_: message (bare), exchange, round, utterance, memory, chunk.

**Consolidation**:
The being's "learn it for good" step, run on its 'sleep' cycle: it fine-tunes its own
model over question/answer pairs synthesized FROM its accumulated knowledge store, so
recurring read facts are baked into the model's WEIGHTS and later recalled WITHOUT
retrieval — not held only in the retrieval store. Falling asleep (the sleep need
crossing a threshold) TRIGGERS it asynchronously and out-of-band; it never blocks the
tick and never drives the being — it writes a re-fine-tuned model, nothing more. The
training pairs are synthesized at build/host time (by Claude); the being's runtime
answers stay its own local model. Distinct from immediate learning through the growing
knowledge store (usable at once, no retrain) and from a lived interaction's memory.
_Avoid_: retrain, memory consolidation (the being's episodic memory), sleep (the need), reindex, cache warming, batch job.

**Fine-tune**:
To adapt the being's OWN open base model to what it has read by training a small
LoRA adapter on the ingested text — host-native on the Mac's GPU. The trained
adapter IS "our model": the being's learned voice, saved as an artifact and later
served behind the language-model port. Learning from a document means fine-tuning
on it (immediately, or later during consolidation).
_Avoid_: train-from-scratch, retrain, pretrain, tune (a config value), calibrate.

**Serve (a model)**:
To make the being's fine-tuned model answerable at runtime — fuse its LoRA adapter
into the base, export GGUF, and register it with a local model server (Ollama) that
answers prompts on an endpoint the language-model port reaches. Serving turns the
trained artifact into a running voice; it produces no new knowledge, only
availability, and drives nothing. One fuse-and-export step per fine-tune.
_Avoid_: deploy, host (the machine), run, expose, publish.

**GGUF**:
The single-file model format the fused model is exported to so a local model server
(Ollama) can load and run it. It is the being's fine-tuned weights packaged to
serve — the base with the LoRA adapter baked in — not a new model.
_Avoid_: checkpoint, safetensors, the adapter (what is fused in), quantization.

**Model server**:
The host-native process (Ollama, on :11434) that loads the GGUF model and answers
prompts over an HTTP endpoint, reached by the local language-model adapter. On the
Mac it runs host-native because the Metal GPU is not passed into the container; in
production it becomes a GPU container behind the SAME port — local→prod is an
endpoint swap. The server serves words; it never decides anything.
_Avoid_: sidecar (the deployment shape), backend, LLM, the adapter, endpoint (the URL).

## Not in the language

- **Caregiver** — there is no caregiver; the being acts on its own state and the
  world. No action summons or depends on an external actor.
- **Hygiene** — not a need here; the being's needs are the six listed above.

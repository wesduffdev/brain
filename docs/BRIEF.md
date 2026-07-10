# Agent Brief — Situated Being ML Simulation Architecture

Version: 0.2
Purpose: Feed this document to a Claude Code agent so it can break the
project into features, refactors, and implementation issues.

> **Direction (v0.2).** This supersedes an earlier baby-centric draft. The
> simulated being is **human-like in psychology** — it has needs, emotions,
> curiosity, memory, and learned expectations — but it is **not a baby, not
> tied to any age or life-stage, and not a literal person**. Throughout this
> document, "the being" means this generic situated agent. Its form and
> appearance are open; only its psychology is modeled here.

---

## 1. Project Intent

We are building a situated-being simulation to learn machine learning,
neural-network-backed prediction, agentic architecture, and simple 2D
rendering.

The being is a simplified, human-like agent. It is not intended to be a
realistic person, and it is not tied to an age, life-stage, or identity. It
inherits human-like qualities: needs, moods, attachment, sensory learning,
curiosity, and developing preferences.

The project should begin small and expand gradually.

The core goal is to create a being that can:

- Exist in a simulated world.
- Perceive objects and environmental conditions (light/dark, sound,
  temperature, and so on).
- Have needs such as hunger, sleep, comfort, safety, warmth, curiosity, and
  hygiene.
- React emotionally to internal and external state, including **fear**.
- Interact with objects.
- Store experiences.
- Learn simple object/outcome expectations.
- Use a neural network for narrow prediction tasks.
- Render simple 2D behavior using PixiJS.
- Run through Docker Compose with clear service boundaries.

---

## 2. Design Boundary (Adults-Only Simulation)

This simulation is intended for adults only.

This project is a psychology and learning simulation about a situated being.
The being is human-like in psychology — needs, moods, attachment, sensory
learning, curiosity, and a developing temperament — but it is not a literal
person and is not tied to an age or life-stage.

The simulation may model high-stress situations, attentive care, poor care,
neglect-like conditions, and consequences to trust, stress response, and
temperament. These are simulation outcomes, not endorsements.

Harm is abstract. Negative caregiver actions and hazards are represented as
state changes (trust / stress / comfort / pain / fear deltas), warnings,
recovery paths, and behavior consequences — never step-by-step depictions of
real-world harm. Every harmful path has a visible consequence and a recovery
path. The simulation must never become instructional content for harming a
real or vulnerable being.

---

## 3. Hard Requirements

The architecture must include:

1. **Neural networks**
   - Use PyTorch.
   - Start with a narrow prediction model, not a full neural brain.

2. **Docker containers and Docker Compose networking**
   - Services should run locally through Docker Compose.
   - Service boundaries should be explicit.

3. **Sidecars where useful**
   - Use a training sidecar/job for PyTorch model training.
   - Do not overuse sidecars too early.

4. **PostgreSQL**
   - Use Postgres for durable memory, event history, training examples, and
     prediction records.

5. **PixiJS renderer**
   - Use PixiJS for the 2D visual layer.
   - The renderer must not own the psychology or decision-making logic.

6. **Fine-tunable tick-based needs**
   - Need drift, action durations, cooldowns, and thresholds must be
     configurable without touching many source files.
   - Example: hunger may increase by 1 point every 30 ticks.
   - The architecture must provide interfaces and config-driven tuning.

---

## 4. Core Architecture Summary

This is a hybrid cognitive architecture.

```text
Markdown docs        = human-readable design knowledge
YAML/JSON config     = runtime-authored configuration
Python memory        = current working state / short-term brain state
PostgreSQL           = long-term memory, events, evidence, training data
PyTorch              = learned prediction / intuition module
Decision system      = executive control and action selection
PixiJS               = visual body / animation layer
Docker Compose       = local service networking and reproducibility
```

Recommended v0 service architecture:

```text
PixiJS Renderer
        ↑
        | WebSocket state updates / user commands
        ↓
Python Engine
        |
        ├── Runtime State / Working Memory
        ├── Config Loader
        ├── Tick Scheduler
        ├── Need System
        ├── Emotion System
        ├── Decision System
        ├── Prediction Service
        ├── Learning Service
        ├── Memory Service
        ├── PostgreSQL
        └── PyTorch Model Artifacts

PyTorch Trainer Sidecar / Job
        |
        ├── Reads training examples from Postgres
        ├── Trains outcome model
        └── Writes model artifact and metrics
```

---

## 5. v0 Recommendation

v0 should be intentionally small.

### v0 Goal

Create a minimal simulation where:

- A being exists in one room.
- The room contains a few objects.
- The being has a small set of needs.
- Needs drift over ticks using config-driven tick intervals.
- The being chooses simple actions using rules and utility scores.
- Interactions are stored in Postgres.
- Training examples are created from interaction events.
- A small PyTorch neural network predicts outcomes from object properties +
  actions + context.
- The neural network runs in shadow mode first.
- PixiJS renders the being's current emotion/action/pose.

### v0 Services

Start with these Docker Compose services:

```text
engine
postgres
renderer
ml-trainer
```

### v0 Services Explained

#### engine

Python FastAPI service.

Responsibilities:

- Owns the simulation tick loop.
- Owns current being state.
- Loads YAML/JSON config.
- Handles player commands.
- Runs the rule/utility decision system.
- Calls prediction service.
- Logs events to Postgres.
- Broadcasts render state to PixiJS over WebSocket.

#### postgres

Durable data store.

Responsibilities:

- Store objects.
- Store interaction events.
- Store memories.
- Store training examples.
- Store prediction records.
- Store model run metadata.

#### renderer

PixiJS frontend service.

Responsibilities:

- Render the being.
- Render simple states such as calm, curious, hungry, sleepy, scared,
  frustrated, excited, comforted.
- Send user commands to the engine.
- Receive render state updates over WebSocket.

The renderer must not decide mood, psychology, learning, or final behavior.

#### ml-trainer

PyTorch training sidecar/job.

Responsibilities:

- Read training examples from Postgres.
- Train a small outcome prediction model.
- Write model artifacts to `/models`.
- Write training metrics to Postgres or a metrics artifact.

This should be a sidecar/job because training can be slower, can fail
independently, may require different dependencies, and should not block the
runtime simulation.

---

## 6. Initial Docker Compose Sketch

```yaml
services:
  engine:
    build: ./engine
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    ports:
      - "8000:8000"
    volumes:
      - ./engine:/app
      - ./config:/config
      - ./models:/models
    environment:
      DATABASE_URL: postgresql+psycopg://sim:sim@postgres:5432/being_sim
      MODEL_PATH: /models/outcome_predictor.pt
      CONFIG_ROOT: /config
    depends_on:
      - postgres

  renderer:
    build: ./renderer
    command: npm run dev -- --host 0.0.0.0
    ports:
      - "5173:5173"
    volumes:
      - ./renderer:/app
      - /app/node_modules
    depends_on:
      - engine

  ml-trainer:
    build: ./engine
    command: python -m app.ml.train_outcome_model
    volumes:
      - ./engine:/app
      - ./models:/models
      - ./config:/config
    environment:
      DATABASE_URL: postgresql+psycopg://sim:sim@postgres:5432/being_sim
      MODEL_OUTPUT_PATH: /models/outcome_predictor.pt
      CONFIG_ROOT: /config
    depends_on:
      - postgres
    profiles:
      - training

  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: sim
      POSTGRES_PASSWORD: sim
      POSTGRES_DB: being_sim
    ports:
      - "5432:5432"
    volumes:
      - being_postgres_data:/var/lib/postgresql/data

volumes:
  being_postgres_data:
```

Run trainer only when needed:

```bash
docker compose --profile training run ml-trainer
```

---

## 7. Repository Structure Recommendation

```text
being-sim/
  docker-compose.yml

  docs/
    architecture.md
    ml_training_plan.md
    being_behavior_spec.md
    tick_tuning_model.md
    design_boundary.md

  config/
    world.yaml
    rooms.yaml
    needs.yaml
    emotions.yaml
    actions.yaml
    object_properties.yaml
    environment.yaml        # light/dark, sound, temperature, air
    outcome_labels.yaml
    safety_rules.yaml
    tick_rates.yaml
    animation_map.yaml

  models/
    outcome_predictor.pt

  engine/
    Dockerfile
    requirements.txt
    app/
      main.py

      domain/
        world.py
        room.py
        environment.py       # light/sound/temperature/air conditions
        object_entity.py
        being_state.py
        need_state.py
        emotion_state.py
        action.py
        interaction_event.py
        prediction.py
        memory.py

      ports/
        clock.py
        repositories.py
        predictor.py
        renderer_gateway.py
        config_provider.py

      services/
        tick_service.py
        need_service.py
        emotion_service.py
        perception_service.py
        decision_service.py
        prediction_service.py
        learning_service.py
        memory_service.py
        render_state_service.py
        command_service.py
        config_service.py

      db/
        models.py
        session.py
        migrations/

      ml/
        outcome_model.py
        train_outcome_model.py
        encode_features.py
        evaluate.py
        inference.py

      tests/
        test_tick_rates.py
        test_need_service.py
        test_outcome_encoding.py
        test_decision_service.py
        test_learning_service.py
        test_prediction_shadow_mode.py

  renderer/
    package.json
    src/
      main.ts
      BeingView.ts
      SocketClient.ts
      RenderState.ts
      CommandPanel.ts
```

---

## 8. Data Storage Guidance

Use Markdown, YAML/JSON, Postgres, and PyTorch model files for different
purposes.

### Markdown

Use Markdown for human-readable design docs: architecture proposals, PRDs,
domain explanations, behavior design, test plans, refactor plans. Markdown
should not be the runtime memory store.

### YAML/JSON Config

Use YAML/JSON for runtime-authored configuration: need rates, tick intervals,
action definitions, emotion thresholds, environmental categories, safety
rules, object property vocabulary, outcome labels, animation mapping. This
allows fine-tuning without changing code.

### PostgreSQL

Use Postgres for dynamic and learned data: interaction events, memories,
object observations, training examples, prediction records, beliefs, model
runs.

### PyTorch Model Artifacts

Use `.pt` files for trained neural-network weights. The database tracks model
metadata; the artifact can live on disk or in mounted storage.

The rule is:

```text
Markdown       = design docs
YAML/JSON      = startup / authored config
Postgres       = learned / dynamic data
PyTorch .pt    = learned model weights
```

---

## 9. Core Domain Models

Start small, but make room for future expansion.

### World

Defines global laws and environmental assumptions: gravity-like behavior, air
and breathability, light/dark, temperature assumptions, global physics rules.

v0 minimal fields:

```json
{
  "id": "world_001",
  "gravity": { "enabled": true, "direction": "down", "strength": 1.0 },
  "air": { "breathable": true, "quality": "normal" }
}
```

### Room

Defines the local place where the being exists.

```json
{
  "id": "room_001",
  "worldId": "world_001",
  "lightLevel": "comfortable",
  "temperature": "comfortable",
  "contains": ["being_001", "obj_red_ball", "obj_bottle"]
}
```

### Environmental Conditions

Model the environment as conditions/sources, not top-level objects. These feed
perception, safety, curiosity, and emotion.

**Light** — categories: `dark`, `too_low`, `dim`, `comfortable`, `bright`,
`too_bright`.

```json
{
  "lightLevel": {
    "lux": 20,
    "category": "too_low",
    "visibility": 0.25,
    "comfortImpact": -10,
    "safetyImpact": -20
  }
}
```

Light affects multiple systems, not just emotion:

```text
dark room
  → visibility drops
  → object-recognition confidence drops
  → uncertainty rises
  → safety need rises
  → scared emotion may become dominant
  → action bias shifts toward cry / seek caregiver / freeze
```

That is much better than `dark = scared`.

**Sound** — categories: `silent`, `quiet`, `normal`, `loud`, `sudden`,
`familiar_voice`, `unknown_sound`, `repetitive_noise`. A loud unknown sound
lowers the safety signal.

**Temperature** — ambient and per-object. Ambient `cool`/`comfortable`/`warm`
shifts the warmth need; an object marked `hot` can produce a pain/`unsafe`
touch outcome.

**Air** (later) — `fresh`, `stale`, `humid`, `dry`, `smoky`, and so on;
useful for comfort, smell, and weather.

### ObjectEntity

Defines targetable objects that can be perceived or interacted with. The being
learns from **properties and outcomes**, not from English names.

```json
{
  "id": "obj_red_ball",
  "developerLabel": "Red Ball",
  "properties": ["round", "rubbery", "smooth", "light", "red"],
  "affordances": ["look", "touch", "push", "grab", "drop"],
  "observableBehaviors": {
    "rollsWhenPushed": true,
    "bouncesWhenDropped": true
  }
}
```

`developerLabel` is for humans. The being may not know "ball" — it only knows
round, red, smooth, rolls-when-pushed, sometimes-bounces, fun.

### BeingState

Current state of the being. No age or life-stage.

```json
{
  "id": "being_001",
  "needs": {
    "hunger": 35,
    "sleep": 40,
    "comfort": 75,
    "warmth": 20,
    "curiosity": 82,
    "safety": 70,
    "hygiene": 90
  },
  "emotion": { "dominant": "curious", "intensity": 0.7 },
  "currentAction": { "type": "observe", "targetId": "obj_red_ball" }
}
```

### EmotionState

v0 emotional states:

- Happy
- Curious
- Hungry
- Sleepy
- **Scared** (fear)
- Frustrated
- Calm
- Excited
- Comforted

Only one emotion is dominant at a time in v0. Emotion is **derived** from
needs, events, predictions, and environment — never set manually.

```text
dark + low caregiver trust + unknown sound → scared
dark + caregiver present + soft blanket    → comforted / sleepy
bright + colorful moving object            → curious / excited
```

### InteractionEvent

Everything meaningful becomes an event.

```json
{
  "eventId": "evt_1001",
  "beingId": "being_001",
  "objectId": "obj_red_ball",
  "action": "push",
  "expectedOutcome": ["roll"],
  "observedOutcome": ["roll", "move_away"],
  "emotionBefore": "curious",
  "emotionAfter": "happy",
  "predictionError": 0.12
}
```

### TrainingExample

Derived from interaction events.

```json
{
  "inputFeatures": { "round": 1, "rubbery": 1, "light": 1, "action_push": 1, "surface_hard": 1 },
  "outputLabels": { "rolls": 1, "bounces": 0, "falls": 0, "causes_pain": 0, "makes_noise": 0, "pleasant": 1, "scary": 0 }
}
```

---

## 10. Tick-Based Architecture and Fine-Tuning

The tick system must be configurable and isolated. Do not hard-code need
drift, action duration, or cooldowns directly in services.

### Recommended Config File — `config/tick_rates.yaml`

```yaml
tick:
  duration_ms: 1000

needs:
  hunger:    { direction: increase,    amount: 1, every_ticks: 30, min: 0, max: 100 }
  sleep:     { direction: increase,    amount: 1, every_ticks: 45, min: 0, max: 100 }
  comfort:   { direction: decrease,    amount: 1, every_ticks: 20, min: 0, max: 100 }
  warmth:    { direction: contextual,  amount: 1, every_ticks: 30, min: 0, max: 100 }
  curiosity: { direction: increase,    amount: 1, every_ticks: 15, min: 0, max: 100 }
  safety:    { direction: contextual,  amount: 1, every_ticks: 10, min: 0, max: 100 }
  hygiene:   { direction: decrease,    amount: 1, every_ticks: 60, min: 0, max: 100 }

actions:
  observe: { duration_ticks: 3,   cooldown_ticks: 1 }
  crawl:   { duration_ticks: 5,   cooldown_ticks: 2 }
  reach:   { duration_ticks: 2,   cooldown_ticks: 1 }
  grab:    { duration_ticks: 2,   cooldown_ticks: 1 }
  cry:     { duration_ticks: 6,   cooldown_ticks: 0 }
  sleep:   { duration_ticks: 120, cooldown_ticks: 10 }
```

### Interfaces to Protect Fine-Tuning

Define ports so tuning does not require touching business logic.

```python
class ClockPort(Protocol):
    def current_tick(self) -> int: ...
    def tick_duration_ms(self) -> int: ...

class TickPolicyProvider(Protocol):
    def get_need_tick_policy(self, need_name: str) -> NeedTickPolicy: ...
    def get_action_tick_policy(self, action_name: str) -> ActionTickPolicy: ...

@dataclass(frozen=True)
class NeedTickPolicy:
    name: str
    direction: str
    amount: int
    every_ticks: int
    min_value: int
    max_value: int

@dataclass(frozen=True)
class ActionTickPolicy:
    action_name: str
    duration_ticks: int
    cooldown_ticks: int
```

The `NeedService` asks the policy provider and applies a policy when
`current_tick % every_ticks == 0`. Changing hunger from 30 ticks to 20 ticks
should require a config change only — no service code changes.

---

## 11. ML Architecture

### First Neural Network — Outcome Predictor

Task:

```text
object properties + action + context → predicted outcomes
```

Example input → output:

```text
round=1 rubbery=1 soft=1 action_drop=1 surface_hard=1
  → falls: 0.96  bounces: 0.82  rolls: 0.61
    causes_pain: 0.01  makes_noise: 0.22  pleasant: 0.70  scary: 0.02
```

This is a **multi-label** prediction model — one action can produce multiple
outcomes:

```text
drop rubber ball  → falls + bounces + rolls
shake rattle      → makes_noise + pleasant
touch hot object  → causes_pain + scary
```

Use a simple feed-forward network to start.

### Shadow Mode First

In v0 the model predicts outcomes but does **not** control the being:

```text
Rule system predicts outcome.
PyTorch predicts outcome.
Actual outcome occurs.
Both predictions are stored.
System compares prediction quality.
```

> Note: in v0 the training data is generated by the rule layer, so the model
> is initially learning to imitate rules we already authored. That is the
> intended way to exercise the full ML loop (collect → encode → train →
> evaluate → infer → compare). Genuine learning signal arrives in v1+, when
> prediction uncertainty starts feeding curiosity.

### ML Stack

PyTorch, NumPy, Pandas, scikit-learn, Pydantic, pytest.
Optional later: MLflow (experiment tracking), DVC (dataset/model versioning),
pgvector (memory similarity).

---

## 12. Decision System

Do not let the neural network control everything. Use a hybrid:

```text
Rules + utility scoring + neural prediction + safety guardrails
```

Inputs: current needs, dominant emotion, nearby objects, perceived properties,
memories, prediction output, safety rules, curiosity, action cooldowns.

Output:

```json
{ "action": "crawl", "targetId": "obj_red_ball", "emotion": "curious",
  "reason": "Curiosity is high and predicted risk is low." }
```

Example: for a hot object where touch predicts pain, safety rules block or
heavily penalize touch, and the being chooses observe / move away / cry /
seek caregiver instead. Learned predictions never bypass safety.

---

## 13. Runtime Flow

```text
1. Engine starts.
2. Loads YAML/JSON config.
3. Connects to Postgres.
4. Loads current being profile.
5. Loads PyTorch model if available.
6. Starts tick loop.

Each tick:
  - TickService increments tick.
  - NeedService applies tick policies.
  - RoomService provides nearby objects/environment.
  - PerceptionService creates perceived state (confidence, uncertainty).
  - PredictionService predicts likely outcomes.
  - DecisionService scores valid actions.
  - SafetyService blocks invalid/unsafe actions.
  - Action is selected.
  - EmotionService updates dominant emotion.
  - LearningService records events and training examples.
  - RenderStateService sends state to PixiJS.
```

---

## 14. PixiJS Rendering Contract

Python sends render state over WebSocket:

```json
{
  "type": "being_state_update",
  "beingId": "being_001",
  "tick": 1024,
  "emotion": "curious",
  "pose": "crawl",
  "action": "observe",
  "intensity": 0.7,
  "needs": { "hunger": 35, "sleep": 40, "comfort": 75, "curiosity": 82 },
  "visual": { "mouth": "small_open", "eyes": "wide", "effects": ["head_tilt"], "thought": "?" }
}
```

The renderer sends commands back:

```json
{ "type": "player_command", "command": "present_object", "targetId": "obj_red_ball" }
```

---

## 15. Database v0 Tables

Start small:

```text
beings
objects
interaction_events
training_examples
prediction_records
model_runs
```

- **beings** — being identity/profile.
- **objects** — object definitions and current known developer data.
- **interaction_events** — meaningful events.
- **training_examples** — model-ready rows derived from events.
- **prediction_records** — model predictions for comparison against actuals.
- **model_runs** — training run metadata.

---

## 16. Testing Strategy

Behavior-driven tests and TDD around service seams.

```text
Tick policy:   hunger rises every 30 ticks → unchanged at 29, +1 at 30.
Need service:  hunger 99, +5 → capped at 100.
Action timing: crawl cooldown 2 → not selectable until cooldown expires.
Shadow mode:   model predicts bounce, actual is bounce → record marked correct.
Decision:      hot object + touch-predicts-pain → touch blocked/penalized.
Learning:      event expected roll + observed roll → training example created.
Render:        emotion curious + action observe → valid pose/visual fields.
```

---

## 17. Deep Module Boundaries

- **ConfigService** — load/validate YAML/JSON, provide typed policies.
  Consumers never see file paths or YAML.
- **TickService** — owns tick progression; does not know need tuning.
- **NeedService** — applies drift from `NeedTickPolicy`, clamps; no YAML/DB.
- **PerceptionService** — turns world truth into a *perceived* world
  (confidence, uncertainty); the being never reads the true world directly.
- **PredictionService** — encode features, call PyTorch, return outcome
  probabilities, support shadow mode; does not choose actions.
- **DecisionService** — score actions from needs + predictions + memory +
  safety; does not render or persist.
- **LearningService** — convert interactions into training examples, update
  memories/beliefs, record prediction errors.
- **RenderStateService** — map domain state to the PixiJS contract; makes no
  psychology decisions.

---

## 18. Version Path

### v0 — Minimal Learning Loop

Docker Compose (engine, postgres, renderer, ml-trainer); config-driven ticks;
basic world/room/object/being; simple needs; simple emotions; simple
rule/utility decisions; Postgres event logging; training-examples table;
PyTorch outcome predictor; shadow mode; PixiJS render state over WebSocket.

Success: simulation runs via Compose; needs drift from config; tick config
changes need no code changes; interactions stored; trainer produces a model
artifact; engine loads it and records predictions; renderer updates from state.

### v1 — Prediction Influences Curiosity

Prediction uncertainty affects curiosity; unknown/surprising objects become
more interesting; prediction error updates memory; more object properties and
outcomes.

### v2 — Prediction Influences Decision Scoring

Neural prediction contributes to utility scores; safety rules remain hard
guardrails; object memories influence action selection.

### v3 — Beliefs and Concept Schemas

Belief records and concept schemas (`unsupported_objects_fall`,
`round_objects_roll`, `rubbery_objects_bounce`, `hot_objects_hurt`,
`dark_reduces_visibility`) with evidence counts and confidence. The being
generalizes from one round object to another and learns nuance.

### v4 — Memory Retrieval and Similarity

Memory retrieval service; optional pgvector for similarity search; more
nuanced object similarity influencing predictions and curiosity.

### v5 — LLM Integration

Natural-language command interpretation, narrative log generation, memory
summarization, personality-flavored text. The LLM converts commands into
structured actions the engine validates; it does not control game logic.

### v6 — Graph Projection (Optional)

A graph database as a read-model/projection only if relationship traversal
becomes central. Postgres stays the source of truth; the graph can be rebuilt
from events.

---

## 19. Important Architectural Rules

1. Do not let PixiJS own behavior.
2. Do not let PyTorch directly control everything.
3. Do not hard-code tick rates in services.
4. Do not use Markdown as runtime memory.
5. Do not start with a graph database.
6. Do not start with an LLM as the whole brain.
7. Use config and interfaces so fine-tuning is isolated.
8. Use Postgres as the source of truth for learned/dynamic data.
9. Use PyTorch first as a narrow outcome predictor.
10. Use tests around deep module seams.

---

## 20. Claude Agent Implementation Instructions

Break the work into vertical slices. Each slice should be independently
testable, include behavior-driven tests, preserve clear module seams, avoid
big-bang rewrites, prefer config-driven tuning over hard-coded constants, and
keep runtime behavior deterministic unless randomness is injected behind an
interface.

Suggested first slices:

1. Docker Compose skeleton.
2. Python FastAPI engine service.
3. Postgres connection and initial migrations.
4. Config loader for YAML files.
5. Tick policy model and tests.
6. NeedService using tick policies.
7. Basic world/room/object/being models.
8. Environmental conditions (light/dark, sound, temperature).
9. Interaction event persistence.
10. Training example generation.
11. PyTorch outcome model and trainer sidecar.
12. Prediction shadow mode.
13. PixiJS renderer WebSocket contract.
14. Render state adapter.
15. Simple decision service + behavior-driven suite around tick/action/decision.

---

## 21. v0 North Star

```text
A Docker Compose project where a Python engine runs a situated being in one
room, with configurable tick-based needs, a few simple objects and
environmental conditions (light/dark, sound, temperature), event logging to
Postgres, a PyTorch outcome-prediction model running in shadow mode, and a
PixiJS renderer showing the being's current emotion/action.
```

This should teach: Docker networking, backend service design, Postgres
persistence, event logging, ML training-data creation, PyTorch model training,
shadow-mode inference, PixiJS rendering, and clean architecture with deep
modules and testable seams.

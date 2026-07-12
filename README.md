# jarvis — situated-being ML simulation

A simulated **being** — human-like in psychology (needs, emotions, curiosity,
memory, learned expectations). The long-term goal is a hybrid brain:
authored rules + a small neural network for narrow prediction, rendered in 2D,
running across Docker services. The near-term goal is to learn ML by building
that loop one honest slice at a time.

The full target architecture lives in [`docs/BRIEF.md`](docs/BRIEF.md) —
Postgres, PyTorch, FastAPI/WebSocket, PixiJS, Docker Compose. This repo builds
toward it in vertical slices; the roadmap below tracks what is actually here
today.

## What exists today

The **v0 Minimal Learning Loop is complete** (`V0-1…V0-11` + `V0-SEC`) and the
being has grown well past it. Today it:

- **Lives a psychological loop.** Needs **drift over ticks** (config-driven), one
  dominant **emotion is derived** from them, it **perceives nearby objects** each
  with a confidence, and **environmental conditions** (dark / loud / cold) push
  contextual needs so fear can fire. It **decides one action** by utility, and an
  absolute **invariant floor** gates every choice — blocking only
  simulation-breaking actions while letting **recoverable harm** (touching
  something hot) land felt consequences it learns from.
- **Learns and remembers.** Every interaction becomes a persisted **memory**;
  **retrieval** recalls the relevant ones before it decides; it forms **object
  concepts and beliefs** that feed the decision as anticipated discomfort;
  **curiosity / surprise** drive exploration; slow **trait drift** (caution /
  curiosity) settles a temperament; a walkable **concept graph** links what it
  knows; and **one-shot aversive learning** lets a single bad moment stick. A
  PyTorch **outcome predictor** trains from interactions (or a synthetic seed
  set via the `ml-trainer` sidecar) and runs in **shadow mode**, with a config
  flip to **active blended prediction** that shapes the decision (safety still
  gates); model inference can run out-of-process behind a config-selected
  **model-service** sidecar (a **PredictionClient** seam: in-process / HTTP /
  fallback) that degrades to the rules/baseline if it is unavailable, so the
  sim never stalls.
- **Runs on an event backbone with an instinct layer.** Domain events travel over
  an **EventBus** (in-memory by default, **Kafka** at runtime), with a
  **transactional outbox** that projects into an idempotent **event log**. A
  fast, pre-conceptual **instinct** neural layer reads sensory/kinematic stimuli
  (approach, **sound-spike**, **touch / contact**) into protective **reactions**
  that bias the displayed emotion and can **safely interrupt** an action (never
  bypassing the floor); an **adaptive temperament** habituates to harmless
  startles and sensitizes after harm.
- **Is exposed, persisted, and rendered.** An **authenticated HTTP + WebSocket
  API** (always-on JWT) serves state and render frames to a **PixiJS renderer**;
  persistence is **Postgres** behind a repository port with **unit-of-work**
  commits; the whole thing runs as a **Docker Compose** stack (engine + postgres
  + kafka + renderer + ml-trainer + model-service (profile-gated)).
- **Has a language faculty — on top of the sim, never driving it.** It gives a
  first-person **self-report** (`POST /ask`) grounded only in its own memories,
  answers **subject queries** ("what do you know about hot things?") from its
  learned concepts, and phrases both through a **config-selected narrator**
  (deterministic template by default; Claude or a local model optional; always
  falling back to the template). A **voicebox** speaks its report (`/speak`) and
  reads a document aloud (`/read`). It keeps a **growing, persistent knowledge
  store** of everything it has read, gives **grounded, cited answers** about it
  (`/ask/reading`), holds **multi-turn conversations** (`/chat`), and takes
  documents in as **reading-as-perception** — forming real memories and concepts
  through the same validated door a lived interaction uses (language never writes
  state).

**Built but host-gated (not "running here").** The being's **own LLM** — LoRA
**fine-tune**, **Ollama serving**, and sleep-triggered **consolidation** — is
implemented behind the language-model port, but it runs **host-native on a Mac
(MLX + Ollama)** because the GPU is not exposed inside the container. Those GPU
paths are **gated off in CI and skip cleanly** there; the offline seams
(deterministic-template narrator, hashing embedder, retrieval/QA against a
fake/deterministic model) run anywhere. See
[`docs/RUNBOOK.md`](docs/RUNBOOK.md) for exactly what runs where.

The full **as-built map is the Architecture diagram below**; the ordered,
status-bearing plan is the **Roadmap**; the decisions behind each seam are the
[ADRs](docs/adr/) (0001–0043). Domain terms are defined in
[`CONTEXT.md`](CONTEXT.md). Where things live:

```
config/                     # ALL tuning (config-only retuning): needs & bands,
                            #   emotions, environment, actions, decision weights,
                            #   safety rules, events, instinct, motion, traits,
                            #   learning rates, milestones, language, voice,
                            #   render hints, and scenarios/
engine/app/
  simulation.py             # the public interface: tick(), state(), read(), + queries
  config_service.py         # YAML -> typed policies (the only config-aware code)
  bootstrap.py              # wires the being from config + ports
  main.py                   # FastAPI: /state /ws /command /ask /ask/reading /chat /speak /read
  domain/                   # BeingState, Room, objects, concepts, events, reactions
  services/                 # the cognition / instinct / learning / language services
  ml/                       # outcome + instinct predictors (encode, model, trainer)
  language/                 # narration, reading, voice built on the language ports
  ports/                    # the seams: clock, repositories, event bus, predictor, LM, voice
  adapters/                 # concrete port impls (Kafka, Claude, local model, espeak, ...)
  db/ · repositories.py · outbox_relay.py   # Postgres persistence + outbox relay
engine/tests/               # behavior-driven tests (lean suite; postgres/kafka/torch gated)
docs/                       # BRIEF, RUNBOOK, SELF_NARRATION, READING_VOICEBOX, adr/
docker-compose.yml          # engine + postgres + kafka + renderer + ml-trainer + model-service
```

## Architecture

The current, **as-built** architecture of the being — a true map of what the
code does today, not the full target in [`docs/BRIEF.md`](docs/BRIEF.md). Domain
terms are defined in [`CONTEXT.md`](CONTEXT.md); the decisions behind each seam
are in [`docs/adr/`](docs/adr/). The fast layers (perception, instinct,
reaction) feed into — but **never bypass** — the safety **invariant floor** that
gates every action
([ADR 0014](docs/adr/0014-invariant-floor-and-outcome-state-effects.md)).

```mermaid
flowchart TB
    %% ---- World / Environment ----
    subgraph world["World / Environment (true world)"]
        Room["Room: objects + affordances"]
        Env["Environmental conditions: light / sound / temperature"]
        Motion["Object motion / kinematics: position + velocity"]
    end

    %% ---- Perception (perceived, never the true world) ----
    subgraph perception["Perception"]
        Perc["PerceptionService: perceived objects + confidence"]
        Stim["StimulusService: derives approach / sound-spike / contact stimuli as the frozen 14-feature vector"]
    end

    %% ---- Event backbone ----
    subgraph backbone["Event backbone"]
        Bus["EventBus port: InMemory default / Kafka runtime"]
        Topics["being.* topics: perception / instinct / model"]
        Outbox["Transactional outbox"]
        Elog["event_log projection (idempotent)"]
    end

    %% ---- Instinct layer (fast, pre-conceptual) ----
    subgraph instinct["Instinct layer"]
        Inst["InstinctService"]
        IModel["InstinctModel (PyTorch) + InstinctEncoder"]
        Temper["TemperamentService: habituation / sensitization"]
        React["Reaction: flinch / freeze / orient / withdraw / ignore + intensity"]
    end

    RResp["ReactionResponseService: emotion bias (visual-only) + safety-gated action interrupt"]

    %% ---- Cognitive core ----
    subgraph core["Cognitive core"]
        Need["NeedService: needs drift over ticks"]
        Emo["EmotionService: dominant emotion (derived)"]
        Dec["DecisionService: utility choice of one action"]
        Safety["SafetyService: invariant floor (absolute)"]
        Pred["OutcomePredictor: rule + neural ensemble (shadow / active)"]
    end

    %% ---- Learning / memory ----
    subgraph learning["Learning / memory"]
        Mem["MemoryService + retrieval"]
        Concepts["ConceptService / BeliefService"]
        KGraph["KnowledgeGraphService: concept graph"]
        Curio["CuriosityService / SurpriseService"]
        Traits["TraitService: caution / curiosity tendencies"]
    end

    %% ---- Language / self-report surface (non-authoritative, read-only) ----
    subgraph language["Language layer (non-authoritative, read-only)"]
        Self["SelfReportService: grounded self-report from memory + subject routing"]
        Subj["SubjectReportService: what it knows/feels about X (from learning)"]
        Res["SubjectResolver: subject term -> perceived-property tokens"]
        Narr["MemorySummaryService / NarrationService"]
        LMPort["LanguageModelPort seam"]
        Sel["build_narrator: config provider selection + fallback-safe"]
        Templ["TemplateLanguageModel: deterministic narrator (offline; default + fallback)"]
        Fake["FakeLanguageModel: in-memory (tests)"]
        Claude["ClaudeLanguageModel: fluent narrator (env-gated)"]
        Local["LocalLanguageModel: local model (S2 = reading R2; Ollama, client-only)"]
        Ingest["Reading ingest: read → clean → chunk into training-ready text (reading R1)"]
        Embed["Embedder: passage → vector (deterministic hashing offline default; sentence-transformers gated) (reading R3)"]
        Store["RetrievalPort / KnowledgeStore: growing, persistent, cumulative knowledge store; top-k cosine, cites source (reading R3; pgvector-ready)"]
        ReadingQA["ReadingQAService: RetrievalPort top-k -> grounded prompt (only retrieved passages + question) -> LanguageModelPort -> cited answer; unread declined honestly + labelled base knowledge (reading R4)"]
        Convo["ConversationService: multi-turn grounded conversation over ReadingQA + conversation-turn history; folds prior turns so a follow-up resolves to the earlier subject; a new unread topic still declined honestly (reading R6)"]
        AValid["ActionValidationService: the validated action door — an allowed action on a currently-perceived object (its analogue of CommandService, over the being's action vocabulary)"]
        ReadPerc["ReadingPerceptionService: a read section → perceived content tokens (deterministic, model-free) → validated observation → the SAME Memory/Concept + curiosity a lived interaction forms; holds NO LanguageModelPort in the write path (reading R7)"]
        Finetune["LoRA fine-tune runner: host-native MLX-LM on the Mac GPU; gated + lazy import (reading R1)"]
        Adapter[("LoRA adapter artifact: our own fine-tuned model (reading R1 → served R2)")]
        Serve["Serve pipeline: fuse LoRA → GGUF → ollama create → Ollama serves :11434 (reading R2; host-native Mac, gated)"]
        Consol["ConsolidationScheduler + run_consolidation: the being's sleep cycle TRIGGERS an ASYNC host-native LoRA pass (never blocks the tick) over Q/A pairs synthesized from the knowledge store via the LanguageModelPort (Claude, BUILD-time); reuses R1 fine-tune + R2 serve so facts are later recalled WITHOUT retrieval (reading R5; config-gated + disabled by default, host-gated)"]
        LCmd["LanguageCommandService: interpret NL into a validated action"]
        VBuild["build_voice: config engine selection (S4 = reading R8)"]
        VPort["VoicePort seam: synthesize self-report / reading answers / documents → speech (reading R8)"]
        Espeak["EspeakVoice: espeak-ng TTS (host-gated; no-op if binary absent)"]
        FakeV["FakeVoice: in-memory (tests)"]
    end

    PG[("Postgres: repositories + unit-of-work + outbox + event_log + instinct + knowledge_chunks + conversation_turns tables")]

    %% ---- Client / transport ----
    subgraph client["Client / transport"]
        API["FastAPI: GET /state + WebSocket /ws render frames (JWT)"]
        Renderer["Renderer (PixiJS)"]
    end

    Trainer["ml-trainer sidecar: trains outcome + instinct models (.pt)"]
    ModelSvc["model-service sidecar (v8): serves BOTH models out-of-process — /predict/outcome + /predict/instinct + /health + /models/active; loads the .pt artifacts; profile-gated"]
    PredClient["PredictionClient seam (v8): InProcess / Http / Fallback — covers BOTH model ports; degrades to the rule/safe baseline on a service outage"]
    Doc(["Document you hand the being (reading R1)"])

    %% ---- Sensing flow ----
    Room --> Perc
    Env --> Perc
    Motion --> Stim
    Room --> Stim
    Perc -->|perceived frame| Stim
    Bus -.->|routed frame via being.perception.taken| Stim
    Perc --> Bus
    Stim --> Bus
    Bus --- Topics

    %% ---- Instinct flow ----
    Bus --> Inst
    Inst --> IModel
    IModel --> React
    Temper -.->|reshapes thresholds| Inst
    React --> Temper
    React --> RResp

    %% ---- Cognitive flow ----
    Env --> Need
    Need --> Emo
    RResp -->|emotion bias| Emo
    Emo --> Dec
    Pred -->|anticipated cost| Dec
    Pred -.->|outcome inference| PredClient
    IModel -.->|instinct inference| PredClient
    PredClient -->|http mode| ModelSvc
    Trainer -.->|.pt artifacts| ModelSvc
    Concepts -->|anticipated discomfort| Dec
    Curio -->|exploration| Dec
    Mem --> Dec
    Traits --> Dec

    %% ---- Safety floor is absolute — nothing bypasses it ----
    Dec ==>|gated by| Safety
    RResp ==>|interrupt gated by| Safety
    Safety ==>|approves| Action["Action on object"]

    %% ---- Learning + persistence ----
    Action --> Mem
    Action --> Pred
    Action --> Bus
    Mem --> Concepts
    Concepts --> KGraph
    Mem --> Curio
    Inst --> Outbox
    Action --> Outbox
    RResp -->|stages reaction events| Outbox
    Outbox --> Elog
    Outbox --> PG
    Elog --> PG
    Mem --> PG

    %% ---- Language + client ----
    Mem -.->|memory snapshots| Self
    Emo -.->|state snapshot| Self
    Self -->|subject query| Subj
    Subj --> Res
    Concepts -.->|learned concepts / beliefs| Subj
    KGraph -.->|explanation paths| Subj
    Subj --> LMPort
    Self --> Narr
    Narr --> LMPort
    LMPort --> Sel
    Sel --> Templ
    Sel -.-> Fake
    Sel -.-> Claude
    Sel -.-> Local
    Claude -.->|on error| Templ
    Local -.->|on error / unavailable| Templ
    Doc --> Ingest
    Ingest -->|training-ready chunks| Finetune
    Ingest -->|chunks| Embed
    Embed -->|embeddings| Store
    Store -->|persist chunks + embeddings| PG
    Store -->|top-k relevant passages| ReadingQA
    ReadingQA -->|grounded prompt| LMPort
    API -->|"/ask/reading"| ReadingQA
    ReadingQA -->|grounded, cited answer| API
    ReadingQA -->|grounded, cited answer per turn| Convo
    Convo -->|folded query per follow-up| ReadingQA
    Convo -->|persist conversation turns| PG
    API -->|"/chat"| Convo
    Convo -->|grounded, cited multi-turn answer| API

    %% ---- Reading-as-perception: a document changes the being ONLY through the validated perception/cognition door, never the LM (reading R7, ADR 0040) ----
    Ingest -->|sections| ReadPerc
    ReadPerc -->|section as a perceivable object| Perc
    ReadPerc ==>|gated by the action door| AValid
    ReadPerc -->|forms a memory keyed on perceived tokens| Mem
    ReadPerc -->|strengthens a concept where a token recurs| Concepts
    ReadPerc -->|new material updates curiosity| Curio
    LCmd ==>|gated by the action door| AValid
    %% NOTE: no edge from LanguageModelPort to Memory/Concept — language never writes state (ADR 0022/0040)
    Finetune -.->|host-native LoRA fine-tune| Adapter
    Adapter -.->|fuse → GGUF → ollama create| Serve
    Serve -.->|Ollama :11434 (host.docker.internal)| Local

    %% ---- Knowledge consolidation on 'sleep': the sim tick TRIGGERS an async, non-blocking LoRA pass; it never runs on the tick thread and never drives the being (reading R5, ADR 0041) ----
    Need -.->|sleep-need rising edge enqueues consolidation (async, non-blocking)| Consol
    Store -.->|accumulated chunks to consolidate| Consol
    LMPort -.->|build-time Q/A pair synthesis (Claude)| Consol
    Consol -.->|consolidation pairs → host-native LoRA fine-tune| Finetune
    Consol -.->|re-fuse → GGUF → ollama create| Serve
    LCmd --> LMPort
    API -->|"/ask"| Self
    Self -->|self-report| API
    API -->|"/speak"| Self
    Self -->|self-report text| VPort
    API -->|"/read: voice a document aloud"| Ingest
    Ingest -.->|cleaned + chunked read-aloud utterances| VPort
    ReadingQA -.->|"answer text (speak=true)"| VPort
    Convo -.->|"answer text (speak=true)"| VPort
    VPort --> VBuild
    VBuild --> Espeak
    VBuild -.-> FakeV
    VPort -->|audio| API
    Emo --> API
    Dec --> API
    React --> API
    API <--> Renderer
    Renderer -->|player command| API
    API -->|player command| Room

    %% ---- Trainer sidecar ----
    PG -.->|training data| Trainer
    Trainer -.->|outcome model .pt| Pred
    Trainer -.->|instinct model .pt| IModel
```

## Run it

**Run & verify.** The full install / verify / train guide — host tooling, Postgres, Kafka, the outcome predictor, and the host-native reading faculty, with a table of what runs where — is [`docs/RUNBOOK.md`](docs/RUNBOOK.md). The essentials:

```bash
make setup          # create engine/.venv and install deps (once)
make test           # run the behavior suite
make demo           # watch the being drift (make demo TICKS=600)
make run            # serve the API on http://localhost:8000  (GET /state, WS /ws)
make train          # train the outcome predictor -> models/outcome_predictor.pt
                    #   (installs torch on first run — heavy, minutes)

# or the full stack in containers:
make up             # docker compose up --build  (engine :8000, postgres :5432)
make down           # stop + remove volumes
```

The API is authenticated (always-on JWT — [ADR 0005](docs/adr/0005-api-authentication.md)).
Copy `.env.example` to `.env` and set a `JWT_SECRET`, then mint a service token
and call the API with it:

```bash
cp .env.example .env                       # then edit JWT_SECRET
export $(grep -v '^#' .env | xargs)        # load JWT_SECRET etc. into the shell
make run &                                  # serve on :8000

curl -s localhost:8000/health              # public → {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' \
  localhost:8000/state                     # no token → 401
TOKEN=$(make -s token)                      # mint a token with the same secret
curl -s -H "Authorization: Bearer $TOKEN" \
  localhost:8000/state                     # → 200 + the being's snapshot
```

The WebSocket `/ws` takes the token as `?token=<jwt>` or the `Authorization`
header. Set `AUTH_REQUIRED=false` only for throwaway local dev (a documented
dev-only no-op — there is no localhost bypass).

No `make`? The equivalent is `python3 -m venv engine/.venv`, install
`engine/requirements.txt` into it, then run modules from `engine/` with
`PYTHONPATH=.` (e.g. `python -m app.demo 300`, `python -m pytest`,
`python -m app.auth_token`).

## Run with Postgres

Persistence uses Postgres (V0-7, [ADR 0007](docs/adr/0007-persistence-repository-port-and-schema-seam.md)).
Start the database on its own, point `DATABASE_URL` at it, and create the schema:

```bash
make db-up                                  # start Postgres, wait until it accepts connections
export DATABASE_URL=postgresql+psycopg://sim:sim@localhost:5432/being_sim
make migrate                                # create the v0 tables (retries until the DB is ready)
```

`make db-up` runs `docker compose up -d --wait postgres`, so it returns only once
the container reports healthy. `make migrate` (and any connect through
`app.db.session`) also **waits for the database to accept connections** with
bounded backoff, so running `make migrate` immediately after `docker compose up`
no longer races Postgres' first-boot init — it retries until the DB is ready and
otherwise **fails with a clear error after a configurable timeout**.

Tune the wait with these optional environment variables (deploy/ops config, same
category as `DATABASE_URL`; defaults in parentheses):

| Variable | Default | Meaning |
|---|---|---|
| `DB_CONNECT_TIMEOUT_SECONDS` | `30` | total budget before giving up with a clear error |
| `DB_CONNECT_BACKOFF_SECONDS` | `0.5` | initial wait between attempts |
| `DB_CONNECT_BACKOFF_MAX_SECONDS` | `5` | cap on the (geometrically growing) wait |
| `DB_CONNECT_BACKOFF_MULTIPLIER` | `2` | growth factor applied to the wait each retry |

With `DATABASE_URL` reachable, the persistence integration tests (the `[postgres]`
variants marked `integration`) run the real round-trip; with it unset or
unreachable they **skip cleanly** with a reason — the database is never faked:

```bash
DATABASE_URL=postgresql+psycopg://sim:sim@localhost:5432/being_sim make test
```

## Roadmap (single source of truth)

The ordered, status-bearing roadmap. One version scheme
([ADR 0018](docs/adr/0018-canonical-v1-v14-roadmap.md)): **v0** is the Minimal
Learning Loop, delivered as slices `V0-1…V0-11` + `V0-SEC`; everything after it
is the canonical **`v1…v14`** capability roadmap. Delivered in parallel **waves**
(sequenced by dependency, not version number), so completion is not strictly
top-to-bottom. Per-version goals, exit criteria, and wave sequencing live in
[`docs/post_v0_execution_plan.md`](docs/post_v0_execution_plan.md); the live
per-wave board/dispatch state in
[`docs/next_loop_execution_plan.md`](docs/next_loop_execution_plan.md). Each
slice is test-first and ends in something observable.

### v0 — Minimal Learning Loop ✅ (`V0-1…V0-11` + `V0-SEC`, all done)

- **V0-1** — Minimal being state: needs drift from config, emotion derived.
- **V0-2** — Objects + a room; the being perceives what is near.
- **V0-3** — Environmental conditions (light/dark, sound, temperature) move
  contextual needs like safety — this is what makes `scared`/fear fire
  ([ADR 0006](docs/adr/0006-environmental-conditions-to-contextual-need-seam.md)).
- **V0-4** — Actions + a simple rule/utility decision; a safety *invariant floor*
  blocks only simulation-breaking actions, while recoverable-but-harmful ones
  (touching something hot) are allowed and land felt consequences the being
  learns from
  ([ADR 0014](docs/adr/0014-invariant-floor-and-outcome-state-effects.md)).
- **V0-5** — Docker Compose skeleton (engine + postgres) + engine image.
- **V0-6** — FastAPI engine: REST `/state` + WebSocket tick stream.
- **V0-7** — Postgres persistence: interaction events + training examples
  ([ADR 0007](docs/adr/0007-persistence-repository-port-and-schema-seam.md)).
- **V0-8** — PyTorch outcome predictor + `ml-trainer` sidecar; the feature/label
  encoding contract is pinned in
  [ADR 0008](docs/adr/0008-outcome-predictor-and-feature-encoding.md).
- **V0-9** — Prediction shadow mode: the model records predictions beside actual
  outcomes without changing behavior
  ([ADR 0011](docs/adr/0011-prediction-shadow-mode-and-predictor-port.md)).
- **V0-10 / V0-10a** — Render-state contract + `RenderStateService`
  ([ADR 0004](docs/adr/0004-render-state-contract.md)).
- **V0-11** — PixiJS renderer showing the being's emotion/needs; sends a
  `player_command` back
  ([ADR 0010](docs/adr/0010-renderer-authentication.md)).
- **V0-SEC** — Always-on JWT API authentication
  ([ADR 0005](docs/adr/0005-api-authentication.md)).

### post-v0 — the canonical `v1…v14` capability roadmap

Sequenced by dependency in waves; a `vN` label is a capability, not a build slot.
Per-version detail and current per-wave status are in the execution plans linked
above (this list does not restate them).

- **v1** — Stable cognitive loop: persisted memory records
  (perception→action→predict→error→memory).
- **v2** — Object concepts and belief formation.
- **v3** — PyTorch outcome prediction becomes active, blended into the decision;
  safety still gates
  ([ADR 0015](docs/adr/0015-active-blended-outcome-prediction.md)).
- **v4** — Curiosity, surprise, and exploration policy.
- **v5** — Environment awareness *(delivered early as V0-3)*.
- **v6** — Memory retrieval and long-term trait drift.
- **v7** — Graph-like concept network (Postgres node/edge tables).
- **v8** — Model-service sidecar and multi-model inference.
- **v9** — Natural language layer (interpret + narrate, never controls the sim).
- **v10** — Developmental progression and scenario system.
- **v11–v14** *(optional)* — vector memory search (pgvector) · reinforcement-
  learning sandbox · multi-shell simulation · production runtime split
  (observability).

See [`docs/adr/`](docs/adr/) for the decisions behind the structure and
[`CLAUDE.md`](CLAUDE.md) for how work is done here.

## How we work (governance index)

The rules and guardrails that govern how work happens here live in
[`CLAUDE.md`](CLAUDE.md); this table is their index. **Any new rule, hook,
guardrail, or sub-agent convention must add or update a row here in the same
change** (enforced by convention — see CLAUDE.md → Documentation).

| What we have | Why | What it does |
|---|---|---|
| Vertical slices | Ship observable value; avoid big-bang | Every change ends in something a user can see/do; the one-sentence outcome is stated first |
| TDD, red-first | Prove behavior, not methods | Write behavior tests, watch them fail, then implement to green |
| Deep modules | Simple interfaces, testable seams | Lots of behavior behind one small public class; no port until something varies across it |
| Deep-module review gate | Catch design drift early | `/legacy-deep-module-review` runs after each slice, before it is called done |
| Domain-model gate | Keep the ubiquitous language current | After each slice, update root `CONTEXT.md` (via the `domain-modeling` skill) with new/changed terms; an ADR only per its 3-part test |
| Architecture-diagram gate | Keep the architecture map honest | After each slice, update the root `README.md` **Architecture** Mermaid diagram for any new/changed module, seam, service, topic, or data flow; a no-change slice says so; sub-agents report the diagram-update outcome |
| Config-driven tuning | Retune without touching code | Rates/thresholds/vocab live in `config/*.yaml`; only `ConfigService` reads them |
| Transactional persistence (unit of work) | Atomic writes; no partial/orphan rows | Repos stage; the caller commits one transaction per logical op (event + example + prediction together); READ COMMITTED; deviations only with a stated reason (ADR 0017) |
| ADRs | Durable decision record | One `docs/adr/NNNN` per significant decision; never rewritten, only superseded |
| No commits on `main` (hook) | Keep `main` reviewed and clean | `.githooks/pre-commit` rejects commits on `main`; all work is a worktree branch → PR |
| API auth (always-on JWT) | Close the state surface by default | Every protected route runs `require_auth` (HS256, sig+exp+iss+aud); `/health` public; always in the code path, gated only by `AUTH_REQUIRED` — no loopback bypass ([ADR 0005](docs/adr/0005-api-authentication.md)) |
| Secrets never committed (env + scan) | Keep secrets out of git | `.env`/`*.pem`/`*.key` gitignored (only `.env.example` committed); the `pre-commit` hook blocks a staged `.env`, key file, or PEM/AWS-key literal |
| Worktrees + wave PRs | Parallel work without clobbering | Each slice runs in its own worktree/branch; a wave rolls up into a single PR |
| Orchestrator vs sub-agents | Clear ownership | Orchestrator owns git + the board; sub-agents own code, commit in their worktree, and report |
| Orchestrator delegates by default | Fast parallelism; small orchestrator context | Orchestrator does only non-delegable acts inline (worktree/branch/merge/PR/branch-delete, board writes) and delegates implementation, verification, reconciliation, authoring, and investigation to sub-agents; it consumes verdicts, not raw output |
| Sub-agent → workflow escalation | Scale to large slices | A sub-agent may spawn a workflow/helper agents, staying within its worktree contract |
| Self-diagnosing / self-healing | Keep the open PR pristine | Defects become bug tickets → `hotfix/<ticket>` → verify → merge back; nothing merges red |
| Closing a wave | Clean, verified finish | After the PR merges: pull, verify, self-heal if needed, delete branches/worktrees, cards → done, report |
| Trello board guardrails | Safe, auditable task flow | Official MCP only; pull from `Ready for Agent`; claim before work; gated one-step moves; a human does Done |
| New-work intake gate | No code before a card | Any new ask — including a direct in-session director request — becomes a board card in our pattern first; the orchestrator mints it and moves it `Ready for Agent` → `in progress` → `in review` → `done`, then normal TDD/PR/gates apply (a procedure, not a hook) |
| Design boundary | Study simulated psychology honestly | Harm is abstract internal state (pain/fear/stress/trust deltas) and **may be lasting** (no forced recovery); the being can be harmed and learn from it; adults-only; the one hard line is never real-world-harm instruction ([ADR 0013](docs/adr/0013-reframed-design-boundary.md)) |
| Dev env (`make`) | Reproducible setup and tests | `make setup/test/demo/run/train/up` — one gitignored venv, identical for everyone; `train` adds the training-only deps |
| This governance index | Keep the docs honest | New rules/hooks/conventions update this table in the same change |

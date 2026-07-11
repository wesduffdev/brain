# Architecture Decision Records

One record per architecturally significant decision. Never rewrite an accepted
ADR — supersede it with a new one and update both statuses.

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-minimal-being-state-and-config-driven-drift.md) | Minimal being state: config-driven need drift and derived emotion | Accepted |
| [0002](0002-perceived-vs-true-world.md) | Perceived world vs. true world: the perception seam | Accepted |
| [0003](0003-transport-and-clock-seam.md) | FastAPI/WebSocket transport and an injectable clock seam | Accepted |
| [0004](0004-render-state-contract.md) | Render-state contract: `being_state_update` frame and `player_command` | Accepted |
| [0005](0005-api-authentication.md) | Always-on API authentication (HS256 JWT) | Accepted |
| [0006](0006-environmental-conditions-to-contextual-need-seam.md) | Environmental conditions → contextual-need seam (fear can fire) | Accepted |
| [0007](0007-persistence-repository-port-and-schema-seam.md) | Persistence: repository-port and schema seam | Accepted |
| [0008](0008-outcome-predictor-and-feature-encoding.md) | Outcome predictor + feature/label encoding contract | Accepted |
| [0009](0009-decision-utility-and-safety-guardrail-seam.md) | Decision (utility) + safety-guardrail seam | Accepted (safety stance refined by [0013](0013-reframed-design-boundary.md)/[0014](0014-invariant-floor-and-outcome-state-effects.md)) |
| [0010](0010-renderer-authentication.md) | Renderer authentication: server-minted service token via env (no login in v0) | Accepted |
| [0011](0011-prediction-shadow-mode-and-predictor-port.md) | Prediction shadow mode + predictor-port seam | Accepted (extended by [0015](0015-active-blended-outcome-prediction.md)) |
| [0012](0012-interaction-event-and-training-example-ports.md) | Interaction-event and training-example repository ports (event→example wiring) | Accepted |
| [0013](0013-reframed-design-boundary.md) | Reframed design boundary: honest, possibly-lasting harm; no forced recovery | Accepted |
| [0014](0014-invariant-floor-and-outcome-state-effects.md) | Invariant floor + outcome→state effects: harm is suffered (allowed + felt deltas), not blocked | Accepted |
| [0015](0015-active-blended-outcome-prediction.md) | Active blended outcome prediction: neural+rule ensemble feeds the decision; safety still gates | Accepted |
| [0016](0016-built-simulation-handle-runtime-session-lifecycle.md) | `BuiltSimulation` handle: explicit runtime session lifecycle (no leaked idle-in-transaction session) | Accepted (commit boundary added by [0017](0017-unit-of-work-transaction-boundary.md)) |
| [0017](0017-unit-of-work-transaction-boundary.md) | Unit-of-work transaction boundary: repositories stage, the caller commits | Accepted |
| [0018](0018-canonical-v1-v14-roadmap.md) | Canonical `v1…v14` roadmap (supersedes BRIEF §18's old `v0…v6` path) | Accepted |
| [0019](0019-object-concepts-and-belief-formation.md) | Object concepts and belief formation | Accepted |
| [0020](0020-curiosity-surprise-and-exploration-policy.md) | Curiosity, surprise, and exploration policy | Accepted |
| [0021](0021-graph-like-concept-network.md) | Graph-like concept network (explanation paths over Postgres node/edge tables) | Accepted |
| [0022](0022-natural-language-layer-and-language-model-port.md) | Natural-language layer & the language-model port | Accepted |
| [0023](0023-aversive-concept-learning-and-belief-decision-feed.md) | One-shot aversive concept learning & the belief→decision feed | Accepted |
| [0024](0024-event-backbone-and-eventbus-port.md) | Event backbone: the `DomainEvent` envelope + EventBus port (in-memory default, Kafka runtime to follow) | Accepted |
| [0025](0025-scheduled-events-vs-real-time-loop.md) | Scheduled events vs. the real-time tick loop | Accepted |
| [0026](0026-instinct-neural-model-strategy.md) | Instinct neural model strategy: separate model, port, and artifact (frozen feature/label contract) | Accepted |
| [0027](0027-perception-motion-and-approach-stimulus.md) | Perception motion & the approach-stimulus seam (extends 0002; builds on 0024 + 0026) | Accepted |
| [0028](0028-transactional-outbox.md) | Transactional outbox for atomic event publish (stage in the unit of work; relay projects into an idempotent event log; extends 0017) | Accepted |
| [0029](0029-instinct-reaction-emotion-and-action-interrupt.md) | Instinct reaction → emotion bias & safe action interruption (staged, config-gated; extends 0011, relates to 0009/0014/0026) | Accepted |
| [0030](0030-sensory-sound-and-touch-stimulus-sources.md) | Sensory stimulus sources: sound spike & contact (touch) (extends 0027; consumes 0026 contract) | Accepted |
| [0031](0031-adaptive-instinct-temperament.md) | Adaptive instinct temperament: habituation & sensitization of reaction sensitivity (extends 0026/0029; relates to the v6 trait drift) | Accepted |
| [0032](0032-self-report-narration-surface.md) | Self-report narration surface: deterministic template narrator behind the language-model port + `SelfReportService` + `POST /ask` (extends 0022; grounded by 0002, gated by 0005) | Accepted |
| [0033](0033-config-selected-narrator-provider-with-template-fallback.md) | Config-selected narrator provider (deterministic / fake / claude / local) with fallback-safe degradation to the deterministic template + client-only local adapter (extends 0022/0032; fallback mirrors 0011; shared with reading R2) | Accepted |
| [0034](0034-subject-query-from-learned-concepts.md) | Subject queries answered from learned concepts: `SubjectResolver` (term → perceived-property tokens) + `SubjectReportService` gathers concept/belief/explanation/memory facts for the `/ask` subject path; unknown subjects declined honestly, model-free (extends 0032/0033; grounded by 0019/0021/0002, on the 0022 seam, gated by 0005) | Accepted |
| [0035](0035-voice-synthesis-port-and-open-source-tts.md) | Voice synthesis port + open-source TTS: `VoicePort` (`synthesize`) with `FakeVoice` + an espeak-ng adapter (graceful no-op when the binary is absent), config-selected engine, and `POST /speak` voicing the grounded self-report (extends 0032/0033; graceful absence mirrors 0011; gated by 0005; the voicebox reading R8 reuses) | Accepted |
| [0036](0036-our-own-language-model.md) | Our own language model: open base (Qwen2.5-3B-Instruct) + LoRA fine-tune; ingest (clean/chunk) is a pure front half, MLX-LM LoRA runs host-native on the Mac (gated, lazy import, loud refusal off-host) and produces a LoRA adapter artifact behind the `LanguageModelPort`; local-Mac → prod GPU container is an endpoint swap (extends 0022; trainer/`ModelRun` pattern from 0008/0026; unit of work 0017) | Accepted |
| [0037](0037-serve-our-model-via-ollama.md) | Serve our fine-tuned model via Ollama behind the `LanguageModelPort`: `make serve-language` fuses R1's LoRA → GGUF → `ollama create` (host-native Mac; gated, lazy import, loud refusal off-host; config-driven Modelfile), served on :11434 and reached by the reused S2 `local` adapter — `narrator.local.model` == `serve.model_name`; local-Mac → prod is an endpoint swap (realizes 0036 §5; extends 0022/0033) | Accepted |
| [0038](0038-retrieval-port-and-growing-knowledge-store.md) | Retrieval port + growing knowledge store: `RetrievalPort` (`add`/`search`) over a persistent, cumulative `knowledge_chunks` store; a deterministic offline hashing `EmbedderPort` default with a gated, lazily-imported sentence-transformers option; `KnowledgeStore` composes embedder + chunk repository + unit of work (brute-force cosine now, pgvector-ready v11); citing source per passage — grounded/cited answering follows in R4 (reading R3; extends 0022/0036/0037; unit of work 0017; FK discipline 0019) | Accepted |
| [0039](0039-grounded-cited-reading-answers.md) | Grounded, cited reading answers: `ReadingQAService` retrieves top-k from the R3 store (ADR 0038), builds a prompt over ONLY the retrieved passages + question, and cites the source from the retrieval result (never the model) — extractive+cited offline, rephrased by a generative narrator when configured; an unread topic declines honestly (no fabricated citation) and may blend a distinctly-labelled base-knowledge answer; on `POST /ask/reading` (extends 0022/0038, gated by 0005, read-only 0022) | Accepted |
| [0040](0040-reading-as-perception.md) | Reading-as-perception: a document CHANGES the being only through the validated perception/cognition door — `ReadingPerceptionService` turns each ingested section into perceived content tokens (deterministic, model-free), routes them through the real `PerceptionService` (drops the developer label, ADR 0002) + `ActionValidationService` (the door), then the SAME `MemoryService`/`ConceptService`/`ExplorationPolicyService` a lived interaction uses (a memory per section; a `token→outcome` concept where a token recurs; curiosity updates); on `Simulation.read()`, one unit of work + clock step per section; the write path holds NO `LanguageModelPort` — language never writes state (reading R7; extends 0022, grounded by 0002, reuses 0014/0019/0020, unit of work 0017) | Accepted |

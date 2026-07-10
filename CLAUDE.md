# Project instructions

## What this is

A situated-being simulation built to learn ML. The being is **human-like in
psychology** — needs, emotions, curiosity, memory, learned expectations. It
acts on its own internal state and the world around it. The full target
architecture is `docs/BRIEF.md`.

## Design boundary (applies to every change)

This is a serious simulation. Within it, the being's state and the world's
events carry real, felt consequences — distress, fear, deprivation, and
negative outcomes are modeled honestly. Those consequences are always
**abstract**: state changes (trust / stress / comfort / pain / fear deltas),
warnings, and recovery paths — never step-by-step depictions of real-world
harm. Every harmful path has a visible consequence and a recovery path. The
project must never become instructional content for harming a real or
vulnerable being. See `docs/design_boundary.md`.

## Development process (applies to every request)

### Vertical slices with a clear outcome

Every request is a vertical slice that ends in observable behavior. Before
writing code, state the slice's outcome in one sentence — what a user can see
or do when it lands that they couldn't before. No model-only or transport-only
work unless the request is explicitly scoped that way. Keep the first pass of
anything minimal; add the next capability in the next slice.

### TDD — red first, then green, behavior-driven

Write the tests before the implementation, and run them and observe them
**fail** before implementing. Then implement until green and re-run the suite.
Never write the implementation first and backfill tests; never claim green
without showing the run.

Tests are **behavior-driven, not method-driven**: each test states one
behavior observable through a module's public interface (`Simulation.tick()`,
`Simulation.state()`, and the interfaces later slices add), and is named for
that behavior (`test_low_safety_reads_as_fear`), not for the method it calls.
Cover behavior end-to-end through the public surface; don't unit-test private
helpers or assert on internal state — wanting to is a sign the module is the
wrong shape.

Mock **only at the seams** — the injected ports and module boundaries
(config, and later the clock, repositories, predictor). Prefer real
collaborators below the seam and fakes with behavior over call-sequence mocks.
If a behavior can't be tested without a new fake, a seam is probably missing —
add the port (an ADR-worthy change), don't patch.

Practicalities:
- Tests live in `engine/tests/` and use **pytest**.
- Run: `cd engine && python -m pytest`

### Deep modules

A lot of behavior behind a small interface. Each module exposes one public
class or small function set (`Simulation`, `ConfigService`, the services) and
hides its logic behind it; the interface is the test surface. Prefer deepening
an existing module over adding a new one. Apply the deletion test before adding
a module (if deleting it would make complexity vanish rather than reappear in
callers, it's a pass-through — don't add it). **Do not introduce a seam until
something actually varies across it** — one implementation means no port yet.

### Deep-module review after every slice

After each slice reaches green — and **before** the slice is called done or
moved to review — run the `/legacy-deep-module-review` skill over the change.
This is a required per-slice gate, not an optional cleanup: it maps the touched
modules and dependencies, flags shallow modules and coupling hotspots, and
proposes deeper aggregations before drift accumulates. Record what it finds and
act on it in the same slice (fold small fixes in; an interface-level change
becomes an ADR and, if larger, its own next slice — never silently deferred).
Sub-agents include the review outcome in their vertical-slice completion report;
the orchestrator does not treat a card as review-ready until it has run.

### Domain-model update after every slice

After each slice reaches green — alongside the deep-module review — keep the
project's **ubiquitous language** current. Apply the `domain-modeling` skill: add
or sharpen the root `CONTEXT.md` glossary for any domain terms the slice
introduced or changed, in the skill's CONTEXT format (what a term *is*, plus
`_Avoid_` synonyms — a pure glossary, no implementation detail). Create
`CONTEXT.md` lazily if it is absent. Record an ADR only when the skill's 3-part
test holds (hard to reverse · surprising without context · a real trade-off). If
a term genuinely needs the director's judgment, surface it in the completion
report rather than block; sub-agents note the domain-model outcome there.

### Config-driven tuning

Drift rates, thresholds, timings, and vocabularies live in `config/*.yaml`, not
in service code. `ConfigService` is the only code that knows config exists; it
hands services typed policies. Retuning must be a config change only.

### Documentation

- `docs/adr/NNNN-slug.md` for every architecturally significant decision
  (**Status / Date / Context / Decision / Consequences**), indexed in
  `docs/adr/README.md`. Never rewrite an accepted ADR — supersede it.
- Any slice that adds or changes an interface adds/updates the relevant ADR in
  the same slice, not as a follow-up.
- One source of truth per fact: the roadmap lives in `README.md`; the brief in
  `docs/BRIEF.md`. Link, don't restate.
- **Governance is indexed in `README.md`.** When you add or change a rule, hook,
  guardrail, or sub-agent convention in `CLAUDE.md`, add/update its row in the
  "How we work (governance index)" table in `README.md` **in the same change** —
  one row: what it is, why, and what it does.

### Security & operational guardrails

Security is a foundation the engine carries from the start, not a later slice.
See [`docs/adr/0005-api-authentication.md`](docs/adr/0005-api-authentication.md).

- **Secrets are never committed.** Real secrets and keys live in an untracked
  `.env` (and `*.pem`/`*.key`), never in the repo; only `.env.example` with
  placeholders is committed. The `pre-commit` hook backs this with a conservative
  scan that blocks a staged `.env`, `*.pem`/`*.key`, or a PEM/AWS-key literal —
  it does **not** flag generic `SECRET=`/entropy (kept low-noise on purpose).
- **API auth is always-on JWT, config-gated, and tested.** Every protected route
  (`GET /state`, and player commands as they land) runs the `require_auth`
  dependency; `/ws` verifies a handshake token; `GET /health` is public. Auth is
  always in the code path and gated only by the `AUTH_REQUIRED` flag — **there is
  no localhost/loopback bypass**. The behaviour (public health, 401 without/with
  a bad token, 200 with a valid one, WS reject/accept) is covered by tests.
- **Local dev uses the same path.** Run with `AUTH_REQUIRED=true` and a
  `JWT_SECRET`, and mint a service token with `make token` (`python -m
  app.auth_token`) to call the API — dev exercises the real guard, not a bypass.
  Setting `AUTH_REQUIRED=false` is an explicit, documented dev-only no-op.

## Parallel execution — git worktrees and wave PRs

**Never commit to `main` directly.** All work — feature slices, chores, docs,
even edits to these rules — happens in a git worktree on a branch and reaches
`main` only through a reviewed PR. This is enforced: a `pre-commit` hook
(`.githooks/pre-commit`, installed by `make setup` via `core.hooksPath`) rejects
any commit made on `main`, so `main` only ever advances by merging a PR. A
worktree is cheap — create one even for a one-line change:
`git worktree add .claude/worktrees/<name> -b <branch> main`.

When several slices are worked at once (a "wave"), each slice runs in its **own
git worktree** so agents never share a working tree:

- **One integration branch per wave:** `wave/<n>`, branched from `main`.
- **One worktree + branch per slice:** `slice/<ticket>` (e.g. `slice/v0-2`),
  branched from the wave branch and checked out under
  `.claude/worktrees/<ticket>/` (gitignored). A sub-agent works **only** inside
  its own worktree — never the main tree or another slice's.
- **Commit per slice, inside its worktree.** The suite runs and stays green in
  the worktree (`cd <worktree>/engine && python -m pytest`).
- **Roll a whole wave up into one PR.** When every slice in the wave is merged
  into `wave/<n>`, open a single PR `wave/<n>` → `main`. Wave 1 is one PR, wave 2
  another, and so on — a human reviews and merges it, and that merge is the
  cards' `Done`.
- **Orchestrator owns git and the board; sub-agents own code.** Sub-agents
  commit inside their worktree and report back; they never push, merge, open
  PRs, or write to Trello. The orchestrator merges slice branches into the wave
  branch, opens the wave PR, and mirrors state to the board.
- **A sub-agent may escalate to a workflow.** When a slice is large enough to
  warrant decomposition (many independent files, a fan-out-then-verify shape), a
  sub-agent may spawn a workflow or its own helper agents to complete it. The
  slice's contract still holds: all work stays inside that slice's worktree;
  nested agents must not write the same files concurrently (partition the files
  or serialize); the slice still lands as commits on its `slice/<ticket>` branch;
  and the sub-agent still returns one completion report. Keep the fan-out
  proportional — a small slice needs no workflow.

### Bugs found during a wave — ticket, hotfix, merge back into the PR

**Intent: the codebase is self-diagnosing and self-healing.** Continuous
verification (the suite, the deep-module gate, integration/Docker checks) is what
*finds* defects; each becomes a bug ticket; each ticket is assigned to a
sub-agent that *heals* it; the fix is verified and merged back — a closed loop
that needs no human hop within an already-authorized wave. The invariant it
serves: **the open wave PR is always pristine — green, verified, and safe for a
human to merge to `main` at any moment.**

So when verification or review turns up a defect in work that is already in
review or in an open wave PR, it does **not** get quietly patched — it goes
through the ticket system:

1. **Document a bug ticket** on the board (the repo's ticket system — see *Task
   source* below), carrying: symptom, how to reproduce, root cause if known,
   affected files, severity, and a link to the PR/commit. The orchestrator
   creates the card (sub-agents never write to the board). A bug in an in-flight
   wave inherits that wave's authorization, so the orchestrator may claim and
   assign it immediately rather than waiting for a human to stage it.
2. **Assign it to a sub-agent** to fix, on a `hotfix/<ticket>` branch in its own
   worktree, branched from the wave branch. Capture the defect with a red test
   first where one can; fix to green; run the deep-module-review gate; return a
   completion report — same contract as any slice.
3. **Verify, then merge back into the PR.** The orchestrator re-runs the failing
   check, confirms it now passes, merges `hotfix/<ticket>` into the wave branch
   (which updates the open PR in place), and moves the bug card to review. If the
   wave PR has already merged to `main`, the fix instead becomes its own ticket →
   `hotfix/<ticket>` PR to `main` (or rolls into the next wave). **Pristine-PR
   invariant:** nothing merges into the wave branch unless its suite is green and
   its outcome verified — the PR never sits red; a change that would break it is
   blocked and re-ticketed, not merged.
4. **Message the director** when a bug is found and again when its hotfix merges
   — the same milestone cadence used for slice completion and wave-PR roll-up.

### Closing a wave (after its PR merges to `main`)

When a human accepts and merges a wave's PR, the orchestrator closes it out —
verify first, then tidy — and reports the result:

1. **Sync `main`** — `git pull` so local `main` matches the merged remote.
2. **Verify the merged tree** — run the full suite (`make test`) and a runtime
   smoke (the demo, plus the Docker stack when a daemon is available); it must be
   green with no errors.
3. **If anything fails, run the self-healing loop above** (bug ticket →
   `hotfix/<ticket>` → verify). The wave PR is already closed, so the fix lands
   as its own PR to `main`. Do not tidy until green.
4. **Only when green, tidy git** — remove the wave's worktrees and delete the
   merged `slice/*` and `wave/<n>` branches (local and remote). Never delete an
   unmerged branch.
5. **Reflect the board** — move the wave's cards to `done` (the human's merge is
   the Done authorization).
6. **Report to the director** — synced + verified + cleaned, or, if a defect
   surfaced, the bug-ticket link and hotfix status. Report faithfully (show the
   test result).

This is triggered by a human merging the PR — an event the harness cannot see —
so it is an orchestrator procedure, not a hook.

## Task source — the NPC Trello board (guardrails)

Development work may be sourced from the Trello board **NPC** (short link
`qBaiErHa`, `https://trello.com/b/qBaiErHa/npc`). When using the board:

- **Official Trello MCP only.** Read or write the board solely through the
  `trello` MCP server's tools. Never substitute another server (the Atlassian
  MCP is Jira/Confluence, not Trello) or raw HTTP/curl. If `trello` is not
  connected, stop and say exactly what's missing — never fabricate board state.
- **Read-first, least privilege.** Verification and triage are read-only. Never
  create, move, archive, or delete cards while verifying. Writes happen only in
  an explicitly-invoked update flow, never as a side effect of reading.
- **Pull only from the intake list.** Agents take work only from the single
  designated `Ready for Agent` list — never scan the whole board for things to
  do. A human moving a card into that list is the authorization to work it.
- **Card → slice contract.** Only work a card that carries a one-sentence
  outcome, acceptance criteria, and links to the relevant files/ADRs (the slice
  discipline above). A card missing a useful description is flagged back to a
  human, not started.
- **Claim before working.** Add a `claimed-by:<session>` marker and check no
  other claim exists before starting, so parallel agents don't grab the same
  card. Release the claim on failure.
- **Writes are gated and mirrored.** An agent may comment progress and move a
  card at most one adjacent state (`In Progress` → `Review`). It never archives
  or deletes; a human performs `Done`/archive. Every board write references the
  git commit/PR so board and code stay reconcilable.
- **Blocked/overdue are hard stops.** Refuse to start a card labeled blocked or
  past its due date; surface it in a triage report instead of working around it.
- **Done means verified.** A card is review-ready only when the suite is green
  (`cd engine && python -m pytest`) and the slice's observable outcome has been
  demonstrated — never on assertion alone.
- **Board = intent, repo = truth.** The board says what to do and in what order;
  the code, tests, ADRs, and `README.md` roadmap remain the authoritative
  record. Design detail belongs in an ADR, not on a card.

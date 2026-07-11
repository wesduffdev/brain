# 0034 — Subject queries answered from learned concepts (`/ask` subject path)

## Status

Accepted (extends [0032](0032-self-report-narration-surface.md) /
[0033](0033-config-selected-narrator-provider-with-template-fallback.md); grounded
by [0019](0019-object-concepts-and-belief-formation.md) /
[0021](0021-graph-like-concept-network.md) / [0002](0002-perceived-vs-true-world.md),
on the [0022](0022-natural-language-layer-and-language-model-port.md) language
seam, gated by [0005](0005-api-authentication.md))

## Date

2026-07-11

## Context

ADR 0032 landed the self-report surface (`POST /ask`) and the deterministic
narrator, and explicitly **deferred subject queries** — "what do you know / how
do you feel about X?" — to a later slice (the self-narration plan,
`docs/SELF_NARRATION.md`, S3). That is this slice.

The being already learns richly: concept schemas keyed on a PERCEIVED property
(ADR 0019), a concept graph whose explanation paths justify a prediction (ADR
0021), the per-object beliefs those concepts form, and the emotions its memories
record. But it had no way to be *asked about* any of it. Two forces shape how it
should answer. First, ADR 0002 — the being knows objects by what it PERCEIVES,
never by a human name; so a subject query cannot be answered by matching an
English label, and the answer must never leak a `developerLabel` or object id.
Second, ADR 0022's grounding rule — language sits on top and may only say what the
being has lived; a subject the being has never encountered must be declined
honestly, not confabulated.

## Decision

**A subject resolver maps the question's subject to PERCEIVED-property tokens.**
`SubjectResolver` reads the subject phrase ("hot things", "the round red thing")
and returns the perceived-property tokens it contains (`["hot"]`,
`["round", "red"]`), drawn from the perceived-property vocabulary
(`config/object_properties.yaml`) plus the being's already-learned concept
features. Resolution is deliberately **vocabulary-bounded**: it maps only to
tokens the being could actually perceive, so a term with no perceptual handle
("dragons") resolves to nothing. Whether the being has *learned* anything about a
resolved property is a separate question — resolving to a valid property it has
never encountered ("square things") still yields an honest "I don't know", never a
borrowed lesson.

**A `SubjectReportService` gathers the learned facts and hands them to the
narrator.** For the resolved properties it gathers, keyed on `(property, outcome)`:
the concept schemas (a perceived feature + action → an outcome, with a
confidence), the graph explanations that corroborate a property → outcome
prediction (and map each object to the properties it shows), the per-object
beliefs that bear on those objects, and the FELT emotion its memories recorded of
things bearing the property. It serializes these into the SAME fact-line grammar
the other narration services use — each line marked `kind=subject` — and hands
them to the config-selected narrator (ADR 0033): the deterministic template
renders them offline, and a real model (S2) reads the same facts under "use only
these facts; do not invent". **No new port** — the one `LanguageModelPort` seam is
reused.

**An unknown subject is answered deterministically, model-free.** When no learned
fact is gathered — whether the subject resolved to no perceived property, or to a
real one never encountered — the service returns the config-driven honest
no-knowledge line WITHOUT ever calling a model, so there is no surface on which a
model could invent a lesson the being has not lived.

**Routing lives in `SelfReportService`; the recent-experience path is untouched.**
`report()` now also accepts the being's `concepts` / `beliefs` / `explanations`
read-backs. A question carrying a `query_markers` connective ("...**about** hot
things") is routed to the subject path; every other question stays on the S1
recent-experience report. `POST /ask` passes the cognitive read-backs (guarded, so
a being without those seams degrades rather than errors).

**The voice and the routing vocabulary are config, not code.** A `subject:` block
in `config/language.yaml` (surfaced as `SubjectQueryPolicy`) holds the query
markers, the max facts an answer cites, and the honest unknown-subject phrasing
(with a `{subject}` slot). Retuning how the being fields a subject — and how it
declines an unknown one — is a YAML change only.

## Consequences

- **The being can be asked what it knows.** `/ask "what do you know about hot
  things?"` → *"When I touched a hot thing, it hurt me and it frightened me —
  afterwards I felt very scared."* — built entirely from its learned concepts,
  graph explanations, and the emotion its memory recorded.
- **Grounded by construction, honest about the unknown.** Every clause traces to a
  learned fact keyed on a perceived property; an unencountered subject is declined
  honestly and never reaches a model. Resolving to perceived properties (never a
  name) preserves ADR 0002 at the cost that a subject the being has no perceptual
  token for simply cannot be asked — the intended trade-off.
- **Fluency remains a later upgrade.** The subject fact-lines cross the same seam
  as every other narration; flipping the narrator to a model (S2) changes only
  phrasing, because the model only ever sees the gathered facts.
- **Read-only, on top of the sim (ADR 0022).** Asking about a subject reads
  snapshot dicts and mutates neither the being nor its log.

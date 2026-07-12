"""ReactionResponseService — the being's ACTIVE response to an instinct reaction
(INS-ACT, ADR 0029).

This is the active counterpart to `InstinctService`'s shadow inference (INS-RT).
It subscribes to `being.instinct.reactions` and turns a TRIGGERED protective
reaction (a label + a scalar intensity; the threshold gating already happened
upstream) into two staged, config-gated effects on the being:

- **Emotion bias (`visual_only`)** — the reaction feeds a TRANSIENT affect signal
  into the being's needs->emotion *derivation* (`bias_needs`): a flinch nudges
  the felt safety used for derivation down, so the being reads as `scared` — the
  emotion is DERIVED, never assigned, and the stored needs are untouched. The
  reaction is also SURFACED in the being's state (`active_reaction`) as the render
  contract RENDER-RX consumes.
- **Action interruption (`allow_interrupt`)** — a reaction at or above the policy
  `intensity_threshold` may CANCEL an interruptible current action (`interrupts`).
  The decision is validated through the injected `SafetyService`: instinct only
  proposes; the invariant floor disposes. An interruption whose protective
  response the floor forbids is SUPPRESSED, not forced.

Lifecycle: reactions arrive on the bus BETWEEN ticks; `begin_tick` latches the
most recent one as the reaction in effect for the current tick, and a tick with
no new reaction clears it (a reaction lingers exactly one tick, then fades). Both
flags default OFF, in which case the service is inert — no bias, no interruption,
no `reaction` field — so behavior is byte-identical to the pre-INS-ACT being and
activation is purely a config flip.

The `EmotionBiasApplied` (state topic) and `ActionInterrupted` (action topic)
events are DURABLE: rather than publishing them straight to the bus, a triggered
reaction STAGES each into the transactional outbox (ADR 0028) inside the tick's
unit of work (ADR 0017); the relay publishes it and projects it into the idempotent
event log — atomic with the tick's writes, no dual-write (REACTION-EVENTS-PERSIST,
ADR 0042, superseding ADR 0029's transient decision).
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from app.domain.event import DomainEvent
from app.domain.outbox import OutboxEntry
from app.policies import ReactionResponsePolicy
from app.ports.events import EventConsumer
from app.ports.repositories import OutboxRepository
from app.services.instinct_service import INSTINCT_REACTIONS_TOPIC, REACTION_TRIGGERED
from app.services.safety_service import SafetyService

# The being.* topics this service stages events onto (EVT-KAFKA catalogue, ADR 0024:
# `action` carries ActionStarted/ActionInterrupted, `state` carries the durable
# brain-state changes NeedChanged/EmotionBiasApplied) and the event types it emits.
STATE_EVENTS_TOPIC = "being.state.events"
ACTION_EVENTS_TOPIC = "being.action.events"
EMOTION_BIAS_APPLIED = "being.state.emotion_bias_applied"
ACTION_INTERRUPTED = "being.action.interrupted"

_SOURCE_SERVICE = "reaction-response-service"
_NEED_FLOOR, _NEED_CEIL = 0, 100


class _ActiveReaction:
    """One triggered reaction in effect for a tick: its label, its scalar intensity,
    and the source event it rode in on (so caused events keep the correlation chain)."""

    __slots__ = ("label", "intensity", "event")

    def __init__(self, label: str, intensity: float, event: DomainEvent) -> None:
        self.label = label
        self.intensity = intensity
        self.event = event


class ReactionResponseService:
    def __init__(
        self,
        policy: ReactionResponsePolicy,
        safety: SafetyService,
        being_id: str,
        *,
        consumer: Optional[EventConsumer] = None,
        outbox: Optional[OutboxRepository] = None,
    ) -> None:
        self._policy = policy
        self._safety = safety
        self._being_id = being_id
        self._outbox = outbox
        # Reactions arrive between ticks; `_incoming` is the latest not-yet-latched
        # one, `_active` the one in effect for the tick currently being processed.
        self._incoming: Optional[_ActiveReaction] = None
        self._active: Optional[_ActiveReaction] = None
        if consumer is not None:
            consumer.subscribe(INSTINCT_REACTIONS_TOPIC, self._on_reaction)

    # --- bus intake -------------------------------------------------------

    def _on_reaction(self, event: DomainEvent) -> None:
        """Record the latest TRIGGERED reaction. A suppressed reaction (or any other
        event on the topic) is ignored — the being acts only on reactions that fired
        (the threshold gating happened upstream, INS-RT)."""
        if event.event_type != REACTION_TRIGGERED:
            return
        payload = event.payload
        if not payload.get("triggered", False):
            return
        self._incoming = _ActiveReaction(
            label=str(payload["reaction"]),
            intensity=float(payload["intensity"]),
            event=event,
        )

    # --- per-tick lifecycle ----------------------------------------------

    def begin_tick(self, tick: int) -> None:
        """Latch the reaction received since the last tick as the one in effect for
        THIS tick; a tick with no new reaction clears it (fade). When `visual_only`
        is on and a reaction is active, stage the bias as an `EmotionBiasApplied`
        state event (durable via the outbox, ADR 0042)."""
        self._active = self._incoming
        self._incoming = None
        if self._active is not None and self._policy.visual_only:
            self._stage(
                STATE_EVENTS_TOPIC,
                EMOTION_BIAS_APPLIED,
                {"reaction": self._active.label, "intensity": self._active.intensity, "tick": tick},
            )

    # --- emotion bias (via DERIVATION, never assignment) ------------------

    def bias_needs(self, needs: Mapping[str, int]) -> Mapping[str, int]:
        """The needs the being's emotion is DERIVED from this tick, overlaid with the
        active reaction's transient affect signal (clamped to the need scale). The
        stored needs are never mutated — only this derivation input is nudged, so a
        flinch reads as `scared` through the ordinary emotion rules. Returns `needs`
        unchanged when `visual_only` is off, no reaction is active, or the label
        carries no bias — the byte-identical default."""
        if self._active is None or not self._policy.visual_only:
            return needs
        bias = self._policy.bias_for(self._active.label)
        if not bias:
            return needs
        biased = dict(needs)
        for need, delta in bias.items():
            nudged = int(biased.get(need, 0)) + int(delta)
            biased[need] = max(_NEED_FLOOR, min(_NEED_CEIL, nudged))
        return biased

    # --- render contract --------------------------------------------------

    def active_reaction(self) -> Optional[dict]:
        """The `{type, intensity}` render contract for the active reaction (the field
        RENDER-RX consumes), or None when nothing is active or neither activation
        step is on — so the `reaction` field is absent in the byte-identical default."""
        if self._active is None or not self._policy.surfaces_reaction:
            return None
        return {"type": self._active.label, "intensity": self._active.intensity}

    # --- action interruption (instinct proposes, SAFETY disposes) ---------

    def interrupt(self, *, action: str, target_id: str, target_properties: Sequence[str], tick: int) -> bool:
        """Break off `action` on `target_id` if the active reaction warrants it, and
        report whether it did — a single command the caller acts on, so it can never
        announce an interruption it did not take. The reaction interrupts only when
        `allow_interrupt` is on, a reaction is active at or above `intensity_threshold`,
        the action is interruptible, AND the SafetyService permits the protective
        response on the target: the invariant floor is never bypassed, so a
        floor-forbidden break-off is SUPPRESSED (returns False), not forced. On a
        genuine interruption it stages an `ActionInterrupted` action event (durable
        via the outbox, ADR 0042) and returns True; otherwise returns False and stays
        silent."""
        if not self._should_interrupt(action=action, target_properties=target_properties):
            return False
        self._stage(
            ACTION_EVENTS_TOPIC,
            ACTION_INTERRUPTED,
            {
                "action": action,
                "targetId": target_id,
                "reaction": self._active.label,
                "intensity": self._active.intensity,
                "tick": tick,
            },
        )
        return True

    def _should_interrupt(self, *, action: str, target_properties: Sequence[str]) -> bool:
        if not self._policy.allow_interrupt or self._active is None:
            return False
        if self._active.intensity < self._policy.intensity_threshold:
            return False
        if not self._policy.is_interruptible(action):
            return False
        blocked = self._safety.block_reason(self._policy.protective_action, target_properties)
        return blocked is None

    # --- staging (transactional outbox, ADR 0028/0042) --------------------

    def _stage(self, topic: str, event_type: str, payload: Mapping[str, Any]) -> None:
        """Stage a reaction event into the transactional outbox rather than
        publishing it directly (ADR 0028/0042): it commits with the tick's unit of
        work, and the relay publishes + projects it into the idempotent event log. A
        caused event keeps the reaction's correlation chain. A no-op when no outbox is
        wired — the byte-identical default, exactly as with no publisher before."""
        if self._outbox is None:
            return
        source = self._active.event if self._active is not None else None
        if source is not None:
            event = source.causes(
                event_type=event_type, source_service=_SOURCE_SERVICE, payload=payload
            )
        else:
            event = DomainEvent.create(
                event_type=event_type,
                event_version=1,
                source_service=_SOURCE_SERVICE,
                being_id=self._being_id,
                payload=payload,
            )
        self._outbox.add(OutboxEntry(topic=topic, event=event))

"""DomainEvent — the versioned envelope every domain event travels in (ADR 0024).

A domain event is a *fact*: something the being's world produced that other
services react to — `being.perception.object_approached`,
`being.instinct.prediction_made`, and the rest of the `being.*` catalogue. This
envelope is the one shape they all share (queue §"Event Schema Requirements"): a
stable identity, a versioned type, when it happened and when it was produced, who
produced it, which being it concerns, the correlation/causation ids that let a
whole chain be traced, and a free-form `payload`.

The envelope validates itself **loudly** on construction: a malformed event
(empty type, non-positive version, naive timestamp, non-mapping payload, ...)
raises rather than being carried silently onward — the same discipline a Kafka
consumer will need when it rebuilds an event off the wire (`from_snapshot`). This
keeps the module deep: producers say only what an event *is* via `create`/`causes`
and never assemble a raw, unchecked envelope.

Correlation vs. causation: a **root** event (`create`) heads its own trace — its
`correlation_id` is its own id and nothing caused it (`causation_id` is `None`). A
**downstream** event (`prior.causes(...)`) inherits the same `correlation_id` and
records the id of the event that caused it, so `A -> B -> C` is one traceable
chain. No broker, no torch, no database is imported here — the envelope is pure.
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_REQUIRED_TEXT_FIELDS = (
    "event_id",
    "event_type",
    "source_service",
    "being_id",
    "correlation_id",
)
_REQUIRED_SNAPSHOT_KEYS = (
    "eventId",
    "eventType",
    "eventVersion",
    "occurredAt",
    "producedAt",
    "sourceService",
    "beingId",
    "correlationId",
    "payload",
)


def _new_id() -> str:
    return str(uuid.uuid4())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


@dataclass(frozen=True)
class DomainEvent:
    """One validated, versioned domain-event envelope (see module docstring)."""

    event_id: str
    event_type: str
    event_version: int
    occurred_at: datetime
    produced_at: datetime
    source_service: str
    being_id: str
    correlation_id: str
    causation_id: Optional[str]
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        errors = []
        for name in _REQUIRED_TEXT_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{name} must be a non-empty string (got {value!r})")
        if (
            isinstance(self.event_version, bool)
            or not isinstance(self.event_version, int)
            or self.event_version < 1
        ):
            errors.append(f"event_version must be an int >= 1 (got {self.event_version!r})")
        for name in ("occurred_at", "produced_at"):
            value = getattr(self, name)
            if not isinstance(value, datetime):
                errors.append(f"{name} must be a datetime (got {value!r})")
            elif value.tzinfo is None:
                errors.append(f"{name} must be timezone-aware (got a naive datetime)")
        if self.causation_id is not None and (
            not isinstance(self.causation_id, str) or not self.causation_id.strip()
        ):
            errors.append(
                f"causation_id must be None or a non-empty string (got {self.causation_id!r})"
            )
        if not isinstance(self.payload, Mapping):
            errors.append(f"payload must be a mapping (got {type(self.payload).__name__})")
        if errors:
            raise ValueError("malformed DomainEvent: " + "; ".join(errors))
        # Freeze a defensive copy so a caller mutating the dict it passed in can
        # never reach an already-delivered event.
        object.__setattr__(self, "payload", dict(self.payload))

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        event_version: int,
        source_service: str,
        being_id: str,
        payload: Mapping[str, Any],
        event_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        occurred_at: Optional[datetime] = None,
        produced_at: Optional[datetime] = None,
    ) -> "DomainEvent":
        """A **root** event that heads its own correlation chain.

        Ids and timestamps are generated when not supplied (supplying them keeps
        a test deterministic). `correlation_id` defaults to the event's own id;
        `causation_id` is `None` because nothing caused a root event.
        """
        resolved_id = event_id or _new_id()
        occurred = occurred_at or _utc_now()
        return cls(
            event_id=resolved_id,
            event_type=event_type,
            event_version=event_version,
            occurred_at=occurred,
            produced_at=produced_at or occurred,
            source_service=source_service,
            being_id=being_id,
            correlation_id=correlation_id or resolved_id,
            causation_id=None,
            payload=payload,
        )

    def causes(
        self,
        *,
        event_type: str,
        source_service: str,
        payload: Mapping[str, Any],
        event_version: int = 1,
        being_id: Optional[str] = None,
        event_id: Optional[str] = None,
        occurred_at: Optional[datetime] = None,
        produced_at: Optional[datetime] = None,
    ) -> "DomainEvent":
        """A **downstream** event caused by this one — same correlation chain.

        The new event inherits this event's `correlation_id` and records this
        event's id as its `causation_id`, so `A.causes(B)` makes `B` traceable
        back to `A`. The being carries through unless overridden.
        """
        resolved_id = event_id or _new_id()
        occurred = occurred_at or _utc_now()
        return DomainEvent(
            event_id=resolved_id,
            event_type=event_type,
            event_version=event_version,
            occurred_at=occurred,
            produced_at=produced_at or occurred,
            source_service=source_service,
            being_id=being_id or self.being_id,
            correlation_id=self.correlation_id,
            causation_id=self.event_id,
            payload=payload,
        )

    def snapshot(self) -> Dict[str, Any]:
        """A plain, JSON-serializable view using the stable camelCase keys the
        wire and, later, Kafka use — timestamps as ISO-8601 strings."""
        return {
            "eventId": self.event_id,
            "eventType": self.event_type,
            "eventVersion": self.event_version,
            "occurredAt": self.occurred_at.isoformat(),
            "producedAt": self.produced_at.isoformat(),
            "sourceService": self.source_service,
            "beingId": self.being_id,
            "correlationId": self.correlation_id,
            "causationId": self.causation_id,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any]) -> "DomainEvent":
        """Rebuild an envelope from its `snapshot()` form, **re-validating** it.

        This is how a consumer reconstructs an event off the wire; a snapshot
        that has lost a required field or carries a bad timestamp is rejected
        loudly rather than producing a half-built event.
        """
        if not isinstance(snapshot, Mapping):
            raise ValueError(
                f"event snapshot must be a mapping (got {type(snapshot).__name__})"
            )
        missing = [key for key in _REQUIRED_SNAPSHOT_KEYS if key not in snapshot]
        if missing:
            raise ValueError(
                "event snapshot missing required field(s): " + ", ".join(missing)
            )
        try:
            occurred_at = _parse_timestamp(snapshot["occurredAt"])
            produced_at = _parse_timestamp(snapshot["producedAt"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"event snapshot has an invalid timestamp: {exc}") from exc
        return cls(
            event_id=snapshot["eventId"],
            event_type=snapshot["eventType"],
            event_version=snapshot["eventVersion"],
            occurred_at=occurred_at,
            produced_at=produced_at,
            source_service=snapshot["sourceService"],
            being_id=snapshot["beingId"],
            correlation_id=snapshot["correlationId"],
            causation_id=snapshot.get("causationId"),
            payload=snapshot["payload"],
        )

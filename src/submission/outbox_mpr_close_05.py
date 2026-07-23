"""MPR-CLOSE-05 durable submission outbox state machine.

The outbox models the minimum live-canary submission lifecycle.  A submission
intent must be recorded before any transport call.  Transport acknowledgement is
never terminal; only explicit landed/confirmed/finalized/rejected/expired states
can finish an attempt, and terminal states are immutable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
import os
import time
from pathlib import Path

_SHA256_RE = set("0123456789abcdef")


class SubmissionOutboxState(StrEnum):
    INTENT_CREATED = "submission_intent_created"
    SIGNED = "signed_by_isolated_signer"
    SUBMITTED = "submitted_to_transport"
    LANDED = "landed"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"
    REJECTED = "rejected"
    EXPIRED = "expired"


TERMINAL_STATES = frozenset(
    {
        SubmissionOutboxState.FINALIZED,
        SubmissionOutboxState.REJECTED,
        SubmissionOutboxState.EXPIRED,
    }
)

_ALLOWED_TRANSITIONS: dict[SubmissionOutboxState, frozenset[SubmissionOutboxState]] = {
    SubmissionOutboxState.INTENT_CREATED: frozenset({SubmissionOutboxState.SIGNED}),
    SubmissionOutboxState.SIGNED: frozenset({SubmissionOutboxState.SUBMITTED}),
    SubmissionOutboxState.SUBMITTED: frozenset(
        {
            SubmissionOutboxState.LANDED,
            SubmissionOutboxState.REJECTED,
            SubmissionOutboxState.EXPIRED,
        }
    ),
    SubmissionOutboxState.LANDED: frozenset(
        {SubmissionOutboxState.CONFIRMED, SubmissionOutboxState.REJECTED}
    ),
    SubmissionOutboxState.CONFIRMED: frozenset(
        {SubmissionOutboxState.FINALIZED, SubmissionOutboxState.REJECTED}
    ),
    SubmissionOutboxState.FINALIZED: frozenset(),
    SubmissionOutboxState.REJECTED: frozenset(),
    SubmissionOutboxState.EXPIRED: frozenset(),
}


class SubmissionOutboxError(ValueError):
    """Raised when the outbox would violate monotonic submission semantics."""


@dataclass(frozen=True, slots=True)
class SubmissionIntent:
    attempt_id: str
    opportunity_id: str
    message_sha256: str
    exact_simulation_hash: str
    reservation_hash: str
    signer_receipt_hash: str | None
    created_at_ns: int

    def __post_init__(self) -> None:
        _require_text(self.attempt_id, "attempt_id")
        _require_text(self.opportunity_id, "opportunity_id")
        for field_name in (
            "message_sha256",
            "exact_simulation_hash",
            "reservation_hash",
        ):
            _require_hash(getattr(self, field_name), field_name)
        if self.signer_receipt_hash is not None:
            _require_hash(self.signer_receipt_hash, "signer_receipt_hash")
        if self.message_sha256 != self.exact_simulation_hash:
            raise SubmissionOutboxError(
                "submission intent must bind the same hash as exact simulation"
            )
        if self.created_at_ns < 0:
            raise SubmissionOutboxError("created_at_ns must be non-negative")

    @property
    def intent_hash(self) -> str:
        return _hash_json(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "mpr-close-05.submission-intent.v1",
            "attempt_id": self.attempt_id,
            "opportunity_id": self.opportunity_id,
            "message_sha256": self.message_sha256,
            "exact_simulation_hash": self.exact_simulation_hash,
            "reservation_hash": self.reservation_hash,
            "signer_receipt_hash": self.signer_receipt_hash,
            "created_at_ns": self.created_at_ns,
        }


@dataclass(frozen=True, slots=True)
class SubmissionOutboxEvent:
    attempt_id: str
    state: SubmissionOutboxState
    intent_hash: str
    observed_at_ns: int
    detail_hash: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.attempt_id, "attempt_id")
        _require_hash(self.intent_hash, "intent_hash")
        if self.detail_hash is not None:
            _require_hash(self.detail_hash, "detail_hash")
        if self.observed_at_ns < 0:
            raise SubmissionOutboxError("observed_at_ns must be non-negative")

    @property
    def event_hash(self) -> str:
        return _hash_json(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "mpr-close-05.submission-outbox-event.v1",
            "attempt_id": self.attempt_id,
            "state": self.state.value,
            "intent_hash": self.intent_hash,
            "observed_at_ns": self.observed_at_ns,
            "detail_hash": self.detail_hash,
        }


@dataclass(slots=True)
class DurableSubmissionOutbox:
    """Small durable JSONL outbox for signer/Jito canary attempts."""

    journal_path: Path | None = None
    clock_ns: Callable[[], int] = time.time_ns
    _intents: dict[str, SubmissionIntent] = field(default_factory=dict)
    _events: dict[str, list[SubmissionOutboxEvent]] = field(default_factory=dict)

    def create_intent(
        self,
        *,
        attempt_id: str,
        opportunity_id: str,
        message_sha256: str,
        exact_simulation_hash: str,
        reservation_hash: str,
        signer_receipt_hash: str | None = None,
    ) -> SubmissionIntent:
        if attempt_id in self._intents:
            raise SubmissionOutboxError("submission attempt already has an intent")
        intent = SubmissionIntent(
            attempt_id=attempt_id,
            opportunity_id=opportunity_id,
            message_sha256=message_sha256,
            exact_simulation_hash=exact_simulation_hash,
            reservation_hash=reservation_hash,
            signer_receipt_hash=signer_receipt_hash,
            created_at_ns=int(self.clock_ns()),
        )
        event = SubmissionOutboxEvent(
            attempt_id=attempt_id,
            state=SubmissionOutboxState.INTENT_CREATED,
            intent_hash=intent.intent_hash,
            observed_at_ns=int(self.clock_ns()),
        )
        self._append(intent, event)
        return intent

    def advance(
        self,
        attempt_id: str,
        next_state: SubmissionOutboxState,
        *,
        detail_hash: str | None = None,
    ) -> SubmissionOutboxEvent:
        intent = self._intents.get(attempt_id)
        if intent is None:
            raise SubmissionOutboxError("submission intent must exist before advancing")
        history = self._events.get(attempt_id, ())
        if not history:
            raise SubmissionOutboxError("submission history is missing intent event")
        current = history[-1].state
        if current in TERMINAL_STATES:
            raise SubmissionOutboxError("terminal submission state is immutable")
        if next_state not in _ALLOWED_TRANSITIONS[current]:
            raise SubmissionOutboxError(
                f"invalid submission transition: {current.value} -> {next_state.value}"
            )
        event = SubmissionOutboxEvent(
            attempt_id=attempt_id,
            state=next_state,
            intent_hash=intent.intent_hash,
            observed_at_ns=int(self.clock_ns()),
            detail_hash=detail_hash,
        )
        self._append(intent, event)
        return event

    def record_transport_ack(self, attempt_id: str, *, ack_hash: str) -> SubmissionOutboxEvent:
        """Record a transport ACK as submitted, never as settlement."""

        return self.advance(
            attempt_id,
            SubmissionOutboxState.SUBMITTED,
            detail_hash=ack_hash,
        )

    def state(self, attempt_id: str) -> SubmissionOutboxState:
        history = self._events.get(attempt_id)
        if not history:
            raise SubmissionOutboxError("unknown submission attempt")
        return history[-1].state

    def events(self, attempt_id: str) -> tuple[SubmissionOutboxEvent, ...]:
        return tuple(self._events.get(attempt_id, ()))

    def _append(self, intent: SubmissionIntent, event: SubmissionOutboxEvent) -> None:
        self._intents.setdefault(intent.attempt_id, intent)
        self._events.setdefault(intent.attempt_id, []).append(event)
        if self.journal_path is not None:
            self._append_journal(intent, event)

    def _append_journal(self, intent: SubmissionIntent, event: SubmissionOutboxEvent) -> None:
        path = self.journal_path
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "intent": intent.to_dict(),
            "event": event.to_dict(),
            "event_hash": event.event_hash,
        }
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SubmissionOutboxError(f"{field_name} is required")


def _require_hash(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in _SHA256_RE for char in value)
        or len(set(value)) == 1
    ):
        raise SubmissionOutboxError(f"{field_name} must be non-placeholder sha256")


def _hash_json(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = [
    "DurableSubmissionOutbox",
    "SubmissionIntent",
    "SubmissionOutboxError",
    "SubmissionOutboxEvent",
    "SubmissionOutboxState",
    "TERMINAL_STATES",
]

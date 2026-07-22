"""PR-187 canonical durable paper-outcome authority.

This module uses the existing lifecycle SQLite connection.  It does not create a
second runtime database, does not sign, and does not submit.  A handoff record is
only promoted after an atomic paper-outcome commit terminalizes the capital
reservation and the resulting envelope is replay-verified from the same store.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
import sqlite3
from typing import Any, Protocol
from uuid import uuid4

from src.paper_shadow.a2_exact_attempt_runtime import (
    A2PaperOutcomeStatus,
    CANONICAL_EXACT_ATTEMPT_PRODUCER,
    ExactAttemptRuntimeRecord,
)

PR187_SCHEMA = "pr187.canonical-paper-outcome.v1"
PR187_RESULT_SCHEMA = "pr187.canonical-paper-outcome-verification.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EVENT_ID = re.compile(r"^[0-9a-f]{32}$")


class PaperOutcomeResult(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


class ReservationTerminalState(StrEnum):
    CONSUMED = "consumed"
    RELEASED = "released"


class PaperOutcomeVerificationState(StrEnum):
    VERIFIED_SUCCESS = "verified_success"
    VERIFIED_FAILURE = "verified_failure"
    BLOCKED = "blocked"


class PaperOutcomeAuthorityError(RuntimeError):
    pass


class LifecycleStorePort(Protocol):
    db: sqlite3.Connection

    def get_attempt(self, attempt_id: str) -> Any: ...

    def clock_ns(self) -> int: ...


@dataclass(frozen=True, slots=True)
class PaperOutcomeCommitRequest:
    handoff: ExactAttemptRuntimeRecord
    logical_opportunity_id: str
    plan_hash: str
    simulation_hash: str
    policy_hash: str
    release_hash: str
    verifier_identity: str
    outcome: PaperOutcomeResult

    def __post_init__(self) -> None:
        if self.handoff.status is not A2PaperOutcomeStatus.EXACT_ATTEMPT_READY_FOR_HANDOFF:
            raise ValueError("PR187_COMMIT_REQUIRES_EXACT_ATTEMPT_HANDOFF")
        if self.handoff.producer_identity != CANONICAL_EXACT_ATTEMPT_PRODUCER:
            raise ValueError("PR187_UNTRUSTED_PRODUCER_IDENTITY")
        if not self.logical_opportunity_id.strip() or not self.verifier_identity.strip():
            raise ValueError("logical opportunity and verifier identity are required")
        for name in ("plan_hash", "simulation_hash", "policy_hash", "release_hash"):
            _require_sha256(getattr(self, name), name)
        if self.handoff.sender_imported or self.handoff.submission_allowed:
            raise ValueError("PR187_HANDOFF_CONTAINS_FORBIDDEN_LIVE_SURFACE")


@dataclass(frozen=True, slots=True)
class PaperOutcomeEnvelope:
    schema: str
    attempt_id: str
    attempt_generation: int
    logical_opportunity_id: str
    exact_request_hash: str
    operation_id: str
    plan_hash: str
    message_hash: str
    simulation_hash: str
    reconciliation_hash: str
    provider_evidence_hash: str
    policy_hash: str
    release_hash: str
    lifecycle_event_id: str
    paper_outcome_event_id: str
    reservation_terminal_state: ReservationTerminalState
    producer_identity: str
    verifier_identity: str
    outcome: PaperOutcomeResult
    committed_at_ns: int
    sender_imported: bool = False
    submission_allowed: bool = False

    def __post_init__(self) -> None:
        if self.schema != PR187_SCHEMA:
            raise ValueError("unsupported PR-187 envelope schema")
        if self.attempt_generation < 0 or self.committed_at_ns < 0:
            raise ValueError("generation and committed time must be non-negative")
        if not self.logical_opportunity_id.strip():
            raise ValueError("logical_opportunity_id is required")
        if not self.producer_identity.strip() or not self.verifier_identity.strip():
            raise ValueError("producer and verifier identities are required")
        if self.producer_identity != CANONICAL_EXACT_ATTEMPT_PRODUCER:
            raise ValueError("PR187_UNTRUSTED_PRODUCER_IDENTITY")
        for name in (
            "attempt_id",
            "exact_request_hash",
            "operation_id",
            "plan_hash",
            "message_hash",
            "simulation_hash",
            "reconciliation_hash",
            "provider_evidence_hash",
            "policy_hash",
            "release_hash",
        ):
            _require_sha256(getattr(self, name), name)
        for name in ("lifecycle_event_id", "paper_outcome_event_id"):
            if not _EVENT_ID.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a 32-character lowercase hex event id")
        expected_reservation = (
            ReservationTerminalState.CONSUMED
            if self.outcome is PaperOutcomeResult.SUCCESS
            else ReservationTerminalState.RELEASED
        )
        if self.reservation_terminal_state is not expected_reservation:
            raise ValueError("outcome and reservation terminal state disagree")
        if self.sender_imported or self.submission_allowed:
            raise ValueError("paper outcome cannot include sender/submission surface")

    @property
    def envelope_hash(self) -> str:
        return _hash_json(self.to_json())

    def to_json(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "attempt_id": self.attempt_id,
            "attempt_generation": self.attempt_generation,
            "logical_opportunity_id": self.logical_opportunity_id,
            "exact_request_hash": self.exact_request_hash,
            "operation_id": self.operation_id,
            "plan_hash": self.plan_hash,
            "message_hash": self.message_hash,
            "simulation_hash": self.simulation_hash,
            "reconciliation_hash": self.reconciliation_hash,
            "provider_evidence_hash": self.provider_evidence_hash,
            "policy_hash": self.policy_hash,
            "release_hash": self.release_hash,
            "lifecycle_event_id": self.lifecycle_event_id,
            "paper_outcome_event_id": self.paper_outcome_event_id,
            "reservation_terminal_state": self.reservation_terminal_state.value,
            "producer_identity": self.producer_identity,
            "verifier_identity": self.verifier_identity,
            "outcome": self.outcome.value,
            "committed_at_ns": self.committed_at_ns,
            "sender_imported": self.sender_imported,
            "submission_allowed": self.submission_allowed,
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> "PaperOutcomeEnvelope":
        return cls(
            schema=str(payload["schema"]),
            attempt_id=str(payload["attempt_id"]),
            attempt_generation=int(payload["attempt_generation"]),
            logical_opportunity_id=str(payload["logical_opportunity_id"]),
            exact_request_hash=str(payload["exact_request_hash"]),
            operation_id=str(payload["operation_id"]),
            plan_hash=str(payload["plan_hash"]),
            message_hash=str(payload["message_hash"]),
            simulation_hash=str(payload["simulation_hash"]),
            reconciliation_hash=str(payload["reconciliation_hash"]),
            provider_evidence_hash=str(payload["provider_evidence_hash"]),
            policy_hash=str(payload["policy_hash"]),
            release_hash=str(payload["release_hash"]),
            lifecycle_event_id=str(payload["lifecycle_event_id"]),
            paper_outcome_event_id=str(payload["paper_outcome_event_id"]),
            reservation_terminal_state=ReservationTerminalState(
                str(payload["reservation_terminal_state"])
            ),
            producer_identity=str(payload["producer_identity"]),
            verifier_identity=str(payload["verifier_identity"]),
            outcome=PaperOutcomeResult(str(payload["outcome"])),
            committed_at_ns=int(payload["committed_at_ns"]),
            sender_imported=bool(payload.get("sender_imported", False)),
            submission_allowed=bool(payload.get("submission_allowed", False)),
        )


@dataclass(frozen=True, slots=True)
class PaperOutcomeVerification:
    schema: str
    state: PaperOutcomeVerificationState
    reason_codes: tuple[str, ...]
    envelope_hash: str
    attempt_id: str
    paper_outcome_event_id: str

    @property
    def authoritative(self) -> bool:
        return self.state is not PaperOutcomeVerificationState.BLOCKED

    @property
    def counts_as_soak_success(self) -> bool:
        return self.state is PaperOutcomeVerificationState.VERIFIED_SUCCESS

    @property
    def a2_status(self) -> A2PaperOutcomeStatus:
        if self.state is PaperOutcomeVerificationState.VERIFIED_SUCCESS:
            return A2PaperOutcomeStatus.RECONCILED_PAPER_SUCCESS
        if self.state is PaperOutcomeVerificationState.VERIFIED_FAILURE:
            return A2PaperOutcomeStatus.RECONCILED_PAPER_FAILURE
        return A2PaperOutcomeStatus.INDETERMINATE

    def to_json(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "state": self.state.value,
            "authoritative": self.authoritative,
            "counts_as_soak_success": self.counts_as_soak_success,
            "reason_codes": list(self.reason_codes),
            "envelope_hash": self.envelope_hash,
            "attempt_id": self.attempt_id,
            "paper_outcome_event_id": self.paper_outcome_event_id,
            "a2_status": self.a2_status.value,
        }


class CanonicalPaperOutcomeStore:
    """Commit and replay-verify paper outcomes in the lifecycle SQLite DB."""

    def __init__(self, lifecycle_store: LifecycleStorePort) -> None:
        self.lifecycle_store = lifecycle_store
        self.db = lifecycle_store.db
        self._migrate()

    def _migrate(self) -> None:
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_outcomes_pr187(
              paper_outcome_event_id TEXT PRIMARY KEY,
              attempt_id TEXT NOT NULL,
              attempt_generation INTEGER NOT NULL,
              operation_id TEXT NOT NULL UNIQUE,
              lifecycle_event_id TEXT NOT NULL,
              outcome TEXT NOT NULL,
              reservation_terminal_state TEXT NOT NULL,
              envelope_json TEXT NOT NULL,
              envelope_hash TEXT NOT NULL,
              created_at_ns INTEGER NOT NULL,
              UNIQUE(attempt_id, attempt_generation)
            )
            """
        )

    def commit(self, request: PaperOutcomeCommitRequest) -> PaperOutcomeEnvelope:
        existing = self.db.execute(
            "SELECT envelope_json FROM paper_outcomes_pr187 WHERE operation_id=?",
            (request.handoff.operation_id,),
        ).fetchone()
        if existing:
            return PaperOutcomeEnvelope.from_json(json.loads(str(existing[0])))

        if request.handoff.attempt_id is None:
            raise PaperOutcomeAuthorityError("PR187_HANDOFF_ATTEMPT_ID_MISSING")
        attempt = self.lifecycle_store.get_attempt(request.handoff.attempt_id)
        if attempt is None:
            raise PaperOutcomeAuthorityError("PR187_DURABLE_ATTEMPT_NOT_FOUND")
        if attempt.key.generation != request.handoff.attempt_generation:
            raise PaperOutcomeAuthorityError("PR187_ATTEMPT_GENERATION_MISMATCH")
        if attempt.key.logical_opportunity_id != request.logical_opportunity_id:
            raise PaperOutcomeAuthorityError("PR187_LOGICAL_OPPORTUNITY_MISMATCH")
        if attempt.key.plan_hash != request.plan_hash:
            raise PaperOutcomeAuthorityError("PR187_PLAN_HASH_MISMATCH")

        lifecycle_event = self.db.execute(
            "SELECT event_id FROM durable_events WHERE attempt_id=? "
            "ORDER BY sequence_no DESC LIMIT 1",
            (request.handoff.attempt_id,),
        ).fetchone()
        if lifecycle_event is None:
            raise PaperOutcomeAuthorityError("PR187_LIFECYCLE_EVENT_MISSING")

        reservation = self.db.execute(
            "SELECT reservation_id,state FROM durable_reservations WHERE attempt_id=?",
            (request.handoff.attempt_id,),
        ).fetchone()
        if reservation is None or str(reservation[1]) != "active":
            raise PaperOutcomeAuthorityError("PR187_ACTIVE_RESERVATION_REQUIRED")

        terminal = (
            ReservationTerminalState.CONSUMED
            if request.outcome is PaperOutcomeResult.SUCCESS
            else ReservationTerminalState.RELEASED
        )
        event_id = uuid4().hex
        now = int(self.lifecycle_store.clock_ns())
        envelope = PaperOutcomeEnvelope(
            schema=PR187_SCHEMA,
            attempt_id=request.handoff.attempt_id,
            attempt_generation=request.handoff.attempt_generation,
            logical_opportunity_id=request.logical_opportunity_id,
            exact_request_hash=request.handoff.exact_request_hash,
            operation_id=request.handoff.operation_id,
            plan_hash=request.plan_hash,
            message_hash=request.handoff.message_hash or "",
            simulation_hash=request.simulation_hash,
            reconciliation_hash=request.handoff.reconciliation_hash or "",
            provider_evidence_hash=request.handoff.provider_evidence_hash,
            policy_hash=request.policy_hash,
            release_hash=request.release_hash,
            lifecycle_event_id=str(lifecycle_event[0]),
            paper_outcome_event_id=event_id,
            reservation_terminal_state=terminal,
            producer_identity=request.handoff.producer_identity,
            verifier_identity=request.verifier_identity,
            outcome=request.outcome,
            committed_at_ns=now,
        )
        encoded = json.dumps(envelope.to_json(), sort_keys=True, separators=(",", ":"))

        with self.db:
            cur = self.db.execute(
                "UPDATE durable_reservations SET state=?,updated_at_ns=? "
                "WHERE attempt_id=? AND state='active'",
                (terminal.value, now, request.handoff.attempt_id),
            )
            if cur.rowcount != 1:
                raise PaperOutcomeAuthorityError("PR187_RESERVATION_TERMINALIZATION_FAILED")
            self.db.execute(
                "UPDATE durable_attempts SET reservation_state=?,updated_at_ns=? "
                "WHERE attempt_id=?",
                (terminal.value, now, request.handoff.attempt_id),
            )
            self.db.execute(
                "INSERT INTO paper_outcomes_pr187 VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    request.handoff.attempt_id,
                    request.handoff.attempt_generation,
                    request.handoff.operation_id,
                    str(lifecycle_event[0]),
                    request.outcome.value,
                    terminal.value,
                    encoded,
                    envelope.envelope_hash,
                    now,
                ),
            )
        return envelope

    def verify(self, envelope: PaperOutcomeEnvelope) -> PaperOutcomeVerification:
        reasons: list[str] = []
        row = self.db.execute(
            "SELECT * FROM paper_outcomes_pr187 WHERE paper_outcome_event_id=?",
            (envelope.paper_outcome_event_id,),
        ).fetchone()
        if row is None:
            reasons.append("PR187_OUTCOME_EVENT_NOT_FOUND")
        else:
            stored_payload = json.loads(str(row[7]))
            stored = PaperOutcomeEnvelope.from_json(stored_payload)
            if stored.envelope_hash != envelope.envelope_hash:
                reasons.append("PR187_ENVELOPE_HASH_MISMATCH")
            if str(row[8]) != envelope.envelope_hash:
                reasons.append("PR187_STORED_ENVELOPE_DIGEST_MISMATCH")

        attempt = self.lifecycle_store.get_attempt(envelope.attempt_id)
        if attempt is None:
            reasons.append("PR187_DURABLE_ATTEMPT_NOT_FOUND")
        else:
            if attempt.key.generation != envelope.attempt_generation:
                reasons.append("PR187_ATTEMPT_GENERATION_MISMATCH")
            if attempt.key.logical_opportunity_id != envelope.logical_opportunity_id:
                reasons.append("PR187_LOGICAL_OPPORTUNITY_MISMATCH")
            if attempt.key.plan_hash != envelope.plan_hash:
                reasons.append("PR187_PLAN_HASH_MISMATCH")
            state = getattr(attempt.reservation_state, "value", attempt.reservation_state)
            if str(state) != envelope.reservation_terminal_state.value:
                reasons.append("PR187_RESERVATION_STATE_MISMATCH")

        event = self.db.execute(
            "SELECT 1 FROM durable_events WHERE event_id=? AND attempt_id=?",
            (envelope.lifecycle_event_id, envelope.attempt_id),
        ).fetchone()
        if event is None:
            reasons.append("PR187_LIFECYCLE_EVENT_REFERENCE_MISSING")
        if envelope.producer_identity != CANONICAL_EXACT_ATTEMPT_PRODUCER:
            reasons.append("PR187_UNTRUSTED_PRODUCER_IDENTITY")
        if envelope.sender_imported or envelope.submission_allowed:
            reasons.append("PR187_FORBIDDEN_LIVE_SURFACE")

        state = PaperOutcomeVerificationState.BLOCKED
        if not reasons:
            state = (
                PaperOutcomeVerificationState.VERIFIED_SUCCESS
                if envelope.outcome is PaperOutcomeResult.SUCCESS
                else PaperOutcomeVerificationState.VERIFIED_FAILURE
            )
        return PaperOutcomeVerification(
            schema=PR187_RESULT_SCHEMA,
            state=state,
            reason_codes=tuple(reasons),
            envelope_hash=envelope.envelope_hash,
            attempt_id=envelope.attempt_id,
            paper_outcome_event_id=envelope.paper_outcome_event_id,
        )


def _require_sha256(value: str, field_name: str) -> str:
    if not _SHA256.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")
    if len(set(value)) == 1 and value[0] in {"0", "f"}:
        raise ValueError(f"{field_name} cannot be a placeholder digest")
    return value


def _hash_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "CanonicalPaperOutcomeStore",
    "PR187_RESULT_SCHEMA",
    "PR187_SCHEMA",
    "PaperOutcomeAuthorityError",
    "PaperOutcomeCommitRequest",
    "PaperOutcomeEnvelope",
    "PaperOutcomeResult",
    "PaperOutcomeVerification",
    "PaperOutcomeVerificationState",
    "ReservationTerminalState",
]

from __future__ import annotations

from dataclasses import dataclass, replace
import sqlite3

import pytest

from src.paper_shadow.a2_exact_attempt_runtime import (
    A2PaperOutcomeStatus,
    CANONICAL_EXACT_ATTEMPT_PRODUCER,
    ExactAttemptRuntimeRecord,
    FailureStage,
)
from src.paper_shadow.paper_outcome_pr187 import (
    CanonicalPaperOutcomeStore,
    PaperOutcomeCommitRequest,
    PaperOutcomeResult,
    PaperOutcomeVerificationState,
)

ATTEMPT = "a1" * 32
REQUEST = "b2" * 32
OPERATION = "c3" * 32
PLAN = "d4" * 32
MESSAGE = "e5" * 32
SIMULATION = "a6" * 32
RECONCILIATION = "b7" * 32
PROVIDER = "c8" * 32
RESULT = "d9" * 32
POLICY = "ea" * 32
RELEASE = "fb" * 32
LIFECYCLE_EVENT = "1a" * 16


@dataclass(frozen=True)
class Key:
    logical_opportunity_id: str
    plan_hash: str
    generation: int


@dataclass(frozen=True)
class Attempt:
    attempt_id: str
    key: Key
    reservation_state: str


class FakeLifecycleStore:
    def __init__(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.execute(
            "CREATE TABLE durable_attempts(attempt_id TEXT PRIMARY KEY,"
            "logical_opportunity_id TEXT,plan_hash TEXT,generation INTEGER,"
            "reservation_state TEXT,updated_at_ns INTEGER)"
        )
        self.db.execute(
            "CREATE TABLE durable_reservations(reservation_id TEXT PRIMARY KEY,"
            "attempt_id TEXT,state TEXT,updated_at_ns INTEGER)"
        )
        self.db.execute(
            "CREATE TABLE durable_events(event_id TEXT PRIMARY KEY,"
            "attempt_id TEXT,sequence_no INTEGER)"
        )
        self.db.execute(
            "INSERT INTO durable_attempts VALUES(?,?,?,?,?,?)",
            (ATTEMPT, "opportunity-1", PLAN, 7, "active", 1),
        )
        self.db.execute(
            "INSERT INTO durable_reservations VALUES(?,?,?,?)",
            ("reservation-1", ATTEMPT, "active", 1),
        )
        self.db.execute(
            "INSERT INTO durable_events VALUES(?,?,?)",
            (LIFECYCLE_EVENT, ATTEMPT, 0),
        )
        self.now = 100

    def clock_ns(self) -> int:
        self.now += 1
        return self.now

    def get_attempt(self, attempt_id: str):
        row = self.db.execute(
            "SELECT * FROM durable_attempts WHERE attempt_id=?", (attempt_id,)
        ).fetchone()
        if row is None:
            return None
        return Attempt(
            attempt_id=row[0],
            key=Key(row[1], row[2], row[3]),
            reservation_state=row[4],
        )


def handoff(producer: str = CANONICAL_EXACT_ATTEMPT_PRODUCER):
    return ExactAttemptRuntimeRecord(
        item_index=0,
        attempt_generation=7,
        status=A2PaperOutcomeStatus.EXACT_ATTEMPT_READY_FOR_HANDOFF,
        reason_code="exact_attempt_ready_for_durable_paper_handoff",
        failure_stage=FailureStage.DURABLE_HANDOFF,
        provider_evidence_hash=PROVIDER,
        result_hash=RESULT,
        exact_request_hash=REQUEST,
        operation_id=OPERATION,
        producer_identity=producer,
        attempt_id=ATTEMPT,
        message_hash=MESSAGE,
        planner_digest=PLAN,
        reconciliation_hash=RECONCILIATION,
    )


def commit_request(*, outcome: PaperOutcomeResult = PaperOutcomeResult.SUCCESS):
    return PaperOutcomeCommitRequest(
        handoff=handoff(),
        logical_opportunity_id="opportunity-1",
        plan_hash=PLAN,
        simulation_hash=SIMULATION,
        policy_hash=POLICY,
        release_hash=RELEASE,
        verifier_identity="canonical-paper-outcome-verifier",
        outcome=outcome,
    )


def test_success_requires_atomic_commit_and_consumes_reservation() -> None:
    lifecycle = FakeLifecycleStore()
    store = CanonicalPaperOutcomeStore(lifecycle)
    envelope = store.commit(commit_request())
    verification = store.verify(envelope)

    assert envelope.reservation_terminal_state.value == "consumed"
    assert lifecycle.get_attempt(ATTEMPT).reservation_state == "consumed"
    assert verification.state is PaperOutcomeVerificationState.VERIFIED_SUCCESS
    assert verification.counts_as_soak_success is True
    assert verification.a2_status is A2PaperOutcomeStatus.RECONCILED_PAPER_SUCCESS


def test_failure_releases_reservation_and_is_not_soak_success() -> None:
    lifecycle = FakeLifecycleStore()
    store = CanonicalPaperOutcomeStore(lifecycle)
    envelope = store.commit(commit_request(outcome=PaperOutcomeResult.FAILURE))
    verification = store.verify(envelope)

    assert envelope.reservation_terminal_state.value == "released"
    assert verification.state is PaperOutcomeVerificationState.VERIFIED_FAILURE
    assert verification.counts_as_soak_success is False


def test_commit_is_idempotent_for_same_typed_operation() -> None:
    lifecycle = FakeLifecycleStore()
    store = CanonicalPaperOutcomeStore(lifecycle)
    first = store.commit(commit_request())
    second = store.commit(commit_request())
    assert second.paper_outcome_event_id == first.paper_outcome_event_id
    assert second.envelope_hash == first.envelope_hash


def test_tampered_envelope_does_not_verify() -> None:
    lifecycle = FakeLifecycleStore()
    store = CanonicalPaperOutcomeStore(lifecycle)
    envelope = store.commit(commit_request())
    tampered = replace(envelope, message_hash="12" * 32)
    verification = store.verify(tampered)
    assert verification.state is PaperOutcomeVerificationState.BLOCKED
    assert "PR187_ENVELOPE_HASH_MISMATCH" in verification.reason_codes


def test_arbitrary_producer_cannot_commit_trusted_outcome() -> None:
    with pytest.raises(ValueError, match="UNTRUSTED_PRODUCER_IDENTITY"):
        PaperOutcomeCommitRequest(
            handoff=handoff("fake.orchestrator"),
            logical_opportunity_id="opportunity-1",
            plan_hash=PLAN,
            simulation_hash=SIMULATION,
            policy_hash=POLICY,
            release_hash=RELEASE,
            verifier_identity="verifier",
            outcome=PaperOutcomeResult.SUCCESS,
        )

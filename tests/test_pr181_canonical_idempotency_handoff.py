from __future__ import annotations

import sqlite3

import pytest

from src.durability.canonical_idempotency import (
    CanonicalIdempotencyStore,
    CanonicalOperationIdentity,
    HandoffRecoveryAction,
    IdempotencyConflict,
)

ATTEMPT = "a" * 64
RESERVATION = "reservation-1"
POLICY = "release-policy-generation-7"

BASE_SCHEMA = """
CREATE TABLE durable_attempts(
 attempt_id TEXT PRIMARY KEY,
 generation INTEGER NOT NULL,
 reservation_id TEXT,
 reservation_state TEXT
);
CREATE TABLE durable_reservations(
 reservation_id TEXT PRIMARY KEY,
 attempt_id TEXT NOT NULL,
 state TEXT NOT NULL
);
"""


def _db(*, attempt_id: str = ATTEMPT, reservation_id: str = RESERVATION):
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(BASE_SCHEMA)
    connection.execute(
        "INSERT INTO durable_attempts VALUES(?,?,?,?)",
        (attempt_id, 1, reservation_id, "active"),
    )
    connection.execute(
        "INSERT INTO durable_reservations VALUES(?,?,?)",
        (reservation_id, attempt_id, "active"),
    )
    return connection


def _identity(payload: dict[str, object] | None = None, *, attempt_id: str = ATTEMPT):
    return CanonicalOperationIdentity.derive(
        domain="paper-runtime",
        attempt_id=attempt_id,
        attempt_generation=1,
        operation="paper_handoff",
        request_payload=payload or {"message_hash": "b" * 64},
        policy_generation=POLICY,
    )


def _commit(store: CanonicalIdempotencyStore, identity=None):
    return store.commit_paper_handoff(
        identity=identity or _identity(),
        reservation_id=RESERVATION,
        result={
            "attempt_id": ATTEMPT,
            "message_hash": "b" * 64,
            "reconciliation_hash": "c" * 64,
        },
        owner_id="paper-outcome-writer",
        lease_ttl_ns=10,
        max_age_ns=100,
    )


def test_pr181_operation_identity_is_payload_bound_and_deterministic() -> None:
    first = _identity()
    same = _identity()
    changed = _identity({"message_hash": "d" * 64})

    assert first.operation_id == same.operation_id
    assert first.operation_id != changed.operation_id
    assert len(first.operation_id) == 64


def test_pr181_bool_is_not_a_valid_attempt_generation() -> None:
    with pytest.raises(ValueError):
        CanonicalOperationIdentity(
            domain="paper-runtime",
            attempt_id=ATTEMPT,
            attempt_generation=True,
            operation="paper_handoff",
            request_payload_hash="b" * 64,
            policy_generation=POLICY,
        )


def test_pr181_commit_is_atomic_with_result_handoff_and_outbox() -> None:
    db = _db()
    store = CanonicalIdempotencyStore(db, clock_ns=lambda: 1_000)
    receipt = _commit(store)

    assert receipt.replayed is False
    assert receipt.attempt_id == ATTEMPT
    assert receipt.reservation_id == RESERVATION
    assert receipt.owner_id == "paper-outcome-writer"
    assert db.execute(
        "SELECT COUNT(*) FROM canonical_operation_results_pr181"
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT COUNT(*) FROM paper_reservation_handoffs_pr181"
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT COUNT(*) FROM paper_handoff_outbox_pr181"
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT state FROM durable_reservations WHERE reservation_id=?",
        (RESERVATION,),
    ).fetchone()[0] == "active"


def test_pr181_exact_duplicate_returns_original_committed_result() -> None:
    db = _db()
    store = CanonicalIdempotencyStore(db, clock_ns=lambda: 1_000)
    first = _commit(store)
    replay = _commit(store)

    assert replay.replayed is True
    assert replay.handoff_id == first.handoff_id
    assert replay.result_digest == first.result_digest
    assert db.execute(
        "SELECT COUNT(*) FROM paper_handoff_outbox_pr181"
    ).fetchone()[0] == 1


def test_pr181_different_payload_for_same_operation_conflicts() -> None:
    db = _db()
    store = CanonicalIdempotencyStore(db, clock_ns=lambda: 1_000)
    _commit(store)

    with pytest.raises(IdempotencyConflict, match="IDEMPOTENCY_CONFLICT"):
        _commit(store, _identity({"message_hash": "d" * 64}))


def test_pr181_unrelated_attempts_do_not_collide() -> None:
    db = _db()
    second_attempt = "e" * 64
    second_reservation = "reservation-2"
    db.execute(
        "INSERT INTO durable_attempts VALUES(?,?,?,?)",
        (second_attempt, 1, second_reservation, "active"),
    )
    db.execute(
        "INSERT INTO durable_reservations VALUES(?,?,?)",
        (second_reservation, second_attempt, "active"),
    )
    store = CanonicalIdempotencyStore(db, clock_ns=lambda: 1_000)
    _commit(store)
    second = store.commit_paper_handoff(
        identity=_identity(attempt_id=second_attempt),
        reservation_id=second_reservation,
        result={
            "attempt_id": second_attempt,
            "message_hash": "b" * 64,
            "reconciliation_hash": "c" * 64,
        },
        owner_id="paper-outcome-writer",
        lease_ttl_ns=10,
        max_age_ns=100,
    )

    assert second.attempt_id == second_attempt
    assert db.execute(
        "SELECT COUNT(*) FROM canonical_operation_results_pr181"
    ).fetchone()[0] == 2


def test_pr181_expired_lease_requires_reclaim_not_auto_release() -> None:
    db = _db()
    store = CanonicalIdempotencyStore(db, clock_ns=lambda: 1_000)
    _commit(store)

    decision = store.recovery_decisions(now_ns=1_011)[0]
    assert decision.action is HandoffRecoveryAction.RECLAIM_EXPIRED_LEASE
    assert db.execute(
        "SELECT state FROM durable_reservations WHERE reservation_id=?",
        (RESERVATION,),
    ).fetchone()[0] == "active"


def test_pr181_max_age_escalates_to_manual_review() -> None:
    db = _db()
    store = CanonicalIdempotencyStore(db, clock_ns=lambda: 1_000)
    _commit(store)

    decision = store.recovery_decisions(now_ns=1_100)[0]
    assert decision.action is HandoffRecoveryAction.MANUAL_REVIEW_MAX_AGE


def test_pr181_acknowledgement_is_fenced_and_completes_outbox() -> None:
    db = _db()
    store = CanonicalIdempotencyStore(db, clock_ns=lambda: 1_000)
    receipt = _commit(store)

    assert store.acknowledge_handoff(
        receipt.handoff_id,
        owner_id="wrong-owner",
        fencing_token=receipt.fencing_token,
    ) is False
    assert store.acknowledge_handoff(
        receipt.handoff_id,
        owner_id=receipt.owner_id,
        fencing_token=receipt.fencing_token,
    ) is True
    assert store.recovery_decisions(now_ns=1_001)[0].action is (
        HandoffRecoveryAction.ACKNOWLEDGED
    )
    assert db.execute(
        "SELECT status FROM paper_handoff_outbox_pr181"
    ).fetchone()[0] == "completed"

from __future__ import annotations

import sqlite3

import pytest

from src.durability.lifecycle import (
    AttemptKey,
    CorruptJournalError,
    DuplicateSubmissionError,
    DurableLifecycleError,
    DurableLifecycleStore,
    LeaseLostError,
    RecoveryAction,
    ReservationState,
)
from src.execution.models import ExecutionState


class FakeClock:
    def __init__(self, value: int = 1_000_000_000) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value

    def advance(self, delta: int) -> None:
        self.value += delta


def create_store(tmp_path, clock: FakeClock) -> DurableLifecycleStore:
    return DurableLifecycleStore(tmp_path / "journal.db", clock_ns=clock)


def create_attempt(
    store: DurableLifecycleStore,
    *,
    suffix: str,
    reservation: bool = False,
):
    key = AttemptKey(f"opp-{suffix}", f"{suffix:0>64}"[-64:], 1)
    return store.create_attempt(
        key,
        idempotency_key=f"create-{suffix}",
        reservation_id=f"reservation-{suffix}" if reservation else None,
        candidate_id=f"candidate-{suffix}" if reservation else None,
        reserved_lamports=50_000 if reservation else 0,
        payload={
            "api_key": "must-not-persist",
            "signed_transaction": b"private-wire-bytes",
            "safe": suffix,
        },
    )


def advance_to_signed(
    store: DurableLifecycleStore,
    attempt_id: str,
    *,
    owner: str,
):
    lease = store.acquire_lease(
        f"attempt:{attempt_id}",
        owner_id=owner,
        ttl_ns=1_000_000,
    )
    current = store.get_attempt(attempt_id)
    assert current is not None
    for index, target in enumerate(
        (
            ExecutionState.COMPILED,
            ExecutionState.STRUCTURALLY_VALIDATED,
            ExecutionState.SIMULATED,
            ExecutionState.APPROVED,
            ExecutionState.SIGNED,
        ),
        start=1,
    ):
        current = store.transition(
            attempt_id,
            expected_revision=current.revision,
            target=target,
            idempotency_key=f"{attempt_id}-transition-{index}",
            lease=lease,
        )
    return current, lease


def test_create_is_atomic_idempotent_and_redacted(tmp_path):
    clock = FakeClock()
    with create_store(tmp_path, clock) as store:
        first = create_attempt(store, suffix="1", reservation=True)
        second = create_attempt(store, suffix="1", reservation=True)

        assert first == second
        assert store.count_rows("durable_attempts") == 1
        assert store.count_rows("durable_reservations") == 1
        assert store.count_rows("durable_events") == 1
        assert store.count_rows("durable_outbox") == 1

        event = store.events_for(first.attempt_id)[0]
        assert "must-not-persist" not in event["payload_json"]
        assert "private-wire-bytes" not in event["payload_json"]
        assert "[REDACTED]" in event["payload_json"]
        assert int(event["redaction_hits"]) >= 2


def test_state_machine_revision_and_stale_fencing_fail_closed(tmp_path):
    clock = FakeClock()
    with create_store(tmp_path, clock) as store:
        attempt = create_attempt(store, suffix="2")
        old = store.acquire_lease(
            f"attempt:{attempt.attempt_id}",
            owner_id="worker-a",
            ttl_ns=10,
        )
        clock.advance(11)
        fresh = store.acquire_lease(
            f"attempt:{attempt.attempt_id}",
            owner_id="worker-b",
            ttl_ns=100,
        )
        assert fresh.fencing_token > old.fencing_token

        with pytest.raises(LeaseLostError):
            store.transition(
                attempt.attempt_id,
                expected_revision=0,
                target=ExecutionState.COMPILED,
                idempotency_key="stale-write",
                lease=old,
            )

        compiled = store.transition(
            attempt.attempt_id,
            expected_revision=0,
            target=ExecutionState.COMPILED,
            idempotency_key="fresh-write",
            lease=fresh,
        )
        assert compiled.revision == 1

        with pytest.raises(DurableLifecycleError, match="revision"):
            store.transition(
                attempt.attempt_id,
                expected_revision=0,
                target=ExecutionState.SIMULATED,
                idempotency_key="wrong-revision",
                lease=fresh,
            )


def test_submission_message_and_idempotency_never_create_second_trade(tmp_path):
    clock = FakeClock()
    with create_store(tmp_path, clock) as store:
        first = create_attempt(store, suffix="3")
        second = create_attempt(store, suffix="4")
        first_signed, first_lease = advance_to_signed(
            store,
            first.attempt_id,
            owner="worker-a",
        )
        second_signed, second_lease = advance_to_signed(
            store,
            second.attempt_id,
            owner="worker-b",
        )
        message_hash = "a" * 64

        submitted = store.record_submission_intent(
            first.attempt_id,
            expected_revision=first_signed.revision,
            message_hash=message_hash,
            transport="rpc",
            submission_signature="sig-one",
            idempotency_key="submit-one",
            lease=first_lease,
        )
        duplicate = store.record_submission_intent(
            first.attempt_id,
            expected_revision=first_signed.revision,
            message_hash=message_hash,
            transport="rpc",
            submission_signature="sig-one",
            idempotency_key="submit-one",
            lease=first_lease,
        )
        assert submitted == duplicate
        assert submitted.state is ExecutionState.SUBMISSION_INTENT_RECORDED

        with pytest.raises(DuplicateSubmissionError):
            store.record_submission_intent(
                second.attempt_id,
                expected_revision=second_signed.revision,
                message_hash=message_hash,
                transport="rpc",
                submission_signature="sig-two",
                idempotency_key="submit-two",
                lease=second_lease,
            )


def test_startup_recovery_releases_only_never_submitted_reservation(tmp_path):
    clock = FakeClock()
    with create_store(tmp_path, clock) as store:
        pre = create_attempt(store, suffix="5", reservation=True)
        submitted = create_attempt(store, suffix="6", reservation=True)
        signed, submitted_lease = advance_to_signed(
            store,
            submitted.attempt_id,
            owner="submitter",
        )
        store.record_submission_intent(
            submitted.attempt_id,
            expected_revision=signed.revision,
            message_hash="b" * 64,
            transport="jito",
            jito_bundle_id="bundle-1",
            idempotency_key="submit-bundle",
            lease=submitted_lease,
        )

        decisions = {
            decision.attempt.attempt_id: decision
            for decision in store.scan_startup_recovery()
        }
        assert decisions[pre.attempt_id].action is RecoveryAction.RESUME_PRE_SUBMISSION
        assert decisions[pre.attempt_id].reservation_active is True
        assert (
            decisions[submitted.attempt_id].action
            is RecoveryAction.RECONCILE_NO_RESUBMIT
        )

        pre_lease = store.acquire_lease(
            f"attempt:{pre.attempt_id}",
            owner_id="recovery",
            ttl_ns=1_000,
        )
        assert store.release_abandoned_reservation(
            pre.attempt_id,
            idempotency_key="release-pre",
            lease=pre_lease,
        )
        recovered = store.get_attempt(pre.attempt_id)
        assert recovered is not None
        assert recovered.reservation_state is ReservationState.RELEASED

        with pytest.raises(DurableLifecycleError, match="cannot be auto-released"):
            store.release_abandoned_reservation(
                submitted.attempt_id,
                idempotency_key="release-submitted",
                lease=submitted_lease,
            )


def test_outbox_claim_completion_and_retention_keep_audit(tmp_path):
    clock = FakeClock()
    with create_store(tmp_path, clock) as store:
        attempt = create_attempt(store, suffix="7")
        items = store.claim_outbox(
            topic="lifecycle.event",
            owner_id="exporter",
            limit=10,
            lease_ns=100,
        )
        assert len(items) == 1
        assert store.complete_outbox(items[0], owner_id="exporter") is True
        assert store.complete_outbox(items[0], owner_id="exporter") is False

        clock.advance(200)
        assert store.purge_completed_outbox(cutoff_ns=clock.value) == 1
        assert store.count_rows("durable_outbox") == 0
        assert store.count_rows("durable_events") == 1
        assert store.count_rows("retention_ledger") == 1
        assert store.events_for(attempt.attempt_id)


def test_immutable_audit_and_integrity_detection(tmp_path):
    clock = FakeClock()
    with create_store(tmp_path, clock) as store:
        attempt = create_attempt(store, suffix="8")
        event_id = store.events_for(attempt.attempt_id)[0]["event_id"]
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            store.db.execute(
                "UPDATE durable_events SET payload_digest=? WHERE event_id=?",
                ("0" * 64, event_id),
            )
        store.integrity_check()


def test_backup_restore_drill_and_checksum(tmp_path):
    clock = FakeClock()
    source_path = tmp_path / "source.db"
    store = DurableLifecycleStore(source_path, clock_ns=clock)
    attempt = create_attempt(store, suffix="9", reservation=True)
    backup = store.backup_to(tmp_path / "backup.db")
    store.close()

    restored = DurableLifecycleStore.restore_from(
        tmp_path / "backup.db",
        tmp_path / "restored.db",
        expected_sha256=backup.sha256,
    )
    try:
        assert restored.get_attempt(attempt.attempt_id) == attempt
        assert restored.count_rows("durable_events") == 1
        restored.integrity_check()
    finally:
        restored.close()

    with pytest.raises(CorruptJournalError, match="checksum"):
        DurableLifecycleStore.restore_from(
            tmp_path / "backup.db",
            tmp_path / "bad-restore.db",
            expected_sha256="0" * 64,
        )


def test_migration_forward_and_safe_empty_rollback(tmp_path):
    path = tmp_path / "migration.db"
    store = DurableLifecycleStore(path)
    store.rollback_empty_schema()
    version = store.db.execute("PRAGMA user_version").fetchone()[0]
    assert version == 0
    store.close()

    reopened = DurableLifecycleStore(path)
    try:
        version = reopened.db.execute("PRAGMA user_version").fetchone()[0]
        assert version == 41
        create_attempt(reopened, suffix="a")
        with pytest.raises(DurableLifecycleError, match="backup restore"):
            reopened.rollback_empty_schema()
    finally:
        reopened.close()

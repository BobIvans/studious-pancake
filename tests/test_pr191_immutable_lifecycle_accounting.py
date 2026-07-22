from __future__ import annotations

from dataclasses import replace
import sqlite3

import pytest

from src.execution.immutable_accounting_pr191 import (
    ImmutableLiveControlStore,
    TerminalAccountingConflict,
)
from src.execution.live_control import LiveControlStore, record_actual_outcome
from src.paper_shadow.immutable_lifecycle_pr191 import (
    ImmutableSQLitePaperLifecycleStore,
    LifecycleImmutabilityConflict,
    OutboxDeliveryState,
)
from src.paper_shadow.structured_runtime import (
    PaperLifecycleTransition,
    SQLitePaperLifecycleStore,
    StructuredPaperRuntimeState,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


def _transition() -> PaperLifecycleTransition:
    return PaperLifecycleTransition(
        run_id="run-191",
        cycle=1,
        state=StructuredPaperRuntimeState.PAPER_OUTCOME,
        terminal_reason="paper_outcome_committed",
        candidates_seen=2,
        events_written=1,
        ready_for_next_cycle=True,
        dependency_reasons=(),
        details={"sender_enabled": False, "live_enabled": False},
        created_at_unix_ms=1_700_000_000_000,
    )


def test_package_cutover_uses_immutable_store() -> None:
    assert SQLitePaperLifecycleStore is ImmutableSQLitePaperLifecycleStore
    assert LiveControlStore is ImmutableLiveControlStore


def test_delivered_outbox_replay_never_resets_acknowledgement(tmp_path) -> None:
    store = SQLitePaperLifecycleStore(tmp_path / "paper.sqlite")
    transition = _transition()

    first = store.record_transition(transition)
    assert first.replayed is False
    assert store.mark_delivered(transition.outbox_id) is True

    replay = store.record_transition(transition)
    assert replay.replayed is True

    row = store.read_outbox()[0]
    assert row["delivery_state"] == OutboxDeliveryState.ACKNOWLEDGED.value
    assert row["delivered"] is True

    with sqlite3.connect(store.path) as conn:
        delivered = conn.execute(
            "SELECT delivered FROM paper_lifecycle_outbox WHERE outbox_id=?",
            (transition.outbox_id,),
        ).fetchone()[0]
    assert delivered == 1


def test_changed_payload_under_same_transition_identity_is_conflict(tmp_path) -> None:
    store = SQLitePaperLifecycleStore(tmp_path / "paper.sqlite")
    transition = _transition()
    store.record_transition(transition)

    changed = replace(transition, candidates_seen=99)
    assert changed.transition_id == transition.transition_id
    with pytest.raises(
        LifecycleImmutabilityConflict, match="PR191_IMMUTABILITY_CONFLICT"
    ):
        store.record_transition(changed)

    assert len(store.read_transitions()) == 1
    assert len(store.read_outbox()) == 1


def test_delivery_lease_uses_fencing_and_append_only_attempts(tmp_path) -> None:
    store = SQLitePaperLifecycleStore(tmp_path / "paper.sqlite")
    transition = _transition()
    store.record_transition(transition)

    lease = store.lease_pending(
        owner="dispatcher-a",
        now_unix_ms=1_000,
        lease_duration_ms=100,
    )[0]
    assert lease.fencing_token == 1

    store.record_delivery_attempt(
        lease,
        result_state=OutboxDeliveryState.FAILED_RETRYABLE,
        error_code="TEMPORARY",
        next_retry_at_unix_ms=1_200,
        now_unix_ms=1_050,
    )
    second = store.lease_pending(
        owner="dispatcher-b",
        now_unix_ms=1_200,
        lease_duration_ms=100,
    )[0]
    assert second.fencing_token == 2
    assert second.attempt_count == 2

    with sqlite3.connect(store.path) as conn:
        attempts = conn.execute(
            "SELECT COUNT(*) FROM paper_lifecycle_outbox_attempt"
        ).fetchone()[0]
    assert attempts == 1


def _post(
    store: LiveControlStore,
    *,
    actual_delta: int = 7,
    operation: str = "actual",
):
    return record_actual_outcome(
        store,
        attempt_id="attempt-191",
        attempt_generation=3,
        config_hash=HASH_A,
        asset="SOL",
        finalized_signature="signature-191",
        settlement_evidence_hash=HASH_B,
        accounting_operation=operation,
        actual_delta=actual_delta,
        simulated_delta=7,
        tolerance=1,
        provenance={"settlement_evidence_hash": HASH_B},
    )


def test_duplicate_terminal_outcome_returns_original_posting(tmp_path) -> None:
    store = LiveControlStore(tmp_path / "live.sqlite")
    try:
        store.db.execute(
            """
            INSERT INTO live_budget_reservations
            VALUES(?,?,?,?,?,?)
            """,
            ("reservation-191", "attempt-191", HASH_A, 100, "reserved", 1.0),
        )
        first = _post(store)
        assert first.replayed is False
        assert store.acknowledge_terminal_outbox(first.outbox_id) is True

        replay = _post(store)
        assert replay.replayed is True
        assert replay.outcome_id == first.outcome_id

        count = store.db.execute(
            "SELECT COUNT(*) FROM live_actual_outcomes WHERE attempt_id=?",
            ("attempt-191",),
        ).fetchone()[0]
        delivery = store.db.execute(
            "SELECT state FROM live_terminal_outbox_delivery WHERE outbox_id=?",
            (first.outbox_id,),
        ).fetchone()[0]
        reservation = store.db.execute(
            "SELECT status FROM live_budget_reservations WHERE reservation_id=?",
            ("reservation-191",),
        ).fetchone()[0]

        assert count == 1
        assert delivery == "acknowledged"
        assert reservation == "settled"
    finally:
        store.db.close()


def test_conflicting_terminal_outcome_freezes_accounting(tmp_path) -> None:
    store = LiveControlStore(tmp_path / "live.sqlite")
    try:
        first = _post(store, actual_delta=7)
        with pytest.raises(
            TerminalAccountingConflict, match="PR191_TERMINAL_ACCOUNTING_CONFLICT"
        ):
            _post(store, actual_delta=8)

        count = store.db.execute(
            "SELECT COUNT(*) FROM live_actual_outcomes WHERE terminal_id=?",
            (first.terminal_id,),
        ).fetchone()[0]
        conflicts = store.db.execute(
            "SELECT COUNT(*) FROM live_accounting_conflicts WHERE terminal_id=?",
            (first.terminal_id,),
        ).fetchone()[0]
        frozen = store.db.execute(
            "SELECT conflict_state FROM live_actual_outcomes WHERE id=?",
            (first.outcome_id,),
        ).fetchone()[0]

        assert count == 1
        assert conflicts == 1
        assert frozen == "frozen"
        assert store.active_latch() is not None
    finally:
        store.db.close()


def test_correction_is_new_append_only_record(tmp_path) -> None:
    store = LiveControlStore(tmp_path / "live.sqlite")
    try:
        original = _post(store, operation="actual")
        correction = record_actual_outcome(
            store,
            attempt_id="attempt-191",
            attempt_generation=3,
            config_hash=HASH_A,
            asset="SOL",
            finalized_signature="signature-191",
            settlement_evidence_hash=HASH_B,
            accounting_operation="correction-1",
            actual_delta=6,
            simulated_delta=7,
            tolerance=1,
            provenance={
                "settlement_evidence_hash": HASH_B,
                "reason": "provider correction",
            },
            correction_of=original.outcome_id,
        )

        rows = store.db.execute(
            """
            SELECT id,actual_delta,supersedes_outcome_id
            FROM live_actual_outcomes ORDER BY id
            """
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["actual_delta"] == 7
        assert rows[1]["actual_delta"] == 6
        assert correction.supersedes_outcome_id == original.outcome_id
    finally:
        store.db.close()

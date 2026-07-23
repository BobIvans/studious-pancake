from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.durability.mpr19_economic_authority import (
    AttemptRequest,
    AttemptState,
    MPR19AuthorityError,
    MPR19EconomicAuthority,
    OutboxState,
    ReservationState,
)


def _request(**overrides: object) -> AttemptRequest:
    data: dict[str, object] = {
        "opportunity_id": "opp-001",
        "wallet_id": "wallet-001",
        "strategy": "recorded-paper-arb",
        "capital_lamports": 100_000,
        "payload": {"route": ["marginfi", "jupiter"], "slot": 123},
    }
    data.update(overrides)
    return AttemptRequest(**data)  # type: ignore[arg-type]


def test_attempt_terminal_outbox_and_replay_are_one_durable_authority(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime" / "mpr19.sqlite3"
    with MPR19EconomicAuthority(db_path) as authority:
        created = authority.create_attempt(_request(), now_ns=1)
        assert created.state is AttemptState.RECORDED
        assert created.reservation_state is ReservationState.ACTIVE
        assert created.revision == 1

        terminal = authority.terminalize_attempt(
            attempt_id=created.attempt_id,
            expected_revision=1,
            terminal_state=AttemptState.REJECTED,
            reservation_state=ReservationState.RELEASED,
            reason_code="rejected_no_profit",
            now_ns=2,
        )
        assert terminal.state is AttemptState.REJECTED
        assert terminal.reservation_state is ReservationState.RELEASED
        assert terminal.revision == 2

        first_claim = authority.claim_outbox(
            owner_id="publisher-a", now_ns=3, lease_ttl_ns=10
        )
        assert first_claim is not None
        assert authority.complete_outbox(
            first_claim, delivered=True, reason_code="published", now_ns=4
        ) is OutboxState.DELIVERED

        report = authority.verify_replay_integrity()
        assert report.event_count == 2
        assert report.terminal_count == 1
        assert report.outbox_pending_count == 1


def test_statement_level_crash_probe_rolls_back_every_partial_write(
    tmp_path: Path,
) -> None:
    for step in (
        "attempt_inserted",
        "reservation_inserted",
        "journal_appended",
        "outbox_queued",
    ):
        db_path = tmp_path / f"{step}.sqlite3"
        authority = MPR19EconomicAuthority(db_path)

        def fail_after(observed: str) -> None:
            if observed == step:
                raise RuntimeError(f"crash-after-{step}")

        with pytest.raises(RuntimeError, match=f"crash-after-{step}"):
            authority.create_attempt(_request(), now_ns=10, step_hook=fail_after)
        authority.close()

        with sqlite3.connect(db_path) as connection:
            for table in (
                "mpr19_attempts",
                "mpr19_capital_reservations",
                "mpr19_event_journal",
                "mpr19_outbox_events",
            ):
                assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_canonical_identity_rejects_bool_float_and_delimiter_collisions() -> None:
    left = _request(opportunity_id="ab", wallet_id="c")
    right = _request(opportunity_id="a", wallet_id="bc")
    assert left.attempt_id != right.attempt_id

    with pytest.raises(ValueError, match="bool/float/NaN"):
        _request(payload={"slot": True})
    with pytest.raises(ValueError, match="bool/float/NaN"):
        _request(payload={"edge": 1.25})
    with pytest.raises(ValueError, match="negative"):
        _request(payload={"slot": -1})


def test_revision_cas_failure_preserves_active_reservation(tmp_path: Path) -> None:
    with MPR19EconomicAuthority(tmp_path / "cas.sqlite3") as authority:
        created = authority.create_attempt(_request(), now_ns=1)
        with pytest.raises(MPR19AuthorityError, match="REVISION_MISMATCH"):
            authority.terminalize_attempt(
                attempt_id=created.attempt_id,
                expected_revision=99,
                terminal_state=AttemptState.FAILED,
                reservation_state=ReservationState.FROZEN,
                reason_code="wrong_revision",
                now_ns=2,
            )
        row = authority.db.execute(
            "SELECT state FROM mpr19_capital_reservations WHERE attempt_id=?",
            (created.attempt_id,),
        ).fetchone()
        assert row[0] == ReservationState.ACTIVE.value
        assert authority.verify_replay_integrity().terminal_count == 0


def test_outbox_stale_owner_cannot_complete_after_reclaim(tmp_path: Path) -> None:
    with MPR19EconomicAuthority(tmp_path / "outbox.sqlite3") as authority:
        authority.create_attempt(_request(), now_ns=1)
        first = authority.claim_outbox(owner_id="publisher-a", now_ns=2, lease_ttl_ns=5)
        assert first is not None
        second = authority.claim_outbox(owner_id="publisher-b", now_ns=8, lease_ttl_ns=5)
        assert second is not None
        assert second.event_id == first.event_id

        with pytest.raises(MPR19AuthorityError, match="STALE_OWNER"):
            authority.complete_outbox(
                first, delivered=True, reason_code="late-publish", now_ns=9
            )
        assert authority.complete_outbox(
            second, delivered=False, reason_code="dead-lettered", now_ns=9
        ) is OutboxState.DEAD_LETTER


def test_replay_detects_materialized_state_tampering(tmp_path: Path) -> None:
    with MPR19EconomicAuthority(tmp_path / "tamper.sqlite3") as authority:
        created = authority.create_attempt(_request(), now_ns=1)
        authority.db.execute(
            "UPDATE mpr19_attempts SET state=? WHERE attempt_id=?",
            (AttemptState.COMPLETED.value, created.attempt_id),
        )
        with pytest.raises(MPR19AuthorityError, match="STATE_DIVERGED"):
            authority.verify_replay_integrity()


def test_backup_restore_is_verified_before_activation(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    backup = tmp_path / "backup" / "source.sqlite3"
    restored = tmp_path / "restore" / "source.sqlite3"

    with MPR19EconomicAuthority(source) as authority:
        created = authority.create_attempt(_request(), now_ns=1)
        authority.terminalize_attempt(
            attempt_id=created.attempt_id,
            expected_revision=1,
            terminal_state=AttemptState.COMPLETED,
            reservation_state=ReservationState.CONSUMED,
            reason_code="paper-completed",
            now_ns=2,
        )
        authority.backup_to(backup)

    restored_authority = MPR19EconomicAuthority.restore_verified(backup, restored)
    try:
        report = restored_authority.verify_replay_integrity()
        assert report.event_count == 2
        assert report.terminal_count == 1
    finally:
        restored_authority.close()

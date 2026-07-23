from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from src.pr206_durable_state import (
    DurableDeadlineError,
    ManualLifecycleClock,
    MigrationDriftError,
    PR206DurableStateStore,
    ProjectionMismatchError,
    ReservationConflictError,
    SemanticIdempotencyCollision,
)
from src.pr195_durable_kernel_v3 import (
    complete_offline_claim,
    evaluate_pr195_durable_kernel,
)
from src.pr195_durable_lifecycle import DuplicateLifecycleKeyError


def _path(tmp_path):
    return tmp_path / "pr206.sqlite"


def _store(tmp_path, clock: ManualLifecycleClock | None = None):
    return PR206DurableStateStore(
        _path(tmp_path),
        trusted_clock=clock or ManualLifecycleClock(),
    )


def test_pr206_reboot_uses_durable_utc_deadline(tmp_path) -> None:
    clock = ManualLifecycleClock(monotonic_ns=10, utc_ns=1_000)
    path = _path(tmp_path)
    with PR206DurableStateStore(path, trusted_clock=clock) as store:
        store.admit_opportunity(
            opportunity_id="opp-a",
            lifecycle_key="route-a",
            expires_after_ns=100,
            terminal_retention_ns=10,
            idempotency_key="admit-a",
        )

    clock.reboot(boot_id="boot-b")
    clock.utc_ns += 101
    with PR206DurableStateStore(path, trusted_clock=clock) as restarted:
        expired = restarted.expire_due_opportunities(terminal_retention_ns=10)
        assert [item.opportunity_id for item in expired] == ["opp-a"]
        assert restarted.get_opportunity("opp-a").state == "expired"


def test_pr206_reboot_rebases_legacy_monotonic_deadline(tmp_path) -> None:
    clock = ManualLifecycleClock(monotonic_ns=500, utc_ns=10_000)
    path = _path(tmp_path)
    with PR206DurableStateStore(path, trusted_clock=clock) as store:
        store.admit_opportunity(
            opportunity_id="opp-a",
            lifecycle_key="route-a",
            expires_after_ns=200,
            terminal_retention_ns=10,
            idempotency_key="admit-a",
        )
    clock.reboot(boot_id="boot-b")
    clock.utc_ns += 50
    with PR206DurableStateStore(path, trusted_clock=clock) as restarted:
        row = restarted.db.execute(
            "SELECT expires_monotonic_ns FROM pr195_opportunities "
            "WHERE opportunity_id='opp-a'"
        ).fetchone()
        assert int(row[0]) == 150


def test_pr206_utc_rollback_fails_closed(tmp_path) -> None:
    clock = ManualLifecycleClock(monotonic_ns=10, utc_ns=1_000)
    path = _path(tmp_path)
    PR206DurableStateStore(path, trusted_clock=clock).close()
    clock.reboot(boot_id="boot-b")
    clock.utc_ns = 999
    with pytest.raises(DurableDeadlineError, match="UTC moved backwards"):
        PR206DurableStateStore(path, trusted_clock=clock)


def test_pr206_admission_replay_requires_same_request_digest(tmp_path) -> None:
    with _store(tmp_path) as store:
        first = store.admit_opportunity(
            opportunity_id="opp-a",
            lifecycle_key="route-a",
            expires_after_ns=100,
            terminal_retention_ns=10,
            idempotency_key="same-key",
            evidence={"slot": 1},
        )
        replay = store.admit_opportunity(
            opportunity_id="opp-a",
            lifecycle_key="route-a",
            expires_after_ns=100,
            terminal_retention_ns=10,
            idempotency_key="same-key",
            evidence={"slot": 1},
        )
        assert replay == first
        with pytest.raises(SemanticIdempotencyCollision):
            store.admit_opportunity(
                opportunity_id="opp-b",
                lifecycle_key="route-b",
                expires_after_ns=100,
                terminal_retention_ns=10,
                idempotency_key="same-key",
                evidence={"slot": 2},
            )


def test_pr206_transition_replay_binds_full_command(tmp_path) -> None:
    with _store(tmp_path) as store:
        store.admit_opportunity(
            opportunity_id="opp-a",
            lifecycle_key="route-a",
            expires_after_ns=100,
            terminal_retention_ns=10,
            idempotency_key="admit-a",
        )
        first = store.claim_opportunity(
            opportunity_id="opp-a",
            expected_revision=0,
            idempotency_key="transition-a",
            evidence={"worker": "one"},
        )
        replay = store.claim_opportunity(
            opportunity_id="opp-a",
            expected_revision=0,
            idempotency_key="transition-a",
            evidence={"worker": "one"},
        )
        assert replay == first
        with pytest.raises(SemanticIdempotencyCollision):
            store.finish_opportunity(
                opportunity_id="opp-a",
                expected_revision=0,
                target_state="released",
                terminal_retention_ns=10,
                idempotency_key="transition-a",
                reason_code="DIFFERENT_COMMAND",
            )


def test_pr206_wallet_replay_is_namespaced_and_semantic(tmp_path) -> None:
    with _store(tmp_path) as store:
        first = store.reserve_wallet_lamports(
            reservation_id="res-a",
            wallet_id="wallet-a",
            attempt_id="attempt-a",
            lamports=600,
            wallet_limit_lamports=1_000,
            idempotency_key="reserve",
        )
        replay = store.reserve_wallet_lamports(
            reservation_id="res-a",
            wallet_id="wallet-a",
            attempt_id="attempt-a",
            lamports=600,
            wallet_limit_lamports=1_000,
            idempotency_key="reserve",
        )
        assert replay == first
        with pytest.raises(SemanticIdempotencyCollision):
            store.reserve_wallet_lamports(
                reservation_id="res-b",
                wallet_id="wallet-a",
                attempt_id="attempt-b",
                lamports=1,
                wallet_limit_lamports=1_000,
                idempotency_key="reserve",
            )
        other_wallet = store.reserve_wallet_lamports(
            reservation_id="res-c",
            wallet_id="wallet-b",
            attempt_id="attempt-c",
            lamports=1,
            wallet_limit_lamports=1_000,
            idempotency_key="reserve",
        )
        assert other_wallet.wallet_id == "wallet-b"


def test_pr206_terminal_fee_replay_conflict_is_rejected(tmp_path) -> None:
    with _store(tmp_path) as store:
        store.reserve_wallet_lamports(
            reservation_id="res-a",
            wallet_id="wallet-a",
            attempt_id="attempt-a",
            lamports=600,
            wallet_limit_lamports=1_000,
            idempotency_key="reserve-a",
        )
        first = store.release_wallet_reservation(
            reservation_id="res-a",
            expected_revision=0,
            charged_fee_lamports=5,
            idempotency_key="release-a",
            principal="wallet-a",
        )
        replay = store.release_wallet_reservation(
            reservation_id="res-a",
            expected_revision=0,
            charged_fee_lamports=5,
            idempotency_key="release-a",
            principal="wallet-a",
        )
        assert replay == first
        with pytest.raises(SemanticIdempotencyCollision):
            store.release_wallet_reservation(
                reservation_id="res-a",
                expected_revision=0,
                charged_fee_lamports=9,
                idempotency_key="release-a",
                principal="wallet-a",
            )
        with pytest.raises(ReservationConflictError, match="settled accounting"):
            store.release_wallet_reservation(
                reservation_id="res-a",
                expected_revision=0,
                charged_fee_lamports=9,
                idempotency_key="release-b",
                principal="wallet-a",
            )


def test_pr206_migration_checksum_is_verified_on_open(tmp_path) -> None:
    path = _path(tmp_path)
    store = PR206DurableStateStore(path, trusted_clock=ManualLifecycleClock())
    store.db.execute("UPDATE pr206_migrations SET checksum='bad' WHERE version=206")
    store.close()
    with pytest.raises(MigrationDriftError):
        PR206DurableStateStore(path, trusted_clock=ManualLifecycleClock())


def test_pr206_parent_migration_checksum_is_verified(tmp_path) -> None:
    path = _path(tmp_path)
    store = PR206DurableStateStore(path, trusted_clock=ManualLifecycleClock())
    store.db.execute(
        "UPDATE pr195_durable_migrations SET checksum='bad' WHERE version=1"
    )
    store.close()
    with pytest.raises(MigrationDriftError):
        PR206DurableStateStore(path, trusted_clock=ManualLifecycleClock())


def test_pr206_materialized_projection_is_replay_verified(tmp_path) -> None:
    with _store(tmp_path) as store:
        store.admit_opportunity(
            opportunity_id="opp-a",
            lifecycle_key="route-a",
            expires_after_ns=100,
            terminal_retention_ns=10,
            idempotency_key="admit-a",
        )
        store.db.execute(
            "UPDATE pr195_opportunities SET state='terminal_success',revision=99,"
            "terminal=1 WHERE opportunity_id='opp-a'"
        )
        with pytest.raises(ProjectionMismatchError):
            store.get_opportunity("opp-a")


def test_pr206_semantic_records_and_terminal_truth_are_immutable(tmp_path) -> None:
    with _store(tmp_path) as store:
        store.reserve_wallet_lamports(
            reservation_id="res-a",
            wallet_id="wallet-a",
            attempt_id="attempt-a",
            lamports=1,
            wallet_limit_lamports=10,
            idempotency_key="reserve-a",
        )
        store.release_wallet_reservation(
            reservation_id="res-a",
            expected_revision=0,
            charged_fee_lamports=1,
            idempotency_key="release-a",
            principal="wallet-a",
        )
        with pytest.raises(sqlite3.DatabaseError):
            store.db.execute(
                "UPDATE pr206_semantic_idempotency SET result_digest='bad'"
            )
        with pytest.raises(sqlite3.DatabaseError):
            store.db.execute("DELETE FROM pr206_reservation_terminal_truth")


def test_pr206_admission_rolls_back_if_truth_write_fails(tmp_path) -> None:
    with _store(tmp_path) as store:
        store.db.execute(
            "CREATE TRIGGER fail_pr206_truth BEFORE INSERT ON "
            "pr206_opportunity_truth BEGIN SELECT RAISE(ABORT,'fault'); END"
        )
        with pytest.raises(sqlite3.DatabaseError, match="fault"):
            store.admit_opportunity(
                opportunity_id="opp-a",
                lifecycle_key="route-a",
                expires_after_ns=100,
                terminal_retention_ns=10,
                idempotency_key="admit-a",
            )
        assert (
            store.db.execute("SELECT COUNT(*) FROM pr195_opportunities").fetchone()[0]
            == 0
        )
        assert (
            store.db.execute(
                "SELECT COUNT(*) FROM pr195_opportunity_events"
            ).fetchone()[0]
            == 0
        )
        assert (
            store.db.execute("SELECT COUNT(*) FROM pr195_lifecycle_keys").fetchone()[0]
            == 0
        )


def test_pr206_reservation_rolls_back_if_digest_write_fails(tmp_path) -> None:
    with _store(tmp_path) as store:
        store.db.execute(
            "CREATE TRIGGER fail_pr206_digest BEFORE INSERT ON "
            "pr206_semantic_idempotency BEGIN SELECT RAISE(ABORT,'fault'); END"
        )
        with pytest.raises(sqlite3.DatabaseError, match="fault"):
            store.reserve_wallet_lamports(
                reservation_id="res-a",
                wallet_id="wallet-a",
                attempt_id="attempt-a",
                lamports=1,
                wallet_limit_lamports=10,
                idempotency_key="reserve-a",
            )
        assert (
            store.db.execute(
                "SELECT COUNT(*) FROM pr195_wallet_reservations"
            ).fetchone()[0]
            == 0
        )


def test_pr206_concurrent_admission_has_one_lifecycle_owner(tmp_path) -> None:
    path = _path(tmp_path)
    first = PR206DurableStateStore(path, trusted_clock=ManualLifecycleClock())
    second = PR206DurableStateStore(path, trusted_clock=ManualLifecycleClock())

    def admit(store, suffix):
        try:
            result = store.admit_opportunity(
                opportunity_id=f"opp-{suffix}",
                lifecycle_key="shared-route",
                expires_after_ns=100,
                terminal_retention_ns=10,
                idempotency_key=f"admit-{suffix}",
            )
            return result.opportunity_id
        except DuplicateLifecycleKeyError:
            return "duplicate"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda item: admit(*item),
                    ((first, "a"), (second, "b")),
                )
            )
        assert sorted(results) in (["duplicate", "opp-a"], ["duplicate", "opp-b"])
        assert (
            first.db.execute("SELECT COUNT(*) FROM pr195_lifecycle_keys").fetchone()[0]
            == 1
        )
    finally:
        first.close()
        second.close()


def test_pr206_readiness_is_derived_from_store_and_blocks_live(tmp_path) -> None:
    with _store(tmp_path) as store:
        store.admit_opportunity(
            opportunity_id="opp-a",
            lifecycle_key="route-a",
            expires_after_ns=100,
            terminal_retention_ns=10,
            idempotency_key="admit-a",
        )
        report = store.inspect_readiness()
        assert report.ready
        assert report.migration_rows_verified == 2
        assert report.projections_verified == 1
        assert report.idempotency_rows_verified == 1
        blocked = store.inspect_readiness(
            live_enabled=True,
            sender_or_signer_enabled=True,
        )
        assert not blocked.ready
        assert "LIVE_ENABLEMENT_NOT_ALLOWED_IN_PR206" in blocked.reason_codes
        assert "SENDER_OR_SIGNER_NOT_ALLOWED_IN_PR206" in blocked.reason_codes


def test_pr195_boolean_claim_is_non_authoritative_after_pr206() -> None:
    claim = complete_offline_claim(evidence_refs=("historical/pr195.json",))
    report = evaluate_pr195_durable_kernel(claim)
    assert not report.ready
    assert "PR206_AUTHORITATIVE_STORE_EVIDENCE_REQUIRED" in report.reason_codes

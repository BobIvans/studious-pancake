from __future__ import annotations

import sqlite3

import pytest

from src.pr195_durable_lifecycle import (
    CapitalReservationError,
    DuplicateLifecycleKeyError,
    DurableLifecycleStore,
    ManualLifecycleClock,
)


def _store(tmp_path, clock: ManualLifecycleClock | None = None) -> DurableLifecycleStore:
    return DurableLifecycleStore(
        tmp_path / "durable-lifecycle.sqlite",
        trusted_clock=clock or ManualLifecycleClock(),
    )


def test_pr195_expiry_releases_pending_lifecycle_key_after_retention(tmp_path) -> None:
    clock = ManualLifecycleClock(monotonic_ns=10, utc_ns=100)
    with _store(tmp_path, clock) as store:
        admitted = store.admit_opportunity(
            opportunity_id="opp-a",
            lifecycle_key="same-route-slot",
            expires_after_ns=5,
            terminal_retention_ns=10,
            idempotency_key="admit-a",
        )
        assert admitted.state == "pending"
        assert store.lifecycle_key_count() == 1

        clock.advance(6)
        expired = store.expire_due_opportunities(terminal_retention_ns=10)
        assert [row.opportunity_id for row in expired] == ["opp-a"]
        assert store.get_opportunity("opp-a").state == "expired"
        assert store.get_opportunity("opp-a").terminal is True
        assert len(store.event_hash_chain("opp-a")) == 2

        with pytest.raises(DuplicateLifecycleKeyError):
            store.admit_opportunity(
                opportunity_id="opp-b",
                lifecycle_key="same-route-slot",
                expires_after_ns=5,
                terminal_retention_ns=10,
                idempotency_key="admit-b-too-early",
            )

        clock.advance(11)
        assert store.compact_released_dedupe() == 1
        replacement = store.admit_opportunity(
            opportunity_id="opp-b",
            lifecycle_key="same-route-slot",
            expires_after_ns=5,
            terminal_retention_ns=10,
            idempotency_key="admit-b",
        )
        assert replacement.state == "pending"
        assert store.lifecycle_key_count() == 1


def test_pr195_dedupe_survives_restart_and_then_compacts(tmp_path) -> None:
    path = tmp_path / "durable-lifecycle.sqlite"
    clock = ManualLifecycleClock(monotonic_ns=1_000, utc_ns=2_000)
    store = DurableLifecycleStore(path, trusted_clock=clock)
    store.admit_opportunity(
        opportunity_id="opp-restart",
        lifecycle_key="route:key",
        expires_after_ns=10,
        terminal_retention_ns=100,
        idempotency_key="admit-restart",
    )
    clock.advance(11)
    store.expire_due_opportunities(terminal_retention_ns=100)
    store.close()

    restarted = DurableLifecycleStore(path, trusted_clock=clock)
    with restarted:
        with pytest.raises(DuplicateLifecycleKeyError):
            restarted.admit_opportunity(
                opportunity_id="opp-duplicate",
                lifecycle_key="route:key",
                expires_after_ns=10,
                terminal_retention_ns=100,
                idempotency_key="admit-duplicate",
            )

        clock.advance(101)
        assert restarted.compact_released_dedupe() == 1
        admitted = restarted.admit_opportunity(
            opportunity_id="opp-after-retention",
            lifecycle_key="route:key",
            expires_after_ns=10,
            terminal_retention_ns=100,
            idempotency_key="admit-after-retention",
        )
        assert admitted.opportunity_id == "opp-after-retention"


def test_pr195_idempotent_admission_replays_same_opportunity_without_new_event(tmp_path) -> None:
    with _store(tmp_path) as store:
        first = store.admit_opportunity(
            opportunity_id="opp-idem",
            lifecycle_key="route:idempotent",
            expires_after_ns=100,
            terminal_retention_ns=100,
            idempotency_key="same-admit",
        )
        replay = store.admit_opportunity(
            opportunity_id="opp-idem",
            lifecycle_key="route:idempotent",
            expires_after_ns=100,
            terminal_retention_ns=100,
            idempotency_key="same-admit",
        )

        assert replay == first
        assert len(store.event_hash_chain("opp-idem")) == 1


def test_pr195_finish_terminal_bounds_dedupe_cardinality(tmp_path) -> None:
    clock = ManualLifecycleClock(monotonic_ns=50, utc_ns=70)
    with _store(tmp_path, clock) as store:
        store.admit_opportunity(
            opportunity_id="opp-terminal",
            lifecycle_key="route:terminal",
            expires_after_ns=100,
            terminal_retention_ns=20,
            idempotency_key="admit-terminal",
        )
        finished = store.finish_opportunity(
            opportunity_id="opp-terminal",
            expected_revision=0,
            target_state="released",
            terminal_retention_ns=20,
            idempotency_key="finish-terminal",
            reason_code="NOT_ECONOMIC",
        )
        assert finished.state == "released"
        assert finished.dedupe_block_until_monotonic_ns == 70

        clock.advance(21)
        assert store.compact_released_dedupe() == 1
        assert store.lifecycle_key_count() == 0
        assert len(store.event_hash_chain("opp-terminal")) == 2


def test_pr195_wallet_reservation_is_serialized_and_idempotent(tmp_path) -> None:
    with _store(tmp_path) as store:
        first = store.reserve_wallet_lamports(
            reservation_id="res-a",
            wallet_id="wallet-a",
            attempt_id="attempt-a",
            lamports=600,
            wallet_limit_lamports=1_000,
            idempotency_key="reserve-a",
        )
        replay = store.reserve_wallet_lamports(
            reservation_id="res-a",
            wallet_id="wallet-a",
            attempt_id="attempt-a",
            lamports=600,
            wallet_limit_lamports=1_000,
            idempotency_key="reserve-a",
        )
        assert replay == first
        assert store.active_reserved_lamports("wallet-a") == 600

        with pytest.raises(CapitalReservationError):
            store.reserve_wallet_lamports(
                reservation_id="res-b",
                wallet_id="wallet-a",
                attempt_id="attempt-b",
                lamports=500,
                wallet_limit_lamports=1_000,
                idempotency_key="reserve-b",
            )

        released = store.release_wallet_reservation(
            reservation_id="res-a",
            expected_revision=0,
            charged_fee_lamports=5,
        )
        assert released.state == "charged_failure"
        assert released.charged_fee_lamports == 5
        assert store.active_reserved_lamports("wallet-a") == 0

        store.reserve_wallet_lamports(
            reservation_id="res-b",
            wallet_id="wallet-a",
            attempt_id="attempt-b",
            lamports=500,
            wallet_limit_lamports=1_000,
            idempotency_key="reserve-b",
        )
        assert store.active_reserved_lamports("wallet-a") == 500


def test_pr195_opportunity_events_are_immutable(tmp_path) -> None:
    with _store(tmp_path) as store:
        store.admit_opportunity(
            opportunity_id="opp-immutable",
            lifecycle_key="route:immutable",
            expires_after_ns=100,
            terminal_retention_ns=100,
            idempotency_key="admit-immutable",
        )

        with pytest.raises(sqlite3.DatabaseError):
            store.db.execute(
                "UPDATE pr195_opportunity_events SET reason_code='MUTATED' "
                "WHERE opportunity_id='opp-immutable'"
            )

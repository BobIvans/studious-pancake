"""Exercise the production SQLite owner; no shared-store or mutex substitute."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest

from src.durability import DurableLifecycleError, DurableLifecycleStore
from src.economics.capital import CapitalEngineError
from src.economics.durable_reservations import DurableCapitalCoordinator
from tests.test_pr057_durable_capital_reservations import (
    _candidate,
    _key,
    _policy,
    _snapshot,
)


def reserve(store, name="first", **changes):
    args = dict(
        wallet_snapshot=_snapshot(16_000_000),
        attempt_key=_key(name),
        idempotency_key=f"reserve:{name}",
    )
    args.update(changes)
    return DurableCapitalCoordinator(store=store, policy=_policy()).reserve(
        _candidate(name, peak_rent_lamports=4_000_000), **args
    )


def test_two_connections_cannot_both_spend_same_balance(tmp_path, monkeypatch):
    path = tmp_path / "journal.db"
    first_read = Event()
    contender = Event()
    original = DurableCapitalCoordinator._ledger_for_snapshot

    with DurableLifecycleStore(path) as left, DurableLifecycleStore(path) as right:
        assert left.db is not right.db

        def trace(sql):
            if sql == "BEGIN IMMEDIATE":
                contender.set()

        right.db.set_trace_callback(trace)

        def controlled(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            if self.store is left:
                first_read.set()
                assert contender.wait(5), "second connection never attempted admission"
            else:
                # Before the fix this runs without a writer lock and records the
                # same zero commitments. After the fix BEGIN above blocks first.
                contender.set()
            return result

        monkeypatch.setattr(
            DurableCapitalCoordinator, "_ledger_for_snapshot", controlled
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(reserve, left, "first")
            assert first_read.wait(5)
            second = pool.submit(reserve, right, "second")
            results = [first.result(timeout=10), second.result(timeout=10)]
        assert sum(item.decision.allowed for item in results) == 1
        assert left.count_rows("durable_reservations") == 1
        assert (
            left.db.execute(
                "SELECT SUM(amount_lamports) FROM durable_reservations WHERE state='active'"
            ).fetchone()[0]
            == 4_555_000
        )


def test_restart_replays_same_decision_without_second_effect(tmp_path):
    path = tmp_path / "journal.db"
    with DurableLifecycleStore(path) as store:
        first = reserve(store)
    with DurableLifecycleStore(path) as store:
        replay = reserve(store, wallet_snapshot=first.wallet_snapshot)
        assert replay == first
        for table in (
            "durable_attempts",
            "durable_reservations",
            "durable_events",
            "durable_outbox",
        ):
            assert store.count_rows(table) == 1


@pytest.mark.parametrize("surface", ["store", "connection", "cursor", "iteration"])
def test_shared_connection_reader_cannot_observe_rolled_back_attempt(surface):
    started = Event()
    with DurableLifecycleStore(":memory:") as store:

        def read():
            started.set()
            if surface == "store":
                return store.get_attempt(_key("uncommitted").attempt_id)
            cursor = store.db.cursor() if surface == "cursor" else store.db
            result = cursor.execute("SELECT * FROM durable_attempts")
            if surface == "iteration":
                return next(iter(result), None)
            return result.fetchone()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with pytest.raises(RuntimeError, match="rollback"):
                with store.write_transaction():
                    store.create_attempt(
                        _key("uncommitted"), idempotency_key="uncommitted"
                    )
                    pending = pool.submit(read)
                    assert started.wait(5)
                    with pytest.raises(TimeoutError):
                        pending.result(timeout=0.1)
                    raise RuntimeError("rollback")
            assert pending.result(timeout=5) is None
        assert store.count_rows("durable_attempts") == 0


@pytest.mark.parametrize(
    "field", ["wallet", "amount", "message", "generation", "policy"]
)
def test_semantic_drift_is_rejected_without_writes(field):
    with DurableLifecycleStore(":memory:") as store:
        first = reserve(store)
        candidate = _candidate("first", peak_rent_lamports=4_000_000)
        snapshot = first.wallet_snapshot
        key = _key("first")
        policy = _policy()
        if field == "wallet":
            snapshot = replace(snapshot, wallet_pubkey="different-wallet")
        elif field == "amount":
            candidate = replace(candidate, requested_flash_loan_lamports=999)
        elif field == "message":
            candidate = replace(candidate, message_hash="different-message")
        elif field == "generation":
            key = replace(key, generation=2)
        else:
            policy = replace(policy, contingency_lamports=500_001)
        with pytest.raises(CapitalEngineError, match="IDEMPOTENCY_SEMANTIC_CONFLICT"):
            DurableCapitalCoordinator(store=store, policy=policy).reserve(
                candidate,
                wallet_snapshot=snapshot,
                attempt_key=key,
                idempotency_key="reserve:first",
            )
        assert store.count_rows("durable_events") == 1
        assert store.count_rows("durable_reservations") == 1


@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
def test_caller_rollback_cannot_be_committed_by_nested_create(error):
    with DurableLifecycleStore(":memory:") as store:
        with pytest.raises(error):
            with store.write_transaction():
                reserve(store)
                raise error("fault after nested create")
        for table in (
            "durable_attempts",
            "durable_reservations",
            "durable_events",
            "durable_outbox",
        ):
            assert store.count_rows(table) == 0


def test_outbox_failure_rolls_back_attempt_and_reservation(monkeypatch):
    with DurableLifecycleStore(":memory:") as store:
        original = store._event

        def fail(**kwargs):
            original(**kwargs)
            raise RuntimeError("fault after outbox insert")

        monkeypatch.setattr(store, "_event", fail)
        with pytest.raises(RuntimeError, match="outbox insert"):
            reserve(store)
        for table in (
            "durable_attempts",
            "durable_reservations",
            "durable_events",
            "durable_outbox",
        ):
            assert store.count_rows(table) == 0


def test_create_attempt_replay_rejects_changed_payload():
    with DurableLifecycleStore(":memory:") as store:
        key = _key("direct")
        store.create_attempt(key, idempotency_key="direct", payload={"amount": 1})
        with pytest.raises(
            DurableLifecycleError, match="IDEMPOTENCY_SEMANTIC_CONFLICT"
        ):
            store.create_attempt(key, idempotency_key="direct", payload={"amount": 2})
        assert store.count_rows("durable_events") == 1

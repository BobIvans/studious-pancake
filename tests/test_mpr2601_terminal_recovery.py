"""Fault injection against the canonical owner and its real SQLite connection."""

import asyncio
from dataclasses import replace
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from src.durability import AttemptKey, DurableLifecycleStore
from src.durability.unified_authority_pr02 import (
    ReservationTerminalState,
    UnifiedAuthorityError,
    UnifiedLifecycleAuthority,
)
from src.economics.durable_reservations import DurableCapitalCoordinator
from src.execution.models import ExecutionState
from test_pr02_unified_lifecycle_authority import FakeTimeAuthority, begin_cycle, digest
from test_pr057_durable_capital_reservations import _policy


@pytest.fixture(params=["memory", "file"])
def owner(request, tmp_path):
    path = ":memory:" if request.param == "memory" else tmp_path / "authority.db"
    with UnifiedLifecycleAuthority(
        path,
        release_digest=digest("release"),
        policy_bundle_hash=digest("policy"),
        time_authority=FakeTimeAuthority(),
        owner_id="worker-a",
        lease_ttl_ns=1_000,
    ) as value:
        yield value


def terminal(owner, fence, **changes):
    values = dict(
        outcome="BLOCKED",
        reason_code="NO_VERIFIED_WORK",
        report_hash=digest("report"),
        report_payload={"status": "BLOCKED"},
        provider_evidence_hash=digest("provider"),
        ready_for_next_cycle=False,
        source_surface="installed-cli",
    )
    values.update(changes)
    return owner.commit_cycle_terminal(fence, **values)


@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
def test_projection_fault_rolls_back_terminal_and_both_outboxes(
    owner, monkeypatch, error
):
    fence = begin_cycle(owner)

    def fail(*args, **kwargs):
        raise error("projection fault")

    monkeypatch.setattr(owner, "_write_a3_projection", fail)
    with pytest.raises(error):
        terminal(owner, fence)
    for table in (
        "pr02_terminal_records",
        "pr02_outbox_event",
        "pr02_outbox_delivery",
        "a3_paper_service_cycles",
        "a3_paper_service_outbox",
    ):
        assert owner.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert (
        owner.db.execute("SELECT terminal_id FROM pr02_intents").fetchone()[0] is None
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_id", "foreign"),
        ("fencing_token", 7),
        ("boot_id", "foreign"),
        ("process_generation", 7),
    ],
)
def test_stale_fence_cannot_commit(owner, field, value):
    fence = replace(begin_cycle(owner), **{field: value})
    with pytest.raises(UnifiedAuthorityError, match="FENCE"):
        terminal(owner, fence)
    assert (
        owner.db.execute("SELECT COUNT(*) FROM pr02_terminal_records").fetchone()[0]
        == 0
    )


def test_terminal_payload_drift_has_no_second_effect(owner):
    fence = begin_cycle(owner)
    first = terminal(owner, fence)
    assert terminal(owner, fence).replayed
    with pytest.raises(UnifiedAuthorityError, match="IMMUTABILITY"):
        terminal(owner, fence, report_payload={"status": "different"})
    assert (
        owner.db.execute("SELECT event_id FROM pr02_outbox_event").fetchone()[0]
        == first.outbox_event_id
    )
    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE"):
        owner.db.execute("UPDATE pr02_terminal_records SET outcome='different'")


def test_same_cycle_key_cannot_change_semantic_request(owner):
    begin_cycle(owner)
    with pytest.raises(UnifiedAuthorityError, match="IMMUTABILITY"):
        owner.begin_cycle_intent(
            run_id="run-a",
            sequence=1,
            config_fingerprint=digest("changed"),
            source_surface="installed-cli",
        )
    assert owner.db.execute("SELECT COUNT(*) FROM pr02_intents").fetchone()[0] == 1


def test_unresolved_intent_after_reboot_requires_reconciliation(owner):
    begin_cycle(owner)
    owner.time_authority.reboot()
    with pytest.raises(UnifiedAuthorityError, match="REQUIRES_RECONCILIATION"):
        begin_cycle(owner)
    assert (
        owner.db.execute("SELECT COUNT(*) FROM pr02_terminal_records").fetchone()[0]
        == 0
    )


def test_reopened_terminal_exact_replay_has_no_new_effect(tmp_path):
    path = tmp_path / "reopen.db"
    kwargs = dict(
        release_digest=digest("release"),
        policy_bundle_hash=digest("policy"),
        time_authority=FakeTimeAuthority(),
        owner_id="worker-a",
        lease_ttl_ns=1_000,
    )
    with UnifiedLifecycleAuthority(path, **kwargs) as first:
        fence = begin_cycle(first)
        committed = terminal(first, fence)
    kwargs["time_authority"].reboot()
    kwargs["owner_id"] = "worker-b"
    with UnifiedLifecycleAuthority(path, **kwargs) as reopened:
        before = reopened.db.total_changes
        replay = terminal(reopened, fence)
        assert replay.replayed and replay.terminal_id == committed.terminal_id
        assert reopened.db.total_changes == before


def test_frozen_terminal_reservation_still_reduces_available_capital(owner):
    key = AttemptKey("ambiguous", "a" * 64, 1)
    attempt = owner.lifecycle.create_attempt(
        key,
        idempotency_key="reserve",
        candidate_id="candidate",
        reservation_id="reservation",
        reserved_lamports=4_555_000,
    )
    fence = owner.begin_attempt_intent(
        attempt_id=attempt.attempt_id,
        attempt_generation=1,
        request_payload={"candidate": "candidate"},
    )
    owner.commit_attempt_terminal(
        fence,
        target_state=ExecutionState.REJECTED,
        reservation_terminal_state=ReservationTerminalState.FROZEN,
        outcome="INDETERMINATE",
        reason_code="AMBIGUOUS",
        report_hash=digest("report"),
        report_payload={"ambiguous": True},
    )
    coordinator = DurableCapitalCoordinator(store=owner.lifecycle, policy=_policy())
    assert coordinator.active_durable_reserved_lamports() == 4_555_000


@pytest.mark.parametrize("committed", [False, True])
def test_process_exit_preserves_only_committed_effects(tmp_path, committed):
    path = tmp_path / "crash.db"
    code = """
import os, sys
from src.durability import AttemptKey, DurableLifecycleStore
store = DurableLifecycleStore(sys.argv[1])
with store.write_transaction():
    store.create_attempt(AttemptKey('crash', 'a' * 64, 1), idempotency_key='create',
        reservation_id='reservation', candidate_id='candidate', reserved_lamports=1)
    if sys.argv[2] == 'False':
        os._exit(73)
os._exit(73)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(path), str(committed)],
        cwd=Path(__file__).resolve().parents[1],
        timeout=20,
    )
    assert result.returncode == 73
    with DurableLifecycleStore(path) as store:
        for table in (
            "durable_attempts",
            "durable_reservations",
            "durable_events",
            "durable_outbox",
        ):
            assert store.count_rows(table) == int(committed)


def test_writer_contention_is_bounded_and_writes_nothing(tmp_path):
    path = tmp_path / "busy.db"
    with (
        DurableLifecycleStore(path) as first,
        DurableLifecycleStore(path, busy_timeout_ms=10) as second,
    ):
        with first.write_transaction():
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                second.create_attempt(
                    AttemptKey("busy", "a" * 64, 1), idempotency_key="busy"
                )
        assert second.count_rows("durable_attempts") == 0

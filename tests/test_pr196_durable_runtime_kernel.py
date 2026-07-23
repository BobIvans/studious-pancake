from __future__ import annotations

import asyncio
import hashlib

import pytest

from src.durability.runtime_kernel_pr196 import (
    PR196ContinuousSupervisor,
    PR196FenceLost,
    PR196LeaseBusy,
    PR196OutboxState,
    PR196RecoveryAction,
    PR196RuntimeKernelStore,
    PR196State,
    PR196SupervisorConfig,
    PR196SupervisorState,
    PR196AttemptIdentity,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _identity(name: str = "opportunity") -> PR196AttemptIdentity:
    return PR196AttemptIdentity(
        opportunity_identity=name,
        evidence_generation=7,
        plan_hash=_sha("plan"),
        attempt_generation=2,
    )


def test_stable_identity_replay_does_not_duplicate_terminal_outbox(tmp_path):
    store = PR196RuntimeKernelStore(tmp_path / "kernel.sqlite3")
    identity = _identity()

    first = store.admit_attempt(identity, admitted_at_ns=10)
    second = store.admit_attempt(identity, admitted_at_ns=20)

    assert first.attempt_id == second.attempt_id
    lease = store.acquire_lease(
        identity,
        owner_id="worker-a",
        now_ns=30,
        lease_ttl_ns=100,
    )
    report = store.terminalize(
        lease,
        state=PR196State.COMPLETED,
        reason="paper_reconciled",
        payload={"net_lamports": 0},
        now_ns=40,
    )
    replay = store.terminalize(
        lease,
        state=PR196State.COMPLETED,
        reason="paper_reconciled",
        payload={"net_lamports": 0},
        now_ns=50,
    )

    assert replay.terminal_hash == report.terminal_hash
    outbox = store.list_outbox()
    assert len(outbox) == 1
    assert outbox[0].attempt_id == identity.attempt_id
    assert outbox[0].state is PR196OutboxState.PENDING


def test_two_process_fencing_steals_stale_lease_and_rejects_old_writer(tmp_path):
    store = PR196RuntimeKernelStore(tmp_path / "kernel.sqlite3")
    identity = _identity()

    old_lease = store.acquire_lease(
        identity,
        owner_id="old-worker",
        now_ns=100,
        lease_ttl_ns=50,
    )
    with pytest.raises(PR196LeaseBusy):
        store.acquire_lease(
            identity,
            owner_id="new-worker",
            now_ns=120,
            lease_ttl_ns=50,
        )

    new_lease = store.acquire_lease(
        identity,
        owner_id="new-worker",
        now_ns=200,
        lease_ttl_ns=50,
    )

    assert new_lease.fencing_token == old_lease.fencing_token + 1
    with pytest.raises(PR196FenceLost):
        store.terminalize(
            old_lease,
            state=PR196State.FAILED,
            reason="stale_writer",
            payload={},
            now_ns=210,
        )
    report = store.terminalize(
        new_lease,
        state=PR196State.BLOCKED,
        reason="safe_blocked",
        payload={"owner": "new-worker"},
        now_ns=220,
    )
    assert report.state is PR196State.BLOCKED


def test_recovery_scanner_separates_stale_leases_and_pending_outbox(tmp_path):
    store = PR196RuntimeKernelStore(tmp_path / "kernel.sqlite3")
    identity = _identity()
    lease = store.acquire_lease(
        identity,
        owner_id="worker-a",
        now_ns=1_000,
        lease_ttl_ns=100,
    )

    stale_items = store.recovery_scan(now_ns=1_200)
    assert any(
        item.action is PR196RecoveryAction.STEAL_STALE_LEASE
        for item in stale_items
    )

    stolen = store.acquire_lease(
        identity,
        owner_id="worker-b",
        now_ns=1_300,
        lease_ttl_ns=100,
    )
    store.terminalize(
        stolen,
        state=PR196State.INCOMPLETE,
        reason="forced_shutdown",
        payload={"previous_fence": lease.fencing_token},
        now_ns=1_350,
    )

    redrive_items = store.recovery_scan(now_ns=1_360)
    assert any(
        item.action is PR196RecoveryAction.DELIVER_OUTBOX
        for item in redrive_items
    )


def test_outbox_claim_and_publish_are_fenced(tmp_path):
    store = PR196RuntimeKernelStore(tmp_path / "kernel.sqlite3")
    identity = _identity()
    lease = store.acquire_lease(
        identity,
        owner_id="worker",
        now_ns=10,
        lease_ttl_ns=100,
    )
    store.terminalize(
        lease,
        state=PR196State.COMPLETED,
        reason="done",
        payload={"ok": True},
        now_ns=20,
    )
    event = store.list_outbox()[0]

    claimed = store.claim_outbox(event.event_id, owner_id="publisher", now_ns=30)
    assert claimed.state is PR196OutboxState.CLAIMED
    with pytest.raises(PR196FenceLost):
        store.mark_outbox_published(
            event.event_id,
            owner_id="different-publisher",
            now_ns=40,
        )
    published = store.mark_outbox_published(
        event.event_id,
        owner_id="publisher",
        now_ns=50,
    )
    assert published.state is PR196OutboxState.PUBLISHED


def test_backup_restore_preserves_attempt_and_outbox_hashes(tmp_path):
    source = tmp_path / "source.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    store = PR196RuntimeKernelStore(source)
    identity = _identity()
    lease = store.acquire_lease(
        identity,
        owner_id="worker",
        now_ns=10,
        lease_ttl_ns=100,
    )
    store.terminalize(
        lease,
        state=PR196State.COMPLETED,
        reason="done",
        payload={"ok": True},
        now_ns=20,
    )

    manifest = store.backup(backup, now_ns=30)
    restored = PR196RuntimeKernelStore(tmp_path / "restored.sqlite3")
    restored.restore_from_backup(backup, expected_sha256=manifest.database_sha256)

    assert restored.integrity_check() == "ok"
    assert (
        restored.list_outbox()[0].payload_hash
        == store.list_outbox()[0].payload_hash
    )


@pytest.mark.asyncio
async def test_supervisor_marks_mandatory_worker_failure_as_unready(tmp_path):
    store = PR196RuntimeKernelStore(tmp_path / "kernel.sqlite3")
    identity = _identity()

    async def failing_runner(_lease):
        raise RuntimeError("boom")

    supervisor = PR196ContinuousSupervisor(
        store,
        identity_source=lambda: identity,
        cycle_runner=failing_runner,
        config=PR196SupervisorConfig(
            owner_id="supervisor",
            max_cycles=1,
            cycle_deadline_seconds=0.1,
            idle_delay_seconds=0,
            mandatory=True,
        ),
        lease_ttl_ns=1_000_000,
        clock_ns=lambda: 1_000,
    )
    summary = await supervisor.run(asyncio.Event())

    assert summary.state is PR196SupervisorState.FAILED
    assert summary.readiness_failed
    assert summary.stop_reason == "mandatory_worker_failed"


def test_runtime_kernel_security_invariants_do_not_use_assertions():
    module = __import__(
        "src.durability.runtime_kernel_pr196",
        fromlist=["runtime_kernel_pr196"],
    )
    source = module.__loader__.get_source("src.durability.runtime_kernel_pr196")

    assert "assert " not in source

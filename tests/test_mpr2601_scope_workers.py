import asyncio
from dataclasses import replace
import time

import pytest

from src.config.runtime import load_runtime_config
from src.durability import DurableLifecycleStore
from src.economics.capital import CapitalEngineError
from src.economics.durable_reservations import DurableCapitalCoordinator
from src.paper_shadow.durable_service_a3 import (
    A3ExactAttemptBatch,
    A3ProviderEvidenceState,
    InstalledDurablePaperService,
)
from src.paper_shadow.repeated_service_pr04 import (
    RepeatedInstalledPaperService,
    RepeatedPaperServiceConfig,
    RepeatedPaperServiceStopReason,
)
from tests.test_mpr2601_durable_atomicity import reserve
from tests.test_mpr2601_terminal_recovery import owner, terminal
from tests.test_pr02_unified_lifecycle_authority import begin_cycle, digest
from tests.test_pr057_durable_capital_reservations import (
    _snapshot,
    _candidate,
    _key,
    _policy,
)


@pytest.mark.parametrize(
    "changes",
    [
        {"captured_at_ns": None},
        {"captured_at_ns": 1},
        {"context_slot": None},
        {"cluster_genesis": None},
        {"captured_at_ns": 2**63 - 1},
    ],
)
def test_unknown_or_stale_snapshot_has_no_durable_effect(changes):
    with DurableLifecycleStore(":memory:") as store:
        with pytest.raises(CapitalEngineError, match="WALLET_SNAPSHOT"):
            reserve(store, wallet_snapshot=replace(_snapshot(), **changes))
        assert store.count_rows("durable_attempts") == 0


def test_wallet_scope_does_not_borrow_another_wallet_balance():
    with DurableLifecycleStore(":memory:") as store:
        reserve(store, "wallet-a")
        poor_wallet = replace(_snapshot(10_000_000), wallet_pubkey="wallet-b")
        assert not reserve(
            store, "wallet-b", wallet_snapshot=poor_wallet
        ).decision.allowed
        rich_wallet = replace(_snapshot(16_000_000), wallet_pubkey="wallet-b")
        assert reserve(store, "wallet-b", wallet_snapshot=rich_wallet).decision.allowed
        assert store.count_rows("durable_reservations") == 2


def test_regressed_snapshot_generation_is_rejected():
    with DurableLifecycleStore(":memory:") as store:
        first = reserve(store)
        snapshot = replace(
            first.wallet_snapshot, context_slot=first.wallet_snapshot.context_slot - 1
        )
        with pytest.raises(CapitalEngineError, match="GENERATION_STALE"):
            reserve(store, "second", wallet_snapshot=snapshot)
        assert store.count_rows("durable_reservations") == 1


def test_cluster_scope_matches_authority_identity(owner):
    coordinator = DurableCapitalCoordinator(store=owner.lifecycle, policy=_policy())
    snapshot = replace(
        _snapshot(), cluster_genesis="wrong-chain", captured_at_ns=1_000_000
    )
    with pytest.raises(CapitalEngineError, match="CLUSTER_MISMATCH"):
        coordinator.reserve(
            _candidate(),
            wallet_snapshot=snapshot,
            attempt_key=_key("chain"),
            idempotency_key="chain",
        )


def test_terminal_replay_after_boot_change_is_read_only(owner):
    fence = begin_cycle(owner)
    first = terminal(owner, fence)
    owner.time_authority.reboot()
    before = owner.db.total_changes
    replay = terminal(owner, fence)
    assert replay.replayed and replay.terminal_id == first.terminal_id
    assert owner.db.total_changes == before


def service(owner, runtime=None):
    return InstalledDurablePaperService(
        load_runtime_config(environ={"PAPER_TRADING_ONLY": "true"}),
        authority=owner,
        batch_source=lambda: A3ExactAttemptBatch(
            A3ProviderEvidenceState(digest("provider"), True)
        ),
        runtime_cycle=runtime,
    )


@pytest.mark.asyncio
async def test_critical_worker_exception_closes_readiness(owner):
    async def failed(*args):
        raise RuntimeError("controlled critical worker death")

    runner = service(owner, failed)
    report = await runner.run_once()
    assert report.status.value == "INDETERMINATE"
    assert not report.ready_for_next_cycle
    assert not runner.ready_for_next_cycle
    assert not runner.incident_recording_failed
    terminal = owner.db.execute(
        "SELECT reason_code FROM pr02_terminal_records"
    ).fetchone()
    assert terminal[0] == "blocked_a3_runtime_cycle_failed_RuntimeError"
    assert owner.db.execute("SELECT COUNT(*) FROM pr02_outbox_event").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_worker_cancellation_closes_readiness_and_records_incident(owner):
    started = asyncio.Event()

    async def blocked(*args):
        started.set()
        await asyncio.Event().wait()

    runner = service(owner, blocked)
    task = asyncio.create_task(runner.run_once())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not runner.ready_for_next_cycle
    assert (
        owner.db.execute("SELECT kind FROM durable_time_incidents").fetchone()[0]
        == "A3_CYCLE_CANCELLED"
    )
    assert (
        owner.db.execute("SELECT COUNT(*) FROM pr02_terminal_records").fetchone()[0]
        == 0
    )
    with pytest.raises(RuntimeError, match="UNRESOLVED"):
        await runner.run_once()


@pytest.mark.asyncio
async def test_cancellation_after_terminal_commit_does_not_compensate(
    owner, monkeypatch
):
    runner = service(owner)
    original = runner._commit

    def committed(*args):
        original(*args)
        raise asyncio.CancelledError()

    monkeypatch.setattr(runner, "_commit", committed)
    with pytest.raises(asyncio.CancelledError):
        await runner.run_once()
    assert not runner.ready_for_next_cycle
    assert (
        owner.db.execute("SELECT COUNT(*) FROM pr02_terminal_records").fetchone()[0]
        == 1
    )
    assert owner.db.execute("SELECT COUNT(*) FROM pr02_outbox_event").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_shutdown_drains_one_inflight_cycle_with_bounded_timeout(owner):
    started = asyncio.Event()

    async def blocked(*args):
        started.set()
        await asyncio.Event().wait()

    runner = service(owner, blocked)
    supervisor = RepeatedInstalledPaperService(
        runner, RepeatedPaperServiceConfig(shutdown_timeout_seconds=0.01)
    )
    stop = asyncio.Event()
    task = asyncio.create_task(supervisor.run(stop))
    await started.wait()
    stop.set()
    result = await asyncio.wait_for(task, timeout=1)
    assert result.stop_reason is RepeatedPaperServiceStopReason.DRAIN_TIMEOUT
    assert not runner.ready_for_next_cycle
    assert not runner._run_lock.locked()
    runner.close()
    runner.close()
    with pytest.raises(RuntimeError, match="CLOSED"):
        await runner.run_once()

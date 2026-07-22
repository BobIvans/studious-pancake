from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sqlite3
import threading
import time

import pytest

from src.persistence.async_writer_pr200 import (
    AsyncPersistenceWriter,
    AsyncPersistenceWriterConfig,
    PersistenceCommit,
    PersistenceOperation,
    PersistenceState,
    PersistenceWorkClass,
)
from src.providers.helius.async_delivery_pr200 import AsyncHeliusDeliveryPlane
from src.providers.helius.delivery import DeliveryLimits, HeliusDeliveryConfig


def _operation(
    operation_id: str,
    work_class: PersistenceWorkClass,
    deadline_ns: int,
    run,
    *,
    estimated_bytes: int = 1,
):
    return PersistenceOperation(
        operation_id=operation_id,
        work_class=work_class,
        deadline_ns=deadline_ns,
        estimated_bytes=estimated_bytes,
        run=run,
    )


@pytest.mark.asyncio
async def test_blocking_writer_work_does_not_freeze_event_loop() -> None:
    writer = AsyncPersistenceWriter(
        AsyncPersistenceWriterConfig(
            max_queue_items=4,
            max_queue_bytes=1024,
            reserved_critical_items=1,
            reserved_critical_bytes=128,
        )
    )
    started = threading.Event()
    release = threading.Event()

    def blocking_commit(_deadline_ns: int) -> PersistenceCommit[str]:
        started.set()
        release.wait(timeout=1)
        return PersistenceCommit(committed=True, value="committed")

    deadline_ns = time.monotonic_ns() + 1_000_000_000
    task = asyncio.create_task(
        writer.submit(
            _operation(
                "blocking",
                PersistenceWorkClass.FINANCIAL_LEDGER,
                deadline_ns,
                blocking_commit,
            )
        )
    )
    assert await asyncio.to_thread(started.wait, 0.5)

    ticked = False

    async def heartbeat() -> None:
        nonlocal ticked
        await asyncio.sleep(0.01)
        ticked = True

    await asyncio.wait_for(heartbeat(), timeout=0.1)
    assert ticked is True
    assert task.done() is False

    release.set()
    result = await task
    assert result.state is PersistenceState.COMMITTED
    await writer.close()


@pytest.mark.asyncio
async def test_timeout_is_unknown_then_reconciles_without_resubmission() -> None:
    writer = AsyncPersistenceWriter(
        AsyncPersistenceWriterConfig(
            max_queue_items=4,
            max_queue_bytes=1024,
            reserved_critical_items=1,
            reserved_critical_bytes=128,
        )
    )

    def slow_commit(_deadline_ns: int) -> PersistenceCommit[str]:
        time.sleep(0.05)
        return PersistenceCommit(committed=True, value="done")

    operation_id = "slow-commit"
    result = await writer.submit(
        _operation(
            operation_id,
            PersistenceWorkClass.FINANCIAL_LEDGER,
            time.monotonic_ns() + 10_000_000,
            slow_commit,
        )
    )
    assert result.state is PersistenceState.UNKNOWN

    await asyncio.sleep(0.07)
    reconciled = writer.lookup(operation_id)
    assert reconciled.state is PersistenceState.COMMITTED
    assert reconciled.value == "done"
    await writer.close()


@pytest.mark.asyncio
async def test_optional_flood_cannot_consume_critical_reserve() -> None:
    writer = AsyncPersistenceWriter(
        AsyncPersistenceWriterConfig(
            max_queue_items=2,
            max_queue_bytes=100,
            reserved_critical_items=1,
            reserved_critical_bytes=10,
        )
    )
    release = threading.Event()
    order: list[str] = []

    def blocker(_deadline_ns: int) -> PersistenceCommit[str]:
        release.wait(timeout=1)
        order.append("blocker")
        return PersistenceCommit(True, "blocker")

    def optional(_deadline_ns: int) -> PersistenceCommit[str]:
        order.append("optional")
        return PersistenceCommit(True, "optional")

    def critical(_deadline_ns: int) -> PersistenceCommit[str]:
        order.append("critical")
        return PersistenceCommit(True, "critical")

    deadline_ns = time.monotonic_ns() + 2_000_000_000
    blocker_task = asyncio.create_task(
        writer.submit(
            _operation(
                "blocker",
                PersistenceWorkClass.MAINTENANCE,
                deadline_ns,
                blocker,
            )
        )
    )
    await asyncio.sleep(0.01)
    optional_task = asyncio.create_task(
        writer.submit(
            _operation(
                "optional",
                PersistenceWorkClass.OBSERVABILITY_EXPORT,
                deadline_ns,
                optional,
            )
        )
    )
    await asyncio.sleep(0.01)

    rejected = await writer.submit(
        _operation(
            "optional-overflow",
            PersistenceWorkClass.OBSERVABILITY_EXPORT,
            deadline_ns,
            optional,
        )
    )
    assert rejected.state is PersistenceState.NOT_SUBMITTED
    assert rejected.reason == "queue_full"

    critical_task = asyncio.create_task(
        writer.submit(
            _operation(
                "critical",
                PersistenceWorkClass.FINANCIAL_LEDGER,
                deadline_ns,
                critical,
            )
        )
    )
    await asyncio.sleep(0.01)
    release.set()
    await asyncio.gather(blocker_task, optional_task, critical_task)

    assert order == ["blocker", "critical", "optional"]
    assert writer.health().queue_rejections == 1
    await writer.close()


@pytest.mark.asyncio
async def test_shutdown_preserves_critical_and_cancels_optional() -> None:
    writer = AsyncPersistenceWriter(
        AsyncPersistenceWriterConfig(
            max_queue_items=4,
            max_queue_bytes=1024,
            reserved_critical_items=1,
            reserved_critical_bytes=128,
        )
    )
    release = threading.Event()

    def blocker(_deadline_ns: int) -> PersistenceCommit[str]:
        release.wait(timeout=1)
        return PersistenceCommit(True, "blocker")

    def commit(value: str):
        return lambda _deadline_ns: PersistenceCommit(True, value)

    deadline_ns = time.monotonic_ns() + 2_000_000_000
    blocker_task = asyncio.create_task(
        writer.submit(
            _operation(
                "blocker",
                PersistenceWorkClass.FINANCIAL_LEDGER,
                deadline_ns,
                blocker,
            )
        )
    )
    await asyncio.sleep(0.01)
    critical_task = asyncio.create_task(
        writer.submit(
            _operation(
                "critical-shutdown",
                PersistenceWorkClass.LIFECYCLE,
                deadline_ns,
                commit("critical"),
            )
        )
    )
    optional_task = asyncio.create_task(
        writer.submit(
            _operation(
                "optional-shutdown",
                PersistenceWorkClass.MAINTENANCE,
                deadline_ns,
                commit("optional"),
            )
        )
    )
    await asyncio.sleep(0.01)
    close_task = asyncio.create_task(writer.close(cancel_optional=True))
    await asyncio.sleep(0)
    release.set()

    blocker_result, critical_result, optional_result = await asyncio.gather(
        blocker_task,
        critical_task,
        optional_task,
    )
    health = await close_task

    assert blocker_result.state is PersistenceState.COMMITTED
    assert critical_result.state is PersistenceState.COMMITTED
    assert optional_result.state is PersistenceState.NOT_SUBMITTED
    assert optional_result.reason == "optional_work_cancelled_during_shutdown"
    assert health.shutdown_clean is True


@pytest.mark.asyncio
async def test_helius_sqlite_lock_keeps_heartbeat_schedulable(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "helius.sqlite3"
    plane = AsyncHeliusDeliveryPlane(
        HeliusDeliveryConfig(
            auth_header="Bearer test",
            store_path=db_path,
            webhook_id="helius-mainnet",
            cluster_genesis="mainnet-genesis",
            limits=DeliveryLimits(
                delivery_deadline_ms=80,
                sqlite_busy_timeout_ms=60,
            ),
        )
    )
    headers = {"authorization": "Bearer test"}
    first = await plane.accept_delivery(
        headers=headers,
        raw_body=json.dumps([{"signature": "SIG-0", "slot": 1}]).encode(),
    )
    assert first.acknowledged is True

    blocker = sqlite3.connect(str(db_path), timeout=0)
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        request_task = asyncio.create_task(
            plane.accept_delivery(
                headers=headers,
                raw_body=json.dumps(
                    [{"signature": "SIG-1", "slot": 2}]
                ).encode(),
            )
        )
        tick_started = time.monotonic()
        await asyncio.sleep(0.01)
        tick_delay = time.monotonic() - tick_started
        assert tick_delay < 0.05
        assert request_task.done() is False
    finally:
        blocker.rollback()
        blocker.close()

    result = await request_task
    assert result.outcome.http_status in {200, 503}
    await plane.close()

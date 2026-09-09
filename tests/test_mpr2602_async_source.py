"""Async producer lifecycle through the actual A3 durable cycle boundary."""

import asyncio
import pytest

from src.config.runtime import load_runtime_config
from src.durability.unified_authority_pr02 import UnifiedLifecycleAuthority
from src.paper_shadow.durable_service_a3 import (
    A3ExactAttemptBatch,
    A3ProviderEvidenceState,
    A3PaperServiceStatus,
    InstalledDurablePaperService,
    InstalledPaperServiceConfig,
)

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest.fixture
def authority():
    with UnifiedLifecycleAuthority(
        ":memory:", release_digest="a" * 64, policy_bundle_hash="b" * 64
    ) as owner:
        yield owner


async def test_async_source_is_awaited_and_blocked_evidence_commits_once(authority):
    calls = []

    async def source():
        await asyncio.sleep(0)
        calls.append("source")
        return A3ExactAttemptBatch(
            A3ProviderEvidenceState("c" * 64, False, ("fixture_blocked",))
        )

    async def must_not_run(*args):
        raise AssertionError("blocked input reached runtime")

    service = InstalledDurablePaperService(
        load_runtime_config(),
        authority=authority,
        batch_source=source,
        runtime_cycle=must_not_run,
    )
    report = await service.run_once()
    assert calls == ["source"]
    assert report.status is A3PaperServiceStatus.BLOCKED
    assert report.terminal_reason == "fixture_blocked"
    assert (
        authority.db.execute("SELECT count(*) FROM pr02_terminal_records").fetchone()[0]
        == 1
    )


async def test_async_source_timeout_cancels_owned_source_before_terminal(authority):
    closed = asyncio.Event()

    async def source():
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    service = InstalledDurablePaperService(
        load_runtime_config(),
        InstalledPaperServiceConfig(cycle_deadline_seconds=0.01),
        authority=authority,
        batch_source=source,
    )
    report = await service.run_once()
    assert closed.is_set()
    assert report.status is A3PaperServiceStatus.INDETERMINATE
    assert not report.ready_for_next_cycle
    assert (
        authority.db.execute("SELECT count(*) FROM pr02_terminal_records").fetchone()[0]
        == 1
    )


async def test_cancellation_during_source_does_not_fabricate_terminal(authority):
    started, closed = asyncio.Event(), asyncio.Event()

    async def source():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    service = InstalledDurablePaperService(
        load_runtime_config(), authority=authority, batch_source=source
    )
    task = asyncio.create_task(service.run_once())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    assert not service.ready_for_next_cycle
    assert (
        authority.db.execute("SELECT count(*) FROM pr02_terminal_records").fetchone()[0]
        == 0
    )
    assert service.recovery_state()

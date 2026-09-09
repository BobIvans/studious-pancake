"""Read-only persisted dependency status and truthful cleanup drain."""

import asyncio

import pytest

from src.durability.unified_authority_pr02 import UnifiedLifecycleAuthority
from src.provider_governance.authority import ProviderSpendAuthority
from src.provider_governance.dependency import DependencyController
from src.provider_governance.models import DependencyFailureKind, DependencyMode
from src.provider_governance.runtime import ProviderGovernance
from src.provider_governance.scheduler import DeadlineAdmissionScheduler
from tests.test_mpr2602_durable_provider import Clock, manifests, persisted, request

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


async def test_restarted_startup_status_reads_disabled_dependency_without_writing():
    clock = Clock()
    with UnifiedLifecycleAuthority(
        ":memory:",
        release_digest="a" * 64,
        policy_bundle_hash="b" * 64,
        time_authority=clock,
    ) as store:
        first = ProviderGovernance(manifests(), store=store)
        await first.dependencies.record_failure(
            "rpc", "one", DependencyFailureKind.AUTH
        )
        restarted = ProviderGovernance(manifests(), store=store)
        before = persisted(store)
        assert restarted.startup_state("rpc")["dependency_mode"] == "disabled"
        assert (
            await restarted.dependencies.snapshot("rpc", "one")
        ).mode is DependencyMode.DISABLED
        assert persisted(store) == before


async def test_diagnostic_read_does_not_advance_elapsed_cooldown():
    clock = Clock()
    with UnifiedLifecycleAuthority(
        ":memory:",
        release_digest="a" * 64,
        policy_bundle_hash="b" * 64,
        time_authority=clock,
    ) as store:
        authority = ProviderSpendAuthority(manifests(), store=store)
        controller = DependencyController(authority=authority)
        await controller.record_failure(
            "rpc", "one", DependencyFailureKind.RATE_LIMITED
        )
        before = persisted(store)
        clock.seconds += 100
        assert controller.peek("rpc", "one").mode is DependencyMode.COOLDOWN
        assert (await controller.snapshot("rpc", "one")).mode is DependencyMode.COOLDOWN
        assert persisted(store) == before


async def test_failed_retained_cleanup_is_retrieved_and_drain_never_reports_success():
    authority = ProviderSpendAuthority(manifests(), clock=lambda: 1000)
    scheduler = DeadlineAdmissionScheduler(
        authority, DependencyController(clock=lambda: 1000), clock=lambda: 1000
    )
    entered = asyncio.Event()
    release_cleanup = asyncio.Event()

    async def fail_unknown(lease):
        await release_cleanup.wait()
        raise RuntimeError("fixture durable cleanup failure")

    authority.mark_unknown = fail_unknown

    async def operation():
        entered.set()
        await asyncio.Event().wait()

    caller = asyncio.create_task(scheduler.execute(request("cancelled"), operation))
    await entered.wait()
    caller.cancel()
    await asyncio.sleep(0)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert not await scheduler.drain_cleanup(0)
    release_cleanup.set()
    assert not await scheduler.drain_cleanup(1)
    assert not await scheduler.drain_cleanup(0)
    diagnostics = await scheduler.snapshot()
    assert diagnostics["cleanup_failures"] == 1
    assert diagnostics["cleanup_error_types"] == ("RuntimeError",)
    assert (await authority.snapshot("rpc"))["active_leases"] == 1

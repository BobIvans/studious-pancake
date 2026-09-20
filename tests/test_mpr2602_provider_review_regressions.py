"""Independent regressions from the durable provider review."""

from dataclasses import replace

import pytest

from src.durability.unified_authority_pr02 import UnifiedLifecycleAuthority
from src.provider_governance.authority import ProviderSpendAuthority
from src.provider_governance.dependency import DependencyController
from src.provider_governance.scheduler import DeadlineAdmissionScheduler
from src.provider_governance.models import (
    DependencyFailureKind,
    DependencyMode,
    ProviderOperation,
    ProviderGovernanceError,
    ProviderAdmissionError,
)
from tests.test_mpr2602_durable_provider import Clock, manifests, request

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest.fixture
def store():
    with UnifiedLifecycleAuthority(
        ":memory:",
        release_digest="a" * 64,
        policy_bundle_hash="b" * 64,
        time_authority=Clock(),
    ) as value:
        yield value


async def test_other_wrapper_old_generation_cannot_issue_after_rotation(store):
    first = ProviderSpendAuthority(manifests(), store=store)
    stale = ProviderSpendAuthority(manifests(), store=store)
    lease = await stale.reserve(request("old-generation"))
    first.replace_entitlement(replace(first.entitlement("rpc"), generation="two"))
    with pytest.raises((ProviderGovernanceError, ProviderAdmissionError)):
        await stale.mark_issued(lease)


async def test_alias_rotation_cannot_raise_shared_pool_concurrency(store):
    authority = ProviderSpendAuthority(manifests(), store=store)
    with pytest.raises(ProviderGovernanceError):
        authority.replace_entitlement(
            replace(authority.entitlement("alias"), max_concurrency=3)
        )


async def test_dependency_rotation_fences_old_probe_from_durable_recovery(store):
    authority = ProviderSpendAuthority(manifests(), store=store)
    dependency = DependencyController(authority=authority)
    await dependency.record_failure("rpc", "one", DependencyFailureKind.TRANSPORT)
    authority.replace_entitlement(
        replace(authority.entitlement("rpc"), generation="two")
    )
    dependency.activate_generation("rpc", "two")
    await dependency.record_success("rpc", "one", ProviderOperation.HEALTH_PROBE)
    actual = await dependency.snapshot("rpc", "two")
    assert actual.generation == "two"
    assert actual.mode is DependencyMode.DEGRADED


async def test_terminal_authority_failure_does_not_poison_scheduler_queue():
    authority = ProviderSpendAuthority(manifests(), clock=lambda: 1000)
    lease = await authority.reserve(request("overrun"))
    await authority.mark_issued(lease)
    await authority.complete(lease, actual_cost_units=6)
    scheduler = DeadlineAdmissionScheduler(
        authority, DependencyController(clock=lambda: 1000), clock=lambda: 1000
    )
    with pytest.raises(ProviderGovernanceError, match="overrun"):
        await scheduler.acquire(request("blocked"))
    assert (await scheduler.snapshot())["queued"] == 0


async def test_same_boot_new_process_cannot_issue_old_reserved_lease():
    clock = Clock()
    with UnifiedLifecycleAuthority(
        ":memory:",
        release_digest="a" * 64,
        policy_bundle_hash="b" * 64,
        time_authority=clock,
    ) as store:
        first = ProviderSpendAuthority(manifests(), store=store)
        lease = await first.reserve(request("old-process"))
        clock.process_generation += 1
        restarted = ProviderSpendAuthority(manifests(), store=store)
        with pytest.raises((ProviderGovernanceError, ProviderAdmissionError)):
            await restarted.mark_issued(lease)

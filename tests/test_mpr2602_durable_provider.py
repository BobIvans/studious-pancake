"""Actual canonical memory-store accounting shared by provider wrappers."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import pytest
from src.durability.unified_authority_pr02 import UnifiedLifecycleAuthority
from src.provider_governance.authority import ProviderSpendAuthority
from src.provider_governance.dependency import DependencyController
from src.provider_governance.models import (
    AdmissionRequest,
    DependencyFailureKind,
    ProviderAdmissionError,
    ProviderEntitlement,
    ProviderGovernanceError,
    ProviderOperation,
)
from src.time_authority import TimeSnapshot, TimeSourceStatus

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class Clock:
    boot_id = "boot-one"
    process_generation = 1
    seconds = 1000.0

    def snapshot(self):
        return TimeSnapshot(
            utc_ns=int(self.seconds * 1e9),
            monotonic_ns=int(self.seconds * 1e9),
            boot_id=self.boot_id,
            process_generation=self.process_generation,
            time_source_status=TimeSourceStatus.SYNCHRONIZED,
            max_uncertainty_ns=1,
        )

    def assert_healthy_for_sensitive_operation(self):
        return self.snapshot()


def manifests():
    one = ProviderEntitlement(
        provider_id="rpc",
        generation="one",
        allowed_operations=frozenset({ProviderOperation.FINALIZATION}),
        window_seconds=10,
        request_limit=10,
        cost_unit_limit=100,
        spend_limit_micros=100,
        max_concurrency=1,
        quota_pool_ref="account-wide",
    )
    return {"rpc": one, "alias": replace(one, provider_id="alias")}


@pytest.fixture
def context():
    clock = Clock()
    with UnifiedLifecycleAuthority(
        ":memory:",
        release_digest="a" * 64,
        policy_bundle_hash="b" * 64,
        time_authority=clock,
    ) as store:
        yield store, clock, ProviderSpendAuthority(manifests(), store=store)


def request(work, *, provider="rpc", spend=20):
    return AdmissionRequest(
        work_id=work,
        provider_id=provider,
        operation=ProviderOperation.FINALIZATION,
        request_fingerprint=work,
        fairness_key="fixture",
        deadline_at=100000,
        estimated_cost_units=5,
        estimated_spend_micros=spend,
    )


async def completed(authority, spend=20):
    lease = await authority.reserve(request("one", spend=spend))
    await authority.mark_issued(lease)
    await authority.complete(lease)
    return lease


def persisted(store):
    return tuple(
        tuple(row) for row in store.db.execute("SELECT * FROM pr02_provider_state")
    )


async def test_two_wrappers_cannot_oversubscribe_same_durable_pool(context):
    store, _, first = context
    second = ProviderSpendAuthority(manifests(), store=store)
    outcomes = await asyncio.gather(
        first.reserve(request("one")),
        second.reserve(request("two")),
        return_exceptions=True,
    )
    assert sum(isinstance(item, ProviderAdmissionError) for item in outcomes) == 1
    assert (await second.snapshot("rpc"))["active_leases"] == 1
    assert (
        store.db.execute("SELECT COUNT(*) FROM pr02_provider_attempts").fetchone()[0]
        == 1
    )


async def test_aliases_share_external_quota_pool(context):
    store, _, authority = context
    await authority.reserve(request("one"))
    with pytest.raises(ProviderAdmissionError, match="concurrency_exhausted"):
        await authority.reserve(request("two", provider="alias"))
    assert (await authority.snapshot("alias"))["reserved_spend_micros"] == 20
    assert len(persisted(store)) == 1


async def test_completion_replay_does_not_charge_twice_and_drift_rejects(context):
    store, _, first = context
    lease = await completed(first)
    second = ProviderSpendAuthority(manifests(), store=store)
    await second.complete(lease)
    assert (await second.snapshot("rpc"))["committed_spend_micros"] == 20
    with pytest.raises(ProviderGovernanceError, match="replay conflict"):
        await second.complete(lease, actual_spend_micros=21)
    assert (await second.snapshot("rpc"))["committed_requests"] == 1


async def test_unknown_issued_work_retains_slots_until_reconciled(context):
    store, clock, authority = context
    lease = await authority.reserve(request("one"))
    await authority.mark_issued(lease)
    await authority.mark_unknown(lease)
    clock.seconds += 100
    restarted = ProviderSpendAuthority(manifests(), store=store)
    with pytest.raises(ProviderGovernanceError, match="cannot be released"):
        await restarted.release(lease)
    with pytest.raises(ProviderAdmissionError, match="concurrency_exhausted"):
        await restarted.reserve(request("two"))
    assert (await restarted.snapshot("rpc"))["active_leases"] == 1
    await restarted.complete(lease)
    assert (await restarted.snapshot("rpc"))["active_leases"] == 0


async def test_actual_overrun_is_durable_and_blocks_new_admission(context):
    store, _, authority = context
    lease = await authority.reserve(request("one"))
    await authority.mark_issued(lease)
    await authority.complete(lease, actual_spend_micros=150)
    restarted = ProviderSpendAuthority(manifests(), store=store)
    assert (await restarted.snapshot("rpc"))["committed_spend_micros"] == 150
    with pytest.raises(ProviderGovernanceError, match="overrun"):
        await restarted.reserve(request("two"))


async def test_rate_window_rollover_preserves_daily_spend(context):
    store, clock, authority = context
    await completed(authority, spend=80)
    clock.seconds += 11
    restarted = ProviderSpendAuthority(manifests(), store=store)
    with pytest.raises(ProviderAdmissionError, match="spend_limit_exhausted"):
        await restarted.reserve(request("two", spend=30))
    await restarted.reserve(request("three", spend=20))
    assert (await restarted.snapshot("rpc"))["committed_spend_micros"] == 80


async def test_diagnostic_snapshot_does_not_reset_or_write_accounting(context):
    store, clock, authority = context
    await completed(authority)
    before = persisted(store)
    clock.seconds += 100000
    snapshot = await authority.snapshot("rpc")
    assert snapshot["committed_spend_micros"] == 20
    assert persisted(store) == before


async def test_reserved_lease_from_original_boot_cannot_be_issued(context):
    store, clock, authority = context
    lease = await authority.reserve(request("one"))
    clock.boot_id = "boot-two"
    clock.process_generation += 1
    restarted = ProviderSpendAuthority(manifests(), store=store)
    with pytest.raises(ProviderGovernanceError, match="old boot"):
        await restarted.mark_issued(lease)


async def test_durable_completion_payload_tampering_is_rejected(context):
    store, _, authority = context
    lease = await completed(authority)
    row = store.db.execute("SELECT payload FROM pr02_provider_attempts").fetchone()
    payload = json.loads(row[0])
    payload["completion"] = [5, 19]
    with store.lifecycle.write_transaction():
        store.db.execute(
            "UPDATE pr02_provider_attempts SET payload=?", (json.dumps(payload),)
        )
    with pytest.raises(ProviderGovernanceError):
        await authority.complete(lease, actual_spend_micros=19)


async def test_auth_failure_remains_disabled_across_dependency_wrappers(context):
    store, clock, authority = context
    first = DependencyController(authority=authority, clock=lambda: clock.seconds)
    await first.record_failure("rpc", "one", DependencyFailureKind.AUTH)
    second = DependencyController(
        authority=ProviderSpendAuthority(manifests(), store=store),
        clock=lambda: clock.seconds,
    )
    await second.record_success("rpc", "one", ProviderOperation.HEALTH_PROBE)
    with pytest.raises(ProviderAdmissionError, match="dependency_disabled"):
        await second.assert_admissible("rpc", "one", ProviderOperation.FINALIZATION)


async def test_retry_after_persists_and_requires_probe_after_cooldown(context):
    store, clock, authority = context
    first = DependencyController(authority=authority, clock=lambda: clock.seconds)
    await first.record_failure(
        "rpc", "one", DependencyFailureKind.RATE_LIMITED, retry_after_seconds=90
    )
    second = DependencyController(
        authority=ProviderSpendAuthority(manifests(), store=store),
        clock=lambda: clock.seconds,
    )
    clock.seconds += 89
    with pytest.raises(ProviderAdmissionError, match="dependency_cooldown"):
        await second.assert_admissible("rpc", "one", ProviderOperation.FINALIZATION)
    clock.seconds += 2
    with pytest.raises(ProviderAdmissionError, match="degraded_operation_denied"):
        await second.assert_admissible("rpc", "one", ProviderOperation.FINALIZATION)
    await second.record_success("rpc", "one", ProviderOperation.DISCOVERY)
    with pytest.raises(ProviderAdmissionError, match="degraded_operation_denied"):
        await second.assert_admissible("rpc", "one", ProviderOperation.FINALIZATION)
    await second.record_success("rpc", "one", ProviderOperation.HEALTH_PROBE)
    await first.assert_admissible("rpc", "one", ProviderOperation.FINALIZATION)


async def test_durable_dependency_deadline_uses_canonical_trusted_time(context):
    store, clock, authority = context
    controller = DependencyController(authority=authority)
    await controller.record_failure(
        "rpc", "one", DependencyFailureKind.RATE_LIMITED, retry_after_seconds=90
    )
    payload = json.loads(
        store.db.execute("SELECT payload FROM pr02_provider_state").fetchone()[0]
    )
    assert payload["dependency"]["retry_at"] == clock.seconds + 90

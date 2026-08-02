from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from src.provider_governance import (
    AdmissionCode,
    AdmissionRequest,
    DeadlineAdmissionScheduler,
    DependencyController,
    DependencyFailureKind,
    DependencyMode,
    ProviderAdmissionError,
    ProviderEntitlement,
    ProviderGovernance,
    ProviderGovernanceError,
    ProviderOperation,
    ProviderSpendAuthority,
)
from src.routing.models import (
    AuthKind,
    ExecutionArtifactKind,
    ProviderCapabilities,
    ProviderCapability,
    ProviderFailure,
    ProviderFailureReason,
    ProviderHealth,
    ProviderRole,
    ProviderStatus,
    QuoteRequest,
)
from src.routing.registry import DiscoveryPlane, ProviderRegistry

SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WALLET = "11111111111111111111111111111111"


class FakeClock:
    def __init__(self, value: float = 1_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def entitlement(
    *,
    provider_id: str = "provider-a",
    generation: str = "generation-1",
    request_limit: int = 4,
    cost_limit: int = 4,
    spend_limit: int = 0,
    max_concurrency: int = 4,
    reserve: int = 1,
) -> ProviderEntitlement:
    return ProviderEntitlement(
        provider_id=provider_id,
        generation=generation,
        allowed_operations=frozenset(
            {
                ProviderOperation.DISCOVERY,
                ProviderOperation.REFINEMENT,
                ProviderOperation.FINALIZATION,
                ProviderOperation.BACKFILL,
                ProviderOperation.HEALTH_PROBE,
            }
        ),
        window_seconds=60.0,
        request_limit=request_limit,
        cost_unit_limit=cost_limit,
        spend_limit_micros=spend_limit,
        max_concurrency=max_concurrency,
        finalization_reserve_requests=reserve,
        finalization_reserve_cost_units=reserve,
        source_ref="test-manifest",
    )


def request_for(
    clock: FakeClock,
    *,
    work_id: str,
    operation: ProviderOperation = ProviderOperation.DISCOVERY,
    fairness_key: str = "tenant-a",
    expected_generation: str | None = "generation-1",
    spend: int = 0,
) -> AdmissionRequest:
    return AdmissionRequest(
        work_id=work_id,
        provider_id="provider-a",
        operation=operation,
        request_fingerprint=f"fingerprint:{work_id}",
        fairness_key=fairness_key,
        deadline_at=clock() + 30.0,
        expected_generation=expected_generation,
        estimated_cost_units=1,
        estimated_spend_micros=spend,
        lease_ttl_seconds=10.0,
    )


def quote_request() -> QuoteRequest:
    return QuoteRequest(
        input_mint=SOL,
        output_mint=USDC,
        amount_base_units=1_000_000,
        user_wallet=WALLET,
        slippage_bps=50,
        input_decimals=9,
        output_decimals=6,
    )


def test_entitlement_hash_is_semantic_and_stable() -> None:
    first = entitlement()
    second = entitlement()

    assert first.manifest_sha256 == second.manifest_sha256
    assert len(first.manifest_sha256) == 64
    assert first.to_dict()["allowed_operations"] == (
        "backfill",
        "discovery",
        "finalization",
        "health_probe",
        "refinement",
    )


@pytest.mark.asyncio
async def test_finalization_reserve_is_protected_transactionally() -> None:
    clock = FakeClock()
    manifest = entitlement(request_limit=3, cost_limit=3, max_concurrency=3, reserve=1)
    authority = ProviderSpendAuthority(
        {manifest.provider_id: manifest}, clock=clock, wall_clock=clock
    )

    first = await authority.reserve(request_for(clock, work_id="d1"))
    second = await authority.reserve(request_for(clock, work_id="d2"))
    with pytest.raises(ProviderAdmissionError) as denied:
        await authority.reserve(request_for(clock, work_id="d3"))
    assert denied.value.code is AdmissionCode.FINALIZATION_RESERVE_PROTECTED
    assert denied.value.retryable

    final = await authority.reserve(
        request_for(
            clock,
            work_id="f1",
            operation=ProviderOperation.FINALIZATION,
        )
    )
    for lease in (first, second, final):
        await authority.mark_issued(lease)
        await authority.complete(lease)

    snapshot = await authority.snapshot("provider-a")
    assert snapshot["committed_requests"] == 3
    assert snapshot["active_leases"] == 0


@pytest.mark.asyncio
async def test_generation_and_spend_limits_fail_closed() -> None:
    clock = FakeClock()
    manifest = entitlement(spend_limit=100, reserve=0)
    authority = ProviderSpendAuthority(
        {manifest.provider_id: manifest}, clock=clock, wall_clock=clock
    )

    with pytest.raises(ProviderAdmissionError) as mismatch:
        await authority.reserve(
            request_for(
                clock,
                work_id="old-generation",
                expected_generation="generation-0",
            )
        )
    assert mismatch.value.code is AdmissionCode.GENERATION_MISMATCH

    lease = await authority.reserve(request_for(clock, work_id="spend-1", spend=80))
    with pytest.raises(ProviderAdmissionError) as exhausted:
        await authority.reserve(request_for(clock, work_id="spend-2", spend=30))
    assert exhausted.value.code is AdmissionCode.SPEND_LIMIT_EXHAUSTED
    await authority.release(lease)


@pytest.mark.asyncio
async def test_replaced_generation_fences_unissued_lease_before_provider_contact() -> (
    None
):
    clock = FakeClock()
    first = entitlement(reserve=0)
    authority = ProviderSpendAuthority(
        {first.provider_id: first}, clock=clock, wall_clock=clock
    )
    lease = await authority.reserve(request_for(clock, work_id="generation-fence"))

    authority.replace_entitlement(entitlement(generation="generation-2", reserve=0))

    with pytest.raises(ProviderAdmissionError) as mismatch:
        await authority.mark_issued(lease)
    assert mismatch.value.code is AdmissionCode.GENERATION_MISMATCH
    await authority.release(lease)
    snapshot = await authority.snapshot("provider-a")
    assert snapshot["active_leases"] == 0
    assert snapshot["committed_requests"] == 0


@pytest.mark.asyncio
async def test_expired_unissued_lease_cleanup_does_not_mask_deadline_failure() -> None:
    clock = FakeClock()
    manifest = entitlement(reserve=0)
    authority = ProviderSpendAuthority(
        {manifest.provider_id: manifest}, clock=clock, wall_clock=clock
    )
    lease = await authority.reserve(request_for(clock, work_id="lease-expired"))
    clock.advance(11.0)

    with pytest.raises(ProviderAdmissionError) as expired:
        await authority.mark_issued(lease)
    assert expired.value.code is AdmissionCode.DEADLINE_EXPIRED
    await authority.release(lease)
    assert (await authority.snapshot("provider-a"))["active_leases"] == 0


@pytest.mark.asyncio
async def test_reserved_lease_cannot_be_committed_without_issue() -> None:
    clock = FakeClock()
    manifest = entitlement(reserve=0)
    authority = ProviderSpendAuthority(
        {manifest.provider_id: manifest}, clock=clock, wall_clock=clock
    )
    lease = await authority.reserve(request_for(clock, work_id="not-issued"))

    with pytest.raises(ProviderGovernanceError, match="reserved"):
        await authority.complete(lease)
    await authority.release(lease)


@pytest.mark.asyncio
async def test_issued_cancellation_is_committed_not_released() -> None:
    clock = FakeClock()
    manifest = entitlement(request_limit=10, cost_limit=10, reserve=0)
    authority = ProviderSpendAuthority(
        {manifest.provider_id: manifest}, clock=clock, wall_clock=clock
    )
    dependencies = DependencyController(clock=clock)
    scheduler = DeadlineAdmissionScheduler(
        authority, dependencies, clock=clock, poll_interval_seconds=0.001
    )
    started = asyncio.Event()

    async def operation() -> None:
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(
        scheduler.execute(request_for(clock, work_id="cancelled"), operation)
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    snapshot = await authority.snapshot("provider-a")
    assert snapshot["committed_requests"] == 1
    assert snapshot["active_leases"] == 0


@pytest.mark.asyncio
async def test_dependency_modes_require_health_probe_for_recovery() -> None:
    clock = FakeClock()
    controller = DependencyController(
        clock=clock, transient_failure_threshold=2, cooldown_seconds=5.0
    )

    await controller.record_failure(
        "provider-a", "generation-1", DependencyFailureKind.TRANSPORT
    )
    degraded = await controller.snapshot("provider-a", "generation-1")
    assert degraded.mode is DependencyMode.DEGRADED
    await controller.assert_admissible(
        "provider-a", "generation-1", ProviderOperation.DISCOVERY
    )
    with pytest.raises(ProviderAdmissionError) as finalization:
        await controller.assert_admissible(
            "provider-a", "generation-1", ProviderOperation.FINALIZATION
        )
    assert finalization.value.code is AdmissionCode.DEGRADED_OPERATION_DENIED

    await controller.record_success(
        "provider-a", "generation-1", ProviderOperation.DISCOVERY
    )
    assert (
        await controller.snapshot("provider-a", "generation-1")
    ).mode is DependencyMode.DEGRADED

    await controller.record_failure(
        "provider-a", "generation-1", DependencyFailureKind.TIMEOUT
    )
    with pytest.raises(ProviderAdmissionError) as cooldown:
        await controller.assert_admissible(
            "provider-a", "generation-1", ProviderOperation.DISCOVERY
        )
    assert cooldown.value.code is AdmissionCode.DEPENDENCY_COOLDOWN
    clock.advance(6.0)
    await controller.assert_admissible(
        "provider-a", "generation-1", ProviderOperation.DISCOVERY
    )
    await controller.record_success(
        "provider-a", "generation-1", ProviderOperation.HEALTH_PROBE
    )
    assert (
        await controller.snapshot("provider-a", "generation-1")
    ).mode is DependencyMode.ACTIVE

    await controller.record_failure(
        "provider-a", "generation-1", DependencyFailureKind.INVALID_SCHEMA
    )
    with pytest.raises(ProviderAdmissionError) as disabled:
        await controller.assert_admissible(
            "provider-a", "generation-1", ProviderOperation.DISCOVERY
        )
    assert disabled.value.code is AdmissionCode.DEPENDENCY_DISABLED
    assert disabled.value.failure_reason == "invalid_schema"
    await controller.assert_admissible(
        "provider-a", "generation-1", ProviderOperation.HEALTH_PROBE
    )
    await controller.assert_admissible(
        "provider-a", "generation-2", ProviderOperation.DISCOVERY
    )


@pytest.mark.asyncio
async def test_scheduler_is_fair_after_one_tenant_used_capacity() -> None:
    clock = FakeClock()
    manifest = entitlement(
        request_limit=10, cost_limit=10, max_concurrency=1, reserve=0
    )
    authority = ProviderSpendAuthority(
        {manifest.provider_id: manifest}, clock=clock, wall_clock=clock
    )
    dependencies = DependencyController(clock=clock)
    scheduler = DeadlineAdmissionScheduler(
        authority, dependencies, clock=clock, poll_interval_seconds=0.001
    )
    release_first = asyncio.Event()
    started_first = asyncio.Event()
    order: list[str] = []

    async def first() -> None:
        order.append("a1")
        started_first.set()
        await release_first.wait()

    async def record(label: str) -> None:
        order.append(label)

    task_a1 = asyncio.create_task(
        scheduler.execute(
            request_for(clock, work_id="a1", fairness_key="tenant-a"), first
        )
    )
    await started_first.wait()
    task_a2 = asyncio.create_task(
        scheduler.execute(
            request_for(clock, work_id="a2", fairness_key="tenant-a"),
            lambda: record("a2"),
        )
    )
    task_b1 = asyncio.create_task(
        scheduler.execute(
            request_for(clock, work_id="b1", fairness_key="tenant-b"),
            lambda: record("b1"),
        )
    )
    await asyncio.sleep(0)
    release_first.set()
    await asyncio.gather(task_a1, task_a2, task_b1)

    assert order == ["a1", "b1", "a2"]


@pytest.mark.asyncio
async def test_expired_work_never_reaches_operation() -> None:
    clock = FakeClock()
    manifest = entitlement(reserve=0)
    governance = ProviderGovernance(
        {manifest.provider_id: manifest}, clock=clock, wall_clock=clock
    )
    called = False

    async def operation() -> None:
        nonlocal called
        called = True

    expired = AdmissionRequest(
        work_id="expired",
        provider_id="provider-a",
        operation=ProviderOperation.DISCOVERY,
        request_fingerprint="expired-fingerprint",
        fairness_key="tenant",
        deadline_at=clock() - 1.0,
        expected_generation="generation-1",
    )
    with pytest.raises(ProviderAdmissionError) as failure:
        await governance.execute(expired, operation)
    assert failure.value.code is AdmissionCode.DEADLINE_EXPIRED
    assert not called


@dataclass
class _FakeCircuit:
    health: ProviderHealth = ProviderHealth.READY

    def record_failure(self, *_: object) -> None:
        self.health = ProviderHealth.UNHEALTHY


class DeniedAdapter:
    provider_id = "denied_provider"
    capabilities = ProviderCapabilities(
        provider_id=provider_id,
        schema_version_pin="denied-provider@test",
        quote=True,
        artifact_kind=ExecutionArtifactKind.NONE,
        exact_in=True,
        exact_out=False,
        legacy_spl=True,
        token_2022=False,
        native_sol=True,
        wsol=True,
        jito_compatible=False,
        exposes_accounts=False,
        exposes_alts=False,
        quote_ttl_seconds=5,
        rate_limit_policy="test",
        auth_kind=AuthKind.NONE,
        role=ProviderRole.DISCOVERY_ONLY,
        admission_reason="test adapter",
    )

    def __init__(self) -> None:
        self.circuit = _FakeCircuit()
        self.calls = 0

    def startup_state(self) -> dict[str, str]:
        return {
            "provider": self.provider_id,
            "state": "discovery_only",
            "reason": "test adapter",
            "artifact_kind": "none",
            "capability_pin": self.capabilities.schema_version_pin,
            "rate_policy": "test",
        }

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider=self.provider_id,
            health=self.circuit.health,
            role=self.capabilities.role,
            capability=ProviderCapability.QUOTE_ONLY,
            reason="test adapter",
        )

    async def request_quote(self, _: QuoteRequest):
        self.calls += 1
        raise AssertionError("admission-denied provider must not be called")


class CircuitOpenAdapter(DeniedAdapter):
    provider_id = "circuit_provider"
    capabilities = ProviderCapabilities(
        provider_id=provider_id,
        schema_version_pin="circuit-provider@test",
        quote=True,
        artifact_kind=ExecutionArtifactKind.NONE,
        exact_in=True,
        exact_out=False,
        legacy_spl=True,
        token_2022=False,
        native_sol=True,
        wsol=True,
        jito_compatible=False,
        exposes_accounts=False,
        exposes_alts=False,
        quote_ttl_seconds=5,
        rate_limit_policy="test",
        auth_kind=AuthKind.NONE,
        role=ProviderRole.DISCOVERY_ONLY,
        admission_reason="test circuit adapter",
    )

    async def request_quote(self, _: QuoteRequest):
        self.calls += 1
        return ProviderFailure(
            provider=self.provider_id,
            reason=ProviderFailureReason.CIRCUIT_OPEN,
            retryable=True,
            detail="probe failed",
        )


@pytest.mark.asyncio
async def test_cooldown_preserves_circuit_reason_without_second_call() -> None:
    adapter = CircuitOpenAdapter()
    registry = ProviderRegistry((adapter,))
    plane = DiscoveryPlane(registry, provider_timeout_seconds=0.1)

    first = await plane.discover(quote_request())
    second = await plane.discover(quote_request())

    assert first.failures[0].reason is ProviderFailureReason.CIRCUIT_OPEN
    assert second.failures[0].reason is ProviderFailureReason.CIRCUIT_OPEN
    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_discovery_plane_uses_governance_before_provider_call() -> None:
    adapter = DeniedAdapter()
    manifest = ProviderEntitlement(
        provider_id=adapter.provider_id,
        generation=adapter.capabilities.schema_version_pin,
        allowed_operations=frozenset({ProviderOperation.HEALTH_PROBE}),
        window_seconds=60.0,
        request_limit=1,
        cost_unit_limit=1,
        spend_limit_micros=0,
        max_concurrency=1,
        source_ref="test-denied",
    )
    governance = ProviderGovernance({adapter.provider_id: manifest})
    registry = ProviderRegistry((adapter,), governance=governance)

    report = registry.startup_report()[0]
    assert report["dependency_mode"] == "active"
    assert report["entitlement_generation"] == adapter.capabilities.schema_version_pin

    batch = await DiscoveryPlane(registry).discover(quote_request())

    assert not batch.quotes
    assert len(batch.failures) == 1
    assert batch.failures[0].reason is ProviderFailureReason.DISABLED
    assert "operation_not_entitled" in batch.failures[0].detail
    assert adapter.calls == 0

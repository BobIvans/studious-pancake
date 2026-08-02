from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from src.provider_governance import (
    AdmissionRequest,
    DeadlineAdmissionScheduler,
    DependencyController,
    ProviderEntitlement,
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


def _entitlement() -> ProviderEntitlement:
    return ProviderEntitlement(
        provider_id="provider-a",
        generation="generation-1",
        allowed_operations=frozenset({ProviderOperation.DISCOVERY}),
        window_seconds=60.0,
        request_limit=3,
        cost_unit_limit=3,
        spend_limit_micros=0,
        max_concurrency=3,
        source_ref="review-regression",
    )


def _request(clock: FakeClock, work_id: str, fairness_key: str) -> AdmissionRequest:
    return AdmissionRequest(
        work_id=work_id,
        provider_id="provider-a",
        operation=ProviderOperation.DISCOVERY,
        request_fingerprint=f"fingerprint:{work_id}",
        fairness_key=fairness_key,
        deadline_at=clock() + 120.0,
        expected_generation="generation-1",
        lease_ttl_seconds=90.0,
    )


@pytest.mark.asyncio
async def test_scheduler_reranks_fairness_after_each_grant() -> None:
    clock = FakeClock()
    manifest = _entitlement()
    authority = ProviderSpendAuthority(
        {manifest.provider_id: manifest},
        clock=clock,
        wall_clock=clock,
    )
    scheduler = DeadlineAdmissionScheduler(
        authority,
        DependencyController(clock=clock),
        clock=clock,
        poll_interval_seconds=0.001,
    )

    # Exhaust the first window without changing the scheduler's fairness counts.
    for index in range(3):
        lease = await authority.reserve(_request(clock, f"seed-{index}", "seed"))
        await authority.mark_issued(lease)
        await authority.complete(lease)

    order: list[str] = []

    async def record(label: str) -> None:
        order.append(label)

    tasks = (
        asyncio.create_task(
            scheduler.execute(
                _request(clock, "a-1", "tenant-a"),
                lambda: record("a-1"),
            )
        ),
        asyncio.create_task(
            scheduler.execute(
                _request(clock, "a-2", "tenant-a"),
                lambda: record("a-2"),
            )
        ),
        asyncio.create_task(
            scheduler.execute(
                _request(clock, "b-1", "tenant-b"),
                lambda: record("b-1"),
            )
        ),
    )
    await asyncio.sleep(0.01)
    clock.advance(61.0)
    await asyncio.gather(*tasks)

    assert order == ["a-1", "b-1", "a-2"]


@dataclass
class _Circuit:
    health: ProviderHealth = ProviderHealth.READY

    def record_failure(self, *_: object) -> None:
        self.health = ProviderHealth.UNHEALTHY


class UnauthorizedAdapter:
    provider_id = "unauthorized_provider"
    capabilities = ProviderCapabilities(
        provider_id=provider_id,
        schema_version_pin="unauthorized-provider@test",
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
        auth_kind=AuthKind.API_KEY,
        role=ProviderRole.DISCOVERY_ONLY,
        admission_reason="test unauthorized adapter",
    )

    def __init__(self) -> None:
        self.circuit = _Circuit()
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

    async def request_quote(self, _: QuoteRequest) -> ProviderFailure:
        self.calls += 1
        return ProviderFailure(
            provider=self.provider_id,
            reason=ProviderFailureReason.HTTP_ERROR,
            retryable=False,
            detail="unauthorized",
            status_code=401,
        )


def _quote_request() -> QuoteRequest:
    return QuoteRequest(
        input_mint=SOL,
        output_mint=USDC,
        amount_base_units=1_000_000,
        user_wallet=WALLET,
        slippage_bps=50,
        input_decimals=9,
        output_decimals=6,
    )


@pytest.mark.asyncio
async def test_http_401_disables_dependency_before_second_provider_call() -> None:
    adapter = UnauthorizedAdapter()
    registry = ProviderRegistry((adapter,))
    plane = DiscoveryPlane(registry, provider_timeout_seconds=0.1)

    first = await plane.discover(_quote_request())
    second = await plane.discover(_quote_request())
    snapshot = await registry.governance.snapshot(adapter.provider_id)

    assert first.failures[0].reason is ProviderFailureReason.HTTP_ERROR
    assert second.failures[0].reason is ProviderFailureReason.DISABLED
    assert adapter.calls == 1
    assert snapshot["dependency_mode"] == "disabled"
    assert snapshot["dependency_reason"] == "hard_failure:auth"

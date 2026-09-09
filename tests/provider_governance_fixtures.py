"""Explicit synthetic entitlements for offline routing regression fixtures only."""

from src.provider_governance import (
    ProviderEntitlement,
    ProviderGovernance,
    ProviderOperation,
)
from src.routing.registry import ProviderRegistry


def reviewed_manifests():
    return {
        provider: ProviderEntitlement(
            provider_id=provider,
            generation="offline-reviewed-fixture-g1",
            allowed_operations=frozenset({ProviderOperation.DISCOVERY}),
            window_seconds=60,
            request_limit=100,
            cost_unit_limit=100,
            spend_limit_micros=0,
            max_concurrency=4,
            source_ref="synthetic-routing-regression-only",
        )
        for provider in ("jupiter_router", "okx_dex", "openocean", "odos")
    }


def reviewed_registry(adapters):
    manifests = reviewed_manifests()
    return ProviderRegistry(
        adapters,
        governance=ProviderGovernance(
            {
                adapter.provider_id: manifests[adapter.provider_id]
                for adapter in adapters
            }
        ),
    )

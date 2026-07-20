"""Composition root for PR-056 runtime discovery."""

from __future__ import annotations

import os
from typing import Any, Mapping

from src.config.runtime import RuntimeConfig
from src.providers.jupiter.quota import JupiterQuotaManager
from src.routing.registry import DiscoveryPlane, ProviderRegistry
from src.runtime_discovery_coordinator import RuntimeDiscoveryCoordinator
from src.runtime_discovery_models import RuntimeDiscoveryUniverse


def build_runtime_discovery(
    config: RuntimeConfig,
    *,
    environ: Mapping[str, str] | None = None,
    transport: Any = None,
    universe: RuntimeDiscoveryUniverse | None = None,
    contract_registry: Any = None,
) -> RuntimeDiscoveryCoordinator:
    """Build one runtime-owned discovery plane and Jupiter quota manager."""

    environment = dict(os.environ if environ is None else environ)
    jupiter = config.providers.jupiter
    if jupiter.enabled and jupiter.api_key_reference is not None:
        resolved = jupiter.api_key_reference.resolve_from_environment(environment)
        if resolved:
            environment["JUPITER_API_KEY"] = resolved
    if not jupiter.enabled:
        environment.pop("JUPITER_API_KEY", None)

    quota = JupiterQuotaManager()
    registry_kwargs: dict[str, Any] = {
        "transport": transport,
        "jupiter_quota": quota,
    }
    if contract_registry is not None:
        registry_kwargs["contract_registry"] = contract_registry
    registry = ProviderRegistry.from_env(environment, **registry_kwargs)
    if not jupiter.enabled:
        registry = ProviderRegistry(
            tuple(
                adapter
                for adapter in registry.adapters
                if adapter.provider_id != "jupiter_router"
            )
        )
    active_universe = universe or RuntimeDiscoveryUniverse.load_default()
    plane = DiscoveryPlane(
        registry,
        provider_timeout_seconds=active_universe.provider_timeout_seconds,
    )
    return RuntimeDiscoveryCoordinator(
        plane=plane,
        universe=active_universe,
        user_wallet=config.wallet.public_key,
        commitment=config.cluster.commitment.value,
        jupiter_quota=quota,
    )

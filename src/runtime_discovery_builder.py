"""Composition root for PR-056 runtime discovery."""

from __future__ import annotations

import os
from typing import Any, Mapping

from src.config.runtime import RuntimeConfig
from src.providers.jupiter.quota import JupiterQuotaManager
from src.routing.provider_config import build_provider_registry_from_config
from src.routing.registry import DiscoveryPlane
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
    quota = JupiterQuotaManager()
    registry = build_provider_registry_from_config(
        config,
        environment,
        transport=transport,
        jupiter_quota=quota,
        contract_registry=contract_registry,
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

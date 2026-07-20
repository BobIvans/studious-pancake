"""Bounded runtime discovery composition for PR-056.

This package owns the provider discovery plane, account-wide Jupiter quota,
configured route universe, snapshot normalization, and detector invocation used
by the supported paper/shadow CLI. It never plans, compiles, signs, or submits.
"""

from src.runtime_discovery_builder import build_runtime_discovery
from src.runtime_discovery_coordinator import RuntimeDiscoveryCoordinator
from src.runtime_discovery_models import (
    DiscoveryClient,
    RuntimeDiscoveryError,
    RuntimeDiscoveryEvidence,
    RuntimeDiscoveryPair,
    RuntimeDiscoveryReport,
    RuntimeDiscoveryUniverse,
)

__all__ = [
    "DiscoveryClient",
    "RuntimeDiscoveryCoordinator",
    "RuntimeDiscoveryError",
    "RuntimeDiscoveryEvidence",
    "RuntimeDiscoveryPair",
    "RuntimeDiscoveryReport",
    "RuntimeDiscoveryUniverse",
    "build_runtime_discovery",
]

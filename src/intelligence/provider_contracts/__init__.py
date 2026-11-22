"""OCA-W13: provider capability registry, data contracts, compatibility."""

from .registry import (
    COMPATIBLE,
    DataContract,
    INCOMPATIBLE,
    KNOWN_MODES,
    MODE_ONE_SHOT,
    MODE_POLL_ONLY,
    MODE_STREAMING,
    MODE_UNAVAILABLE,
    PARTIAL,
    ProviderCapability,
    ProviderCapabilityRegistry,
    REGISTRY_SCHEMA,
    UNKNOWN,
    evaluate_compatibility,
)

__all__ = [
    "COMPATIBLE",
    "DataContract",
    "INCOMPATIBLE",
    "KNOWN_MODES",
    "MODE_ONE_SHOT",
    "MODE_POLL_ONLY",
    "MODE_STREAMING",
    "MODE_UNAVAILABLE",
    "PARTIAL",
    "REGISTRY_SCHEMA",
    "ProviderCapability",
    "ProviderCapabilityRegistry",
    "UNKNOWN",
    "evaluate_compatibility",
]

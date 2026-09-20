"""Installed desired-state management for external provider resources."""

from .engine import ApplyResult, ExternalResourceProvider, ProviderConflict, apply_plan
from .ledger import MutationConflict, MutationLedger
from .models import (
    DesiredResource,
    DesiredState,
    ExternalResourceError,
    OperationKind,
    PlanOperation,
    RemoteInventory,
    RemoteResource,
    ResourceKey,
    SealedPlan,
    canonical_json,
    canonical_sha256,
)
from .planner import build_plan, executable_operations

__all__ = [
    "ApplyResult",
    "DesiredResource",
    "DesiredState",
    "ExternalResourceError",
    "ExternalResourceProvider",
    "MutationConflict",
    "MutationLedger",
    "OperationKind",
    "PlanOperation",
    "ProviderConflict",
    "RemoteInventory",
    "RemoteResource",
    "ResourceKey",
    "SealedPlan",
    "apply_plan",
    "build_plan",
    "canonical_json",
    "canonical_sha256",
    "executable_operations",
]

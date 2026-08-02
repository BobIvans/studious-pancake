"""Explicit rollback classification for release transitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RollbackClass(StrEnum):
    CODE_ONLY = "code_only"
    CONFIGURATION = "configuration"
    SCHEMA_COMPATIBLE = "schema_compatible"
    FORWARD_RECOVERY_ONLY = "forward_recovery_only"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True, slots=True)
class RollbackDecision:
    rollback_class: RollbackClass
    allowed: bool
    reason: str


def decide_rollback(
    *,
    storage_backward_readable: bool,
    configuration_compatible: bool,
    provider_contracts_compatible: bool,
    destructive_contraction: bool,
    immutable_previous_artifact_available: bool,
    verified_backup_available: bool,
) -> RollbackDecision:
    if destructive_contraction:
        return RollbackDecision(
            RollbackClass.FORWARD_RECOVERY_ONLY,
            False,
            "destructive contraction forbids downgrade",
        )
    if not immutable_previous_artifact_available or not verified_backup_available:
        return RollbackDecision(
            RollbackClass.FORBIDDEN,
            False,
            "immutable previous artifact and verified backup are required",
        )
    if not storage_backward_readable:
        return RollbackDecision(
            RollbackClass.FORWARD_RECOVERY_ONLY,
            False,
            "previous code cannot read current durable state",
        )
    if not configuration_compatible or not provider_contracts_compatible:
        return RollbackDecision(
            RollbackClass.FORBIDDEN,
            False,
            "configuration or provider contracts are incompatible",
        )
    return RollbackDecision(
        RollbackClass.SCHEMA_COMPATIBLE,
        True,
        "immutable artifact, backup, and compatibility requirements are satisfied",
    )

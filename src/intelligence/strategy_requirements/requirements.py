"""Strategy data requirements and provider compatibility (OCA-W14).

Declarative requirements link strategies to the provider capabilities they
need. Qualification state is derived and conservative: UNKNOWN compatibility
can never reach QUALIFIED, and eligibility / data / capital / authority states
are tracked separately — never collapsed into one badge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..provider_contracts.registry import (
    UNKNOWN,
    ProviderCapabilityRegistry,
    evaluate_compatibility,
)

REGISTRY_SCHEMA = "studious.strategy-requirements.v1"

# Separate qualification states (evidence vocabulary; unknown is never zero).
DATA_UNKNOWN = "DATA_UNKNOWN"
DATA_COMPATIBLE = "DATA_COMPATIBLE"
DATA_PARTIAL = "DATA_PARTIAL"
DATA_INCOMPATIBLE = "DATA_INCOMPATIBLE"

QUALIFICATION_NOT_QUALIFIED = "NOT_QUALIFIED"
QUALIFICATION_DATA_READY = "DATA_READY"  # still not a live authority


@dataclass(frozen=True)
class StrategyDataRequirement:
    """One declared data requirement of one strategy."""

    strategy_id: str
    provider_id: str
    capability: str
    mode: str | None = None
    max_staleness_seconds: int | None = None
    replay: bool = False

    def to_record(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "provider_id": self.provider_id,
            "capability": self.capability,
            "mode": self.mode,
            "max_staleness_seconds": self.max_staleness_seconds,
            "replay": self.replay,
        }

    def as_eval_request(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "max_staleness_seconds": self.max_staleness_seconds,
            "replay": self.replay,
        }


class StrategyRequirementRegistry:
    """Deterministic registry of declared strategy data requirements."""

    def __init__(self) -> None:
        self._requirements: dict[tuple[str, str, str], StrategyDataRequirement] = {}

    def declare(self, requirement: StrategyDataRequirement) -> StrategyDataRequirement:
        key = (requirement.strategy_id, requirement.provider_id, requirement.capability)
        self._requirements[key] = requirement
        return requirement

    def for_strategy(self, strategy_id: str) -> list[StrategyDataRequirement]:
        keys = sorted(key for key in self._requirements if key[0] == strategy_id)
        return [self._requirements[key] for key in keys]

    def records(self) -> list[dict[str, Any]]:
        return [
            self._requirements[key].to_record() for key in sorted(self._requirements)
        ]


def evaluate_strategy(
    requirement: StrategyDataRequirement,
    providers: ProviderCapabilityRegistry,
) -> dict[str, Any]:
    """Evaluate one requirement against the declared capability registry.

    Returns the compatibility verdict plus the derived data state and the
    qualification state (which stays NOT_QUALIFIED unless every requirement is
    at least DATA_COMPATIBLE against declared evidence — and even then it is
    DATA_READY, not a live authority).
    """
    capability = providers.get(requirement.provider_id, requirement.capability)
    verdict = evaluate_compatibility(requirement.as_eval_request(), capability)
    status = verdict["status"]
    if status == UNKNOWN:
        data_state = DATA_UNKNOWN
    elif status == "COMPATIBLE":
        data_state = DATA_COMPATIBLE
    elif status == "PARTIAL":
        data_state = DATA_PARTIAL
    else:
        data_state = DATA_INCOMPATIBLE
    qualification = (
        QUALIFICATION_DATA_READY
        if data_state == DATA_COMPATIBLE
        else QUALIFICATION_NOT_QUALIFIED
    )
    return {
        "strategy_id": requirement.strategy_id,
        "provider_id": requirement.provider_id,
        "capability": requirement.capability,
        "verdict": verdict,
        "data_state": data_state,
        "qualification_state": qualification,
        "note": (
            "DATA_READY is declared-evidence only; live authority requires "
            "governed qualification (QPR/R-02 gates) and observed evidence (OCA-W10)"
        ),
    }

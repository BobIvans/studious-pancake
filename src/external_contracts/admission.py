"""Bind PR-026 runtime configuration to verified PR-027 contract pins."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from src.config.runtime import RuntimeConfig
from src.external_contracts.drift import detect_drift
from src.external_contracts.models import ContractCapability, ContractStatus
from src.external_contracts.registry import ExternalContractRegistry


@dataclass(frozen=True, slots=True)
class ProviderAdmission:
    provider: str
    allowed: bool
    reason: str
    contract_id: str | None


@dataclass(frozen=True, slots=True)
class RuntimeAdmissionReport:
    schema_version: str
    execution_allowed: bool
    diagnostic: str
    providers: tuple[ProviderAdmission, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "execution_allowed": self.execution_allowed,
            "diagnostic": self.diagnostic,
            "providers": [asdict(item) for item in self.providers],
        }


def _first(registry: ExternalContractRegistry, provider: str):
    entries = registry.provider(provider)
    return entries[0] if entries else None


def evaluate_runtime_admission(
    config: RuntimeConfig,
    registry: ExternalContractRegistry | None = None,
) -> RuntimeAdmissionReport:
    active_registry = registry or ExternalContractRegistry.load_default()
    drift = detect_drift(active_registry)
    decisions: list[ProviderAdmission] = []

    jupiter = _first(active_registry, "jupiter")
    jupiter_allowed = bool(
        jupiter
        and jupiter.status is ContractStatus.ACTIVE
        and ContractCapability.COMPOSABLE_INSTRUCTIONS in jupiter.capabilities
        and drift.ok
    )
    decisions.append(
        ProviderAdmission(
            "jupiter",
            jupiter_allowed,
            "verified-composable-pin" if jupiter_allowed else "contract-not-active-composable",
            jupiter.id if jupiter else None,
        )
    )

    jito = _first(active_registry, "jito")
    decisions.append(
        ProviderAdmission(
            "jito",
            False,
            "credential-shape-never-promotes-an-unverified-contract",
            jito.id if jito else None,
        )
    )

    marginfi = _first(active_registry, "marginfi")
    marginfi_reason = "marginfi-disabled-until-pr028-binary-conformance"
    if config.providers.marginfi.enabled:
        configured = config.providers.marginfi.program_id
        pinned = marginfi.deployment_program_id if marginfi else None
        if configured != pinned:
            marginfi_reason = "configured-marginfi-program-does-not-match-official-pin"
    decisions.append(
        ProviderAdmission(
            "marginfi",
            False,
            marginfi_reason,
            marginfi.id if marginfi else None,
        )
    )

    execution_allowed = drift.execution_allowed and all(
        item.allowed
        for item in decisions
        if item.provider in {"jupiter", "marginfi"}
    )
    diagnostic = "verified" if execution_allowed else (
        "disabled-contract-drift" if not drift.ok else "disabled-contract-admission"
    )
    return RuntimeAdmissionReport(
        schema_version="pr027.runtime-admission.v1",
        execution_allowed=execution_allowed,
        diagnostic=diagnostic,
        providers=tuple(decisions),
    )

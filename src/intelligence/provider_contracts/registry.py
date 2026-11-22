"""Provider capability registry and versioned data contracts (OCA-W13).

Additive, read-only-by-default provider contract layer. It never enables a
provider: every registry entry defaults to disabled, and enablement authority
stays with the existing governance owners (``src/provider_governance/``,
``src/external_contracts/``). This package only declares typed contracts and
capability/health/identity/mode records so strategies can be evaluated against
declared — and later, observed — capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

REGISTRY_SCHEMA = "studious.provider-contracts.v1"

# Declared source capture modes (OCA-W0C taxonomy). Declared modes are
# statements; observed modes require OCA-W10 runtime evidence and are tracked
# separately with provenance.
MODE_STREAMING = "STREAMING"
MODE_POLL_ONLY = "POLL_ONLY"
MODE_ONE_SHOT = "ONE_SHOT"
MODE_UNAVAILABLE = "UNAVAILABLE"
KNOWN_MODES = {MODE_STREAMING, MODE_POLL_ONLY, MODE_ONE_SHOT, MODE_UNAVAILABLE}

COMPATIBLE = "COMPATIBLE"
PARTIAL = "PARTIAL"
INCOMPATIBLE = "INCOMPATIBLE"
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class DataContract:
    """Versioned data contract for one provider capability."""

    contract_id: str
    schema_version: int = 1
    units: str = "unknown"
    decimals: int | None = None
    timestamp_semantics: str = "unknown"  # event|ingest|recorded
    cursor_field: str | None = None
    replay_capable: bool = False
    rate_limit_policy: str = "unknown"
    fields: tuple[dict[str, str], ...] = field(default=())

    def to_record(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "schema_version": self.schema_version,
            "units": self.units,
            "decimals": self.decimals,
            "timestamp_semantics": self.timestamp_semantics,
            "cursor_field": self.cursor_field,
            "replay_capable": self.replay_capable,
            "rate_limit_policy": self.rate_limit_policy,
            "fields": [dict(item) for item in self.fields],
        }


@dataclass
class ProviderCapability:
    """One capability declaration for one provider."""

    provider_id: str
    capability: str
    mode: str
    contract: DataContract | None = None
    chain_identity_required: bool = False
    enabled: bool = False  # never set True by this package
    evidence: str = "DECLARED_ONLY"

    def __post_init__(self) -> None:
        if self.mode not in KNOWN_MODES:
            raise ValueError(f"unknown source mode: {self.mode}")
        if self.enabled:
            raise ValueError("registry entries are always disabled by construction")

    def to_record(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "capability": self.capability,
            "mode": self.mode,
            "enabled": self.enabled,
            "evidence": self.evidence,
            "chain_identity_required": self.chain_identity_required,
            "contract": self.contract.to_record() if self.contract else None,
        }


class ProviderCapabilityRegistry:
    """Deterministic registry of declared capabilities. Never enables."""

    def __init__(self) -> None:
        self._capabilities: dict[tuple[str, str], ProviderCapability] = {}

    def declare(self, capability: ProviderCapability) -> ProviderCapability:
        key = (capability.provider_id, capability.capability)
        self._capabilities[key] = capability
        return capability

    def get(self, provider_id: str, capability: str) -> ProviderCapability | None:
        return self._capabilities.get((provider_id, capability))

    def providers(self) -> list[str]:
        return sorted({provider for provider, _ in self._capabilities})

    def records(self) -> list[dict[str, Any]]:
        return [
            self._capabilities[key].to_record() for key in sorted(self._capabilities)
        ]

    def enabled_count(self) -> int:
        return sum(1 for item in self._capabilities.values() if item.enabled)


def evaluate_compatibility(
    requirement: dict[str, Any],
    capability: ProviderCapability | None,
) -> dict[str, Any]:
    """Evaluate a strategy data requirement against a declared capability.

    Output is COMPATIBLE/PARTIAL/INCOMPATIBLE/UNKNOWN with reason codes.
    UNKNOWN is never promoted; missing evidence yields UNKNOWN, not zero.
    """
    reasons: list[str] = []
    if capability is None:
        return {"status": UNKNOWN, "reason_codes": ["CAPABILITY_NOT_DECLARED"]}
    if capability.evidence != "OBSERVED":
        reasons.append("DECLARED_ONLY_NO_OBSERVED_EVIDENCE")
    required_mode = requirement.get("mode")
    if required_mode is not None and capability.mode != required_mode:
        reasons.append(f"MODE_MISMATCH_{capability.mode}_VS_{required_mode}")
    freshness = requirement.get("max_staleness_seconds")
    contract = capability.contract
    if freshness is not None and contract is None:
        reasons.append("NO_DATA_CONTRACT_FOR_FRESHNESS_EVALUATION")
    if requirement.get("replay") and (contract is None or not contract.replay_capable):
        reasons.append("REPLAY_NOT_CONTRACTED")
    if capability.mode == MODE_UNAVAILABLE:
        reasons.append("SOURCE_UNAVAILABLE")
        return {"status": INCOMPATIBLE, "reason_codes": reasons}
    # DECLARED_ONLY evidence is informational: it downgrades nothing by
    # itself, but it is always surfaced so callers cannot mistake declared
    # capability for observed capability.
    severity = [
        code for code in reasons if code != "DECLARED_ONLY_NO_OBSERVED_EVIDENCE"
    ]
    if len(severity) >= 2:
        return {"status": INCOMPATIBLE, "reason_codes": reasons}
    if severity:
        return {"status": PARTIAL, "reason_codes": reasons}
    reasons.append("CLEAN_AGAINST_DECLARED_EVIDENCE_ONLY")
    return {"status": COMPATIBLE, "reason_codes": reasons}

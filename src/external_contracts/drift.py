"""Deterministic drift reporting for pinned external artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from typing import Any

from src.external_contracts.models import ExternalContract
from src.external_contracts.registry import ExternalContractRegistry


@dataclass(frozen=True, slots=True)
class DriftFinding:
    contract_id: str
    artifact_path: str
    expected_sha256: str
    observed_sha256: str | None
    state: str


@dataclass(frozen=True, slots=True)
class ContractGateState:
    contract_id: str
    provider: str
    status: str
    promotion_state: str
    local_artifact_integrity: bool
    remote_schema_freshness: bool
    credentialed_api_conformance: bool
    deployed_program_attestation: bool
    execution_conformance: bool
    promotion_evidence: bool
    execution_allowed: bool


@dataclass(frozen=True, slots=True)
class DriftReport:
    schema_version: str
    ok: bool
    execution_allowed: bool
    diagnostic: str
    findings: tuple[DriftFinding, ...]
    contract_states: tuple[ContractGateState, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "execution_allowed": self.execution_allowed,
            "diagnostic": self.diagnostic,
            "findings": [asdict(item) for item in self.findings],
            "contract_states": [asdict(item) for item in self.contract_states],
        }


def _gate_state(contract: ExternalContract, local_ok: bool) -> ContractGateState:
    evidence = contract.evidence
    return ContractGateState(
        contract.id,
        contract.provider,
        contract.status.value,
        contract.promotion_state.value,
        local_ok and evidence.local_artifact_integrity,
        evidence.remote_schema_freshness,
        evidence.credentialed_api_conformance,
        evidence.deployed_program_attestation,
        evidence.execution_conformance,
        evidence.promotion_evidence,
        contract.execution_allowed and local_ok,
    )


def detect_drift(registry: ExternalContractRegistry) -> DriftReport:
    findings: list[DriftFinding] = []
    local_integrity_by_contract: dict[str, bool] = {}
    for contract in sorted(registry.contracts, key=lambda item: item.id):
        local_ok = True
        for pin in sorted(contract.artifacts, key=lambda item: item.path):
            path = registry.resolve_artifact(pin.path)
            if not path.is_file():
                if pin.required:
                    local_ok = False
                    findings.append(
                        DriftFinding(
                            contract.id,
                            pin.path,
                            pin.sha256,
                            None,
                            "missing",
                        )
                    )
                continue
            observed = hashlib.sha256(path.read_bytes()).hexdigest()
            if observed != pin.sha256:
                local_ok = False
                findings.append(
                    DriftFinding(
                        contract.id,
                        pin.path,
                        pin.sha256,
                        observed,
                        "mismatch",
                    )
                )
        local_integrity_by_contract[contract.id] = local_ok

    ok = not findings
    contract_states = tuple(
        _gate_state(
            contract,
            local_integrity_by_contract.get(contract.id, False),
        )
        for contract in sorted(registry.contracts, key=lambda item: item.id)
    )
    execution_allowed = ok and any(item.execution_allowed for item in contract_states)
    if not ok:
        diagnostic = "disabled-contract-drift"
    elif not execution_allowed:
        diagnostic = "blocked-no-execution-conformance"
    else:
        diagnostic = "verified-execution-allowed"
    return DriftReport(
        schema_version="pr054.contract-drift.v2",
        ok=ok,
        execution_allowed=execution_allowed,
        diagnostic=diagnostic,
        findings=tuple(findings),
        contract_states=contract_states,
    )

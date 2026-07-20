"""Deterministic drift reporting for pinned external artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from typing import Any

from src.external_contracts.registry import ExternalContractRegistry


@dataclass(frozen=True, slots=True)
class DriftFinding:
    contract_id: str
    artifact_path: str
    expected_sha256: str
    observed_sha256: str | None
    state: str


@dataclass(frozen=True, slots=True)
class DriftReport:
    schema_version: str
    ok: bool
    execution_allowed: bool
    diagnostic: str
    findings: tuple[DriftFinding, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "execution_allowed": self.execution_allowed,
            "diagnostic": self.diagnostic,
            "findings": [asdict(item) for item in self.findings],
        }


def detect_drift(registry: ExternalContractRegistry) -> DriftReport:
    findings: list[DriftFinding] = []
    for contract in sorted(registry.contracts, key=lambda item: item.id):
        for pin in sorted(contract.artifacts, key=lambda item: item.path):
            path = registry.resolve_artifact(pin.path)
            if not path.is_file():
                if pin.required:
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
                findings.append(
                    DriftFinding(
                        contract.id,
                        pin.path,
                        pin.sha256,
                        observed,
                        "mismatch",
                    )
                )
    ok = not findings
    active_contracts = registry.active()
    execution_allowed = ok and bool(active_contracts)
    if not ok:
        diagnostic = "disabled-contract-drift"
    elif not active_contracts:
        diagnostic = "disabled-no-active-contracts"
    else:
        diagnostic = "verified"
    return DriftReport(
        schema_version="pr027.contract-drift.v1",
        ok=ok,
        execution_allowed=execution_allowed,
        diagnostic=diagnostic,
        findings=tuple(findings),
    )

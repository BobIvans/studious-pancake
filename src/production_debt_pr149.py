"""PR-149 production debt and external compatibility inventory.

The repository deliberately remains fail-closed.  This module makes the remaining
production debt machine-readable and prevents quarantined legacy code or stale
external API contracts from being mistaken for active runtime capability.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

PR149_SCHEMA_VERSION = "pr149.production-debt-report.v1"
DEFAULT_POLICY_PATH = Path("src/resources/production_debt_pr149.json")
DEFAULT_CAPABILITIES_PATH = Path("src/resources/capabilities.json")
DEFAULT_CONTRACTS_PATH = Path("src/resources/external_contracts.json")


class DebtSeverity(StrEnum):
    """Operational severity of one production-readiness finding."""

    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"
    CRITICAL = "critical"


class DebtKind(StrEnum):
    """Stable finding categories consumed by review and release tooling."""

    PRODUCT_STATE = "product_state"
    ACTIVE_LEGACY_IMPORT = "active_legacy_import"
    ACTIVE_STALE_ENDPOINT = "active_stale_endpoint"
    ACTIVE_INCOMPLETE_CODE = "active_incomplete_code"
    QUARANTINED_DEBT = "quarantined_debt"
    EXTERNAL_CONTRACT = "external_contract"
    REGISTRY_INTEGRITY = "registry_integrity"


@dataclass(frozen=True, slots=True)
class DebtFinding:
    """One deterministic production debt observation."""

    finding_id: str
    kind: DebtKind
    severity: DebtSeverity
    summary: str
    path: str | None = None
    component_id: str | None = None
    contract_id: str | None = None
    remediation_group: str | None = None
    active: bool = False
    quarantined: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "kind": self.kind.value,
            "severity": self.severity.value,
            "summary": self.summary,
            "path": self.path,
            "component_id": self.component_id,
            "contract_id": self.contract_id,
            "remediation_group": self.remediation_group,
            "active": self.active,
            "quarantined": self.quarantined,
        }


@dataclass(frozen=True, slots=True)
class ProductionDebtReport:
    """Deterministic repository audit result.

    ``integrity_ok`` means known debt is honestly represented and quarantined.
    It is intentionally different from ``production_ready``.
    """

    schema_version: str
    product_state: str
    live_available: bool
    integrity_ok: bool
    production_ready: bool
    findings: tuple[DebtFinding, ...]
    umbrella_groups: tuple[Mapping[str, object], ...]
    report_sha256: str

    def to_dict(self) -> dict[str, object]:
        counts = {severity.value: 0 for severity in DebtSeverity}
        for finding in self.findings:
            counts[finding.severity.value] += 1
        return {
            "schema_version": self.schema_version,
            "product_state": self.product_state,
            "live_available": self.live_available,
            "integrity_ok": self.integrity_ok,
            "production_ready": self.production_ready,
            "finding_counts": counts,
            "findings": [finding.to_dict() for finding in self.findings],
            "umbrella_groups": [dict(group) for group in self.umbrella_groups],
            "report_sha256": self.report_sha256,
        }


def audit_repository(
    root: Path | str,
    *,
    policy_path: Path | str = DEFAULT_POLICY_PATH,
    capabilities_path: Path | str = DEFAULT_CAPABILITIES_PATH,
    contracts_path: Path | str = DEFAULT_CONTRACTS_PATH,
) -> ProductionDebtReport:
    """Audit production debt without network access or runtime side effects."""

    repository_root = Path(root).resolve()
    policy = _load_json(repository_root / Path(policy_path))
    capabilities = _load_json(repository_root / Path(capabilities_path))
    contracts = _load_json(repository_root / Path(contracts_path))

    findings: list[DebtFinding] = []
    product_state = str(capabilities.get("product_state", ""))
    live_available = bool(
        _mapping(capabilities.get("runtime_modes", {}), "runtime_modes")
        .get("live", {})
        .get("available", False)
    )

    _audit_product_state(policy, product_state, live_available, findings)
    components = _component_records(capabilities)
    _audit_components(repository_root, policy, components, findings)
    _audit_external_contracts(policy, contracts, findings)

    ordered_findings = tuple(
        sorted(
            findings,
            key=lambda item: (
                item.severity.value,
                item.kind.value,
                item.finding_id,
            ),
        )
    )
    integrity_ok = not any(
        finding.severity is DebtSeverity.CRITICAL for finding in ordered_findings
    )
    production_ready = integrity_ok and not any(
        finding.severity in {DebtSeverity.BLOCKER, DebtSeverity.CRITICAL}
        for finding in ordered_findings
    )
    umbrella_groups = tuple(
        _mapping(item, "umbrella_group")
        for item in _sequence(policy.get("umbrella_groups", ()), "umbrella_groups")
    )
    unsigned = {
        "schema_version": PR149_SCHEMA_VERSION,
        "product_state": product_state,
        "live_available": live_available,
        "integrity_ok": integrity_ok,
        "production_ready": production_ready,
        "findings": [finding.to_dict() for finding in ordered_findings],
        "umbrella_groups": [dict(group) for group in umbrella_groups],
    }
    report_sha256 = hashlib.sha256(_canonical_json(unsigned)).hexdigest()
    return ProductionDebtReport(
        schema_version=PR149_SCHEMA_VERSION,
        product_state=product_state,
        live_available=live_available,
        integrity_ok=integrity_ok,
        production_ready=production_ready,
        findings=ordered_findings,
        umbrella_groups=umbrella_groups,
        report_sha256=report_sha256,
    )


def _audit_product_state(
    policy: Mapping[str, Any],
    product_state: str,
    live_available: bool,
    findings: list[DebtFinding],
) -> None:
    required_state = str(policy.get("required_product_state", ""))
    required_live = bool(policy.get("required_live_available", False))
    if product_state != required_state:
        findings.append(
            DebtFinding(
                finding_id="PRODUCT_STATE_DRIFT",
                kind=DebtKind.PRODUCT_STATE,
                severity=DebtSeverity.CRITICAL,
                summary=(
                    f"capability product_state is {product_state!r}; "
                    f"expected {required_state!r}"
                ),
                remediation_group="RELEASE_OPERATIONS",
                active=True,
            )
        )
    else:
        findings.append(
            DebtFinding(
                finding_id="PRODUCT_STATE_EXPLICITLY_NOT_READY",
                kind=DebtKind.PRODUCT_STATE,
                severity=DebtSeverity.BLOCKER,
                summary=(
                    "supported product contract explicitly remains "
                    "not-production-ready"
                ),
                remediation_group="EXECUTION_VERTICAL",
                active=True,
            )
        )
    if live_available != required_live:
        findings.append(
            DebtFinding(
                finding_id="LIVE_MODE_AVAILABILITY_DRIFT",
                kind=DebtKind.PRODUCT_STATE,
                severity=DebtSeverity.CRITICAL,
                summary=(
                    "live mode availability contradicts the fail-closed debt policy"
                ),
                remediation_group="RELEASE_OPERATIONS",
                active=True,
            )
        )


def _audit_components(
    root: Path,
    policy: Mapping[str, Any],
    components: Sequence[Mapping[str, Any]],
    findings: list[DebtFinding],
) -> None:
    forbidden_imports = tuple(
        str(item)
        for item in _sequence(
            policy.get("forbidden_active_import_roots", ()),
            "forbidden_active_import_roots",
        )
    )
    forbidden_endpoints = tuple(
        str(item)
        for item in _sequence(
            policy.get("forbidden_active_endpoint_fragments", ()),
            "forbidden_active_endpoint_fragments",
        )
    )
    allowed_quarantine = {
        str(item)
        for item in _sequence(
            policy.get("allowed_quarantined_paths", ()),
            "allowed_quarantined_paths",
        )
    }

    for component in components:
        component_id = str(component.get("id", ""))
        component_path = str(component.get("path", ""))
        active = bool(component.get("active_in_supported_entrypoint", False))
        quarantined = bool(component.get("quarantined", False))
        if not component_id or not component_path:
            findings.append(
                DebtFinding(
                    finding_id="MALFORMED_CAPABILITY_COMPONENT",
                    kind=DebtKind.REGISTRY_INTEGRITY,
                    severity=DebtSeverity.CRITICAL,
                    summary="capability component is missing id or path",
                    active=active,
                    quarantined=quarantined,
                )
            )
            continue

        path = root / component_path
        if not path.exists():
            findings.append(
                DebtFinding(
                    finding_id=f"MISSING_COMPONENT_PATH:{component_id}",
                    kind=DebtKind.REGISTRY_INTEGRITY,
                    severity=DebtSeverity.CRITICAL,
                    summary="capability component path does not exist",
                    path=component_path,
                    component_id=component_id,
                    active=active,
                    quarantined=quarantined,
                )
            )
            continue

        if quarantined:
            severity = (
                DebtSeverity.INFO
                if component_path in allowed_quarantine
                else DebtSeverity.WARNING
            )
            findings.append(
                DebtFinding(
                    finding_id=f"QUARANTINED_COMPONENT:{component_id}",
                    kind=DebtKind.QUARANTINED_DEBT,
                    severity=severity,
                    summary=(
                        "legacy or fixture-only component remains outside the "
                        "supported runtime"
                    ),
                    path=component_path,
                    component_id=component_id,
                    remediation_group=_component_group(component_id),
                    active=active,
                    quarantined=True,
                )
            )

        if not active:
            continue
        for source_path in _python_sources(path):
            source = source_path.read_text(encoding="utf-8")
            relative = source_path.relative_to(root).as_posix()
            _audit_active_source(
                source,
                relative,
                component_id,
                forbidden_imports,
                forbidden_endpoints,
                findings,
            )


def _audit_active_source(
    source: str,
    path: str,
    component_id: str,
    forbidden_imports: Sequence[str],
    forbidden_endpoints: Sequence[str],
    findings: list[DebtFinding],
) -> None:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        findings.append(
            DebtFinding(
                finding_id=f"ACTIVE_SYNTAX_ERROR:{path}",
                kind=DebtKind.ACTIVE_INCOMPLETE_CODE,
                severity=DebtSeverity.CRITICAL,
                summary=f"active source does not parse: {exc.msg}",
                path=path,
                component_id=component_id,
                remediation_group="EXECUTION_VERTICAL",
                active=True,
            )
        )
        return

    imported = _import_roots(tree)
    for forbidden in forbidden_imports:
        if any(
            name == forbidden or name.startswith(f"{forbidden}.")
            for name in imported
        ):
            findings.append(
                DebtFinding(
                    finding_id=f"ACTIVE_LEGACY_IMPORT:{component_id}:{forbidden}",
                    kind=DebtKind.ACTIVE_LEGACY_IMPORT,
                    severity=DebtSeverity.CRITICAL,
                    summary=(
                        "active component imports quarantined runtime root "
                        f"{forbidden}"
                    ),
                    path=path,
                    component_id=component_id,
                    remediation_group="EXECUTION_VERTICAL",
                    active=True,
                )
            )

    for endpoint in forbidden_endpoints:
        if endpoint in source:
            findings.append(
                DebtFinding(
                    finding_id=f"ACTIVE_STALE_ENDPOINT:{component_id}:{endpoint}",
                    kind=DebtKind.ACTIVE_STALE_ENDPOINT,
                    severity=DebtSeverity.CRITICAL,
                    summary=(
                        "active component contains stale provider endpoint "
                        f"{endpoint}"
                    ),
                    path=path,
                    component_id=component_id,
                    remediation_group="DATA_RELIABILITY",
                    active=True,
                )
            )

    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and _raises_not_implemented(node):
            findings.append(
                DebtFinding(
                    finding_id=(
                        "ACTIVE_NOT_IMPLEMENTED:"
                        f"{component_id}:{path}:{node.lineno}"
                    ),
                    kind=DebtKind.ACTIVE_INCOMPLETE_CODE,
                    severity=DebtSeverity.CRITICAL,
                    summary="active component raises NotImplementedError",
                    path=path,
                    component_id=component_id,
                    remediation_group="EXECUTION_VERTICAL",
                    active=True,
                )
            )


def _audit_external_contracts(
    policy: Mapping[str, Any],
    registry: Mapping[str, Any],
    findings: list[DebtFinding],
) -> None:
    requirements = _mapping(
        policy.get("external_contract_requirements", {}),
        "external_contract_requirements",
    )
    contracts = {
        str(item.get("id")): item
        for item in (
            _mapping(raw, "external_contract")
            for raw in _sequence(registry.get("contracts", ()), "contracts")
        )
        if item.get("id")
    }

    for contract_id, raw_requirement in requirements.items():
        requirement = _mapping(raw_requirement, f"requirement:{contract_id}")
        remediation_group = str(requirement.get("remediation_group", "")) or None
        contract = contracts.get(contract_id)
        if contract is None:
            findings.append(
                DebtFinding(
                    finding_id=f"MISSING_EXTERNAL_CONTRACT:{contract_id}",
                    kind=DebtKind.REGISTRY_INTEGRITY,
                    severity=DebtSeverity.CRITICAL,
                    summary="required external contract is absent from the registry",
                    contract_id=contract_id,
                    remediation_group=remediation_group,
                    active=True,
                )
            )
            continue
        _validate_contract_shape(contract_id, contract, requirement, findings)
        evidence = _mapping(contract.get("evidence", {}), f"evidence:{contract_id}")
        for evidence_name in _sequence(
            requirement.get("required_evidence", ()),
            f"required_evidence:{contract_id}",
        ):
            name = str(evidence_name)
            if not bool(evidence.get(name, False)):
                findings.append(
                    DebtFinding(
                        finding_id=f"EXTERNAL_EVIDENCE_PENDING:{contract_id}:{name}",
                        kind=DebtKind.EXTERNAL_CONTRACT,
                        severity=DebtSeverity.BLOCKER,
                        summary=f"external contract evidence {name} is not proven",
                        contract_id=contract_id,
                        remediation_group=remediation_group,
                        active=True,
                    )
                )


def _validate_contract_shape(
    contract_id: str,
    contract: Mapping[str, Any],
    requirement: Mapping[str, Any],
    findings: list[DebtFinding],
) -> None:
    remediation_group = str(requirement.get("remediation_group", "")) or None
    expected_status = requirement.get("required_status")
    if expected_status is not None and contract.get("status") != expected_status:
        _contract_drift(
            findings,
            contract_id,
            "status",
            f"expected {expected_status!r}, got {contract.get('status')!r}",
            remediation_group,
        )
    expected_program = requirement.get("required_program_id")
    if (
        expected_program is not None
        and contract.get("deployment_program_id") != expected_program
    ):
        _contract_drift(
            findings,
            contract_id,
            "program_id",
            "deployment program id does not match the reviewed mainnet identity",
            remediation_group,
        )

    probe = contract.get("conformance_probe")
    if probe is None:
        if requirement.get("required_endpoint_fragment") or requirement.get(
            "required_method"
        ):
            _contract_drift(
                findings,
                contract_id,
                "probe_missing",
                "required conformance probe is missing",
                remediation_group,
            )
        return
    probe_mapping = _mapping(probe, f"conformance_probe:{contract_id}")
    endpoint_fragment = requirement.get("required_endpoint_fragment")
    if endpoint_fragment is not None and str(endpoint_fragment) not in str(
        probe_mapping.get("url", "")
    ):
        _contract_drift(
            findings,
            contract_id,
            "endpoint",
            "conformance probe endpoint drifted from the reviewed contract",
            remediation_group,
        )
    required_method = requirement.get("required_method")
    if (
        required_method is not None
        and str(probe_mapping.get("method", "")).upper()
        != str(required_method).upper()
    ):
        _contract_drift(
            findings,
            contract_id,
            "method",
            "conformance probe HTTP method drifted from the reviewed contract",
            remediation_group,
        )


def _contract_drift(
    findings: list[DebtFinding],
    contract_id: str,
    suffix: str,
    summary: str,
    remediation_group: str | None,
) -> None:
    findings.append(
        DebtFinding(
            finding_id=f"EXTERNAL_CONTRACT_DRIFT:{contract_id}:{suffix}",
            kind=DebtKind.EXTERNAL_CONTRACT,
            severity=DebtSeverity.CRITICAL,
            summary=summary,
            contract_id=contract_id,
            remediation_group=remediation_group,
            active=True,
        )
    )


def _component_records(
    capabilities: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        _mapping(item, "capability_component")
        for item in _sequence(capabilities.get("components", ()), "components")
    )


def _component_group(component_id: str) -> str:
    if "jito" in component_id or "sender" in component_id:
        return "SUBMISSION_SETTLEMENT"
    if "provider" in component_id or "strategy" in component_id:
        return "EXECUTION_VERTICAL"
    return "RELEASE_OPERATIONS"


def _python_sources(path: Path) -> tuple[Path, ...]:
    if path.is_file():
        return (path,) if path.suffix == ".py" else ()
    return tuple(
        sorted(
            candidate
            for candidate in path.rglob("*.py")
            if "__pycache__" not in candidate.parts
        )
    )


def _import_roots(tree: ast.AST) -> frozenset[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return frozenset(names)


def _raises_not_implemented(node: ast.Raise) -> bool:
    value = node.exc
    if isinstance(value, ast.Name):
        return value.id == "NotImplementedError"
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        return value.func.id == "NotImplementedError"
    return False


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"required audit input missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON audit input: {path}") from exc
    return _mapping(payload, path.as_posix())


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _sequence(value: object, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{label} must be an array")
    return value


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-production-ready", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    report = audit_repository(args.root)
    payload = report.to_dict()
    if args.json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        print(
            f"integrity_ok={report.integrity_ok} "
            f"production_ready={report.production_ready} "
            f"findings={len(report.findings)} "
            f"sha256={report.report_sha256}"
        )
    if not report.integrity_ok:
        return 1
    if args.require_production_ready and not report.production_ready:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_CAPABILITIES_PATH",
    "DEFAULT_CONTRACTS_PATH",
    "DEFAULT_POLICY_PATH",
    "DebtFinding",
    "DebtKind",
    "DebtSeverity",
    "PR149_SCHEMA_VERSION",
    "ProductionDebtReport",
    "audit_repository",
    "main",
]

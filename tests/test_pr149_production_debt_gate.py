from __future__ import annotations

import json
from pathlib import Path

from src.production_debt_pr149 import DebtKind, DebtSeverity, audit_repository, main

ROOT = Path(__file__).resolve().parents[1]


def test_repository_debt_is_honest_but_not_production_ready() -> None:
    report = audit_repository(ROOT)

    assert report.integrity_ok is True
    assert report.production_ready is False
    assert report.product_state == "not-production-ready"
    assert report.live_available is False
    assert len(report.report_sha256) == 64
    assert any(
        finding.kind is DebtKind.EXTERNAL_CONTRACT
        and finding.severity is DebtSeverity.BLOCKER
        for finding in report.findings
    )
    assert {group["id"] for group in report.umbrella_groups} == {
        "EXECUTION_VERTICAL",
        "SUBMISSION_SETTLEMENT",
        "DATA_RELIABILITY",
        "RELEASE_OPERATIONS",
    }


def test_cli_integrity_mode_passes_but_production_requirement_blocks() -> None:
    assert main(["--root", str(ROOT), "--json"]) == 0
    assert main(["--root", str(ROOT), "--require-production-ready"]) == 2


def test_active_legacy_import_is_critical(tmp_path: Path) -> None:
    root = _minimal_repository(tmp_path)
    active = root / "src/active.py"
    active.write_text("import src.ingest.tx_builder\n", encoding="utf-8")

    report = audit_repository(root)

    assert report.integrity_ok is False
    assert any(
        finding.kind is DebtKind.ACTIVE_LEGACY_IMPORT
        and finding.severity is DebtSeverity.CRITICAL
        for finding in report.findings
    )


def test_active_stale_jupiter_endpoint_is_critical(tmp_path: Path) -> None:
    root = _minimal_repository(tmp_path)
    active = root / "src/active.py"
    active.write_text(
        'ENDPOINT = "https://api.jup.ag/swap/v2/swap-instructions"\n',
        encoding="utf-8",
    )

    report = audit_repository(root)

    assert report.integrity_ok is False
    assert any(
        finding.kind is DebtKind.ACTIVE_STALE_ENDPOINT
        and finding.severity is DebtSeverity.CRITICAL
        for finding in report.findings
    )


def test_active_not_implemented_is_critical(tmp_path: Path) -> None:
    root = _minimal_repository(tmp_path)
    active = root / "src/active.py"
    active.write_text(
        "def execute() -> None:\n    raise NotImplementedError\n",
        encoding="utf-8",
    )

    report = audit_repository(root)

    assert report.integrity_ok is False
    assert any(
        finding.kind is DebtKind.ACTIVE_INCOMPLETE_CODE
        and finding.severity is DebtSeverity.CRITICAL
        for finding in report.findings
    )


def test_quarantined_legacy_debt_is_reported_without_integrity_failure(
    tmp_path: Path,
) -> None:
    root = _minimal_repository(tmp_path, include_quarantine=True)
    legacy = root / "src/legacy_arb_bot.py"
    legacy.write_text("raise NotImplementedError\n", encoding="utf-8")

    report = audit_repository(root)

    assert report.integrity_ok is True
    assert any(
        finding.kind is DebtKind.QUARANTINED_DEBT and finding.quarantined
        for finding in report.findings
    )


def test_contract_endpoint_drift_is_critical(tmp_path: Path) -> None:
    root = _minimal_repository(tmp_path)
    contracts_path = root / "src/resources/external_contracts.json"
    payload = json.loads(contracts_path.read_text(encoding="utf-8"))
    payload["contracts"][0]["conformance_probe"]["url"] = (
        "https://api.jup.ag/swap/v1/quote"
    )
    contracts_path.write_text(json.dumps(payload), encoding="utf-8")

    report = audit_repository(root)

    assert report.integrity_ok is False
    assert any(
        finding.finding_id
        == "EXTERNAL_CONTRACT_DRIFT:jupiter.swap-v2-build:endpoint"
        for finding in report.findings
    )


def test_report_hash_is_deterministic() -> None:
    first = audit_repository(ROOT)
    second = audit_repository(ROOT)

    assert first.report_sha256 == second.report_sha256
    assert first.to_dict() == second.to_dict()


def _minimal_repository(path: Path, *, include_quarantine: bool = False) -> Path:
    root = path / "repo"
    resources = root / "src/resources"
    resources.mkdir(parents=True)
    (root / "src/active.py").write_text("VALUE = 1\n", encoding="utf-8")

    policy = json.loads(
        (ROOT / "src/resources/production_debt_pr149.json").read_text(
            encoding="utf-8"
        )
    )
    (resources / "production_debt_pr149.json").write_text(
        json.dumps(policy),
        encoding="utf-8",
    )

    components = [
        {
            "id": "runtime.active",
            "kind": "runtime",
            "path": "src/active.py",
            "capability": "implemented",
            "active_in_supported_entrypoint": True,
            "quarantined": False,
            "allowed_modes": ["disabled"],
            "reason": "test fixture",
        }
    ]
    if include_quarantine:
        components.append(
            {
                "id": "execution.legacy_monolith",
                "kind": "legacy",
                "path": "src/legacy_arb_bot.py",
                "capability": "fixture-only",
                "active_in_supported_entrypoint": False,
                "quarantined": True,
                "allowed_modes": ["disabled"],
                "reason": "test fixture",
            }
        )
    capabilities = {
        "product_state": "not-production-ready",
        "runtime_modes": {"live": {"available": False}},
        "components": components,
    }
    (resources / "capabilities.json").write_text(
        json.dumps(capabilities),
        encoding="utf-8",
    )

    contracts = {
        "contracts": [
            _contract(
                "jupiter.swap-v2-build",
                "jupiter",
                "active",
                "https://api.jup.ag/swap/v2/build?taker=111",
                "GET",
                deployment_program_id=None,
            ),
            _contract(
                "jito.low-latency-json-rpc",
                "jito",
                "disabled-unverified",
                "https://mainnet.block-engine.jito.wtf/api/v1/getTipAccounts",
                "POST",
                deployment_program_id=None,
            ),
            _contract(
                "marginfi.v2-mainnet-source-identity",
                "marginfi",
                "disabled-unverified",
                None,
                None,
                deployment_program_id=(
                    "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"
                ),
            ),
        ]
    }
    (resources / "external_contracts.json").write_text(
        json.dumps(contracts),
        encoding="utf-8",
    )
    return root


def _contract(
    contract_id: str,
    provider: str,
    status: str,
    url: str | None,
    method: str | None,
    *,
    deployment_program_id: str | None,
) -> dict[str, object]:
    probe = None if url is None else {"url": url, "method": method}
    return {
        "id": contract_id,
        "provider": provider,
        "status": status,
        "deployment_program_id": deployment_program_id,
        "conformance_probe": probe,
        "evidence": {
            "local_artifact_integrity": True,
            "remote_schema_freshness": False,
            "credentialed_api_conformance": False,
            "deployed_program_attestation": False,
            "execution_conformance": False,
            "promotion_evidence": False,
        },
    }

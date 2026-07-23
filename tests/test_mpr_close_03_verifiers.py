from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mpr_close_03_verifiers import (
    SCHEMA_DRIFT,
    SCHEMA_EXTERNAL,
    SCHEMA_SOLANA,
    verify_external_contracts,
    verify_provider_drift_probes,
    verify_solana_v0_alt_conformance,
)


def test_solana_verifier_smoke_contract() -> None:
    report = verify_solana_v0_alt_conformance()

    assert report.schema_version == SCHEMA_SOLANA
    assert isinstance(report.ok, bool)
    assert isinstance(report.facts, dict)
    assert isinstance(report.blockers, tuple)
    assert "router_uses_swap_v2_build" in report.facts
    assert "helius_delivery_module" in report.facts
    assert "helius_authenticated_ingress_module" in report.facts
    assert "helius_rooted_recovery_module" in report.facts


def test_external_contracts_verifier_smoke_contract() -> None:
    report = verify_external_contracts()

    assert report.schema_version == SCHEMA_EXTERNAL
    assert isinstance(report.ok, bool)
    assert isinstance(report.facts, dict)
    assert isinstance(report.blockers, tuple)
    assert "jupiter_status" in report.facts
    assert "okx_status" in report.facts
    assert "openocean_status" in report.facts
    assert "odos_status" in report.facts
    assert "kamino_reviewed_combination_count" in report.facts


def test_provider_drift_probe_verifier_smoke_contract() -> None:
    report = verify_provider_drift_probes()

    assert report.schema_version == SCHEMA_DRIFT
    assert isinstance(report.ok, bool)
    assert isinstance(report.facts, dict)
    assert isinstance(report.blockers, tuple)
    assert "contract_count" in report.facts
    assert "artifact_count" in report.facts
    assert "redaction_secret_hits" in report.facts
    assert "missing_artifacts" in report.facts

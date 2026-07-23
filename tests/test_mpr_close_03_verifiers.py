from __future__ import annotations

from src.mpr_close_03_verifiers import (
    SCHEMA_DRIFT,
    SCHEMA_EXTERNAL,
    SCHEMA_SOLANA,
    verify_external_contracts,
    verify_provider_drift_probes,
    verify_solana_v0_alt_conformance,
)


def test_solana_verifier_reports_router_and_helius_modules() -> None:
    report = verify_solana_v0_alt_conformance()

    assert report.schema_version == SCHEMA_SOLANA
    assert report.facts["router_uses_swap_v2_build"] is True
    assert report.facts["helius_delivery_module"] is True
    assert report.facts["helius_authenticated_ingress_module"] is True
    assert isinstance(report.blockers, tuple)



def test_external_contracts_verifier_keeps_discovery_boundaries_fail_closed() -> None:
    report = verify_external_contracts()

    assert report.schema_version == SCHEMA_EXTERNAL
    assert report.facts["jupiter_status"] == "active"
    assert report.facts["okx_status"] == "discovery-only"
    assert report.facts["openocean_status"] == "discovery-only"
    assert report.facts["odos_status"] == "discovery-only"
    assert report.facts["kamino_reviewed_combination_count"] == 0



def test_provider_drift_probe_verifier_reports_missing_artifacts_without_secrets() -> None:
    report = verify_provider_drift_probes()

    assert report.schema_version == SCHEMA_DRIFT
    assert report.facts["contract_count"] >= 1
    assert report.facts["artifact_count"] >= 1
    assert report.facts["redaction_secret_hits"] == 0
    assert isinstance(report.facts["missing_artifacts"], list)

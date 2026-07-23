from __future__ import annotations

from src.mpr_close_03_verifiers import (
    SCHEMA_DRIFT,
    SCHEMA_EXTERNAL,
    SCHEMA_SOLANA,
    verify_external_contracts,
    verify_provider_drift_probes,
    verify_solana_v0_alt_conformance,
)


def test_solana_verifier_reports_router_and_helius_shape() -> None:
    report = verify_solana_v0_alt_conformance()

    assert report.schema_version == SCHEMA_SOLANA
    assert report.facts["router_uses_swap_v2_build"] is True
    assert isinstance(report.facts["helius_delivery_module"], bool)
    assert isinstance(report.facts["helius_authenticated_ingress_module"], bool)
    assert isinstance(report.facts["helius_rooted_recovery_module"], bool)
    assert isinstance(report.facts["v0_occurrences"], int)
    assert isinstance(report.facts["finalized_occurrences"], int)
    assert isinstance(report.facts["alt_occurrences"], int)
    assert isinstance(report.blockers, tuple)


def test_external_contracts_verifier_keeps_non_jupiter_routes_fail_closed() -> None:
    report = verify_external_contracts()

    assert report.schema_version == SCHEMA_EXTERNAL
    assert report.facts["jupiter_status"] == "active"
    assert report.facts["okx_status"] != "active"
    assert report.facts["openocean_status"] != "active"
    assert report.facts["odos_status"] != "active"
    assert isinstance(report.facts["kamino_reviewed_combination_count"], int)
    assert report.facts["kamino_reviewed_combination_count"] >= 0
    assert report.facts["kamino_claims_enabled_support"] == (
        report.facts["kamino_reviewed_combination_count"] > 0
    )


def test_provider_drift_probe_verifier_reports_manifest_shape_without_secrets() -> None:
    report = verify_provider_drift_probes()

    assert report.schema_version == SCHEMA_DRIFT
    assert report.facts["contract_count"] >= 1
    assert report.facts["artifact_count"] >= 1
    assert report.facts["redaction_secret_hits"] == 0
    assert report.facts["reviewed_source_markers"] >= 1
    assert isinstance(report.facts["missing_artifacts"], list)

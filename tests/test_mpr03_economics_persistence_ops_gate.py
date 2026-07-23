from __future__ import annotations

import json

import pytest

from src.mpr03_economics_persistence_ops_gate import (
    REQUIRED_BACKUP_FAULTS,
    REQUIRED_BACKUP_STEPS,
    REQUIRED_DEBT_IDS,
    REQUIRED_MANIFEST_KEYS,
    REQUIRED_METRICS,
    REQUIRED_READINESS_STATES,
    SCHEMA_VERSION,
    assert_mpr03_ready,
    validate_mpr03_evidence,
)

DIGEST = "a" * 64


def materialized(path: str = "evidence/report.json", digest: str = DIGEST) -> dict[str, str]:
    return {"path": path, "sha256": digest}


def valid_evidence() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "debt_ids": sorted(REQUIRED_DEBT_IDS),
        "upstream": {
            "mpr01_accepted": True,
            "mpr01_report_sha256": "1" * 64,
            "mpr02_accepted": True,
            "mpr02_report_sha256": "2" * 64,
        },
        "finalized_economics": {
            "integer_base_units_only": True,
            "quote_bound": True,
            "simulation_bound": True,
            "reservation_bound": True,
            "payer_balance_deltas_bound": True,
            "token_account_deltas_bound": True,
            "flashloan_repayment_math_bound": True,
            "fail_closed_when_finalized_unavailable": True,
            "gross_spread_can_mark_success": False,
            "conservative_net_required": True,
            "negative_or_zero_net_blocks_success": True,
            "materialized_report": materialized("evidence/economics.json", "3" * 64),
        },
        "persistence": {
            "approved_factory_only": True,
            "direct_sqlite_connect_sites_remaining": 0,
            "direct_aiosqlite_connect_sites_remaining": 0,
            "central_pragma_policy": True,
            "schema_fingerprint": True,
            "migration_version_guard": True,
            "exactly_once_terminal_state": True,
            "crash_restart_no_duplicate_terminal": True,
        },
        "backup_recovery": {
            "publication_steps": list(REQUIRED_BACKUP_STEPS),
            "restore_validation": True,
            "rollback_markers": True,
            "previous_generation_preserved": True,
            "fault_matrix": sorted(REQUIRED_BACKUP_FAULTS),
        },
        "observability": {
            "readiness_states": sorted(REQUIRED_READINESS_STATES),
            "readiness_not_static_config_flag": True,
            "live_denied_state_present": True,
            "metrics": sorted(REQUIRED_METRICS),
            "stable_cardinality": True,
            "secret_redaction_corpus": True,
        },
        "shadow_soak": {
            "sender_free": True,
            "lineage_counts": {
                "synthetic": 2,
                "recorded": 3,
                "credentialed": 1,
                "finalized": 0,
            },
            "synthetic_counted_as_real_release_evidence": False,
            "recorded_counted_as_real_release_evidence": False,
            "materialized_report": materialized("evidence/shadow_soak.json", "4" * 64),
        },
        "release_manifest": {
            key: {"status": "available", "sha256": "5" * 64}
            for key in REQUIRED_MANIFEST_KEYS
        },
        "secret_incident_drill": {
            "rotation_drill": True,
            "revocation_drill": True,
            "diagnostic_redaction_drill": True,
            "materialized_report": materialized("evidence/secret_drill.json", "6" * 64),
        },
        "forbidden_runtime": {
            "live_execution_requested": False,
            "signer_requested": False,
            "sender_requested": False,
            "private_key_material_present": False,
        },
    }


def codes(report):
    return {violation.code for violation in report.violations}


def test_happy_path_allows_only_sender_free_evidence_review():
    report = validate_mpr03_evidence(valid_evidence())

    assert report.ready is True
    assert report.paper_shadow_evidence_review_allowed is True
    assert report.operational_paper_ready_allowed is False
    assert report.live_execution_allowed is False
    assert report.signer_allowed is False
    assert report.sender_allowed is False
    assert json.loads(report.to_json())["ready"] is True


def test_requires_exact_schema_and_debt_coverage():
    evidence = valid_evidence()
    evidence["schema_version"] = "old"
    evidence["debt_ids"] = sorted(REQUIRED_DEBT_IDS - {"evidence.real-shadow-soak"})

    report = validate_mpr03_evidence(evidence)

    assert {"BAD_SCHEMA_VERSION", "DEBT_COVERAGE_MISMATCH"} <= codes(report)


def test_requires_mpr01_and_mpr02_materialized_dependencies():
    evidence = valid_evidence()
    evidence["upstream"]["mpr01_accepted"] = False
    evidence["upstream"]["mpr02_report_sha256"] = "placeholder"

    report = validate_mpr03_evidence(evidence)

    assert {"MPR01_NOT_ACCEPTED", "MPR02_NOT_ACCEPTED"} <= codes(report)


def test_blocks_incomplete_finalized_economics_and_gross_spread_success():
    evidence = valid_evidence()
    evidence["finalized_economics"]["payer_balance_deltas_bound"] = False
    evidence["finalized_economics"]["gross_spread_can_mark_success"] = True

    report = validate_mpr03_evidence(evidence)

    assert {
        "FINALIZED_ECONOMICS_INCOMPLETE",
        "GROSS_SPREAD_SUCCESS_ALLOWED",
    } <= codes(report)


def test_blocks_source_only_economic_report():
    evidence = valid_evidence()
    evidence["finalized_economics"]["materialized_report"] = {
        "path": "/tmp/economics.json",
        "sha256": "7" * 64,
    }

    report = validate_mpr03_evidence(evidence)

    assert "ECONOMICS_REPORT_NOT_MATERIALIZED" in codes(report)


def test_requires_persistence_factory_and_zero_direct_sqlite_islands():
    evidence = valid_evidence()
    evidence["persistence"]["direct_sqlite_connect_sites_remaining"] = 4

    report = validate_mpr03_evidence(evidence)

    assert "PERSISTENCE_CUTOVER_INCOMPLETE" in codes(report)


def test_requires_generation_backup_protocol_and_fault_matrix():
    evidence = valid_evidence()
    evidence["backup_recovery"]["publication_steps"] = ["write", "rename"]
    evidence["backup_recovery"]["fault_matrix"] = ["wal_checkpoint"]

    report = validate_mpr03_evidence(evidence)

    assert {
        "BACKUP_PROTOCOL_INCOMPLETE",
        "BACKUP_FAULT_MATRIX_INCOMPLETE",
    } <= codes(report)


def test_requires_operational_readiness_states_and_metrics():
    evidence = valid_evidence()
    evidence["observability"]["readiness_states"] = ["safe_idle"]
    evidence["observability"]["metrics"] = ["queue_depth"]

    report = validate_mpr03_evidence(evidence)

    assert {"READINESS_STATES_INCOMPLETE", "OBSERVABILITY_METRICS_INCOMPLETE"} <= codes(report)


def test_blocks_synthetic_or_recorded_data_counted_as_real_release_evidence():
    evidence = valid_evidence()
    evidence["shadow_soak"]["synthetic_counted_as_real_release_evidence"] = True
    evidence["shadow_soak"]["lineage_counts"].pop("finalized")

    report = validate_mpr03_evidence(evidence)

    assert {
        "SHADOW_SOAK_LINEAGE_INCOMPLETE",
        "SYNTHETIC_RELEASE_EVIDENCE_ALLOWED",
    } <= codes(report)


def test_release_manifest_entries_must_be_digest_or_explicit_fail_closed_missing():
    evidence = valid_evidence()
    evidence["release_manifest"]["image_digest"] = {
        "status": "available",
        "sha256": "not-a-digest",
    }
    evidence["release_manifest"]["sbom_digest"] = {
        "status": "fail_closed_missing",
        "reason": "not built in this environment",
    }
    evidence["release_manifest"].pop("wheel_digest")

    report = validate_mpr03_evidence(evidence)

    assert {
        "RELEASE_MANIFEST_KEYS_MISSING",
        "RELEASE_MANIFEST_NOT_FAIL_CLOSED",
    } <= codes(report)


def test_secret_incident_drill_must_be_materialized_and_complete():
    evidence = valid_evidence()
    evidence["secret_incident_drill"]["revocation_drill"] = False
    evidence["secret_incident_drill"]["materialized_report"]["sha256"] = "bad"

    report = validate_mpr03_evidence(evidence)

    assert "SECRET_INCIDENT_DRILL_INCOMPLETE" in codes(report)


@pytest.mark.parametrize(
    "field",
    [
        "live_execution_requested",
        "signer_requested",
        "sender_requested",
        "private_key_material_present",
    ],
)
def test_forbids_live_signer_sender_and_private_key_surfaces(field):
    evidence = valid_evidence()
    evidence["forbidden_runtime"][field] = True

    report = validate_mpr03_evidence(evidence)

    assert "FORBIDDEN_RUNTIME_SURFACE_REQUESTED" in codes(report)


def test_assert_ready_raises_stable_codes():
    evidence = valid_evidence()
    evidence["persistence"]["approved_factory_only"] = False

    with pytest.raises(ValueError) as exc:
        assert_mpr03_ready(evidence)

    assert "PERSISTENCE_CUTOVER_INCOMPLETE" in str(exc.value)


def test_fail_closed_manifest_missing_reason_is_rejected():
    evidence = valid_evidence()
    evidence["release_manifest"]["image_digest"] = {
        "status": "fail_closed_missing",
        "reason": "",
    }

    report = validate_mpr03_evidence(evidence)

    assert "RELEASE_MANIFEST_NOT_FAIL_CLOSED" in codes(report)

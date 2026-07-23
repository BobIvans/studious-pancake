from __future__ import annotations

import copy

import pytest

from src.production_operations_pr199 import (
    PR199_SCHEMA_VERSION,
    PR199OperationsError,
    cutover_capability_allowed,
    live_capability_allowed,
    validate_operations_evidence,
)

_HASH = "a" * 64


def _evidence() -> dict[str, object]:
    return {
        "schema_version": PR199_SCHEMA_VERSION,
        "release": {
            "release_manifest_hash": _HASH,
            "signed": True,
            "signer_identity": "release-reviewer-1",
            "independent_reviewed": True,
            "artifact_hashes": {
                "source_commit_sha": "1" * 64,
                "wheel_sha256": "2" * 64,
                "runtime_image_digest": "3" * 64,
                "sbom_sha256": "4" * 64,
                "provenance_sha256": "5" * 64,
                "config_generation_hash": "6" * 64,
                "policy_bundle_hash": "7" * 64,
                "capability_manifest_hash": "8" * 64,
                "database_schema_hash": "9" * 64,
            },
        },
        "readiness": {
            "liveness_endpoint": "/livez",
            "readiness_endpoint": "/readyz",
            "liveness_uses_process_health_only": True,
            "readiness_uses_durable_dependencies": True,
            "readiness_uses_active_task_health": True,
            "readiness_closes_on": {
                "dead_strategy": True,
                "stale_rooted_data": True,
                "db_degraded": True,
                "admission_latch": True,
                "outbox_backlog": True,
            },
            "management_auth_required": True,
        },
        "observability": {
            "low_cardinality_labels": True,
            "secrets_redacted": True,
            "trace_binds_attempt_release_config": True,
            "alerts_cover_readiness_slo_and_dr": True,
            "audit_export_hash": "b" * 64,
        },
        "dr": {
            "backup_manifest_signed": True,
            "backup_generation_bound": True,
            "restore_uses_temp_sibling": True,
            "previous_generation_preserved": True,
            "overwrite_open_db_prevented": True,
            "event_replay_matches_materialized_state": True,
            "restore_hashes_match": True,
        },
        "qualification": {
            "slo_budgets": {
                "event_loop_lag_p99_ms": True,
                "db_commit_p99_ms": True,
                "recovery_rto_seconds": True,
                "unknown_submission_max_seconds": True,
                "memory_fd_growth": True,
            },
            "fault_drills": {
                "kill_9_during_state_transition": True,
                "disk_full": True,
                "clock_jump": True,
                "dns_failure": True,
                "provider_outage": True,
                "signer_outage": True,
                "backup_during_wal_writes": True,
            },
        },
        "deployment": {
            "immutable_image_digest": True,
            "non_root": True,
            "read_only_rootfs": True,
            "no_new_privileges": True,
            "capabilities_dropped": True,
            "egress_deny_default": True,
            "secrets_externalized": True,
            "live_enabled": False,
        },
    }


def _codes(report) -> set[str]:
    return {diagnostic.code for diagnostic in report.diagnostics}


def test_pr199_accepts_complete_signed_operations_evidence() -> None:
    report = validate_operations_evidence(_evidence())

    assert report.ok is True
    assert report.diagnostics == ()
    assert len(report.evidence_hash) == 64
    assert report.to_dict()["live_capability_allowed"] is False
    assert live_capability_allowed() is False
    assert cutover_capability_allowed() is False


def test_pr199_rejects_unsigned_or_unreviewed_release() -> None:
    evidence = _evidence()
    release = copy.deepcopy(evidence["release"])
    release["signed"] = False
    release["independent_reviewed"] = False
    evidence["release"] = release

    report = validate_operations_evidence(evidence)

    assert report.ok is False
    assert "RELEASE_NOT_SIGNED" in _codes(report)
    assert "RELEASE_NOT_REVIEWED" in _codes(report)


def test_pr199_rejects_missing_artifact_binding() -> None:
    evidence = _evidence()
    release = copy.deepcopy(evidence["release"])
    hashes = copy.deepcopy(release["artifact_hashes"])
    del hashes["provenance_sha256"]
    hashes["wheel_sha256"] = "not-a-hash"
    release["artifact_hashes"] = hashes
    evidence["release"] = release

    report = validate_operations_evidence(evidence)

    assert report.ok is False
    assert "ARTIFACT_HASH_MISSING" in _codes(report)
    assert "ARTIFACT_HASH_INVALID" in _codes(report)


def test_pr199_rejects_liveness_readiness_conflation() -> None:
    evidence = _evidence()
    readiness = copy.deepcopy(evidence["readiness"])
    readiness["readiness_endpoint"] = readiness["liveness_endpoint"]
    readiness["readiness_closes_on"]["dead_strategy"] = False
    readiness["management_auth_required"] = False
    evidence["readiness"] = readiness

    report = validate_operations_evidence(evidence)

    assert report.ok is False
    assert "READINESS_LIVENESS_NOT_SEPARATED" in _codes(report)
    assert "READINESS_CLOSURE_MISSING" in _codes(report)
    assert "MANAGEMENT_PLANE_UNAUTHENTICATED" in _codes(report)


def test_pr199_rejects_unsafe_restore_evidence() -> None:
    evidence = _evidence()
    dr = copy.deepcopy(evidence["dr"])
    dr["restore_uses_temp_sibling"] = False
    dr["previous_generation_preserved"] = False
    dr["event_replay_matches_materialized_state"] = False
    evidence["dr"] = dr

    report = validate_operations_evidence(evidence)

    assert report.ok is False
    assert "REQUIRED_EVIDENCE_MISSING" in _codes(report)


def test_pr199_rejects_missing_slo_and_fault_drills() -> None:
    evidence = _evidence()
    qualification = copy.deepcopy(evidence["qualification"])
    qualification["slo_budgets"]["db_commit_p99_ms"] = False
    qualification["fault_drills"]["disk_full"] = False
    evidence["qualification"] = qualification

    report = validate_operations_evidence(evidence)

    assert report.ok is False
    assert "SLO_BUDGET_MISSING" in _codes(report)
    assert "FAULT_DRILL_MISSING" in _codes(report)


def test_pr199_rejects_observability_and_deployment_gaps() -> None:
    evidence = _evidence()
    observability = copy.deepcopy(evidence["observability"])
    observability["secrets_redacted"] = False
    observability["low_cardinality_labels"] = False
    deployment = copy.deepcopy(evidence["deployment"])
    deployment["read_only_rootfs"] = False
    deployment["live_enabled"] = True
    evidence["observability"] = observability
    evidence["deployment"] = deployment

    report = validate_operations_evidence(evidence)

    assert report.ok is False
    assert "OBSERVABILITY_EVIDENCE_MISSING" in _codes(report)
    assert "REQUIRED_EVIDENCE_MISSING" in _codes(report)
    assert "LIVE_ENABLEMENT_OUT_OF_SCOPE" in _codes(report)


def test_pr199_rejects_wrong_schema() -> None:
    evidence = _evidence()
    evidence["schema_version"] = "old"

    with pytest.raises(PR199OperationsError, match="unsupported"):
        validate_operations_evidence(evidence)

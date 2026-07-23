from __future__ import annotations

import copy

import pytest

from src.production_cutover_pr200 import (
    PR200_CUTOVER_SCHEMA_VERSION,
    PR200CutoverError,
    cutover_capability_allowed,
    live_capability_allowed,
    validate_pr200_cutover_evidence,
)
from src.production_sandbox_pr200 import PR200_SCHEMA_VERSION

_DIGEST = "a" * 64
_OTHER_DIGEST = "b" * 64


def _sandbox_manifest() -> dict[str, object]:
    return {
        "schema_version": PR200_SCHEMA_VERSION,
        "artifact_hashes": {
            "source_commit_sha": "1" * 64,
            "wheel_sha256": "2" * 64,
            "runtime_image_digest": "3" * 64,
            "sbom_sha256": "4" * 64,
            "config_generation_hash": "5" * 64,
            "protocol_registry_hash": "6" * 64,
        },
        "egress": {
            "deny_by_default": True,
            "allowed_origins": [
                "https://api.mainnet-beta.solana.com",
                "https://api.jup.ag",
            ],
        },
        "services": [
            {
                "name": "runtime",
                "role": "runtime",
                "image": f"ghcr.io/bobivans/flashloan-runtime@sha256:{_DIGEST}",
                "read_only_root": True,
                "no_new_privileges": True,
                "cap_drop_all": True,
                "arbitrary_internet": False,
                "can_read_signer_key": False,
                "secret_sources": ["secret-manager://flashloan/runtime-env"],
                "networks": ["runtime-egress"],
            },
            {
                "name": "signer",
                "role": "signer",
                "image": f"ghcr.io/bobivans/flashloan-signer@sha256:{_OTHER_DIGEST}",
                "read_only_root": True,
                "no_new_privileges": True,
                "cap_drop_all": True,
                "arbitrary_internet": False,
                "can_read_signer_key": True,
                "secret_sources": ["keychain://flashloan/canary-signer"],
                "networks": ["signer-ipc"],
            },
        ],
        "active_submitters": 1,
        "live_enabled": False,
        "signer_key_exportable": False,
        "signed_release_pointer": True,
        "rollback_rehearsed": True,
        "outstanding_attempts_reconciled": True,
    }


def _true_flags(*names: str) -> dict[str, bool]:
    return {name: True for name in names}


def _evidence() -> dict[str, object]:
    return {
        "schema_version": PR200_CUTOVER_SCHEMA_VERSION,
        "phase": "canary",
        "sandbox_manifest": _sandbox_manifest(),
        "release": _true_flags(
            "release_manifest_signed",
            "wheel_digest_bound",
            "image_digest_pinned",
            "sbom_attached",
            "provenance_attached",
            "config_hash_bound",
            "capability_manifest_bound",
            "program_idl_hashes_bound",
        ),
        "readiness": _true_flags(
            "liveness_endpoint_separate",
            "readiness_endpoint_separate",
            "readiness_closes_on_dead_strategy",
            "readiness_closes_on_stale_rooted_data",
            "readiness_closes_on_db_degradation",
            "readiness_closes_on_latch",
        ),
        "backup_restore": _true_flags(
            "rehearsed",
            "restored_in_clean_env",
            "event_chain_verified",
            "schema_verified",
            "outstanding_intents_verified",
            "rpo_zero_for_signed_intents",
        ),
        "rollback": _true_flags(
            "drain_only_runbook",
            "rehearsed",
            "preserves_db_source_of_truth",
            "no_legacy_writer_after_cutover",
            "outstanding_intents_reconciled",
        ),
        "legacy_surfaces": _true_flags(
            "legacy_arb_bot_unavailable",
            "alternative_live_writers_unavailable",
            "source_only_live_paths_unavailable",
            "production_image_excludes_legacy_entrypoints",
        ),
        "slo_budgets": {
            name: {"passed_under_fault": True, "evidence_hash": "c" * 64}
            for name in (
                "event_loop_lag",
                "queue_age",
                "provider_latency",
                "db_transition_latency",
                "recovery_time",
                "memory_fd_growth",
            )
        },
        "fault_drills": [
            {
                "name": name,
                "passed": True,
                "invariant": "fail closed",
                "evidence_hash": "d" * 64,
            }
            for name in (
                "kill_9",
                "disk_full",
                "clock_jump",
                "dns_failure",
                "provider_outage",
                "signer_outage",
                "backup_during_wal",
            )
        ],
        "live_enabled": False,
        "automatic_cutover_enabled": False,
    }


def _codes(report) -> set[str]:
    return {diagnostic.code for diagnostic in report.diagnostics}


def test_pr200_cutover_accepts_complete_offline_evidence() -> None:
    report = validate_pr200_cutover_evidence(_evidence())

    assert report.ok is True
    assert report.diagnostics == ()
    assert len(report.evidence_hash) == 64
    assert len(report.sandbox_manifest_hash) == 64
    assert report.live_capability_allowed is False
    assert report.cutover_capability_allowed is False
    assert live_capability_allowed() is False
    assert cutover_capability_allowed() is False


def test_pr200_cutover_rejects_dirty_sandbox_manifest() -> None:
    evidence = _evidence()
    sandbox = copy.deepcopy(evidence["sandbox_manifest"])
    sandbox["active_submitters"] = 2
    evidence["sandbox_manifest"] = sandbox

    report = validate_pr200_cutover_evidence(evidence)

    assert report.ok is False
    assert "ACTIVE_SUBMITTER_FENCE_INVALID" in _codes(report)
    assert "SANDBOX_MANIFEST_NOT_READY" in _codes(report)


def test_pr200_cutover_rejects_incomplete_readiness_and_backup() -> None:
    evidence = _evidence()
    readiness = copy.deepcopy(evidence["readiness"])
    readiness["readiness_closes_on_dead_strategy"] = False
    evidence["readiness"] = readiness
    backup = copy.deepcopy(evidence["backup_restore"])
    del backup["event_chain_verified"]
    evidence["backup_restore"] = backup

    report = validate_pr200_cutover_evidence(evidence)

    assert report.ok is False
    assert "READINESS_EVIDENCE_INCOMPLETE" in _codes(report)
    assert "BACKUP_RESTORE_EVIDENCE_INCOMPLETE" in _codes(report)


def test_pr200_cutover_rejects_missing_slo_and_fault_drill() -> None:
    evidence = _evidence()
    slo = copy.deepcopy(evidence["slo_budgets"])
    slo["queue_age"]["passed_under_fault"] = False
    del slo["memory_fd_growth"]
    evidence["slo_budgets"] = slo
    evidence["fault_drills"] = [
        drill for drill in evidence["fault_drills"] if drill["name"] != "disk_full"
    ]

    report = validate_pr200_cutover_evidence(evidence)

    assert report.ok is False
    assert "SLO_BUDGET_NOT_PROVEN" in _codes(report)
    assert "SLO_BUDGET_MISSING" in _codes(report)
    assert "FAULT_DRILL_MISSING" in _codes(report)


def test_pr200_cutover_rejects_legacy_and_automatic_cutover() -> None:
    evidence = _evidence()
    legacy = copy.deepcopy(evidence["legacy_surfaces"])
    legacy["legacy_arb_bot_unavailable"] = False
    evidence["legacy_surfaces"] = legacy
    evidence["automatic_cutover_enabled"] = True
    evidence["live_enabled"] = True

    report = validate_pr200_cutover_evidence(evidence)

    assert report.ok is False
    assert "LEGACY_SURFACE_NOT_QUARANTINED" in _codes(report)
    assert "AUTOMATIC_CUTOVER_FORBIDDEN" in _codes(report)
    assert "LIVE_ENABLEMENT_OUT_OF_SCOPE" in _codes(report)


def test_pr200_cutover_rejects_bad_schema_and_phase() -> None:
    evidence = _evidence()
    evidence["schema_version"] = "wrong"

    with pytest.raises(PR200CutoverError, match="unsupported"):
        validate_pr200_cutover_evidence(evidence)

    evidence = _evidence()
    evidence["phase"] = "launch-everything"

    with pytest.raises(PR200CutoverError, match="unsupported cutover phase"):
        validate_pr200_cutover_evidence(evidence)

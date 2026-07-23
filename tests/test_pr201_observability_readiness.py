from __future__ import annotations

import pytest

from src.operations.pr201_observability_readiness import (
    BackupRestoreRehearsal,
    DeploymentHardeningSnapshot,
    ManagementReadinessSnapshot,
    PR201EvidenceError,
    ReadinessSignal,
    ReleaseImageManifest,
    SloBudget,
    SloMeasurement,
    evaluate_slos,
    operator_readiness_report,
    sanitize_observability_event,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64
IMAGE = "ghcr.io/bobivans/studious-pancake@sha256:" + "1" * 64


def _readiness(**overrides: object) -> ManagementReadinessSnapshot:
    values = {
        "run_id": "run/201",
        "source_commit": HASH_A,
        "image_digest": IMAGE,
        "config_hash": HASH_B,
        "contract_evidence_hash": HASH_C,
        "observed_at_ms": 1_000,
        "liveness_healthy": True,
        "safe_idle_allowed": True,
        "data_ready": True,
        "paper_worker_alive": True,
        "paper_workload_fresh": True,
        "protocol_ready": True,
        "db_healthy": True,
        "outbox_healthy": True,
        "signals": (
            ReadinessSignal(
                name="paper-worker",
                healthy=True,
                mandatory=True,
                stale=False,
                evidence_hash=HASH_D,
            ),
        ),
    }
    values.update(overrides)
    return ManagementReadinessSnapshot(**values)


def _slo_pass() -> dict[str, object]:
    return evaluate_slos(
        SloBudget(
            max_cycle_freshness_ms=1_000,
            max_durable_inbox_lag_ms=500,
            max_queue_age_ms=2_000,
            min_provider_success_ratio=0.95,
            min_reconciliation_completeness_ratio=1.0,
            max_shutdown_ms=5_000,
            max_recovery_ms=30_000,
            max_db_contention_ms=100,
        ),
        SloMeasurement(
            cycle_freshness_ms=100,
            durable_inbox_lag_ms=10,
            queue_age_ms=20,
            provider_success_ratio=0.99,
            reconciliation_completeness_ratio=1.0,
            shutdown_ms=1_000,
            recovery_ms=10_000,
            db_contention_ms=5,
            data_loss_detected=False,
        ),
    )


def _deployment_pass() -> dict[str, object]:
    return DeploymentHardeningSnapshot(
        image_digest=IMAGE,
        sbom_sha256=HASH_A,
        attestation_sha256=HASH_B,
        seccomp_profile_sha256=HASH_C,
        resource_limits_sha256=HASH_D,
        non_root_user=True,
        read_only_rootfs=True,
        cap_drop_all=True,
        no_new_privileges=True,
        persistent_volume_owner_uid=10001,
    ).evaluate()


def _backup_pass() -> dict[str, object]:
    return BackupRestoreRehearsal(
        before_state_hash=HASH_A,
        before_outbox_hash=HASH_B,
        before_accounting_hash=HASH_C,
        restored_state_hash=HASH_A,
        restored_outbox_hash=HASH_B,
        restored_accounting_hash=HASH_C,
        migration_rehearsed=True,
        integrity_check_passed=True,
        destructive_test_id="restore-drill/1",
        rto_ms=1_000,
        rpo_ms=0,
    ).evaluate(max_rto_ms=5_000, max_rpo_ms=0)


def _manifest() -> ReleaseImageManifest:
    return ReleaseImageManifest(
        source_commit=HASH_A,
        lock_hash=HASH_B,
        wheel_hash=HASH_C,
        image_digest=IMAGE,
        config_hash=HASH_D,
        contract_evidence_hash=HASH_E,
        soak_artifact_hash=HASH_F,
    )


def test_healthy_is_impossible_when_mandatory_worker_dead_or_stale() -> None:
    dead = _readiness(paper_worker_alive=False).evaluate()
    assert dead["healthy"] is False
    assert "PR201_MANDATORY_PAPER_WORKER_DEAD" in dead["blockers"]

    stale = _readiness(
        signals=(
            ReadinessSignal(
                name="paper-worker",
                healthy=True,
                mandatory=True,
                stale=True,
                evidence_hash=HASH_D,
            ),
        )
    ).evaluate()
    assert stale["healthy"] is False
    assert "PR201_STALE_MANDATORY_SIGNAL:paper-worker" in stale["blockers"]


def test_readiness_planes_are_separate_and_live_remains_disabled() -> None:
    report = _readiness().evaluate()
    assert report["healthy"] is True
    assert report["liveness"] is True
    assert report["safe_idle"] is True
    assert report["data_readiness"] is True
    assert report["paper_workload_readiness"] is True
    assert report["protocol_readiness"] is True
    assert report["db_outbox_health"] is True
    assert report["live_gate"] is False
    assert report["signer_reachable"] is False
    assert report["sender_reachable"] is False

    with pytest.raises(PR201EvidenceError, match="PR201_LIVE_MUST_REMAIN_DISABLED"):
        _readiness(live_enabled=True)


def test_slo_budget_blocks_lag_ratio_and_data_loss() -> None:
    blocked = evaluate_slos(
        SloBudget(
            max_cycle_freshness_ms=1_000,
            max_durable_inbox_lag_ms=500,
            max_queue_age_ms=2_000,
            min_provider_success_ratio=0.95,
            min_reconciliation_completeness_ratio=1.0,
            max_shutdown_ms=5_000,
            max_recovery_ms=30_000,
            max_db_contention_ms=100,
        ),
        SloMeasurement(
            cycle_freshness_ms=2_000,
            durable_inbox_lag_ms=600,
            queue_age_ms=2_001,
            provider_success_ratio=0.90,
            reconciliation_completeness_ratio=0.99,
            shutdown_ms=5_001,
            recovery_ms=30_001,
            db_contention_ms=101,
            data_loss_detected=True,
        ),
    )
    assert blocked["slo_passed"] is False
    assert "PR201_DATA_LOSS_INVARIANT_VIOLATED" in blocked["blockers"]
    assert "PR201_PROVIDER_SUCCESS_SLO_VIOLATED" in blocked["blockers"]


def test_logs_are_redacted_and_cardinality_bounded() -> None:
    sanitized = sanitize_observability_event(
        {
            "message": "ok",
            "api_key": "secret",
            "authorization": "Bearer abc",
            "label.provider": "jupiter",
            "details": "x" * 200,
        },
        label_budget=2,
        max_value_length=32,
    )
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["authorization"] == "[REDACTED]"
    assert isinstance(sanitized["details"], dict)
    assert sanitized["details"]["truncated"] is True

    with pytest.raises(PR201EvidenceError, match="PR201_LABEL_CARDINALITY"):
        sanitize_observability_event(
            {"label.a": "1", "label.b": "2", "label.c": "3"},
            label_budget=2,
        )


def test_deployment_hardening_rejects_root_and_mutable_runtime() -> None:
    blocked = DeploymentHardeningSnapshot(
        image_digest=IMAGE,
        sbom_sha256=HASH_A,
        attestation_sha256=HASH_B,
        seccomp_profile_sha256=HASH_C,
        resource_limits_sha256=HASH_D,
        non_root_user=False,
        read_only_rootfs=False,
        cap_drop_all=False,
        no_new_privileges=False,
        persistent_volume_owner_uid=0,
    ).evaluate()
    assert blocked["deployment_hardened"] is False
    assert "PR201_CONTAINER_ROOT_USER" in blocked["blockers"]
    assert "PR201_ROOTFS_NOT_READ_ONLY" in blocked["blockers"]
    assert "PR201_PERSISTENT_VOLUME_ROOT_OWNED" in blocked["blockers"]


def test_backup_restore_rehearsal_binds_state_outbox_and_accounting_hashes() -> None:
    passed = _backup_pass()
    assert passed["backup_restore_passed"] is True

    blocked = BackupRestoreRehearsal(
        before_state_hash=HASH_A,
        before_outbox_hash=HASH_B,
        before_accounting_hash=HASH_C,
        restored_state_hash=HASH_A,
        restored_outbox_hash=HASH_D,
        restored_accounting_hash=HASH_C,
        migration_rehearsed=False,
        integrity_check_passed=True,
        destructive_test_id="restore-drill/2",
        rto_ms=10_000,
        rpo_ms=1,
    ).evaluate(max_rto_ms=5_000, max_rpo_ms=0)
    assert blocked["backup_restore_passed"] is False
    assert "PR201_RESTORED_OUTBOX_HASH_MISMATCH" in blocked["blockers"]
    assert "PR201_MIGRATION_REHEARSAL_MISSING" in blocked["blockers"]
    assert "PR201_RTO_EXCEEDED" in blocked["blockers"]


def test_release_manifest_binds_exact_image_and_evidence_hashes() -> None:
    manifest = _manifest()
    same = _manifest()
    changed = ReleaseImageManifest(
        source_commit=HASH_A,
        lock_hash=HASH_B,
        wheel_hash=HASH_C,
        image_digest="ghcr.io/bobivans/studious-pancake@sha256:" + "2" * 64,
        config_hash=HASH_D,
        contract_evidence_hash=HASH_E,
        soak_artifact_hash=HASH_F,
    )
    assert manifest.manifest_hash == same.manifest_hash
    assert manifest.manifest_hash != changed.manifest_hash
    assert manifest.to_dict()["image_digest"] == IMAGE


def test_operator_report_combines_all_planes_and_stays_sender_free() -> None:
    report = operator_readiness_report(
        readiness=_readiness(),
        slo=_slo_pass(),
        deployment=_deployment_pass(),
        backup_restore=_backup_pass(),
        release_manifest=_manifest(),
    )
    assert report["operator_ready"] is True
    assert report["live_enabled"] is False
    assert report["signer_reachable"] is False
    assert report["sender_reachable"] is False
    assert report["submission_allowed"] is False

    blocked = operator_readiness_report(
        readiness=_readiness(paper_workload_fresh=False),
        slo=_slo_pass(),
        deployment=_deployment_pass(),
        backup_restore=_backup_pass(),
        release_manifest=_manifest(),
    )
    assert blocked["operator_ready"] is False
    assert "PR201_PAPER_WORKLOAD_STALE" in blocked["blockers"]

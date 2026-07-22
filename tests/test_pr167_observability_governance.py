from __future__ import annotations

from dataclasses import replace

import pytest

from src.pr167_observability_governance import (
    ArchiveDeleteManifest,
    DataClassification,
    DataFieldPolicy,
    EvidenceCorrection,
    EvidenceObjectPolicy,
    EvidenceRecord,
    ManifestAction,
    MetricCardinalityPolicy,
    MetricDefinition,
    MetricKind,
    PR167GovernanceError,
    PR167GovernancePackage,
    REQUIRED_SLO_HISTOGRAMS,
    RetentionClass,
    RetentionPolicy,
    SLOMetricSet,
    StorageBudget,
    StorageUsage,
    WALCompactionPolicy,
    build_authoritative_evidence_view,
    evaluate_pr167_governance,
    validate_archive_delete_manifest,
)

pytestmark = pytest.mark.unit

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64


def _fields() -> tuple[DataFieldPolicy, ...]:
    return (
        DataFieldPolicy(
            field_path="events.trace_id",
            classification=DataClassification.OPERATIONAL_METADATA,
            retention_class=RetentionClass.OPERATIONAL,
            hot_retention_days=14,
            warm_archive_days=90,
            immutable_retention_days=180,
            deletion_allowed=False,
        ),
        DataFieldPolicy(
            field_path="settlement.finalized_pnl_lamports",
            classification=DataClassification.IMMUTABLE_AUDIT,
            retention_class=RetentionClass.FINANCIAL_AUDIT,
            hot_retention_days=90,
            warm_archive_days=365,
            immutable_retention_days=365,
            deletion_allowed=False,
        ),
        DataFieldPolicy(
            field_path="debug.sample_payload",
            classification=DataClassification.TEMPORARY_DEBUG,
            retention_class=RetentionClass.DELETE_ALLOWED,
            hot_retention_days=1,
            warm_archive_days=0,
            immutable_retention_days=0,
            deletion_allowed=True,
        ),
    )


def _metrics() -> tuple[MetricDefinition, ...]:
    return tuple(
        MetricDefinition(
            name=name,
            kind=MetricKind.HISTOGRAM,
            labels=("environment", "component", "stage", "provider", "outcome"),
            populated=True,
        )
        for name in sorted(REQUIRED_SLO_HISTOGRAMS)
    ) + (
        MetricDefinition(
            name="evidence_records_total",
            kind=MetricKind.COUNTER,
            labels=("environment", "classification", "outcome"),
            populated=True,
        ),
    )


def _metric_policy(max_series: int = 10_000) -> MetricCardinalityPolicy:
    return MetricCardinalityPolicy(
        allowed_label_values={
            "environment": ("paper", "canary"),
            "component": ("runtime", "provider", "storage"),
            "stage": ("quote", "simulate", "settle", "archive"),
            "provider": ("jupiter", "okx", "rpc", "internal"),
            "outcome": ("ok", "blocked", "failed"),
            "classification": ("operational", "financial", "security"),
        },
        max_estimated_series=max_series,
    )


def _object_policy() -> EvidenceObjectPolicy:
    return EvidenceObjectPolicy(
        content_addressed_uri="cas://evidence/" + SHA_B,
        payload_sha256=SHA_B,
        encrypted=True,
        immutable_lock=True,
        local_cache_max_bytes=1024,
        verified_retrieval=True,
    )


def _records() -> tuple[EvidenceRecord, ...]:
    return (
        EvidenceRecord(
            evidence_ref="ev.original",
            classification=DataClassification.OPERATIONAL_METADATA,
            retention_class=RetentionClass.OPERATIONAL,
            digest_sha256=SHA_A,
            size_bytes=1024,
            local_payload_allowed=True,
        ),
        EvidenceRecord(
            evidence_ref="ev.correction",
            classification=DataClassification.IMMUTABLE_AUDIT,
            retention_class=RetentionClass.SECURITY_AUDIT,
            digest_sha256=SHA_C,
            size_bytes=512,
            local_payload_allowed=False,
        ),
        EvidenceRecord(
            evidence_ref="ev.replacement",
            classification=DataClassification.OPERATIONAL_METADATA,
            retention_class=RetentionClass.OPERATIONAL,
            digest_sha256=SHA_D,
            size_bytes=1024,
            local_payload_allowed=True,
        ),
        EvidenceRecord(
            evidence_ref="ev.financial",
            classification=DataClassification.IMMUTABLE_AUDIT,
            retention_class=RetentionClass.FINANCIAL_AUDIT,
            digest_sha256=SHA_E,
            size_bytes=32_000,
            local_payload_allowed=False,
            object_policy=_object_policy(),
            related_attempt_ref="attempt.finalized.1",
        ),
    )


def _package(**overrides: object) -> PR167GovernancePackage:
    metrics = _metrics()
    values: dict[str, object] = {
        "retention_policy": RetentionPolicy(
            fields=_fields(),
            minimum_financial_retention_days=365,
            immutable_audit_retention_days=365,
            backup_retention_days=90,
        ),
        "storage_budget": StorageBudget(
            lifecycle_db_hard_cap_bytes=1_000_000_000,
            observability_db_hard_cap_bytes=1_000_000_000,
            wal_hard_cap_bytes=100_000_000,
            evidence_object_hard_cap_bytes_per_day=100_000_000,
            logs_hard_cap_bytes_per_day=100_000_000,
            metrics_series_hard_cap=10_000,
            trace_events_hard_cap_per_minute=10_000,
        ),
        "current_usage": StorageUsage(
            lifecycle_db_bytes=10_000,
            observability_db_bytes=10_000,
            wal_bytes=10_000,
            evidence_object_bytes_per_day=10_000,
            logs_bytes_per_day=10_000,
            metrics_series=100,
            trace_events_per_minute=100,
        ),
        "evidence_records": _records(),
        "corrections": (
            EvidenceCorrection(
                original_ref="ev.original",
                correction_ref="ev.correction",
                replacement_ref="ev.replacement",
                correction_reason="operator corrected stale provider payload",
                signed_manifest_sha256=SHA_A,
            ),
        ),
        "metric_policy": _metric_policy(),
        "metrics": metrics,
        "slo_metrics": SLOMetricSet(metrics),
        "wal_policy": WALCompactionPolicy(
            checkpoint_interval_seconds=300,
            max_wal_bytes=100_000_000,
            minimum_free_disk_bytes=1_000_000_000,
            corruption_safe_archive=True,
            fail_closed_on_hard_cap=True,
        ),
        "archive_delete_manifests": (
            ArchiveDeleteManifest(
                action=ManifestAction.ARCHIVE,
                evidence_refs=("ev.original", "ev.replacement"),
                requested_by="operator.audit",
                reason="move corrected operational evidence to warm archive",
                created_at_ns=1,
                signed_manifest_sha256=SHA_B,
                approval_ref="approval.archive.1",
            ),
        ),
        "cost_budget_present": True,
        "access_audit_enabled": True,
    }
    values.update(overrides)
    return PR167GovernancePackage(**values)


def test_ready_governance_is_manual_review_only() -> None:
    result = evaluate_pr167_governance(_package())

    assert result.ready_for_manual_review is True
    assert result.runtime_live_enabled is False
    assert result.write_path_can_purge_financial_evidence is False
    assert result.blockers == ()
    assert result.estimated_metric_series > 0


def test_metric_high_cardinality_labels_are_rejected() -> None:
    with pytest.raises(PR167GovernanceError, match="high-cardinality"):
        MetricDefinition(
            name="bad_metric_total",
            kind=MetricKind.COUNTER,
            labels=("attempt_id",),
        )


def test_unbounded_metric_series_blocks_governance() -> None:
    package = _package(metric_policy=_metric_policy(max_series=1))

    result = evaluate_pr167_governance(package)

    assert result.ready_for_manual_review is False
    assert "metric-series-hard-cap-exceeded" in result.blockers


def test_storage_hard_cap_blocks_governance() -> None:
    package = _package(
        current_usage=StorageUsage(
            lifecycle_db_bytes=2_000_000_000,
            observability_db_bytes=10_000,
            wal_bytes=10_000,
            evidence_object_bytes_per_day=10_000,
            logs_bytes_per_day=10_000,
            metrics_series=100,
            trace_events_per_minute=100,
        )
    )

    result = evaluate_pr167_governance(package)

    assert "lifecycle_db_bytes:hard-cap-exceeded" in result.blockers


def test_missing_slo_histogram_is_rejected() -> None:
    metrics = tuple(
        metric for metric in _metrics() if metric.name != "quote_age_seconds"
    )

    with pytest.raises(PR167GovernanceError, match="quote_age_seconds"):
        SLOMetricSet(metrics)


def test_large_evidence_requires_content_addressed_object_policy() -> None:
    with pytest.raises(PR167GovernanceError, match="large evidence"):
        EvidenceRecord(
            evidence_ref="ev.large",
            classification=DataClassification.OPERATIONAL_METADATA,
            retention_class=RetentionClass.OPERATIONAL,
            digest_sha256=SHA_A,
            size_bytes=32_000,
            local_payload_allowed=False,
        )


def test_correction_chain_builds_authoritative_view() -> None:
    records = _records()
    correction = EvidenceCorrection(
        original_ref="ev.original",
        correction_ref="ev.correction",
        replacement_ref="ev.replacement",
        correction_reason="correct stale evidence",
        signed_manifest_sha256=SHA_A,
    )

    view = build_authoritative_evidence_view(records, (correction,))

    assert view["ev.original"] == "ev.replacement"
    assert view["ev.financial"] == "ev.financial"


def test_financial_evidence_delete_manifest_is_rejected() -> None:
    manifest = ArchiveDeleteManifest(
        action=ManifestAction.DELETE,
        evidence_refs=("ev.financial",),
        requested_by="operator.audit",
        reason="bad delete attempt",
        created_at_ns=1,
        signed_manifest_sha256=SHA_B,
        approval_ref="approval.delete.1",
    )

    with pytest.raises(PR167GovernanceError, match="cannot delete audit"):
        validate_archive_delete_manifest(manifest, _records())


def test_secret_evidence_is_rejected() -> None:
    with pytest.raises(PR167GovernanceError, match="secret payloads"):
        EvidenceRecord(
            evidence_ref="ev.secret",
            classification=DataClassification.SECRET,
            retention_class=RetentionClass.SECURITY_AUDIT,
            digest_sha256=SHA_A,
            size_bytes=10,
        )


def test_placeholder_hash_is_rejected() -> None:
    with pytest.raises(PR167GovernanceError, match="non-placeholder sha256"):
        replace(_object_policy(), payload_sha256="0" * 64)

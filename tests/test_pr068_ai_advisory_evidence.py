from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.ai_advisory import (
    AIAdvisoryEvidencePackage,
    AIAdvisoryReadinessGate,
    AdvisoryFailureCode,
    DriftMonitorReport,
    EvaluationSplitKind,
    ModelEvaluationReport,
    ModelRegistryEntry,
    PromotionState,
    ShadowABReport,
)


NOW = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64
DIGEST_E = "e" * 64
DIGEST_F = "f" * 64


def _registry() -> ModelRegistryEntry:
    return ModelRegistryEntry(
        model_id="advisory-v1",
        provider="offline-evaluator",
        model_version="2026-07-21",
        artifact_sha256=DIGEST_A,
        prompt_template_sha256=DIGEST_B,
        feature_schema_sha256=DIGEST_C,
        training_dataset_sha256=DIGEST_D,
        evaluation_dataset_sha256=DIGEST_E,
        registered_at=NOW,
        registered_by="ml-review@example.com",
        advisory_only=True,
        promotion_state=PromotionState.SHADOW_ONLY,
        trading_authority_enabled=False,
    )


def _evaluation() -> ModelEvaluationReport:
    return ModelEvaluationReport(
        model_id="advisory-v1",
        evaluation_id="eval-20260721",
        split_kind=EvaluationSplitKind.TIME_SPLIT,
        train_window_end=NOW - timedelta(days=14),
        evaluation_window_start=NOW - timedelta(days=13),
        evaluation_window_end=NOW - timedelta(days=1),
        sample_count=1_000,
        precision_at_threshold=0.70,
        recall_at_threshold=0.33,
        brier_score=0.18,
        calibration_error=0.04,
        p95_latency_ms=120,
        evaluation_dataset_sha256=DIGEST_E,
        report_sha256=DIGEST_F,
        generated_at=NOW,
        evaluator="ml-review@example.com",
    )


def _drift() -> DriftMonitorReport:
    return DriftMonitorReport(
        model_id="advisory-v1",
        drift_id="drift-20260721",
        baseline_dataset_sha256=DIGEST_E,
        observed_dataset_sha256=DIGEST_D,
        feature_drift_score=0.03,
        prediction_drift_score=0.04,
        missing_feature_rate=0.001,
        checked_at=NOW,
        monitor="ml-monitor@example.com",
        automatic_disable_recorded=True,
        report_sha256=DIGEST_A,
    )


def _ab() -> ShadowABReport:
    return ShadowABReport(
        model_id="advisory-v1",
        experiment_id="shadow-ab-20260721",
        control_policy_id="rules-only-v1",
        candidate_policy_id="advisory-v1",
        sample_count=1_000,
        candidate_recommendations=200,
        live_decisions_taken=0,
        automatic_disable_recorded=True,
        human_reviewed=True,
        report_sha256=DIGEST_B,
        observed_at=NOW,
        reviewer="risk@example.com",
    )


def _package(**changes: object) -> AIAdvisoryEvidencePackage:
    payload: dict[str, object] = {
        "generated_at": NOW,
        "generated_by": "ml-review@example.com",
        "registry": (_registry(),),
        "evaluations": (_evaluation(),),
        "drift_reports": (_drift(),),
        "ab_reports": (_ab(),),
        "human_reviewed": True,
        "reviewer": "risk@example.com",
    }
    payload.update(changes)
    return AIAdvisoryEvidencePackage(**payload)


def test_complete_ai_advisory_evidence_is_ready_but_never_authoritative() -> None:
    result = AIAdvisoryReadinessGate().evaluate(_package())

    assert result.ready is True
    assert result.state == "advisory-evidence-ready"
    assert result.blockers == ()
    assert result.ai_authority_enabled is False
    assert result.trading_mutation_allowed is False
    assert result.warnings == ("AI_ADVISORY_ONLY_NO_TRADING_AUTHORITY",)


def test_ai_trading_authority_cannot_be_registered() -> None:
    with pytest.raises(ValueError, match="advisory-only"):
        ModelRegistryEntry(
            model_id="unsafe",
            provider="offline",
            model_version="v1",
            artifact_sha256=DIGEST_A,
            prompt_template_sha256=DIGEST_B,
            feature_schema_sha256=DIGEST_C,
            training_dataset_sha256=DIGEST_D,
            evaluation_dataset_sha256=DIGEST_E,
            registered_at=NOW,
            registered_by="ml-review@example.com",
            advisory_only=False,
            trading_authority_enabled=True,
        )


def test_missing_human_review_and_duplicate_registry_block() -> None:
    package = _package(
        human_reviewed=False,
        reviewer="",
        registry=(_registry(), _registry()),
    )

    result = AIAdvisoryReadinessGate().evaluate(package)

    assert AdvisoryFailureCode.HUMAN_REVIEW_MISSING.value in result.blockers
    assert (
        f"{AdvisoryFailureCode.MODEL_REGISTRY_DUPLICATE.value}:advisory-v1"
        in result.blockers
    )
    assert result.ready is False


def test_random_or_in_sample_evaluation_cannot_promote_advisory_evidence() -> None:
    evaluation = replace(_evaluation(), split_kind=EvaluationSplitKind.RANDOM)
    result = AIAdvisoryReadinessGate().evaluate(_package(evaluations=(evaluation,)))

    assert (
        f"{AdvisoryFailureCode.TIME_SPLIT_EVALUATION_MISSING.value}:advisory-v1"
        in result.blockers
    )


def test_metric_latency_and_dataset_failures_are_blocked() -> None:
    evaluation = replace(
        _evaluation(),
        evaluation_dataset_sha256=DIGEST_A,
        sample_count=10,
        precision_at_threshold=0.10,
        p95_latency_ms=9_000,
    )

    result = AIAdvisoryReadinessGate().evaluate(_package(evaluations=(evaluation,)))

    assert (
        f"{AdvisoryFailureCode.DATASET_HASH_MISMATCH.value}:advisory-v1"
        in result.blockers
    )
    assert (
        f"{AdvisoryFailureCode.EVALUATION_SAMPLE_TOO_SMALL.value}:advisory-v1"
        in result.blockers
    )
    assert (
        f"{AdvisoryFailureCode.EVALUATION_METRIC_BELOW_THRESHOLD.value}:advisory-v1"
        in result.blockers
    )
    assert (
        f"{AdvisoryFailureCode.LATENCY_TOO_HIGH.value}:advisory-v1"
        in result.blockers
    )


def test_drift_and_missing_automatic_disable_block() -> None:
    drift = replace(
        _drift(),
        feature_drift_score=0.50,
        prediction_drift_score=0.50,
        missing_feature_rate=0.20,
        automatic_disable_recorded=False,
    )

    result = AIAdvisoryReadinessGate().evaluate(_package(drift_reports=(drift,)))

    assert (
        f"{AdvisoryFailureCode.FEATURE_DRIFT_TOO_HIGH.value}:advisory-v1"
        in result.blockers
    )
    assert (
        f"{AdvisoryFailureCode.PREDICTION_DRIFT_TOO_HIGH.value}:advisory-v1"
        in result.blockers
    )
    assert (
        f"{AdvisoryFailureCode.MISSING_FEATURE_RATE_TOO_HIGH.value}:advisory-v1"
        in result.blockers
    )
    assert (
        f"{AdvisoryFailureCode.DRIFT_AUTODISABLE_MISSING.value}:advisory-v1"
        in result.blockers
    )


def test_shadow_ab_must_not_take_live_decisions() -> None:
    ab = replace(
        _ab(),
        sample_count=20,
        live_decisions_taken=1,
        automatic_disable_recorded=False,
        human_reviewed=False,
    )

    result = AIAdvisoryReadinessGate().evaluate(_package(ab_reports=(ab,)))

    assert (
        f"{AdvisoryFailureCode.AB_SAMPLE_TOO_SMALL.value}:advisory-v1"
        in result.blockers
    )
    assert (
        f"{AdvisoryFailureCode.AB_LIVE_DECISIONS_PRESENT.value}:advisory-v1"
        in result.blockers
    )
    assert (
        f"{AdvisoryFailureCode.AB_AUTOMATIC_DISABLE_MISSING.value}:advisory-v1"
        in result.blockers
    )
    assert (
        f"{AdvisoryFailureCode.AB_HUMAN_REVIEW_MISSING.value}:advisory-v1"
        in result.blockers
    )


def test_unregistered_extra_reports_are_blocked() -> None:
    extra_evaluation = replace(_evaluation(), model_id="unknown-model")

    result = AIAdvisoryReadinessGate().evaluate(
        _package(evaluations=(_evaluation(), extra_evaluation))
    )

    assert (
        f"{AdvisoryFailureCode.MODEL_NOT_IN_REGISTRY.value}:unknown-model"
        in result.blockers
    )

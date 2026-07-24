from __future__ import annotations

from dataclasses import replace

import pytest

from src.mpr_next_06_shadow_soak_final_promotion import (
    EvidenceArtifact,
    MPRNext06Report,
    MPRNext06State,
    REQUIRED_JITO_STATES,
    evaluate_mpr_next_06,
    sample_review_ready_evidence,
)


def _codes(report: MPRNext06Report) -> set[str]:
    return {blocker.code for blocker in report.blockers}


def test_review_ready_evidence_is_default_off_and_not_production_ready_claim() -> None:
    report = evaluate_mpr_next_06(sample_review_ready_evidence())

    assert report.schema_version == "mpr-next-06.shadow-soak-final-promotion.v1"
    assert report.state is MPRNext06State.REVIEW_READY
    assert report.accepted is True
    assert report.blockers == ()
    assert report.missing_gate_artifacts == ()
    assert report.missing_release_artifacts == ()
    assert report.unrestricted_live_allowed is False
    assert report.production_ready_claimed is False


def test_mpr29_requires_72_hour_non_synthetic_soak_and_clean_incidents() -> None:
    evidence = sample_review_ready_evidence()
    report = evaluate_mpr_next_06(
        replace(
            evidence,
            shadow_soak=replace(
                evidence.shadow_soak,
                continuous_hours=24,
                non_synthetic_provider_evidence=False,
                unresolved_p0_incidents=1,
                unresolved_p1_incidents=1,
            ),
        )
    )

    codes = _codes(report)
    assert report.state is MPRNext06State.BLOCKED
    assert "MPRNEXT06_SOAK_TOO_SHORT" in codes
    assert "MPRNEXT06_MPR29_EVIDENCE_INCOMPLETE" in codes
    assert "MPRNEXT06_UNRESOLVED_P0_INCIDENTS" in codes
    assert "MPRNEXT06_UNRESOLVED_P1_INCIDENTS" in codes


def test_mpr30_rejects_ack_as_profit_unrestricted_live_and_auto_resend() -> None:
    evidence = sample_review_ready_evidence()
    report = evaluate_mpr_next_06(
        replace(
            evidence,
            submission_finality=replace(
                evidence.submission_finality,
                default_off=False,
                ack_or_bundle_id_used_as_profit=True,
                unrestricted_live_enabled=True,
                unknown_outcome_auto_resend_enabled=True,
            ),
        )
    )

    codes = _codes(report)
    assert "MPRNEXT06_MPR30_NOT_DEFAULT_OFF" in codes
    assert "MPRNEXT06_ACK_USED_AS_PROFIT" in codes
    assert "MPRNEXT06_UNRESTRICTED_LIVE_FORBIDDEN" in codes
    assert "MPRNEXT06_UNKNOWN_OUTCOME_AUTO_RESEND" in codes
    assert report.unrestricted_live_allowed is False


def test_jito_lifecycle_must_reach_finalized_and_reconciled() -> None:
    evidence = sample_review_ready_evidence()
    report = evaluate_mpr_next_06(
        replace(
            evidence,
            submission_finality=replace(
                evidence.submission_finality,
                jito_lifecycle_states=("created", "submitted", "landed"),
            ),
        )
    )

    assert "MPRNEXT06_JITO_LIFECYCLE_INCOMPLETE" in _codes(report)
    assert tuple(REQUIRED_JITO_STATES[-2:]) == ("finalized", "reconciled")


def test_all_gate_and_release_artifacts_are_required() -> None:
    evidence = sample_review_ready_evidence()
    artifacts = tuple(
        artifact for artifact in evidence.artifacts if artifact.artifact_id != "MPR-30"
    )
    report = evaluate_mpr_next_06(replace(evidence, artifacts=artifacts))

    assert report.state is MPRNext06State.BLOCKED
    assert report.missing_gate_artifacts == ("MPR-30",)
    assert "MPRNEXT06_MISSING_GATE_ARTIFACTS" in _codes(report)


def test_artifacts_must_be_signed_reviewed_immutable_and_not_synthetic() -> None:
    evidence = sample_review_ready_evidence()
    first = evidence.artifacts[0]
    artifacts = (replace(first, signed=False, reviewed=False, immutable=False, synthetic=True),) + evidence.artifacts[1:]
    report = evaluate_mpr_next_06(replace(evidence, artifacts=artifacts))

    codes = _codes(report)
    assert "MPRNEXT06_UNSIGNED_ARTIFACT" in codes
    assert "MPRNEXT06_UNREVIEWED_ARTIFACT" in codes
    assert "MPRNEXT06_MUTABLE_ARTIFACT" in codes
    assert "MPRNEXT06_SYNTHETIC_ARTIFACT" in codes


def test_mpr31_cannot_close_debt_from_in_memory_or_unsigned_evidence() -> None:
    evidence = sample_review_ready_evidence()
    report = evaluate_mpr_next_06(
        replace(
            evidence,
            mpr31_loads_only_immutable_artifacts=False,
            production_debt_closes_only_with_signed_artifacts=False,
            final_promotion_default_off=False,
        )
    )

    codes = _codes(report)
    assert "MPRNEXT06_MPR31_ACCEPTS_MEMORY_DTO" in codes
    assert "MPRNEXT06_DEBT_CLOSURE_WITHOUT_ARTIFACTS" in codes
    assert "MPRNEXT06_FINAL_PROMOTION_NOT_DEFAULT_OFF" in codes


def test_strict_types_reject_bool_as_int_and_bad_hash() -> None:
    with pytest.raises(ValueError, match="continuous_hours must be a strict integer"):
        replace(sample_review_ready_evidence().shadow_soak, continuous_hours=True)

    with pytest.raises(ValueError, match="sha256 must be sha256 hex"):
        EvidenceArtifact(
            artifact_id="bad",
            sha256="not-a-sha",
            signed=True,
            reviewed=True,
            immutable=True,
        )

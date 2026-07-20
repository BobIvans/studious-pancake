from __future__ import annotations

from src.venues.pump import (
    DEFAULT_MIN_SHADOW_SOAK_MINUTES,
    PumpContractManifest,
    PumpPromotionEvidence,
    PumpPromotionStatus,
    evaluate_pump_promotion,
)


def _rpc_evidence() -> PumpPromotionEvidence:
    return PumpPromotionEvidence(
        first_vertical_stable=True,
        pr064_release_ready=True,
        rpc_conformance_passed=True,
        rpc_programs_verified=2,
        rpc_account_samples=2,
    )


def _verified_evidence() -> PumpPromotionEvidence:
    return PumpPromotionEvidence(
        first_vertical_stable=True,
        pr064_release_ready=True,
        rpc_conformance_passed=True,
        rpc_programs_verified=2,
        rpc_account_samples=2,
        shadow_soak_minutes=DEFAULT_MIN_SHADOW_SOAK_MINUTES,
        shadow_soak_candidates=3,
        shadow_soak_replay_deterministic=True,
        unexplained_failures=0,
        evidence_package_sha256="a" * 64,
        human_review_accepted=True,
    )


def test_default_pump_promotion_blocks_until_rpc_and_soak_evidence() -> None:
    report = evaluate_pump_promotion(PumpPromotionEvidence())

    assert report.status is PumpPromotionStatus.BLOCKED
    assert report.shadow_soak_allowed is False
    assert report.shadow_soak_verified is False
    assert report.live_allowed is False
    assert "first_vertical_stable_required" in report.reason_codes
    assert "pr064_release_ready_required" in report.reason_codes
    assert "pump_rpc_conformance_required" in report.reason_codes


def test_rpc_conformance_only_is_ready_for_shadow_soak_not_verified() -> None:
    report = evaluate_pump_promotion(_rpc_evidence())

    assert report.status is PumpPromotionStatus.READY_FOR_SHADOW_SOAK
    assert report.shadow_soak_allowed is True
    assert report.shadow_soak_verified is False
    assert report.live_allowed is False
    assert "pump_shadow_soak_minutes_below_threshold" in report.reason_codes
    assert "pump_shadow_soak_human_review_required" in report.reason_codes


def test_full_pump_evidence_verifies_shadow_soak_but_never_live() -> None:
    report = evaluate_pump_promotion(_verified_evidence())

    assert report.status is PumpPromotionStatus.SHADOW_SOAK_VERIFIED
    assert report.reason_codes == ()
    assert report.shadow_soak_allowed is True
    assert report.shadow_soak_verified is True
    assert report.live_allowed is False
    assert report.to_dict() == {
        "schema_version": "pr065.pump-promotion.v1",
        "status": "shadow_soak_verified",
        "reason_codes": [],
        "required_families": 2,
        "shadow_soak_allowed": True,
        "shadow_soak_verified": True,
        "live_allowed": False,
    }


def test_manifest_live_capability_cannot_be_promoted_by_evidence() -> None:
    manifest = PumpContractManifest.load()
    raw = dict(manifest.raw)
    raw["live_capability"] = "ENABLED_BY_TEST"

    report = evaluate_pump_promotion(
        _verified_evidence(),
        manifest=PumpContractManifest(raw),
    )

    assert report.status is PumpPromotionStatus.BLOCKED
    assert report.live_allowed is False
    assert "manifest_live_capability_must_remain_denied" in report.reason_codes

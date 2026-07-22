from __future__ import annotations

import json

from src.release_soak_canary_prd import (
    Blocker,
    CanaryPolicy,
    ReleaseEvidence,
    SoakEvidence,
    default_blocked_preflight,
    evaluate_prd_preflight,
    report_from_json,
    report_to_json,
)


def _soak() -> SoakEvidence:
    return SoakEvidence(
        duration_hours=72,
        synthetic_rows=0,
        sender_reachable=False,
        wheel_hash="sha256:wheel",
        image_digest="sha256:image",
        policy_hash="sha256:policy",
        reservation_leak_lamports=0,
        reconciliation_backlog=0,
        restart_recovery_proven=True,
        resource_limits_proven=True,
    )


def _release() -> ReleaseEvidence:
    return ReleaseEvidence(
        wheel_hash="sha256:wheel",
        image_digest="sha256:image",
        sbom_hash="sha256:sbom",
        provenance_hash="sha256:provenance",
        source_wheel_parity=True,
        non_root=True,
        read_only_rootfs=True,
        caps_dropped=True,
        no_new_privileges=True,
        egress_allowlist=True,
        secrets_externalized=True,
    )


def _canary() -> CanaryPolicy:
    return CanaryPolicy(
        live_requested=False,
        sender_reachable=False,
        wallet_lamports=10_000_000,
        max_notional_lamports=1_000_000,
        max_transactions_per_day=3,
        max_daily_loss_lamports=500_000,
        signer_expiry_seconds=300,
        second_reviewer=True,
        kill_switch_rehearsed=True,
        rollback_rehearsed=True,
    )


def test_prd_default_is_blocked_without_real_evidence() -> None:
    report = default_blocked_preflight()

    assert report.live_enabled is False
    assert report.review_ready is False
    assert set(report.blockers) == {
        Blocker.SOAK_MISSING,
        Blocker.RELEASE_ARTIFACT_MISSING,
        Blocker.CANARY_LIMIT_MISSING,
    }


def test_prd_ready_evidence_still_does_not_enable_live() -> None:
    report = evaluate_prd_preflight(
        soak=_soak(),
        release=_release(),
        canary=_canary(),
    )

    assert report.review_ready is True
    assert report.live_enabled is False
    assert report.manual_review_required is True


def test_prd_blocks_synthetic_soak_and_sender_reachability() -> None:
    soak = SoakEvidence(
        duration_hours=72,
        synthetic_rows=1,
        sender_reachable=True,
        wheel_hash="sha256:wheel",
        image_digest="sha256:image",
        policy_hash="sha256:policy",
        restart_recovery_proven=True,
        resource_limits_proven=True,
    )

    report = evaluate_prd_preflight(
        soak=soak,
        release=_release(),
        canary=_canary(),
    )

    assert Blocker.SYNTHETIC_SOAK in report.blockers
    assert Blocker.SENDER_REACHABLE in report.blockers


def test_prd_blocks_release_mismatch_and_missing_hardening() -> None:
    release = ReleaseEvidence(
        wheel_hash="sha256:other",
        image_digest="sha256:other",
        sbom_hash="sha256:sbom",
        provenance_hash="sha256:provenance",
        source_wheel_parity=False,
        non_root=False,
        read_only_rootfs=True,
        caps_dropped=True,
        no_new_privileges=True,
        egress_allowlist=True,
        secrets_externalized=True,
    )

    report = evaluate_prd_preflight(
        soak=_soak(),
        release=release,
        canary=_canary(),
    )

    assert Blocker.RELEASE_ARTIFACT_MISSING in report.blockers
    assert Blocker.RELEASE_HARDENING_MISSING in report.blockers
    assert Blocker.SOURCE_WHEEL_PARITY_MISSING in report.blockers


def test_prd_blocks_unsafe_canary_request() -> None:
    canary = CanaryPolicy(
        live_requested=True,
        sender_reachable=True,
        wallet_lamports=0,
        max_notional_lamports=0,
        max_transactions_per_day=0,
        max_daily_loss_lamports=0,
        signer_expiry_seconds=0,
        second_reviewer=False,
        kill_switch_rehearsed=False,
        rollback_rehearsed=False,
    )

    report = evaluate_prd_preflight(
        soak=_soak(),
        release=_release(),
        canary=canary,
    )

    assert Blocker.LIVE_REQUESTED in report.blockers
    assert Blocker.SENDER_REACHABLE in report.blockers
    assert Blocker.CANARY_LIMIT_MISSING in report.blockers
    assert Blocker.CANARY_REVIEW_MISSING in report.blockers
    assert Blocker.ROLLBACK_REHEARSAL_MISSING in report.blockers
    assert report.live_enabled is False


def test_prd_report_roundtrip_keeps_live_disabled() -> None:
    report = evaluate_prd_preflight(
        soak=_soak(),
        release=_release(),
        canary=_canary(),
    )

    loaded = report_from_json(json.loads(report_to_json(report)))

    assert loaded.review_ready is True
    assert loaded.live_enabled is False

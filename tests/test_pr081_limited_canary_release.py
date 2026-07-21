from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from src.release_gate.limited_canary import (
    PR078_SECURITY_EVIDENCE_NAME,
    PR080_SENDER_CONFORMANCE_NAME,
    REQUIRED_LATCHES,
    REQUIRED_SENDER_CONTROLS,
    EvidenceRef,
    LimitedCanaryPackage,
    LimitedCanaryState,
    evaluate_limited_canary,
)
from src.shadow_soak.real_soak import RealShadowSoakReadiness, RealShadowSoakState

ASSEMBLED = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
PROGRAM_ID = "11111111111111111111111111111111"


def _soak() -> RealShadowSoakReadiness:
    return RealShadowSoakReadiness(
        run_id="pr079-run",
        state=RealShadowSoakState.READY_FOR_RELEASE_EVIDENCE,
        release_evidence_ready=True,
        live_allowed=False,
        blockers=(),
        warnings=(),
        package_sha256="1" * 64,
        soak_evidence_sha256="2" * 64,
        immutable_bundle_sha256="3" * 64,
        duration_seconds=73 * 60 * 60,
        candidates_seen=10,
        replay_pass_rate_bps=10_000,
    )


def _evidence(name: str, seed: str) -> EvidenceRef:
    return EvidenceRef(
        name=name,
        sha256=seed * 64,
        source_commit=seed * 40,
        passed=True,
        human_reviewed=True,
        reviewer="reviewer",
    )


def _manifest() -> dict[str, str]:
    return {
        "code_commit": "9" * 40,
        "config_fingerprint_sha256": "a" * 64,
        "contract_pins_sha256": "b" * 64,
        "sbom_sha256": "c" * 64,
        "image_digest_sha256": "d" * 64,
        "image_signature_sha256": "e" * 64,
        "pr078_security_evidence_sha256": "4" * 64,
        "pr079_evidence_sha256": "1" * 64,
        "pr080_sender_conformance_sha256": "6" * 64,
        "rollback_plan_sha256": "f" * 64,
    }


def _package(**overrides) -> LimitedCanaryPackage:
    values = {
        "real_soak": _soak(),
        "pr078_security": _evidence(PR078_SECURITY_EVIDENCE_NAME, "4"),
        "pr080_sender": _evidence(PR080_SENDER_CONFORMANCE_NAME, "6"),
        "sender_controls": {control: True for control in REQUIRED_SENDER_CONTROLS},
        "enablement_steps": {
            "release-owner-signoff": ASSEMBLED - timedelta(minutes=3),
            "security-owner-signoff": ASSEMBLED - timedelta(minutes=2),
            "operator-arm-command": ASSEMBLED - timedelta(minutes=1),
        },
        "allowlist": (
            {
                "pair": "SOL/USDC",
                "provider": "jupiter",
                "program_id": PROGRAM_ID,
                "max_exposure_lamports": 10_000,
                "protected_reserve_lamports": 15_000_000,
                "reviewed": True,
            },
        ),
        "limits": {
            "max_exposure_lamports": 10_000,
            "protected_reserve_lamports": 15_000_000,
            "max_loss_lamports": 5_000,
            "max_failed_attempts": 1,
            "stale_after_seconds": 30,
            "max_outstanding_submissions": 1,
        },
        "latches": {
            latch: {"armed": True, "tested": True, "blocks_on_trigger": True}
            for latch in REQUIRED_LATCHES
        },
        "manifest": _manifest(),
        "assembled_at": ASSEMBLED,
        "assembled_by": "operator",
        "default_live_enabled": False,
        "manual_kill_switch_armed": True,
        "post_trade_reconciliation_required": True,
        "indeterminate_outcome_open": False,
        "rollback_requires_code_change": False,
    }
    values.update(overrides)
    return LimitedCanaryPackage(**values)


def test_pr081_accepts_review_ready_package_without_enabling_live() -> None:
    result = evaluate_limited_canary(_package())

    assert result.state is LimitedCanaryState.READY_FOR_MANUAL_CANARY_REVIEW
    assert result.manual_canary_review_ready is True
    assert result.default_live_enabled is False
    assert result.runtime_live_enabled is False
    assert result.blockers == ()
    assert result.max_outstanding_submissions == 1


def test_pr081_blocks_when_default_live_is_enabled() -> None:
    result = evaluate_limited_canary(_package(default_live_enabled=True))

    assert result.state is LimitedCanaryState.BLOCKED
    assert "DEFAULT_LIVE_ENABLED" in result.blockers
    assert result.runtime_live_enabled is False


def test_pr081_blocks_without_pr079_release_evidence() -> None:
    blocked_soak = replace(
        _soak(),
        state=RealShadowSoakState.BLOCKED,
        release_evidence_ready=False,
    )
    result = evaluate_limited_canary(_package(real_soak=blocked_soak))

    assert "PR079_REAL_SOAK_NOT_RELEASE_READY" in result.blockers
    assert "PR079_REAL_SOAK_BLOCKED" in result.blockers


def test_pr081_blocks_without_sender_conformance_controls() -> None:
    controls = {control: True for control in REQUIRED_SENDER_CONTROLS}
    controls["fake_ack_rejected"] = False
    controls["no_resend_under_ambiguity"] = False
    result = evaluate_limited_canary(_package(sender_controls=controls))

    assert "PR080_CONTROL_MISSING:fake_ack_rejected" in result.blockers
    assert "PR080_CONTROL_MISSING:no_resend_under_ambiguity" in result.blockers


def test_pr081_requires_every_latch_tested_and_armed() -> None:
    latches = {
        latch: {"armed": True, "tested": True, "blocks_on_trigger": True}
        for latch in REQUIRED_LATCHES
    }
    latches["indeterminate-outcome"] = {
        "armed": True,
        "tested": False,
        "blocks_on_trigger": True,
    }
    result = evaluate_limited_canary(_package(latches=latches))

    assert "LATCH_NOT_TESTED:indeterminate-outcome" in result.blockers


def test_pr081_blocks_indeterminate_outcome_and_codeful_rollback() -> None:
    result = evaluate_limited_canary(
        _package(indeterminate_outcome_open=True, rollback_requires_code_change=True)
    )

    assert "INDETERMINATE_OUTCOME_OPEN" in result.blockers
    assert "ROLLBACK_TO_SHADOW_REQUIRES_CODE_CHANGE" in result.blockers


def test_pr081_blocks_allowlist_exposure_above_tiny_limit() -> None:
    result = evaluate_limited_canary(
        _package(
            allowlist=(
                {
                    "pair": "SOL/USDC",
                    "provider": "jupiter",
                    "program_id": PROGRAM_ID,
                    "max_exposure_lamports": 20_000,
                    "protected_reserve_lamports": 15_000_000,
                    "reviewed": True,
                },
            )
        )
    )

    assert (
        f"ALLOWLIST_EXPOSURE_EXCEEDS_LIMIT:SOL/USDC:jupiter:{PROGRAM_ID}"
        in result.blockers
    )

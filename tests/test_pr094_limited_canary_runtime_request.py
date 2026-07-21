from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.release_gate.limited_canary import (
    PR078_SECURITY_EVIDENCE_NAME,
    PR080_SENDER_CONFORMANCE_NAME,
    PR092_REAL_SOAK_EVIDENCE_NAME,
    PR093_SENDER_LIFECYCLE_NAME,
    REQUIRED_LATCHES,
    REQUIRED_RUNTIME_ACKS,
    REQUIRED_SENDER_CONTROLS,
    EvidenceRef,
    LimitedCanaryPackage,
    LimitedCanaryRuntimeRequest,
    LimitedCanaryRuntimeState,
    evaluate_limited_canary_runtime_request,
)
from src.shadow_soak.real_soak import RealShadowSoakReadiness, RealShadowSoakState

ASSEMBLED = datetime(2026, 7, 21, 12, tzinfo=timezone.utc)
PROGRAM_ID = "11111111111111111111111111111111"


def _soak() -> RealShadowSoakReadiness:
    return RealShadowSoakReadiness(
        run_id="pr092-run",
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
        "pr092_soak_evidence_sha256": "7" * 64,
        "pr093_sender_lifecycle_sha256": "8" * 64,
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
        "pr092_real_soak": _evidence(PR092_REAL_SOAK_EVIDENCE_NAME, "7"),
        "pr093_sender_lifecycle": _evidence(PR093_SENDER_LIFECYCLE_NAME, "8"),
    }
    values.update(overrides)
    return LimitedCanaryPackage(**values)


def _request(package: LimitedCanaryPackage, **overrides) -> LimitedCanaryRuntimeRequest:
    values = {
        "reviewed_package_sha256": package.package_sha256,
        "requested_at": package.assembled_at + timedelta(minutes=1),
        "requested_by": "human-operator",
        "runtime_default_live_enabled": False,
        "env_override_requested": False,
        "acknowledgement_steps": {
            acknowledgement: True for acknowledgement in REQUIRED_RUNTIME_ACKS
        },
        "max_exposure_lamports": 10_000,
        "max_outstanding_submissions": 1,
    }
    values.update(overrides)
    return LimitedCanaryRuntimeRequest(**values)


def test_pr094_runtime_request_can_be_review_ready_without_enabling_live() -> None:
    package = _package()

    result = evaluate_limited_canary_runtime_request(package, _request(package))

    assert result.state is LimitedCanaryRuntimeState.READY_FOR_HUMAN_CONTROLLED_CANARY
    assert result.canary_runtime_ready is True
    assert result.package_manual_review_ready is True
    assert result.default_live_enabled is False
    assert result.runtime_live_enabled is False
    assert result.blockers == ()
    assert result.max_outstanding_submissions == 1


def test_pr094_rejects_env_only_canary_activation() -> None:
    package = _package()

    result = evaluate_limited_canary_runtime_request(
        package,
        _request(package, env_override_requested=True),
    )

    assert result.state is LimitedCanaryRuntimeState.BLOCKED
    assert "ENV_ONLY_CANARY_ENABLE_FORBIDDEN" in result.blockers
    assert result.runtime_live_enabled is False


def test_pr094_requires_runtime_request_to_match_reviewed_package_hash() -> None:
    package = _package()

    result = evaluate_limited_canary_runtime_request(
        package,
        _request(package, reviewed_package_sha256="a" * 64),
    )

    assert result.state is LimitedCanaryRuntimeState.BLOCKED
    assert "CANARY_PACKAGE_HASH_MISMATCH" in result.blockers


def test_pr094_requires_pr092_and_pr093_evidence_refs() -> None:
    package = _package(pr092_real_soak=None, pr093_sender_lifecycle=None)

    result = evaluate_limited_canary_runtime_request(package, _request(package))

    assert "PR092_EVIDENCE_MISSING" in result.blockers
    assert "PR093_EVIDENCE_MISSING" in result.blockers


def test_pr094_runtime_request_cannot_expand_reviewed_limits() -> None:
    package = _package()

    result = evaluate_limited_canary_runtime_request(
        package,
        _request(package, max_exposure_lamports=20_000, max_outstanding_submissions=2),
    )

    assert "RUNTIME_REQUIRES_ONE_OUTSTANDING_SUBMISSION" in result.blockers
    assert "RUNTIME_OUTSTANDING_LIMIT_MISMATCH" in result.blockers
    assert "RUNTIME_EXPOSURE_EXCEEDS_REVIEWED_PACKAGE" in result.blockers

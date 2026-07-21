from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

from src.release_gate.reviewed_canary import (
    PR104_RELEASE_EVIDENCE_NAME,
    PR105_SHADOW_SOAK_EVIDENCE_NAME,
    PR106_SENDER_LIFECYCLE_EVIDENCE_NAME,
    REQUIRED_PR107_LATCHES,
    REQUIRED_PR107_SIGNOFFS,
    ReviewedCanaryAllowlistEntry,
    ReviewedCanaryEvidenceRef,
    ReviewedCanaryLatch,
    ReviewedCanaryState,
    ReviewedLimitedCanaryPackage,
    evaluate_pr107_reviewed_canary_package,
)

ASSEMBLED = datetime(2026, 7, 21, 14, tzinfo=timezone.utc)
PROGRAM_ID = "11111111111111111111111111111111"


def _sha(seed: str) -> str:
    return seed * 64


def _git(seed: str) -> str:
    return seed * 40


def _evidence(name: str, seed: str) -> ReviewedCanaryEvidenceRef:
    return ReviewedCanaryEvidenceRef(
        name=name,
        sha256=_sha(seed),
        source_commit=_git(seed),
        passed=True,
        human_reviewed=True,
        reviewer="reviewer",
    )


def _allowlist(**overrides) -> ReviewedCanaryAllowlistEntry:
    values = {
        "pair": "SOL/USDC",
        "provider": "jupiter",
        "program_id": PROGRAM_ID,
        "max_exposure_lamports": 10_000,
        "protected_reserve_lamports": 15_000_000,
        "reviewed": True,
    }
    values.update(overrides)
    return ReviewedCanaryAllowlistEntry(**values)


def _latch(name: str, **overrides) -> ReviewedCanaryLatch:
    values = {"name": name, "armed": True, "tested": True, "blocks_on_trigger": True}
    values.update(overrides)
    return ReviewedCanaryLatch(**values)


def _signoffs(**overrides) -> dict[str, datetime]:
    values = {
        name: ASSEMBLED - timedelta(minutes=index + 1)
        for index, name in enumerate(REQUIRED_PR107_SIGNOFFS)
    }
    values.update(overrides)
    return values


def _package(**overrides) -> ReviewedLimitedCanaryPackage:
    values = {
        "code_commit": _git("9"),
        "config_sha256": _sha("a"),
        "contract_pins_sha256": _sha("b"),
        "rollback_plan_sha256": _sha("c"),
        "pr104_release_evidence": _evidence(PR104_RELEASE_EVIDENCE_NAME, "4"),
        "pr105_shadow_soak": _evidence(PR105_SHADOW_SOAK_EVIDENCE_NAME, "5"),
        "pr106_sender_lifecycle": _evidence(
            PR106_SENDER_LIFECYCLE_EVIDENCE_NAME,
            "6",
        ),
        "allowlist": (_allowlist(),),
        "latches": tuple(_latch(name) for name in REQUIRED_PR107_LATCHES),
        "human_signoffs": _signoffs(),
        "max_exposure_lamports": 10_000,
        "protected_reserve_lamports": 15_000_000,
        "max_outstanding_submissions": 1,
        "default_live_enabled": False,
        "env_can_enable_live": False,
        "manual_kill_switch_armed": True,
        "post_trade_reconciliation_required": True,
        "rollback_requires_code_change": False,
        "indeterminate_outcome_open": False,
        "one_outstanding_submission_enforced": True,
        "isolated_signer_reviewed": True,
        "assembled_at": ASSEMBLED,
        "assembled_by": "release-operator",
    }
    values.update(overrides)
    return ReviewedLimitedCanaryPackage(**values)


def test_pr107_ready_package_is_review_only_and_never_runtime_live() -> None:
    result = evaluate_pr107_reviewed_canary_package(_package())

    assert result.state is ReviewedCanaryState.READY_FOR_MANUAL_CANARY_REVIEW
    assert result.ready_for_manual_canary_review is True
    assert result.default_live_enabled is False
    assert result.runtime_live_enabled is False
    assert result.supported_command_can_submit is False
    assert result.max_outstanding_submissions == 1
    assert result.blockers == ()


def test_pr107_requires_pr104_pr105_and_pr106_reviewed_evidence() -> None:
    result = evaluate_pr107_reviewed_canary_package(
        _package(
            pr104_release_evidence=replace(
                _evidence(PR104_RELEASE_EVIDENCE_NAME, "4"),
                passed=False,
            ),
            pr105_shadow_soak=replace(
                _evidence("wrong-soak", "5"),
                human_reviewed=False,
            ),
            pr106_sender_lifecycle=replace(
                _evidence(PR106_SENDER_LIFECYCLE_EVIDENCE_NAME, "6"),
                human_reviewed=False,
            ),
        )
    )

    assert "PR104_EVIDENCE_BLOCKED" in result.blockers
    assert "PR105_WRONG_EVIDENCE_NAME" in result.blockers
    assert "PR105_EVIDENCE_NOT_REVIEWED" in result.blockers
    assert "PR106_EVIDENCE_NOT_REVIEWED" in result.blockers


def test_pr107_blocks_env_or_default_live_activation() -> None:
    result = evaluate_pr107_reviewed_canary_package(
        _package(default_live_enabled=True, env_can_enable_live=True)
    )

    assert "DEFAULT_LIVE_ENABLED" in result.blockers
    assert "ENV_CAN_ENABLE_LIVE" in result.blockers
    assert result.runtime_live_enabled is False
    assert result.supported_command_can_submit is False


def test_pr107_requires_tiny_one_submission_limits() -> None:
    result = evaluate_pr107_reviewed_canary_package(
        _package(
            max_exposure_lamports=100_000_000,
            max_outstanding_submissions=2,
            one_outstanding_submission_enforced=False,
        )
    )

    assert "CANARY_EXPOSURE_NOT_TINY" in result.blockers
    assert "CANARY_REQUIRES_ONE_OUTSTANDING_SUBMISSION" in result.blockers
    assert "ONE_OUTSTANDING_SUBMISSION_NOT_ENFORCED" in result.blockers


def test_pr107_requires_reviewed_allowlist_and_protected_reserve() -> None:
    result = evaluate_pr107_reviewed_canary_package(
        _package(
            allowlist=(
                _allowlist(
                    reviewed=False,
                    max_exposure_lamports=20_000,
                    protected_reserve_lamports=1,
                ),
            )
        )
    )

    prefix = f"SOL/USDC:jupiter:{PROGRAM_ID}"
    assert f"ALLOWLIST_NOT_REVIEWED:{prefix}" in result.blockers
    assert f"ALLOWLIST_EXPOSURE_EXCEEDS_PACKAGE:{prefix}" in result.blockers
    assert f"ALLOWLIST_RESERVE_TOO_LOW:{prefix}" in result.blockers


def test_pr107_requires_latches_and_final_human_signoffs() -> None:
    latches = tuple(
        _latch(name, tested=False) if name == "ambiguity" else _latch(name)
        for name in REQUIRED_PR107_LATCHES
        if name != "manual-kill-switch"
    )
    signoffs = _signoffs(
        **{"operator-final-arm-signoff": ASSEMBLED + timedelta(minutes=1)}
    )
    result = evaluate_pr107_reviewed_canary_package(
        _package(latches=latches, human_signoffs=signoffs)
    )

    assert "LATCH_MISSING:manual-kill-switch" in result.blockers
    assert "LATCH_NOT_TESTED:ambiguity" in result.blockers
    assert "SIGNOFF_AFTER_ASSEMBLY:operator-final-arm-signoff" in result.blockers


def test_pr107_stable_json_result_includes_package_hash() -> None:
    result = evaluate_pr107_reviewed_canary_package(_package())
    encoded = json.dumps(result.to_dict(), sort_keys=True)

    assert "ready-for-manual-canary-review" in encoded
    assert result.package_sha256 in encoded

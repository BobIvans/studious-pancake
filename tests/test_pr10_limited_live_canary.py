from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src.live_canary.roadmap_pr10 import (
    COMPILE_TIME_CANARY_ENABLED,
    EXPECTED_PREREQUISITES,
    MAX_CANARY_EXPOSURE_LAMPORTS,
    PR10CanaryError,
    PR10CanaryRequest,
    PR10CanaryScope,
    PR10CanaryState,
    PR10PrerequisiteEvidence,
    REQUIRED_LATCHES,
    evaluate_pr10_canary_foundation,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
COMMIT = "d" * 40
NOW = 2_000_000


def _scope(**overrides: object) -> PR10CanaryScope:
    values: dict[str, object] = {
        "pair": "SOL/USDC",
        "provider": "jupiter",
        "program_ids": ("11111111111111111111111111111111",),
        "transport": "rpc",
        "max_exposure_lamports": 1_000_000,
        "protected_reserve_lamports": 10_000_000,
        "max_network_fee_lamports": 10_000,
        "max_priority_fee_lamports": 5_000,
        "max_jito_tip_lamports": 0,
        "reviewed": True,
    }
    values.update(overrides)
    return PR10CanaryScope(**values)


def _request(**overrides: object) -> PR10CanaryRequest:
    values: dict[str, object] = {
        "release_digest_sha256": SHA_A,
        "policy_bundle_sha256": SHA_B,
        "code_commit": COMMIT,
        "environment": "protected-canary",
        "cluster_genesis_sha256": SHA_C,
        "requested_by": "requester",
        "release_approved_by": "release-owner",
        "risk_approved_by": "risk-owner",
        "operator_armed_by": "operator",
        "requested_at_ms": NOW - 1_000,
        "expires_at_ms": NOW + 60_000,
        "scopes": (_scope(),),
        "latches": {name: True for name in REQUIRED_LATCHES},
        "minimum_wallet_reserve_lamports": 10_000_000,
        "max_outstanding_submissions": 1,
        "runtime_default_live_enabled": False,
        "environment_activation_requested": False,
        "ai_authority": False,
        "rollback_to_shadow_without_code_change": True,
        "post_trade_reconciliation_required": True,
        "unresolved_settlement": False,
        "active_exposure_open": False,
        "isolated_signer_boundary_reviewed": True,
        "finalized_settlement_boundary_reviewed": True,
        "protected_deployment_reviewed": True,
    }
    values.update(overrides)
    return PR10CanaryRequest(**values)


def _evidence(request: PR10CanaryRequest) -> tuple[PR10PrerequisiteEvidence, ...]:
    return tuple(
        PR10PrerequisiteEvidence(
            roadmap_pr=roadmap_pr,
            artifact_sha256=f"{index:x}" * 64,
            source_commit=request.code_commit,
            release_digest_sha256=request.release_digest_sha256,
            policy_bundle_sha256=request.policy_bundle_sha256,
            reviewer_id=f"reviewer-{index % 3}",
            reviewed_at_ms=NOW - 10_000,
            expires_at_ms=NOW + 120_000,
            passed=True,
            human_reviewed=True,
            immutable=True,
            synthetic=False,
        )
        for index, roadmap_pr in enumerate(EXPECTED_PREREQUISITES, start=1)
    )


def test_complete_foundation_is_review_ready_but_cannot_enable_or_submit() -> None:
    request = _request()
    result = evaluate_pr10_canary_foundation(
        _evidence(request),
        request,
        now_ms=NOW,
    )

    assert result.state is PR10CanaryState.READY_FOR_INDEPENDENT_ACTIVATION_REVIEW
    assert result.prerequisites_complete is True
    assert result.ready_for_independent_activation_review is True
    assert COMPILE_TIME_CANARY_ENABLED is False
    assert result.compile_time_canary_enabled is False
    assert result.runtime_live_enabled is False
    assert result.submission_allowed is False
    assert result.supported_command_can_submit is False
    assert result.blockers == ()


def test_missing_pr09_evidence_blocks() -> None:
    request = _request()
    evidence = _evidence(request)[:-1]
    result = evaluate_pr10_canary_foundation(evidence, request, now_ms=NOW)

    assert result.state is PR10CanaryState.BLOCKED
    assert "PREREQUISITE_MISSING:PR-09" in result.blockers


def test_duplicate_prerequisite_blocks() -> None:
    request = _request()
    evidence = _evidence(request)
    result = evaluate_pr10_canary_foundation(
        evidence + (evidence[0],),
        request,
        now_ms=NOW,
    )

    assert "DUPLICATE_PREREQUISITE:PR-01" in result.blockers


def test_release_and_policy_drift_block() -> None:
    request = _request()
    evidence = list(_evidence(request))
    evidence[2] = replace(
        evidence[2],
        release_digest_sha256=SHA_C,
        policy_bundle_sha256=SHA_C,
    )
    result = evaluate_pr10_canary_foundation(evidence, request, now_ms=NOW)

    assert "PREREQUISITE_RELEASE_MISMATCH:PR-03" in result.blockers
    assert "PREREQUISITE_POLICY_MISMATCH:PR-03" in result.blockers


def test_environment_or_ai_activation_is_forbidden() -> None:
    request = _request(
        runtime_default_live_enabled=True,
        environment_activation_requested=True,
        ai_authority=True,
    )
    result = evaluate_pr10_canary_foundation(
        _evidence(request),
        request,
        now_ms=NOW,
    )

    assert "RUNTIME_DEFAULT_LIVE_ENABLED" in result.blockers
    assert "ENVIRONMENT_ONLY_ACTIVATION_FORBIDDEN" in result.blockers
    assert "AI_AUTHORITY_FORBIDDEN" in result.blockers
    assert result.runtime_live_enabled is False
    assert result.submission_allowed is False


def test_scope_must_be_single_reviewed_and_tiny() -> None:
    oversized = _scope(max_exposure_lamports=MAX_CANARY_EXPOSURE_LAMPORTS + 1)
    request = _request(scopes=(oversized, _scope(reviewed=False)))
    result = evaluate_pr10_canary_foundation(
        _evidence(request),
        request,
        now_ms=NOW,
    )

    assert "CANARY_REQUIRES_EXACTLY_ONE_SCOPE" in result.blockers
    assert "CANARY_EXPOSURE_EXCEEDS_TINY_CAP" in result.blockers
    assert "CANARY_SCOPE_NOT_REVIEWED" in result.blockers


def test_role_separation_and_one_outstanding_are_required() -> None:
    request = _request(
        release_approved_by="requester",
        max_outstanding_submissions=2,
    )
    result = evaluate_pr10_canary_foundation(
        _evidence(request),
        request,
        now_ms=NOW,
    )

    assert "SEPARATION_OF_DUTIES_VIOLATION" in result.blockers
    assert "CANARY_REQUIRES_ONE_OUTSTANDING_SUBMISSION" in result.blockers


def test_expired_evidence_and_unresolved_state_block() -> None:
    request = _request(
        unresolved_settlement=True,
        active_exposure_open=True,
    )
    evidence = list(_evidence(request))
    evidence[0] = replace(evidence[0], expires_at_ms=NOW - 1)
    result = evaluate_pr10_canary_foundation(evidence, request, now_ms=NOW)

    assert "PREREQUISITE_EXPIRED:PR-01" in result.blockers
    assert "UNRESOLVED_SETTLEMENT_PRESENT" in result.blockers
    assert "ACTIVE_EXPOSURE_PRESENT" in result.blockers


def test_jito_and_rpc_scope_tip_rules_fail_closed() -> None:
    with pytest.raises(PR10CanaryError, match="rpc scope cannot include a Jito tip"):
        _scope(max_jito_tip_lamports=1)
    with pytest.raises(
        PR10CanaryError,
        match="jito-single scope requires a positive tip cap",
    ):
        _scope(transport="jito-single", max_jito_tip_lamports=0)


def test_request_hash_is_deterministic() -> None:
    first = _request()
    second = _request()
    assert first.request_sha256 == second.request_sha256


def test_pr10_foundation_has_no_signer_sender_or_network_imports() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "src" / "live_canary" / "roadmap_pr10.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "Keypair",
        "solders",
        "src.execution.senders",
        "sendTransaction",
        "jito_executor",
        "aiohttp",
        "httpx",
        "requests",
    )
    assert all(token not in source for token in forbidden)

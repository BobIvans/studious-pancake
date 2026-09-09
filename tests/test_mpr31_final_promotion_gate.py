from __future__ import annotations

from dataclasses import asdict
import hashlib
import json

import pytest

from src.release_gate.mpr31_final_promotion_gate import (
    FinalPromotionBundle,
    ImmutableArchiveEvidence,
    MPR31FinalPromotionGate,
    MPR2611Qualification,
    MPR2612FinalReleaseGate,
    OperatorCommandEvidence,
    PromotionStatus,
    ReleaseApproval,
    ReleaseProposal,
    ReleaseState,
    RootedTreasuryEvidence,
    SignedEvidenceArtifact,
    TinyCanaryProposal,
    UpstreamMprEvidence,
)

D = "a" * 64
D2 = "b" * 64
D3 = "c" * 64
NOW = 1_000_000


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def qualification(**overrides: object) -> MPR2611Qualification:
    data: dict[str, object] = {
        "schema_version": "mpr-2611.production-qualification.v1",
        "release_id": "release-A",
        "source_commit": D,
        "source_tree_digest": D,
        "wheel_digest": D,
        "runtime_image_digest": D,
        "signer_image_digest": D,
        "config_generation_digest": D,
        "policy_generation_digest": D,
        "production_debt_digest": D,
        "runtime_authority_digest": D,
        "dependency_closure_digest": D,
        "sbom_provenance_digest": D,
        "platform_matrix_digest": D,
        "predecessor_evidence_digest": D,
        "qualification_semantic_digest": D,
        "production_qualification_passed": True,
        "eligible_for_release_review": True,
        "release_claim_allowed": False,
        "live_enabled": False,
        "unresolved_p0_blockers": 0,
    }
    data.update(overrides)
    digest_payload = dict(data)
    digest_payload.pop("qualification_semantic_digest")
    data["qualification_semantic_digest"] = _sha(digest_payload)
    return MPR2611Qualification(**data)


def proposal(q: MPR2611Qualification, **overrides: object) -> ReleaseProposal:
    data: dict[str, object] = {
        "release_id": q.release_id,
        "source_commit": q.source_commit,
        "source_tree_digest": q.source_tree_digest,
        "wheel_digest": q.wheel_digest,
        "runtime_image_digest": q.runtime_image_digest,
        "signer_image_digest": q.signer_image_digest,
        "config_generation_digest": q.config_generation_digest,
        "policy_generation_digest": q.policy_generation_digest,
        "qualification_digest": q.qualification_semantic_digest,
        "runtime_authority_digest": q.runtime_authority_digest,
        "production_surface_digest": D,
        "production_debt_digest": q.production_debt_digest,
        "sbom_provenance_digest": q.sbom_provenance_digest,
        "platform_matrix_digest": q.platform_matrix_digest,
        "rollback_target_generation": 0,
        "created_at_ns": 1,
        "not_before_ns": 2,
        "expires_at_ns": 2_000_000,
        "proposer_principal": "human-proposer",
        "proposal_nonce": "nonce-1",
    }
    data.update(overrides)
    return ReleaseProposal(**data)


def approval(p: ReleaseProposal, q: MPR2611Qualification, principal: str, key: str, **overrides: object) -> ReleaseApproval:
    data: dict[str, object] = {
        "principal_id": principal,
        "public_key_id": key,
        "role": "release-reviewer",
        "release_id": p.release_id,
        "proposal_digest": p.proposal_digest,
        "qualification_digest": q.qualification_semantic_digest,
        "issued_at_ns": 1,
        "not_before_ns": 2,
        "expires_at_ns": 2_000_000,
        "signature": "cryptographic-signature-fixture",
    }
    data.update(overrides)
    return ReleaseApproval(**data)


def gate(*, signature_ok: bool = True) -> MPR2612FinalReleaseGate:
    return MPR2612FinalReleaseGate(
        qualification_verifier=lambda q: q.production_qualification_passed,
        signature_verifier=lambda approval, payload: signature_ok and bool(payload) and approval.signature.startswith("cryptographic-"),
        trust_resolver=lambda approval: approval.principal_id if approval.principal_id.startswith("human-") else None,
    )


def valid_release():
    q = qualification()
    p = proposal(q)
    approvals = (
        approval(p, q, "human-one", "key-one"),
        approval(p, q, "human-two", "key-two"),
    )
    return q, p, approvals


def test_successful_release_is_production_ready_but_live_stays_default_off() -> None:
    q, p, approvals = valid_release()
    decision = gate().evaluate(q, p, approvals, now_ns=NOW)
    assert decision.allowed is True
    assert decision.state is ReleaseState.RELEASED_PRODUCTION_DEFAULT_OFF
    assert decision.production_ready is True
    assert decision.release_claim_allowed is True
    assert decision.product_state == "production-ready-default-off"
    assert decision.live_enabled is False
    assert decision.unrestricted_live_allowed is False
    assert decision.automatic_scale_up_allowed is False


def test_t2612_001_digest_only_forgery_cannot_release() -> None:
    q, p, approvals = valid_release()
    forged = tuple(
        ReleaseApproval(**(asdict(item) | {"signature": D})) for item in approvals
    )
    decision = gate().evaluate(q, p, forged, now_ns=NOW)
    assert decision.allowed is False
    assert "BLOCKED_SIGNATURE_AUTHENTICITY" in decision.reason_codes


def test_same_human_or_same_public_key_cannot_satisfy_two_human_review() -> None:
    q = qualification()
    p = proposal(q)
    same_human = (
        approval(p, q, "human-one", "key-one"),
        approval(p, q, "human-one", "key-two"),
    )
    assert "BLOCKED_DISTINCT_HUMAN_REVIEW" in gate().evaluate(q, p, same_human, now_ns=NOW).reason_codes
    same_key = (
        approval(p, q, "human-one", "key-one"),
        approval(p, q, "human-two", "key-one"),
    )
    assert "BLOCKED_DISTINCT_HUMAN_REVIEW" in gate().evaluate(q, p, same_key, now_ns=NOW).reason_codes


def test_bot_or_untrusted_reviewer_does_not_count_as_human() -> None:
    q = qualification()
    p = proposal(q)
    approvals = (
        approval(p, q, "human-one", "key-one"),
        approval(p, q, "ci-bot", "key-two"),
    )
    decision = gate().evaluate(q, p, approvals, now_ns=NOW)
    assert decision.allowed is False
    assert "BLOCKED_REVIEWER_IDENTITY" in decision.reason_codes
    assert "BLOCKED_HUMAN_APPROVALS" in decision.reason_codes


def test_qualification_for_release_a_cannot_release_b() -> None:
    q = qualification()
    p = proposal(q, release_id="release-B")
    approvals = (
        approval(p, q, "human-one", "key-one"),
        approval(p, q, "human-two", "key-two"),
    )
    decision = gate().evaluate(q, p, approvals, now_ns=NOW)
    assert "BLOCKED_RELEASE_ID_MISMATCH" in decision.reason_codes


def test_artifact_or_policy_mutation_after_qualification_blocks() -> None:
    q = qualification()
    p = proposal(q, runtime_image_digest=D2, policy_generation_digest=D3)
    approvals = (
        approval(p, q, "human-one", "key-one"),
        approval(p, q, "human-two", "key-two"),
    )
    decision = gate().evaluate(q, p, approvals, now_ns=NOW)
    assert "BLOCKED_RUNTIME_IMAGE_MISMATCH" in decision.reason_codes
    assert "BLOCKED_POLICY_GENERATION_MISMATCH" in decision.reason_codes


def test_stale_or_wrong_proposal_approval_fails_closed() -> None:
    q = qualification()
    p = proposal(q)
    bad = (
        approval(p, q, "human-one", "key-one", expires_at_ns=NOW),
        approval(p, q, "human-two", "key-two", proposal_digest=D2),
    )
    decision = gate().evaluate(q, p, bad, now_ns=NOW)
    assert "BLOCKED_APPROVAL_EXPIRED" in decision.reason_codes
    assert "BLOCKED_APPROVAL_WRONG_PROPOSAL" in decision.reason_codes


def test_qualification_cannot_self_grant_release_or_live() -> None:
    q = qualification(release_claim_allowed=True, live_enabled=True)
    p = proposal(q)
    approvals = (
        approval(p, q, "human-one", "key-one"),
        approval(p, q, "human-two", "key-two"),
    )
    decision = gate().evaluate(q, p, approvals, now_ns=NOW)
    assert "BLOCKED_QUALIFICATION_PRIVILEGE_ESCALATION" in decision.reason_codes


def test_proposal_cannot_request_live_unlimited_or_auto_scale() -> None:
    q = qualification()
    p = proposal(q, live_enabled=True, unrestricted_live_allowed=True, automatic_scale_up_allowed=True)
    approvals = (
        approval(p, q, "human-one", "key-one"),
        approval(p, q, "human-two", "key-two"),
    )
    decision = gate().evaluate(q, p, approvals, now_ns=NOW)
    assert decision.allowed is False
    assert "BLOCKED_AUTOMATIC_LIVE_REQUEST" in decision.reason_codes


def test_hard_safety_latch_blocks_release() -> None:
    q, p, approvals = valid_release()
    decision = gate().evaluate(q, p, approvals, now_ns=NOW, hard_safety_latch_active=True)
    assert decision.allowed is False
    assert "BLOCKED_HARD_SAFETY_LATCH" in decision.reason_codes


def test_historical_mpr31_structural_gate_is_no_longer_release_authority() -> None:
    artifact = SignedEvidenceArtifact(
        kind="artifact-truth", digest=D, signature_digest=D,
        reviewer_digests=(D2,), issued_at_ns=1, expires_at_ns=2_000_000,
        size_bytes=1, immutable_uri="memory://fake",
    )
    upstream = tuple(
        UpstreamMprEvidence(mpr, SignedEvidenceArtifact(
            kind=kind, digest=D, signature_digest=D, reviewer_digests=(D2,),
            issued_at_ns=1, expires_at_ns=2_000_000, size_bytes=1,
            immutable_uri="memory://fake",
        ))
        for mpr, kind in {
            "MPR-25": "artifact-truth",
            "MPR-26": "durable-authority",
            "MPR-27": "rooted-provider-plane",
            "MPR-28": "exact-economic-execution",
            "MPR-29": "continuous-paper-shadow-soak",
            "MPR-30": "cryptographic-submission-boundary",
        }.items()
    )
    bundle = FinalPromotionBundle(
        source_digest=D, wheel_digest=D, image_digest=D, config_digest=D, policy_digest=D,
        upstream_mprs=upstream,
        treasury=RootedTreasuryEvidence(D, D, D, D, 0, 0, 0, False),
        archive=ImmutableArchiveEvidence(D, D, D, D, D, True),
        operator_command=OperatorCommandEvidence(D, D, D, D, D, 1, 2_000_000),
        canary=TinyCanaryProposal(1, 1, D, True, False),
        now_ns=NOW,
    )
    decision = MPR31FinalPromotionGate().evaluate(bundle)
    assert decision.status is PromotionStatus.BLOCKED
    assert decision.ready is False
    assert decision.canary_authorized_default_off is False
    assert "MPR2612_CANONICAL_RELEASE_GATE_REQUIRED" in decision.reason_codes
    assert artifact.signature_digest == D

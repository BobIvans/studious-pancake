from __future__ import annotations

import pytest

from src.release_gate.mpr31_final_promotion_gate import (
    ALLOWED_DEPENDENCY_KINDS,
    FinalPromotionBundle,
    ImmutableArchiveEvidence,
    MPR31Error,
    MPR31FinalPromotionGate,
    OperatorCommandEvidence,
    PromotionStatus,
    REQUIRED_UPSTREAM_MPRS,
    RootedTreasuryEvidence,
    SignedEvidenceArtifact,
    TinyCanaryProposal,
    UpstreamMprEvidence,
)

DIGEST = "a" * 64
SIG = "b" * 64
REVIEWER_1 = "c" * 64
REVIEWER_2 = "d" * 64
NOW_NS = 1_000_000

_KIND_BY_MPR = {
    "MPR-25": "artifact-truth",
    "MPR-26": "durable-authority",
    "MPR-27": "rooted-provider-plane",
    "MPR-28": "exact-economic-execution",
    "MPR-29": "continuous-paper-shadow-soak",
    "MPR-30": "cryptographic-submission-boundary",
}


def artifact(kind: str, *, issued_at_ns: int = 1, expires_at_ns: int = 2_000_000) -> SignedEvidenceArtifact:
    return SignedEvidenceArtifact(
        kind=kind,
        digest=DIGEST,
        signature_digest=SIG,
        reviewer_digests=(REVIEWER_1, REVIEWER_2),
        issued_at_ns=issued_at_ns,
        expires_at_ns=expires_at_ns,
        size_bytes=128,
        immutable_uri="s3://immutable-release-evidence/mpr31.json",
    )


def upstream() -> tuple[UpstreamMprEvidence, ...]:
    return tuple(
        UpstreamMprEvidence(mpr_id=mpr_id, artifact=artifact(kind))
        for mpr_id, kind in _KIND_BY_MPR.items()
    )


def valid_bundle(**overrides: object) -> FinalPromotionBundle:
    data: dict[str, object] = {
        "source_digest": DIGEST,
        "wheel_digest": DIGEST,
        "image_digest": DIGEST,
        "config_digest": DIGEST,
        "policy_digest": DIGEST,
        "upstream_mprs": upstream(),
        "treasury": RootedTreasuryEvidence(
            wallet_balance_root_digest=DIGEST,
            token_inventory_root_digest=DIGEST,
            provider_quorum_digest=DIGEST,
            policy_generation_digest=DIGEST,
            unresolved_exposure_lamports=0,
            rolling_loss_lamports=0,
            daily_loss_lamports=0,
            hard_latch_active=False,
        ),
        "archive": ImmutableArchiveEvidence(
            exported_segment_digest=DIGEST,
            remote_receipt_quorum_digest=DIGEST,
            immutable_object_digest=DIGEST,
            signed_head_digest=DIGEST,
            retention_policy_digest=DIGEST,
            replay_verified=True,
        ),
        "operator_command": OperatorCommandEvidence(
            principal_digest=DIGEST,
            role_session_digest=DIGEST,
            command_digest=DIGEST,
            command_signature_digest=DIGEST,
            mfa_freshness_digest=DIGEST,
            not_before_ns=1,
            expires_at_ns=2_000_000,
        ),
        "canary": TinyCanaryProposal(
            manual_transaction_count=1,
            max_canary_loss_lamports=10,
            rollback_plan_digest=DIGEST,
            post_canary_review_required=True,
            live_expansion_requested=False,
        ),
        "now_ns": NOW_NS,
        "live_runtime_requested": False,
    }
    data.update(overrides)
    return FinalPromotionBundle(**data)


def test_ready_bundle_only_authorizes_default_off_one_manual_canary() -> None:
    decision = MPR31FinalPromotionGate().evaluate(valid_bundle())

    assert decision.status is PromotionStatus.READY_DEFAULT_OFF
    assert decision.ready
    assert decision.canary_authorized_default_off
    assert decision.reason_codes == ("MPR31_READY_FOR_ONE_MANUAL_CANARY_DEFAULT_OFF",)
    assert len(decision.bundle_hash) == 64


def test_missing_mpr25_to_mpr30_blocks_promotion() -> None:
    decision = MPR31FinalPromotionGate().evaluate(valid_bundle(upstream_mprs=()))

    assert decision.status is PromotionStatus.BLOCKED
    assert not decision.canary_authorized_default_off
    assert {f"MPR31_MISSING_UPSTREAM:{mpr}" for mpr in REQUIRED_UPSTREAM_MPRS} <= set(decision.reason_codes)


def test_upstream_evidence_must_be_fresh_and_not_future_dated() -> None:
    expired = UpstreamMprEvidence("MPR-25", artifact("artifact-truth", expires_at_ns=NOW_NS))
    future = UpstreamMprEvidence("MPR-26", artifact("durable-authority", issued_at_ns=NOW_NS + 1))
    remaining = tuple(item for item in upstream() if item.mpr_id not in {"MPR-25", "MPR-26"})

    decision = MPR31FinalPromotionGate().evaluate(valid_bundle(upstream_mprs=(expired, future, *remaining)))

    assert "MPR31_UPSTREAM_EXPIRED:MPR-25" in decision.reason_codes
    assert "MPR31_UPSTREAM_NOT_YET_VALID:MPR-26" in decision.reason_codes
    assert decision.status is PromotionStatus.BLOCKED


def test_unsigned_or_self_declared_evidence_is_rejected_at_constructor() -> None:
    with pytest.raises(MPR31Error, match="signature_digest"):
        SignedEvidenceArtifact(
            kind="artifact-truth",
            digest=DIGEST,
            signature_digest="not-a-digest",
            reviewer_digests=(REVIEWER_1,),
            issued_at_ns=1,
            expires_at_ns=2,
            size_bytes=1,
            immutable_uri="s3://immutable/evidence.json",
        )
    with pytest.raises(MPR31Error, match="MPR31_DUPLICATE_REVIEWER_DIGEST"):
        SignedEvidenceArtifact(
            kind="artifact-truth",
            digest=DIGEST,
            signature_digest=SIG,
            reviewer_digests=(REVIEWER_1, REVIEWER_1),
            issued_at_ns=1,
            expires_at_ns=2,
            size_bytes=1,
            immutable_uri="s3://immutable/evidence.json",
        )


def test_treasury_loss_exposure_and_latch_block_promotion() -> None:
    treasury = RootedTreasuryEvidence(
        wallet_balance_root_digest=DIGEST,
        token_inventory_root_digest=DIGEST,
        provider_quorum_digest=DIGEST,
        policy_generation_digest=DIGEST,
        unresolved_exposure_lamports=1,
        rolling_loss_lamports=11,
        daily_loss_lamports=12,
        hard_latch_active=True,
    )
    decision = MPR31FinalPromotionGate().evaluate(valid_bundle(treasury=treasury))

    assert {
        "MPR31_HARD_LATCH_ACTIVE",
        "MPR31_UNRESOLVED_EXPOSURE",
        "MPR31_DAILY_LOSS_EXCEEDS_CANARY_LIMIT",
        "MPR31_ROLLING_LOSS_EXCEEDS_CANARY_LIMIT",
    } <= set(decision.reason_codes)
    assert decision.status is PromotionStatus.BLOCKED


def test_archive_replay_must_be_verified_from_immutable_receipts() -> None:
    archive = ImmutableArchiveEvidence(
        exported_segment_digest=DIGEST,
        remote_receipt_quorum_digest=DIGEST,
        immutable_object_digest=DIGEST,
        signed_head_digest=DIGEST,
        retention_policy_digest=DIGEST,
        replay_verified=False,
    )

    decision = MPR31FinalPromotionGate().evaluate(valid_bundle(archive=archive))

    assert decision.status is PromotionStatus.BLOCKED
    assert "MPR31_ARCHIVE_REPLAY_NOT_VERIFIED" in decision.reason_codes


def test_operator_command_window_is_enforced() -> None:
    future_command = OperatorCommandEvidence(
        principal_digest=DIGEST,
        role_session_digest=DIGEST,
        command_digest=DIGEST,
        command_signature_digest=DIGEST,
        mfa_freshness_digest=DIGEST,
        not_before_ns=NOW_NS + 1,
        expires_at_ns=NOW_NS + 100,
    )
    expired_command = OperatorCommandEvidence(
        principal_digest=DIGEST,
        role_session_digest=DIGEST,
        command_digest=DIGEST,
        command_signature_digest=DIGEST,
        mfa_freshness_digest=DIGEST,
        not_before_ns=1,
        expires_at_ns=NOW_NS,
    )

    assert "MPR31_OPERATOR_COMMAND_NOT_YET_VALID" in MPR31FinalPromotionGate().evaluate(
        valid_bundle(operator_command=future_command)
    ).reason_codes
    assert "MPR31_OPERATOR_COMMAND_EXPIRED" in MPR31FinalPromotionGate().evaluate(
        valid_bundle(operator_command=expired_command)
    ).reason_codes


def test_canary_expansion_and_multiple_transactions_are_forbidden() -> None:
    canary = TinyCanaryProposal(
        manual_transaction_count=2,
        max_canary_loss_lamports=10,
        rollback_plan_digest=DIGEST,
        post_canary_review_required=False,
        live_expansion_requested=True,
    )
    decision = MPR31FinalPromotionGate().evaluate(valid_bundle(canary=canary))

    assert decision.status is PromotionStatus.BLOCKED
    assert {
        "MPR31_CANARY_EXPANSION_FORBIDDEN",
        "MPR31_CANARY_MUST_BE_ONE_MANUAL_TRANSACTION",
        "MPR31_POST_CANARY_REVIEW_REQUIRED",
    } <= set(decision.reason_codes)


def test_live_runtime_requested_blocks_even_valid_evidence() -> None:
    decision = MPR31FinalPromotionGate().evaluate(valid_bundle(live_runtime_requested=True))

    assert decision.status is PromotionStatus.BLOCKED
    assert "MPR31_LIVE_RUNTIME_MUST_REMAIN_DEFAULT_OFF" in decision.reason_codes


def test_unknown_dependency_kind_and_mpr_are_rejected() -> None:
    assert "artifact-truth" in ALLOWED_DEPENDENCY_KINDS
    with pytest.raises(MPR31Error, match="MPR31_UNKNOWN_UPSTREAM_MPR"):
        UpstreamMprEvidence("MPR-99", artifact("artifact-truth"))
    with pytest.raises(MPR31Error, match="MPR31_UNKNOWN_UPSTREAM_EVIDENCE_KIND"):
        UpstreamMprEvidence("MPR-25", artifact("caller-declared-claim"))


def test_bool_is_not_accepted_as_integer_identity() -> None:
    with pytest.raises(MPR31Error, match="manual_transaction_count"):
        TinyCanaryProposal(
            manual_transaction_count=True,
            max_canary_loss_lamports=10,
            rollback_plan_digest=DIGEST,
            post_canary_review_required=True,
            live_expansion_requested=False,
        )

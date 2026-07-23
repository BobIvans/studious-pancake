from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from src.new_mega_pr05_live_canary_boundary import (
    AuthenticatedPermit,
    BoundaryState,
    CanaryBudget,
    CanaryUsage,
    DurablePermitAuthority,
    FinalizedSettlementEvidence,
    IsolatedSigner,
    MessageAuthorization,
    PermitRequest,
    ReviewerKey,
    SettlementStatus,
    SubmissionIntent,
    TipEvidence,
    Transport,
    assert_blockheight_allows_consumption,
    evaluate_canary_latches,
    make_authenticated_permit,
    reconcile_finalized_settlement,
    sample_ready_flow,
    validate_permit,
    validate_submission_identity,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
MESSAGE = b"exact-final-simulated-versioned-message"
MESSAGE_HASH = hashlib.sha256(MESSAGE).hexdigest()


def _issuer() -> ReviewerKey:
    return ReviewerKey("issuer-key", "issuer-secret", "issuer")


def _reviewer() -> ReviewerKey:
    return ReviewerKey("reviewer-key", "reviewer-secret", "reviewer")


def _authorization() -> MessageAuthorization:
    return MessageAuthorization(
        attempt_id="attempt-1",
        attempt_generation=1,
        wallet="wallet-a",
        market="SOL/USDC",
        asset="SOL",
        exact_message_hash=MESSAGE_HASH,
        final_simulation_hash=DIGEST_A,
        policy_hash=DIGEST_B,
        evidence_bundle_hash=DIGEST_C,
        selected_transport=Transport.JITO,
        tip_lamports=1_000,
        last_valid_block_height=10_000,
        safety_margin_blocks=100,
    )


def _request(authorization: MessageAuthorization | None = None) -> PermitRequest:
    authorization = authorization or _authorization()
    return PermitRequest(
        nonce="nonce-1",
        attempt_id=authorization.attempt_id,
        attempt_generation=authorization.attempt_generation,
        wallet=authorization.wallet,
        market=authorization.market,
        asset=authorization.asset,
        exact_message_hash=authorization.exact_message_hash,
        transport=authorization.selected_transport,
        tip_lamports=authorization.tip_lamports,
        evidence_bundle_hash=authorization.evidence_bundle_hash,
        issued_at_unix_ns=100,
        expires_at_unix_ns=1_000,
        policy_hash=authorization.policy_hash,
        session_hash=DIGEST_A,
        reviewer_set_hash=DIGEST_B,
    )


def _permit(authorization: MessageAuthorization | None = None) -> AuthenticatedPermit:
    return make_authenticated_permit(request=_request(authorization), issuer=_issuer(), reviewer=_reviewer())


def test_sample_ready_flow_keeps_unrestricted_live_disabled() -> None:
    payload = sample_ready_flow()

    assert payload["schema_version"] == "new-mega-pr05.live-canary-boundary.v1"
    assert payload["permit_state"] == BoundaryState.READY_FOR_BOUNDED_CANARY_REVIEW.value
    assert payload["reconciliation_state"] == BoundaryState.READY_FOR_BOUNDED_CANARY_REVIEW.value
    assert payload["canary_state"] == BoundaryState.READY_FOR_BOUNDED_CANARY_REVIEW.value
    assert payload["unrestricted_live_allowed"] is False
    assert payload["finalized_settlement"] is True
    assert payload["manual_review_required"] is False


def test_isolated_signer_rejects_one_byte_message_drift() -> None:
    signer = IsolatedSigner(signer_id="signer-1", signer_secret="secret", public_key="pubkey")

    with pytest.raises(ValueError, match="PR05_SIGNER_MESSAGE_HASH_MISMATCH"):
        signer.sign_authorized_message(
            authorization=_authorization(),
            exact_message_bytes=MESSAGE + b"!",
            current_block_height=9_700,
        )


def test_permit_requires_independent_authenticated_second_reviewer() -> None:
    authorization = _authorization()
    permit = _permit(authorization)
    forged = AuthenticatedPermit(
        request=permit.request,
        issuer_key_id=permit.issuer_key_id,
        issuer_signature=permit.issuer_signature,
        reviewer_key_id=permit.reviewer_key_id,
        reviewer_signature="0" * 64,
    )

    report = validate_permit(
        permit=forged,
        authorization=authorization,
        keyring={_issuer().key_id: _issuer(), _reviewer().key_id: _reviewer()},
        trusted_now_unix_ns=500,
        current_evidence_bundle_hash=authorization.evidence_bundle_hash,
    )

    assert report.state is BoundaryState.BLOCKED
    assert {item.code for item in report.blockers} == {"PR05_BAD_REVIEWER_SIGNATURE"}


def test_future_or_expired_permit_is_rejected() -> None:
    authorization = _authorization()
    permit = _permit(authorization)

    report = validate_permit(
        permit=permit,
        authorization=authorization,
        keyring={_issuer().key_id: _issuer(), _reviewer().key_id: _reviewer()},
        trusted_now_unix_ns=1_000,
        current_evidence_bundle_hash=authorization.evidence_bundle_hash,
    )

    assert report.state is BoundaryState.BLOCKED
    assert "PR05_PERMIT_TIME_INVALID" in {item.code for item in report.blockers}


def test_durable_permit_authority_allows_one_issue_and_one_consumption(tmp_path) -> None:
    authority = DurablePermitAuthority(tmp_path / "permits.sqlite3")
    permit = _permit()

    assert authority.issue_once(permit) is True
    assert authority.issue_once(permit) is False
    assert authority.consume_once(permit, now_unix_ns=500) is True
    assert authority.consume_once(permit, now_unix_ns=501) is False


def test_current_blockheight_margin_is_mandatory() -> None:
    with pytest.raises(ValueError, match="PR05_BLOCKHASH_EXPIRED_OR_TOO_CLOSE"):
        assert_blockheight_allows_consumption(
            authorization=_authorization(),
            current_block_height=9_950,
        )


def test_tip_and_transport_must_be_derived_from_signed_wire() -> None:
    authorization = _authorization()
    permit = _permit(authorization)
    signer = IsolatedSigner(signer_id="signer-1", signer_secret="secret", public_key="pubkey")
    signed = signer.sign_authorized_message(
        authorization=authorization,
        exact_message_bytes=MESSAGE,
        current_block_height=9_700,
    )
    wrong_tip = TipEvidence(
        source="signed_wire",
        signed_wire_hash=signed.signed_wire_hash,
        transport=Transport.RPC,
        tip_lamports=signed.tip_lamports + 1,
    )

    blockers = validate_submission_identity(
        permit=permit,
        authorization=authorization,
        signed_wire=signed,
        tip_evidence=wrong_tip,
    )

    assert {item.code for item in blockers} == {"PR05_TIP_TRANSPORT_MISMATCH", "PR05_TIP_AMOUNT_MISMATCH"}


def test_ack_or_unknown_outcome_goes_to_manual_review_not_resend() -> None:
    intent = SubmissionIntent(
        permit_hash=_permit().permit_hash,
        attempt_id="attempt-1",
        attempt_generation=1,
        exact_message_hash=MESSAGE_HASH,
        signed_wire_hash=DIGEST_A,
        selected_transport=Transport.JITO,
        tip_lamports=1_000,
        status=SettlementStatus.TRANSPORT_ACK,
        ack_or_bundle_id="bundle-id-is-transport-only",
    )
    settlement = FinalizedSettlementEvidence(
        status=SettlementStatus.TRANSPORT_ACK,
        signature_hash=DIGEST_B,
        finalized_slot=None,
        exact_message_hash=MESSAGE_HASH,
        signed_wire_hash=DIGEST_A,
        instruction_hash=DIGEST_C,
        fee_lamports=5_000,
        payer_delta_lamports=0,
        token_delta_hash=DIGEST_C,
        realized_pnl_lamports=None,
        selected_transport=Transport.JITO,
        tip_lamports=1_000,
    )

    report = reconcile_finalized_settlement(intent=intent, settlement=settlement)

    assert report.state is BoundaryState.MANUAL_REVIEW
    assert report.finalized_settlement is False
    assert report.realized_pnl_lamports is None
    assert "PR05_ACK_OR_UNKNOWN_NOT_FINAL" in {item.code for item in report.blockers}


def test_finalized_settlement_binds_message_wire_transport_tip_and_realized_pnl() -> None:
    intent = SubmissionIntent(
        permit_hash=_permit().permit_hash,
        attempt_id="attempt-1",
        attempt_generation=1,
        exact_message_hash=MESSAGE_HASH,
        signed_wire_hash=DIGEST_A,
        selected_transport=Transport.RPC,
        tip_lamports=500,
        status=SettlementStatus.LANDED,
    )
    settlement = FinalizedSettlementEvidence(
        status=SettlementStatus.FINALIZED,
        signature_hash=DIGEST_B,
        finalized_slot=123,
        exact_message_hash=MESSAGE_HASH,
        signed_wire_hash=DIGEST_A,
        instruction_hash=DIGEST_C,
        fee_lamports=5_000,
        payer_delta_lamports=30_000,
        token_delta_hash=DIGEST_C,
        realized_pnl_lamports=25_000,
        selected_transport=Transport.RPC,
        tip_lamports=500,
    )

    report = reconcile_finalized_settlement(intent=intent, settlement=settlement)

    assert report.state is BoundaryState.READY_FOR_BOUNDED_CANARY_REVIEW
    assert report.finalized_settlement is True
    assert report.realized_pnl_lamports == 25_000


def test_canary_latches_block_budget_overrun_and_missing_second_reviewer() -> None:
    budget = CanaryBudget(
        wallet="wallet-a",
        market="SOL/USDC",
        asset="SOL",
        max_count=1,
        max_notional_lamports=100,
        max_tip_lamports=10,
        max_daily_loss_lamports=5,
        max_total_loss_lamports=7,
        not_before_unix_ns=100,
        not_after_unix_ns=1_000,
        evidence_bundle_hash=DIGEST_C,
    )
    usage = CanaryUsage(
        count=2,
        notional_lamports=101,
        tip_lamports=11,
        daily_loss_lamports=6,
        total_loss_lamports=8,
    )

    report = evaluate_canary_latches(
        budget=budget,
        usage=usage,
        trusted_now_unix_ns=500,
        second_reviewer_present=False,
        evidence_bundle_hash=DIGEST_C,
    )

    codes = {item.code for item in report.blockers}
    assert report.kill_latch_triggered is True
    assert "PR05_SECOND_REVIEWER_REQUIRED" in codes
    assert "PR05_CANARY_COUNT_LATCH" in codes
    assert "PR05_CANARY_NOTIONAL_LATCH" in codes
    assert "PR05_CANARY_TIP_LATCH" in codes
    assert "PR05_CANARY_DAILY_LOSS_LATCH" in codes
    assert "PR05_CANARY_TOTAL_LOSS_LATCH" in codes


def test_resend_generation_requires_archive_complete_absence_proof() -> None:
    authorization = replace(_authorization(), attempt_generation=2)
    request = _request(authorization)
    permit = make_authenticated_permit(request=request, issuer=_issuer(), reviewer=_reviewer())

    report = validate_permit(
        permit=permit,
        authorization=authorization,
        keyring={_issuer().key_id: _issuer(), _reviewer().key_id: _reviewer()},
        trusted_now_unix_ns=500,
        current_evidence_bundle_hash=authorization.evidence_bundle_hash,
    )

    assert report.state is BoundaryState.BLOCKED
    assert "PR05_RESEND_PROOF_REQUIRED" in {item.code for item in report.blockers}

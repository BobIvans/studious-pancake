from __future__ import annotations

from dataclasses import replace

from src.pr223_cryptographic_trust_settlement_gate import (
    PR223ApprovalEnvelope,
    PR223Evidence,
    PR223State,
    REQUIRED_FINDINGS,
    evaluate_pr223_evidence,
)


HEX = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
HEX_D = "d" * 64
HEX_E = "e" * 64
HEX_F = "f" * 64


def _approval(principal_id: str, envelope_hash: str) -> PR223ApprovalEnvelope:
    return PR223ApprovalEnvelope(
        principal_id=principal_id,
        role="approver",
        envelope_hash=envelope_hash,
        authorization_hash=HEX_B,
        issued_at_ns=100,
        expires_at_ns=1_000,
        fresh_trusted_time=True,
        independent=True,
    )


def _evidence() -> PR223Evidence:
    return PR223Evidence(
        release_artifact_hash=HEX,
        trust_bundle_hash=HEX_B,
        signer_policy_hash=HEX_C,
        authorization_schema_hash=HEX_D,
        settlement_schema_hash=HEX_E,
        archive_policy_hash=HEX_F,
        findings_covered=REQUIRED_FINDINGS,
        real_ed25519_verification=True,
        canonical_serialization=True,
        schema_domain_separated=True,
        key_rotation_supported=True,
        key_revocation_supported=True,
        not_before_enforced=True,
        exact_message_digest_bound=True,
        wallet_release_provider_market_bound=True,
        nonce_consumed_durably=True,
        authorization_issued_at_ns=100,
        authorization_not_before_ns=100,
        authorization_expires_at_ns=1_000,
        evaluation_time_ns=500,
        permit_consumed_with_intent=True,
        intent_outbox_atomic=True,
        dispatched_before_handoff=True,
        provider_idempotency_bound=True,
        unknown_reconciliation_owner=True,
        transport_payload_digest_match=True,
        min_context_slot_bound=True,
        blockhash_bound=True,
        ack_not_landing=True,
        bundle_id_not_landing=True,
        finalized_get_transaction_required=True,
        finalized_identity_matches_intent=True,
        fee_balance_token_deltas_materialized=True,
        archive_receipt_worm=True,
        archive_receipt_bytes_rehashed=True,
        archive_receipt_revision_immutable=True,
        aggregate_budget_verified=True,
        rollback_proof_bound=True,
        dual_approvals=(
            _approval("alice", HEX),
            _approval("bob", HEX_C),
        ),
    )


def test_pr223_happy_path_is_ready_but_still_sender_free() -> None:
    report = evaluate_pr223_evidence(_evidence())

    assert report.schema_version == "pr223.cryptographic-trust-signer-settlement.v1"
    assert report.state is PR223State.READY_FOR_PR223_FOUNDATION
    assert report.blockers == ()
    assert report.signer_allowed is False
    assert report.sender_allowed is False
    assert report.live_execution_allowed is False
    assert len(report.evidence_hash) == 64


def test_pr223_missing_findings_block_foundation() -> None:
    report = evaluate_pr223_evidence(replace(_evidence(), findings_covered=("F-025",)))

    assert report.state is PR223State.BLOCKED
    assert any(item.code == "PR223_FINDINGS_INCOMPLETE" for item in report.blockers)


def test_pr223_future_or_expired_authorization_is_rejected() -> None:
    future = evaluate_pr223_evidence(
        replace(_evidence(), authorization_issued_at_ns=900, evaluation_time_ns=500)
    )
    expired = evaluate_pr223_evidence(
        replace(_evidence(), authorization_expires_at_ns=400, evaluation_time_ns=500)
    )

    assert any(item.code == "PR223_FUTURE_AUTHORIZATION" for item in future.blockers)
    assert any(item.code == "PR223_AUTHORIZATION_EXPIRED" for item in expired.blockers)



def test_pr223_runtime_must_not_have_private_key_or_live_sender() -> None:
    report = evaluate_pr223_evidence(
        replace(
            _evidence(),
            runtime_private_key_access=True,
            sender_requested=True,
            live_execution_requested=True,
        )
    )

    codes = {item.code for item in report.blockers}
    assert "PR223_PRIVATE_KEY_EXPOSED" in codes
    assert "PR223_SENDER_REQUESTED" in codes
    assert "PR223_LIVE_REQUESTED" in codes



def test_pr223_dispatch_must_remain_atomic() -> None:
    report = evaluate_pr223_evidence(
        replace(
            _evidence(),
            permit_consumed_with_intent=False,
            intent_outbox_atomic=False,
            unknown_reconciliation_owner=False,
        )
    )

    assert report.state is PR223State.BLOCKED
    assert any(item.code == "PR223_DISPATCH_NOT_ATOMIC" for item in report.blockers)



def test_pr223_transport_ack_or_bundle_id_cannot_count_as_landing() -> None:
    report = evaluate_pr223_evidence(
        replace(_evidence(), ack_not_landing=False, bundle_id_not_landing=False)
    )

    assert report.state is PR223State.BLOCKED
    assert any(
        item.code == "PR223_TRANSPORT_BINDING_INCOMPLETE" for item in report.blockers
    )



def test_pr223_finalized_transaction_is_required_for_settlement() -> None:
    report = evaluate_pr223_evidence(
        replace(
            _evidence(),
            finalized_get_transaction_required=False,
            finalized_identity_matches_intent=False,
        )
    )

    assert report.state is PR223State.BLOCKED
    assert any(
        item.code == "PR223_FINALITY_NOT_AUTHORITATIVE" for item in report.blockers
    )



def test_pr223_archive_receipt_must_be_immutable_and_rehashed() -> None:
    report = evaluate_pr223_evidence(
        replace(
            _evidence(),
            archive_receipt_worm=False,
            archive_receipt_bytes_rehashed=False,
            archive_receipt_revision_immutable=False,
        )
    )

    assert report.state is PR223State.BLOCKED
    assert any(item.code == "PR223_ARCHIVE_NOT_IMMUTABLE" for item in report.blockers)



def test_pr223_dual_approval_requires_two_distinct_fresh_principals() -> None:
    report = evaluate_pr223_evidence(
        replace(
            _evidence(),
            dual_approvals=(
                _approval("alice", HEX),
                _approval("alice", HEX_B),
            ),
        )
    )

    assert report.state is PR223State.BLOCKED
    assert any(
        item.code == "PR223_DUAL_APPROVAL_NOT_DISTINCT" for item in report.blockers
    )

from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

from src.pr211_signer_outbox_finality_gate import (
    PR211Blocker,
    PR211EvidenceError,
    ApprovalSignatureEvidence,
    DurableOutboxEvidence,
    FinalizedSettlementEvidence,
    PR211SignerOutboxFinalityEvidence,
    SCHEMA_VERSION,
    SignatureVerificationEvidence,
    SignedPayloadAuthorization,
    evaluate_pr211_signer_outbox_finality,
)


def h(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def complete_evidence() -> PR211SignerOutboxFinalityEvidence:
    message = h("exact-message")
    intent = h("intent")
    transport = h("transport")
    sig = h("signature")
    verification = SignatureVerificationEvidence(
        exact_message_sha256=message,
        signature_verifier_sha256=h("verifier"),
        signer_public_key_hashes=(h("signer-a"),),
        signature_sha256s=(sig,),
        all_signatures_verified=True,
    )
    signed = SignedPayloadAuthorization(
        request_id="permit-211",
        authorization_sha256=h("authorization"),
        exact_message_sha256=message,
        not_before_block_height=100,
        requested_block_height=110,
        signed_at_block_height=120,
        expires_at_block_height=200,
        current_block_height=130,
        safety_margin_blocks=20,
        signature_verification=verification,
    )
    approval = ApprovalSignatureEvidence(
        approval_payload_sha256=h("approval-payload"),
        release_set_sha256=h("release"),
        policy_bundle_sha256=h("policy"),
        canary_limits_sha256=h("limits"),
        required_threshold=2,
        verified_signature_count=2,
        distinct_approver_principal_hashes=(h("approver-a"), h("approver-b")),
        approver_role_hashes=(h("reviewer"), h("risk")),
        threshold_signatures_verified=True,
        not_before_ms=1_000,
        expires_at_ms=10_000,
        evaluated_at_ms=2_000,
    )
    outbox = DurableOutboxEvidence(
        permit_consumed_and_intent_created_in_one_transaction=True,
        immutable_intent_sha256=intent,
        exact_message_sha256=message,
        selected_transport_sha256=transport,
        outbox_row_sha256=h("outbox"),
        outbox_claim_fenced=True,
        dispatcher_received_only_opaque_intent_id=True,
        response_recorded_idempotently=True,
        finality_reconciled_idempotently=True,
        blind_resend_possible=False,
        crash_before_send_reconciled=True,
        crash_after_send_before_ack_reconciled=True,
        late_landing_freezes_descendants=True,
    )
    settlement = FinalizedSettlementEvidence(
        intent_sha256=intent,
        exact_message_sha256=message,
        signature_sha256=sig,
        selected_transport_sha256=transport,
        genesis_hash_sha256=h("genesis"),
        commitment="finalized",
        intent_min_context_slot=500,
        compile_context_slot=501,
        simulation_context_slot=502,
        send_context_slot=503,
        landed_slot=504,
        raw_get_transaction_sha256=h("raw-get-transaction"),
        transaction_meta_sha256=h("meta"),
        pre_balances_sha256=h("pre-balances"),
        post_balances_sha256=h("post-balances"),
        token_balance_delta_sha256=h("token-delta"),
        landed=True,
        finalized=True,
        transaction_err=None,
        charged_fee_lamports=5_000,
        fee_from_get_transaction_meta=True,
    )
    return PR211SignerOutboxFinalityEvidence(
        pr210_evidence_accepted=True,
        pr210_report_sha256=h("pr210"),
        release_set_sha256=h("release"),
        signed_payload=signed,
        approval=approval,
        outbox=outbox,
        settlement=settlement,
    )


def blockers(report) -> set[str]:
    return set(report.blockers)


def test_complete_evidence_is_ready_but_does_not_enable_live_or_sender() -> None:
    report = evaluate_pr211_signer_outbox_finality(complete_evidence())

    assert report.schema_version == SCHEMA_VERSION
    assert report.ready
    assert report.blockers == ()
    assert report.live_execution_allowed is False
    assert report.signer_import_allowed is False
    assert report.sender_import_allowed is False
    assert len(report.evidence_hash) == 64


def test_signed_payload_after_expiry_is_blocked() -> None:
    evidence = complete_evidence()
    signed = replace(evidence.signed_payload, signed_at_block_height=220)

    report = evaluate_pr211_signer_outbox_finality(
        replace(evidence, signed_payload=signed)
    )

    assert not report.ready
    assert PR211Blocker.SIGNED_AFTER_AUTHORIZATION_EXPIRY.value in blockers(report)


def test_current_height_too_close_to_expiry_is_blocked() -> None:
    evidence = complete_evidence()
    signed = replace(
        evidence.signed_payload,
        current_block_height=190,
        safety_margin_blocks=10,
    )

    report = evaluate_pr211_signer_outbox_finality(
        replace(evidence, signed_payload=signed)
    )

    assert not report.ready
    assert PR211Blocker.CURRENT_HEIGHT_TOO_CLOSE_TO_EXPIRY.value in blockers(report)


def test_signature_set_hash_only_is_not_cryptographic_verification() -> None:
    evidence = complete_evidence()
    verification = replace(
        evidence.signed_payload.signature_verification,
        all_signatures_verified=False,
        signature_set_hash_only=True,
    )
    signed = replace(evidence.signed_payload, signature_verification=verification)

    report = evaluate_pr211_signer_outbox_finality(
        replace(evidence, signed_payload=signed)
    )

    assert not report.ready
    assert PR211Blocker.SIGNATURES_NOT_LOCALLY_VERIFIED.value in blockers(report)
    assert PR211Blocker.SIGNATURE_SET_HASH_ONLY.value in blockers(report)


def test_hash_only_canary_approval_is_blocked() -> None:
    evidence = complete_evidence()
    approval = replace(
        evidence.approval,
        threshold_signatures_verified=False,
        hash_only_approval=True,
    )

    report = evaluate_pr211_signer_outbox_finality(replace(evidence, approval=approval))

    assert not report.ready
    assert PR211Blocker.APPROVAL_NOT_CRYPTOGRAPHIC.value in blockers(report)


def test_failed_landed_transaction_requires_authoritative_fee() -> None:
    evidence = complete_evidence()
    settlement = replace(
        evidence.settlement,
        transaction_err="InstructionError",
        charged_fee_lamports=0,
        fee_from_get_transaction_meta=False,
    )

    report = evaluate_pr211_signer_outbox_finality(
        replace(evidence, settlement=settlement)
    )

    assert not report.ready
    assert PR211Blocker.LANDED_FEE_NOT_AUTHORITATIVE.value in blockers(report)


def test_caller_supplied_hash_only_finality_is_blocked() -> None:
    evidence = complete_evidence()
    settlement = replace(evidence.settlement, caller_supplied_hash_only=True)

    report = evaluate_pr211_signer_outbox_finality(
        replace(evidence, settlement=settlement)
    )

    assert not report.ready
    assert PR211Blocker.FINALITY_NOT_MATERIALIZED.value in blockers(report)


def test_min_context_slot_lineage_mismatch_is_blocked() -> None:
    evidence = complete_evidence()
    settlement = replace(
        evidence.settlement,
        intent_min_context_slot=700,
        compile_context_slot=600,
    )

    report = evaluate_pr211_signer_outbox_finality(
        replace(evidence, settlement=settlement)
    )

    assert not report.ready
    assert PR211Blocker.FINALITY_CONTEXT_MISMATCH.value in blockers(report)


def test_outbox_must_be_atomic_and_never_allow_blind_resend() -> None:
    evidence = complete_evidence()
    outbox = replace(
        evidence.outbox,
        permit_consumed_and_intent_created_in_one_transaction=False,
        blind_resend_possible=True,
        crash_after_send_before_ack_reconciled=False,
    )

    report = evaluate_pr211_signer_outbox_finality(replace(evidence, outbox=outbox))

    assert not report.ready
    assert PR211Blocker.OUTBOX_PROTOCOL_INCOMPLETE.value in blockers(report)
    assert PR211Blocker.OUTBOX_ALLOWS_BLIND_RESEND.value in blockers(report)
    assert PR211Blocker.CRASH_MATRIX_INCOMPLETE.value in blockers(report)


def test_pr210_dependency_and_reachable_live_surface_are_blockers() -> None:
    evidence = replace(
        complete_evidence(),
        pr210_evidence_accepted=False,
        live_execution_reachable=True,
        signer_import_reachable=True,
    )

    report = evaluate_pr211_signer_outbox_finality(evidence)

    assert not report.ready
    assert PR211Blocker.PR210_NOT_ACCEPTED.value in blockers(report)
    assert PR211Blocker.LIVE_OR_SENDER_REACHABLE.value in blockers(report)


def test_placeholder_digests_are_rejected() -> None:
    with pytest.raises(PR211EvidenceError, match="placeholder"):
        SignatureVerificationEvidence(
            exact_message_sha256="0" * 64,
            signature_verifier_sha256=h("verifier"),
            signer_public_key_hashes=(h("signer"),),
            signature_sha256s=(h("sig"),),
            all_signatures_verified=True,
        )


def test_report_json_is_stable() -> None:
    report = evaluate_pr211_signer_outbox_finality(complete_evidence())
    payload = json.loads(report.to_json())

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["ready"] is True
    assert payload["blockers"] == []

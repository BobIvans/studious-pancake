from __future__ import annotations

from src.live_boundary.mega_pr03_v3_signer_cryptographic_evidence import (
    REQUIRED_COVERAGE,
    DispatchCryptographicEvidence,
    MegaPR03V3SignerEvidence,
    MegaPR03V3State,
    SignerMessageReviewEvidence,
    SignerSignatureEvidence,
    blockers_by_code,
    evaluate_mega_pr03_v3_signer_evidence,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64
E = "e" * 64
F = "1" * 64
G = "2" * 64


def _evidence() -> MegaPR03V3SignerEvidence:
    return MegaPR03V3SignerEvidence(
        coverage_items=REQUIRED_COVERAGE,
        mega_pr02_paper_qualified=True,
        mega_pr02_evidence_sha256=A,
        two_person_approval_sha256=B,
        message_review=SignerMessageReviewEvidence(
            reviewed_message_bytes_sha256=C,
            caller_intent_message_sha256=C,
            decoded_programs_sha256=D,
            decoded_accounts_sha256=E,
            decoded_amounts_fees_sha256=F,
            semantic_bounds_sha256=G,
            simulation_evidence_sha256=A,
            signer_reparsed_exact_message_bytes=True,
            programs_accounts_amounts_fees_reviewed=True,
            simulation_message_identity_matched=True,
            message_mutation_after_review_impossible=True,
        ),
        signature=SignerSignatureEvidence(
            isolated_signer_process_sha256=B,
            signer_binary_sha256=C,
            key_authority_generation_sha256=D,
            public_key_sha256=E,
            signature_sha256=F,
            signed_wire_sha256=G,
            verification_transcript_sha256=A,
            key_loaded_inside_signer_boundary=True,
            private_key_exportable=False,
            private_key_visible_to_runtime=False,
            signature_produced_by_isolated_signer=True,
            signed_wire_built_by_isolated_signer=True,
            signature_verified_against_public_key_and_message=True,
            caller_supplied_signed_wire_sha256_present=False,
            caller_supplied_signature_sha256_present=False,
        ),
        dispatch=DispatchCryptographicEvidence(
            evidence_record_sha256=B,
            authorization_intent_sha256=C,
            dispatch_token_sha256=D,
            dispatch_receipt_sha256=E,
            evidence_persisted_before_dispatch=True,
            dispatch_token_consumed_once=True,
            replay_or_duplicate_dispatch_rejected=True,
            durable_audit_receipt_written=True,
            crash_recovery_does_not_replay_signature=True,
        ),
    )


def _codes(evidence: MegaPR03V3SignerEvidence) -> set[str]:
    report = evaluate_mega_pr03_v3_signer_evidence(evidence)
    return set(blockers_by_code(report))


def test_complete_evidence_allows_only_next_review() -> None:
    report = evaluate_mega_pr03_v3_signer_evidence(_evidence())

    assert report.state is MegaPR03V3State.READY_FOR_FINALIZED_RECONCILIATION_REVIEW
    assert report.finalized_reconciliation_review_allowed is True
    assert report.bounded_canary_review_allowed is True
    assert report.live_execution_allowed is False
    assert report.sender_allowed is False
    assert report.unrestricted_live_allowed is False
    assert report.automatic_scale_up_allowed is False
    assert report.blockers == ()


def test_requires_impl39_coverage() -> None:
    e = _evidence()
    e = MegaPR03V3SignerEvidence(
        tuple(item for item in REQUIRED_COVERAGE if item != "IMPL-39"),
        e.mega_pr02_paper_qualified,
        e.mega_pr02_evidence_sha256,
        e.two_person_approval_sha256,
        e.message_review,
        e.signature,
        e.dispatch,
    )

    assert "MEGA_PR03_V3_MISSING_COVERAGE" in _codes(e)


def test_rejects_message_identity_mismatch() -> None:
    e = _evidence()
    review = SignerMessageReviewEvidence(
        **{**e.message_review.__dict__, "caller_intent_message_sha256": D}
    )
    e = MegaPR03V3SignerEvidence(
        e.coverage_items,
        e.mega_pr02_paper_qualified,
        e.mega_pr02_evidence_sha256,
        e.two_person_approval_sha256,
        review,
        e.signature,
        e.dispatch,
    )

    assert "MEGA_PR03_V3_MESSAGE_IDENTITY_MISMATCH" in _codes(e)


def test_rejects_caller_supplied_signed_wire_and_signature_digests() -> None:
    e = _evidence()
    signature = SignerSignatureEvidence(
        **{
            **e.signature.__dict__,
            "caller_supplied_signed_wire_sha256_present": True,
            "caller_supplied_signature_sha256_present": True,
        }
    )
    e = MegaPR03V3SignerEvidence(
        e.coverage_items,
        e.mega_pr02_paper_qualified,
        e.mega_pr02_evidence_sha256,
        e.two_person_approval_sha256,
        e.message_review,
        signature,
        e.dispatch,
    )

    codes = _codes(e)
    assert "MEGA_PR03_V3_CALLER_SUPPLIED_SIGNED_WIRE_DIGEST" in codes
    assert "MEGA_PR03_V3_CALLER_SUPPLIED_SIGNATURE_DIGEST" in codes


def test_requires_signer_produced_signature_wire_and_local_verification() -> None:
    e = _evidence()
    signature = SignerSignatureEvidence(
        **{
            **e.signature.__dict__,
            "signature_produced_by_isolated_signer": False,
            "signed_wire_built_by_isolated_signer": False,
            "signature_verified_against_public_key_and_message": False,
        }
    )
    e = MegaPR03V3SignerEvidence(
        e.coverage_items,
        e.mega_pr02_paper_qualified,
        e.mega_pr02_evidence_sha256,
        e.two_person_approval_sha256,
        e.message_review,
        signature,
        e.dispatch,
    )

    codes = _codes(e)
    assert "MEGA_PR03_V3_SIGNATURE_NOT_SIGNER_PRODUCED" in codes
    assert "MEGA_PR03_V3_SIGNED_WIRE_NOT_SIGNER_BUILT" in codes
    assert "MEGA_PR03_V3_SIGNATURE_NOT_LOCALLY_VERIFIED" in codes


def test_private_key_must_not_be_exportable_or_runtime_visible() -> None:
    e = _evidence()
    signature = SignerSignatureEvidence(
        **{
            **e.signature.__dict__,
            "private_key_exportable": True,
            "private_key_visible_to_runtime": True,
        }
    )
    e = MegaPR03V3SignerEvidence(
        e.coverage_items,
        e.mega_pr02_paper_qualified,
        e.mega_pr02_evidence_sha256,
        e.two_person_approval_sha256,
        e.message_review,
        signature,
        e.dispatch,
    )

    codes = _codes(e)
    assert "MEGA_PR03_V3_EXPORTABLE_PRIVATE_KEY" in codes
    assert "MEGA_PR03_V3_RUNTIME_PRIVATE_KEY_ACCESS" in codes


def test_evidence_must_be_durable_before_one_time_dispatch() -> None:
    e = _evidence()
    dispatch = DispatchCryptographicEvidence(
        **{
            **e.dispatch.__dict__,
            "evidence_persisted_before_dispatch": False,
            "dispatch_token_consumed_once": False,
            "replay_or_duplicate_dispatch_rejected": False,
        }
    )
    e = MegaPR03V3SignerEvidence(
        e.coverage_items,
        e.mega_pr02_paper_qualified,
        e.mega_pr02_evidence_sha256,
        e.two_person_approval_sha256,
        e.message_review,
        e.signature,
        dispatch,
    )

    codes = _codes(e)
    assert "MEGA_PR03_V3_EVIDENCE_AFTER_DISPATCH" in codes
    assert "MEGA_PR03_V3_DISPATCH_TOKEN_NOT_CONSUMED_ONCE" in codes
    assert "MEGA_PR03_V3_REPLAY_OR_DUPLICATE_DISPATCH_ALLOWED" in codes


def test_megapr02_dependency_remains_required() -> None:
    e = _evidence()
    e = MegaPR03V3SignerEvidence(
        e.coverage_items,
        False,
        e.mega_pr02_evidence_sha256,
        e.two_person_approval_sha256,
        e.message_review,
        e.signature,
        e.dispatch,
    )

    assert "MEGA_PR03_V3_MEGA_PR02_NOT_QUALIFIED" in _codes(e)


def test_live_sender_unrestricted_and_scaleup_requests_are_blocked() -> None:
    e = _evidence()
    e = MegaPR03V3SignerEvidence(
        e.coverage_items,
        e.mega_pr02_paper_qualified,
        e.mega_pr02_evidence_sha256,
        e.two_person_approval_sha256,
        e.message_review,
        e.signature,
        e.dispatch,
        live_execution_requested=True,
        sender_requested=True,
        unrestricted_live_requested=True,
        automatic_scale_up_requested=True,
    )

    codes = _codes(e)
    assert "MEGA_PR03_V3_LIVE_EXECUTION_REQUESTED" in codes
    assert "MEGA_PR03_V3_SENDER_REQUESTED" in codes
    assert "MEGA_PR03_V3_UNRESTRICTED_LIVE_REQUESTED" in codes
    assert "MEGA_PR03_V3_AUTOMATIC_SCALE_UP_REQUESTED" in codes


def test_placeholder_hashes_are_rejected_and_report_hash_is_deterministic() -> None:
    e = _evidence()
    signature = SignerSignatureEvidence(
        **{**e.signature.__dict__, "signature_sha256": "0" * 64}
    )
    e = MegaPR03V3SignerEvidence(
        e.coverage_items,
        e.mega_pr02_paper_qualified,
        e.mega_pr02_evidence_sha256,
        e.two_person_approval_sha256,
        e.message_review,
        signature,
        e.dispatch,
    )

    assert "MEGA_PR03_V3_BAD_SIGNATURE_HASH" in _codes(e)
    assert (
        evaluate_mega_pr03_v3_signer_evidence(_evidence()).evidence_hash
        == evaluate_mega_pr03_v3_signer_evidence(_evidence()).evidence_hash
    )

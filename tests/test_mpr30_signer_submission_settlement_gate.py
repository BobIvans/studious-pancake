from __future__ import annotations

from dataclasses import replace

from src.mpr30_signer_submission_settlement_gate import (
    MPR30Evidence,
    MPR30PermitEnvelope,
    MPR30State,
    REQUIRED_FINDINGS,
    evaluate_mpr30_evidence,
)


HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
HEX_D = "d" * 64
HEX_E = "e" * 64
HEX_F = "f" * 64
HEX_1 = "1" * 64



def _permit() -> MPR30PermitEnvelope:
    return MPR30PermitEnvelope(
        reviewer_principal_id="reviewer-1",
        envelope_hash=HEX_A,
        permit_hash=HEX_B,
        exact_message_hash=HEX_C,
        policy_generation_hash=HEX_D,
        release_generation_hash=HEX_E,
        config_generation_hash=HEX_F,
        nonce_hash=HEX_1,
        issued_at_ns=100,
        not_before_ns=100,
        expires_at_ns=1_000,
        revocation_generation=1,
        canonical_signed_envelope=True,
        independent_reviewer=True,
        fresh_trusted_time=True,
    )



def _evidence() -> MPR30Evidence:
    return MPR30Evidence(
        signer_policy_hash=HEX_A,
        submission_fsm_hash=HEX_B,
        settlement_policy_hash=HEX_C,
        archive_registry_hash=HEX_D,
        findings_covered=REQUIRED_FINDINGS,
        signer_decodes_message_bytes_internally=True,
        caller_metadata_not_trusted=True,
        byte_derived_programs_accounts_signers=True,
        alt_identity_derived_from_bytes=True,
        permit_envelope_cryptographically_signed=True,
        permit_binds_exact_bytes_identity=True,
        permit_binds_release_config_policy_generation=True,
        permit_binds_risk_limits_and_reviewer_identity=True,
        permit_nonce_revocation_ttl_enforced=True,
        permit_issue_consume_intent_atomic=True,
        sender_receives_only_opaque_intent_id=True,
        intent_contains_exact_signed_bytes=True,
        jito_bundle_identity_covers_all_members=True,
        every_bundle_member_reviewed=True,
        fsm_monotonic_and_terminal_immutable=True,
        stale_lower_finality_observations_advisory=True,
        transport_staged_evidence_materialized=True,
        ambiguous_retry_only_after_body_write=True,
        absence_proof_independent_and_registered=True,
        absence_proof_blockheight_deadline_freeze_bound=True,
        rooted_finalized_settlement_required=True,
        settlement_binds_exact_intent_identity=True,
        caller_booleans_or_hashes_cannot_finalize=True,
        default_live_off=True,
        default_signer_off=True,
        default_sender_off=True,
        permit=_permit(),
    )



def test_mpr30_happy_path_is_ready_but_default_off() -> None:
    report = evaluate_mpr30_evidence(_evidence())

    assert report.schema_version == "mpr30.cryptographic-signer-submission-rooted-settlement.v1"
    assert report.state is MPR30State.READY_FOR_MPR30_FOUNDATION
    assert report.blockers == ()
    assert report.signer_allowed is False
    assert report.sender_allowed is False
    assert report.live_execution_allowed is False
    assert len(report.evidence_hash) == 64



def test_mpr30_missing_findings_block_foundation() -> None:
    report = evaluate_mpr30_evidence(replace(_evidence(), findings_covered=("F-314",)))

    assert report.state is MPR30State.BLOCKED
    assert any(item.code == "MPR30_FINDINGS_INCOMPLETE" for item in report.blockers)



def test_mpr30_runtime_cannot_expose_key_or_reach_signer_ipc() -> None:
    report = evaluate_mpr30_evidence(
        replace(
            _evidence(),
            runtime_private_key_access=True,
            signer_ipc_reachable_without_permit=True,
            signer_requested=True,
            sender_requested=True,
            live_execution_requested=True,
        )
    )

    codes = {item.code for item in report.blockers}
    assert "MPR30_PRIVATE_KEY_EXPOSED" in codes
    assert "MPR30_SIGNER_IPC_BYPASS" in codes
    assert "MPR30_SIGNER_REQUESTED" in codes
    assert "MPR30_SENDER_REQUESTED" in codes
    assert "MPR30_LIVE_REQUESTED" in codes



def test_mpr30_permit_must_be_cryptographic_and_time_bound() -> None:
    report = evaluate_mpr30_evidence(
        replace(
            _evidence(),
            permit_envelope_cryptographically_signed=False,
            permit_nonce_revocation_ttl_enforced=False,
            permit=replace(
                _permit(),
                canonical_signed_envelope=False,
                independent_reviewer=False,
                fresh_trusted_time=False,
                not_before_ns=50,
                expires_at_ns=90,
                revocation_generation=0,
            ),
        )
    )

    codes = {item.code for item in report.blockers}
    assert "MPR30_PERMIT_NOT_CRYPTOGRAPHIC" in codes
    assert "MPR30_ENVELOPE_NOT_CANONICAL" in codes
    assert "MPR30_REVIEWER_NOT_INDEPENDENT" in codes
    assert "MPR30_TRUSTED_TIME_NOT_FRESH" in codes
    assert "MPR30_NOT_BEFORE_REGRESSION" in codes
    assert "MPR30_BAD_EXPIRY_WINDOW" in codes
    assert "MPR30_BAD_REVOCATION_GENERATION" in codes



def test_mpr30_issue_consume_intent_must_be_one_shot() -> None:
    report = evaluate_mpr30_evidence(
        replace(
            _evidence(),
            permit_issue_consume_intent_atomic=False,
            sender_receives_only_opaque_intent_id=False,
            intent_contains_exact_signed_bytes=False,
        )
    )

    assert report.state is MPR30State.BLOCKED
    assert any(item.code == "MPR30_INTENT_NOT_ONESHOT" for item in report.blockers)



def test_mpr30_jito_bundle_identity_and_transport_staging_are_mandatory() -> None:
    report = evaluate_mpr30_evidence(
        replace(
            _evidence(),
            jito_bundle_identity_covers_all_members=False,
            every_bundle_member_reviewed=False,
            transport_staged_evidence_materialized=False,
            ambiguous_retry_only_after_body_write=False,
        )
    )

    codes = {item.code for item in report.blockers}
    assert "MPR30_BUNDLE_IDENTITY_INCOMPLETE" in codes
    assert "MPR30_TRANSPORT_EVIDENCE_INCOMPLETE" in codes



def test_mpr30_fsm_and_rooted_settlement_cannot_be_weakened() -> None:
    report = evaluate_mpr30_evidence(
        replace(
            _evidence(),
            fsm_monotonic_and_terminal_immutable=False,
            stale_lower_finality_observations_advisory=False,
            rooted_finalized_settlement_required=False,
            settlement_binds_exact_intent_identity=False,
            caller_booleans_or_hashes_cannot_finalize=False,
        )
    )

    codes = {item.code for item in report.blockers}
    assert "MPR30_FSM_NOT_MONOTONIC" in codes
    assert "MPR30_SETTLEMENT_NOT_ROOTED" in codes



def test_mpr30_absence_proof_must_be_independent_and_freeze_bound() -> None:
    report = evaluate_mpr30_evidence(
        replace(
            _evidence(),
            absence_proof_independent_and_registered=False,
            absence_proof_blockheight_deadline_freeze_bound=False,
        )
    )

    assert report.state is MPR30State.BLOCKED
    assert any(item.code == "MPR30_ABSENCE_PROOF_UNSAFE" for item in report.blockers)



def test_mpr30_default_off_flags_must_remain_true() -> None:
    report = evaluate_mpr30_evidence(
        replace(_evidence(), default_live_off=False, default_signer_off=False, default_sender_off=False)
    )

    assert report.state is MPR30State.BLOCKED
    assert any(item.code == "MPR30_DEFAULT_OFF_BROKEN" for item in report.blockers)

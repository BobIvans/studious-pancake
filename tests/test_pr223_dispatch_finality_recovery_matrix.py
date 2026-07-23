from dataclasses import replace
import json

from src.pr223_dispatch_finality_recovery_matrix import (
    REQUIRED_AUTH_BINDINGS,
    REQUIRED_CRASH_POINTS,
    REQUIRED_CROSS_PLANE_STORES,
    REQUIRED_FINALITY_FIELDS,
    REQUIRED_FINDINGS,
    SCHEMA_VERSION,
    ArchiveReconciliationGovernanceEvidence,
    CapabilityPosture,
    DispatchRecoveryEvidence,
    EvidenceRef,
    IsolatedCustodyEvidence,
    PR223DispatchFinalityEvidence,
    PrerequisiteEvidence,
    TransportFinalityEvidence,
    TrustAndAuthorizationEvidence,
    evaluate_pr223_dispatch_finality,
)


GOOD_SHA = "a" * 64
GOOD_SHA_B = "b" * 64


def valid_evidence() -> PR223DispatchFinalityEvidence:
    return PR223DispatchFinalityEvidence(
        schema_version=SCHEMA_VERSION,
        finding_coverage=frozenset(REQUIRED_FINDINGS),
        evidence_refs=(
            EvidenceRef(
                name="dispatch-finality-matrix",
                sha256=GOOD_SHA,
                uri="s3://worm-bucket/pr223/dispatch-finality-matrix.json",
            ),
        ),
        prerequisites=PrerequisiteEvidence(
            pr219_accepted=True,
            pr220_accepted=True,
            pr222_accepted=True,
            prior_pr223_gate_accepted=True,
            pr222_exact_message_sha256=GOOD_SHA,
            pr223_gate_report_sha256=GOOD_SHA_B,
        ),
        trust_authorization=TrustAndAuthorizationEvidence(
            root_signed_trust_bundle=True,
            real_ed25519_verification=True,
            canonical_serialization=True,
            schema_domain_separation=True,
            key_rotation_revocation_checked=True,
            not_before_enforced=True,
            expiry_enforced=True,
            future_issued_rejected=True,
            authorization_bindings=frozenset(REQUIRED_AUTH_BINDINGS),
            authorization_not_caller_boolean=True,
            authorization_not_caller_hash=True,
        ),
        custody=IsolatedCustodyEvidence(
            runtime_has_no_private_key_access=True,
            signer_separate_package=True,
            signer_separate_process_user_network=True,
            signer_uses_hsm_kms_or_owner_only_key=True,
            signer_decodes_exact_message_bytes=True,
            signer_binds_pr222_message_digest=True,
            signer_produces_signature=True,
            signer_builds_signed_wire=True,
            local_signature_verification_transcript=True,
            runtime_cannot_request_raw_key_export=True,
        ),
        dispatch=DispatchRecoveryEvidence(
            permit_intent_outbox_single_transaction=True,
            one_permit_one_message_digest=True,
            replay_denied=True,
            stale_config_denied=True,
            stale_shadow_evidence_denied=True,
            dispatched_record_before_transport=True,
            idempotent_provider_key_bound=True,
            unknown_reconciliation_owner=True,
            no_blind_resend=True,
            daily_debit_limits_durable=True,
            crash_points_covered=frozenset(REQUIRED_CRASH_POINTS),
            duplicate_debit_impossible=True,
        ),
        transport_finality=TransportFinalityEvidence(
            transport_payload_digest_bound=True,
            transport_endpoint_min_context_slot_blockhash_bound=True,
            transport_tip_bound=True,
            ack_is_not_landing=True,
            bundle_id_is_not_landing=True,
            rpc_signature_is_not_finality=True,
            finalized_get_transaction_required=True,
            finality_fields=frozenset(REQUIRED_FINALITY_FIELDS),
            failed_landed_fee_and_balance_deltas_recorded=True,
            settlement_transport_matches_intent=True,
            fork_reorg_uncle_rebroadcast_matrix=True,
        ),
        archive_reconciliation_governance=ArchiveReconciliationGovernanceEvidence(
            archive_receipt_rehashes_published_bytes=True,
            archive_receipt_remote_worm=True,
            archive_receipt_immutable_no_upsert=True,
            cross_plane_stores=frozenset(REQUIRED_CROSS_PLANE_STORES),
            corrections_append_only=True,
            reconciliation_reads_authoritative_stores=True,
            dual_approval_distinct=True,
            approval_fresh_trusted_time=True,
            aggregate_budget_checked=True,
            rollback_proof_present=True,
            tiny_canary_requires_final_settlement=True,
            canary_disabled_by_default=True,
        ),
    )


def test_valid_report_allows_only_review_not_live_or_signer() -> None:
    report = evaluate_pr223_dispatch_finality(valid_evidence())
    assert report.accepted
    assert report.dispatch_finality_review_allowed
    assert not report.signer_allowed
    assert not report.sender_allowed
    assert not report.live_execution_allowed
    assert not report.private_key_material_allowed
    parsed = json.loads(report.to_json())
    assert parsed["accepted"] is True


def test_missing_finding_blocks_acceptance() -> None:
    ev = valid_evidence()
    ev = replace(ev, finding_coverage=frozenset(sorted(REQUIRED_FINDINGS)[1:]))
    report = evaluate_pr223_dispatch_finality(ev)
    assert not report.accepted
    assert any(reason.startswith("FINDINGS_MISSING:") for reason in report.reasons)


def test_requires_prior_pr219_pr220_pr222_and_initial_pr223_gate() -> None:
    ev = valid_evidence()
    ev = replace(
        ev,
        prerequisites=replace(
            ev.prerequisites,
            pr220_accepted=False,
            pr222_accepted=False,
            prior_pr223_gate_accepted=False,
        ),
    )
    report = evaluate_pr223_dispatch_finality(ev)
    assert "PR223_PR220_NOT_ACCEPTED" in report.reasons
    assert "PR223_PR222_NOT_ACCEPTED" in report.reasons
    assert "PR223_INITIAL_GATE_NOT_ACCEPTED" in report.reasons


def test_placeholder_or_self_attested_evidence_is_rejected() -> None:
    ev = valid_evidence()
    ev = replace(
        ev,
        evidence_refs=(
            EvidenceRef(
                name="self-report",
                sha256="0" * 64,
                uri="/tmp/report.json",
                signed=False,
                immutable=False,
                produced_by_runtime=True,
            ),
        ),
    )
    report = evaluate_pr223_dispatch_finality(ev)
    assert any("placeholder sha256" in reason for reason in report.reasons)
    assert any(reason.startswith("EVIDENCE_SELF_ATTESTED:self-report") for reason in report.reasons)


def test_caller_hash_boolean_authorization_and_missing_bindings_are_rejected() -> None:
    ev = valid_evidence()
    ev = replace(
        ev,
        trust_authorization=replace(
            ev.trust_authorization,
            authorization_not_caller_boolean=False,
            authorization_not_caller_hash=False,
            authorization_bindings=frozenset(REQUIRED_AUTH_BINDINGS - {"nonce", "transport"}),
        ),
    )
    report = evaluate_pr223_dispatch_finality(ev)
    assert "AUTHORIZATION_CALLER_BOOLEAN_ACCEPTED" in report.reasons
    assert "AUTHORIZATION_CALLER_HASH_ACCEPTED" in report.reasons
    assert any(reason.startswith("AUTHORIZATION_BINDINGS_MISSING:") for reason in report.reasons)


def test_future_or_expired_authorization_invariants_are_required() -> None:
    ev = valid_evidence()
    ev = replace(
        ev,
        trust_authorization=replace(
            ev.trust_authorization,
            future_issued_rejected=False,
            expiry_enforced=False,
            not_before_enforced=False,
        ),
    )
    report = evaluate_pr223_dispatch_finality(ev)
    assert "FUTURE_ISSUED_NOT_REJECTED" in report.reasons
    assert "EXPIRY_NOT_ENFORCED" in report.reasons
    assert "NOT_BEFORE_NOT_ENFORCED" in report.reasons


def test_runtime_key_access_or_non_signer_signature_is_rejected() -> None:
    ev = valid_evidence()
    ev = replace(
        ev,
        custody=replace(
            ev.custody,
            runtime_has_no_private_key_access=False,
            signer_produces_signature=False,
            signer_builds_signed_wire=False,
            local_signature_verification_transcript=False,
        ),
    )
    report = evaluate_pr223_dispatch_finality(ev)
    assert "RUNTIME_PRIVATE_KEY_ACCESS" in report.reasons
    assert "SIGNATURE_NOT_SIGNER_PRODUCED" in report.reasons
    assert "SIGNED_WIRE_NOT_SIGNER_BUILT" in report.reasons
    assert "LOCAL_SIGNATURE_VERIFY_MISSING" in report.reasons


def test_non_atomic_dispatch_or_missing_crash_points_are_rejected() -> None:
    ev = valid_evidence()
    ev = replace(
        ev,
        dispatch=replace(
            ev.dispatch,
            permit_intent_outbox_single_transaction=False,
            crash_points_covered=frozenset(REQUIRED_CRASH_POINTS - {"after_transport_handoff"}),
            duplicate_debit_impossible=False,
        ),
    )
    report = evaluate_pr223_dispatch_finality(ev)
    assert "PERMIT_INTENT_OUTBOX_NOT_ATOMIC" in report.reasons
    assert "DUPLICATE_DEBIT_POSSIBLE" in report.reasons
    assert any(reason.startswith("CRASH_POINTS_MISSING:") for reason in report.reasons)


def test_ack_bundle_or_rpc_signature_cannot_be_finality() -> None:
    ev = valid_evidence()
    ev = replace(
        ev,
        transport_finality=replace(
            ev.transport_finality,
            ack_is_not_landing=False,
            bundle_id_is_not_landing=False,
            rpc_signature_is_not_finality=False,
        ),
    )
    report = evaluate_pr223_dispatch_finality(ev)
    assert "ACK_COUNTS_AS_LANDING" in report.reasons
    assert "BUNDLE_ID_COUNTS_AS_LANDING" in report.reasons
    assert "RPC_SIGNATURE_COUNTS_AS_FINALITY" in report.reasons


def test_finalized_transaction_materialization_requires_complete_fields() -> None:
    ev = valid_evidence()
    ev = replace(
        ev,
        transport_finality=replace(
            ev.transport_finality,
            finality_fields=frozenset(REQUIRED_FINALITY_FIELDS - {"meta_fee", "program_logs"}),
            finalized_get_transaction_required=False,
        ),
    )
    report = evaluate_pr223_dispatch_finality(ev)
    assert "FINALIZED_GET_TRANSACTION_NOT_REQUIRED" in report.reasons
    assert any(reason.startswith("FINALITY_FIELDS_MISSING:") for reason in report.reasons)


def test_archive_receipt_and_cross_plane_reconciliation_must_be_immutable() -> None:
    ev = valid_evidence()
    ev = replace(
        ev,
        archive_reconciliation_governance=replace(
            ev.archive_reconciliation_governance,
            archive_receipt_immutable_no_upsert=False,
            corrections_append_only=False,
            cross_plane_stores=frozenset(REQUIRED_CROSS_PLANE_STORES - {"accounting"}),
        ),
    )
    report = evaluate_pr223_dispatch_finality(ev)
    assert "ARCHIVE_UPSERT_ALLOWED" in report.reasons
    assert "CORRECTIONS_NOT_APPEND_ONLY" in report.reasons
    assert any(reason.startswith("CROSS_PLANE_STORES_MISSING:") for reason in report.reasons)


def test_governance_requires_dual_approval_budget_rollback_and_disabled_default_canary() -> None:
    ev = valid_evidence()
    ev = replace(
        ev,
        archive_reconciliation_governance=replace(
            ev.archive_reconciliation_governance,
            dual_approval_distinct=False,
            aggregate_budget_checked=False,
            rollback_proof_present=False,
            canary_disabled_by_default=False,
        ),
    )
    report = evaluate_pr223_dispatch_finality(ev)
    assert "DUAL_APPROVAL_NOT_DISTINCT" in report.reasons
    assert "AGGREGATE_BUDGET_NOT_CHECKED" in report.reasons
    assert "ROLLBACK_PROOF_MISSING" in report.reasons
    assert "CANARY_ENABLED_BY_DEFAULT" in report.reasons


def test_forbidden_runtime_capabilities_block_even_with_otherwise_valid_evidence() -> None:
    ev = valid_evidence()
    ev = replace(
        ev,
        capabilities=CapabilityPosture(
            signer_allowed=True,
            sender_allowed=True,
            live_execution_allowed=True,
            private_key_material_allowed=True,
            automatic_canary_allowed=True,
            unrestricted_live_allowed=True,
        ),
    )
    report = evaluate_pr223_dispatch_finality(ev)
    assert "SIGNER_ALLOWED" in report.reasons
    assert "SENDER_ALLOWED" in report.reasons
    assert "LIVE_EXECUTION_ALLOWED" in report.reasons
    assert "PRIVATE_KEY_MATERIAL_ALLOWED" in report.reasons
    assert "AUTOMATIC_CANARY_ALLOWED" in report.reasons
    assert "UNRESTRICTED_LIVE_ALLOWED" in report.reasons

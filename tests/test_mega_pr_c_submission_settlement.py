from __future__ import annotations

from dataclasses import replace

import pytest

from src.mega_pr_c_submission_settlement import (
    FinalizedSettlementEvidence,
    IsolatedSignerBoundary,
    JitoRpcSubmissionPolicy,
    OneTimeAuthorization,
    ProvenMessageBundle,
    SubmissionSettlementPackage,
    SubmissionSettlementState,
    TransportObservation,
    UpstreamReadinessEvidence,
    derive_idempotency_key,
    evaluate_submission_settlement_package,
)

pytestmark = pytest.mark.unit

H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64
H5 = "5" * 64
H6 = "6" * 64
H7 = "7" * 64
H8 = "8" * 64
H9 = "9" * 64
HA = "a" * 64
HB = "b" * 64
HC = "c" * 64
HD = "d" * 64
HE = "e" * 64
HF = "f" * 64


def _package() -> SubmissionSettlementPackage:
    upstream = UpstreamReadinessEvidence(
        canonical_paper_vertical_merged=True,
        provider_protocol_conformance_merged=True,
        real_sender_free_soak_completed=True,
        release_candidate_pinned=True,
        live_default_disabled=True,
        paper_message_identity_stable=True,
        evidence_bundle_hash=H1,
    )
    signer = IsolatedSignerBoundary(
        signer_service_identity="signer-prod-1",
        expected_signer_pubkey="Signer111111111111111111111111111111111111",
        network_runtime_private_key_absent=True,
        runtime_cannot_import_keypair=True,
        signer_general_internet_blocked=True,
        signer_uses_authenticated_ipc_only=True,
        signer_parses_unsigned_message=True,
        signer_verifies_payer_and_signers=True,
        signer_verifies_programs_and_writable_accounts=True,
        signer_verifies_alt_resolution=True,
        signer_verifies_instruction_semantics=True,
    )
    message = ProvenMessageBundle(
        logical_opportunity_id="opp-1",
        attempt_id="attempt-1",
        attempt_generation=1,
        final_request_hash=H2,
        policy_hash=H3,
        plan_hash=H4,
        final_simulation_hash=H5,
        cpi_graph_hash=H6,
        final_fee_hash=H7,
        blockhash_evidence_hash=H8,
        alt_evidence_hash=H9,
        serialized_message_hash=HA,
        unsigned_wire_hash=HB,
        payer="Payer1111111111111111111111111111111111111",
        signer_set_hash=HC,
        writable_accounts_hash=HD,
        wire_size_bytes=900,
        same_message_jito_tip_lamports=5_000,
        standalone_tip_transaction_allowed=False,
    )
    authorization = OneTimeAuthorization(
        authorization_id="auth-1",
        signer_service_identity=signer.signer_service_identity,
        expected_signer_pubkey=signer.expected_signer_pubkey,
        request_hash=message.final_request_hash,
        policy_hash=message.policy_hash,
        message_hash=message.serialized_message_hash,
        unsigned_wire_hash=message.unsigned_wire_hash,
        nonce="nonce-1",
        issued_at_ns=100,
        expires_at_ns=200,
        verification_chain_hash=HE,
        durable_consumed_state=True,
    )
    submission = _submission(message=message, authorization=authorization)
    policy = JitoRpcSubmissionPolicy(
        one_strategy_transaction_only=True,
        same_message_tip_only=True,
        no_multiregion_shotgun=True,
        bundle_ack_is_not_settlement=True,
        direct_rpc_fallback_requires_explicit_policy=True,
        bundle_only_requires_reviewed_policy=True,
        max_transactions_per_hour=1,
        max_transactions_per_day=3,
        max_tip_lamports=10_000,
        max_fee_lamports=50_000,
    )
    transport = TransportObservation(
        json_rpc_ack_received=True,
        bundle_status_observed=True,
        signature_observed=True,
        timed_out_or_unknown=False,
        treated_as_economic_success=False,
    )
    settlement = FinalizedSettlementEvidence(
        signature="sig-1",
        expected_signature="sig-1",
        message_hash=message.serialized_message_hash,
        expected_message_hash=message.serialized_message_hash,
        finalized_get_transaction=True,
        transaction_version_supported=True,
        signature_matches_message=True,
        loaded_addresses_reconciled=True,
        native_balances_reconciled=True,
        token_balances_reconciled=True,
        inner_instructions_reconciled=True,
        logs_reconciled=True,
        return_data_reconciled=True,
        compute_units_reconciled=True,
        marginfi_repayment_proven=True,
        fees_tips_rent_cleanup_reconciled=True,
        unresolved_or_conflicting_status=False,
        pnl_booked_from_finalized_actuals_only=True,
        actual_net_lamports=123,
        evidence_hash=HF,
    )
    return SubmissionSettlementPackage(
        upstream=upstream,
        signer=signer,
        message=message,
        authorization=authorization,
        submission_intent=submission,
        transport_policy=policy,
        transport_observation=transport,
        finalized_settlement=settlement,
    )


def _submission(
    *, message: ProvenMessageBundle, authorization: OneTimeAuthorization
):
    return __import__(
        "src.mega_pr_c_submission_settlement",
        fromlist=["DurableSubmissionIntent"],
    ).DurableSubmissionIntent(
        intent_id="intent-1",
        authorization_id=authorization.authorization_id,
        attempt_id=message.attempt_id,
        attempt_generation=message.attempt_generation,
        message_hash=message.serialized_message_hash,
        idempotency_key=derive_idempotency_key(
            authorization_id=authorization.authorization_id,
            message_hash=message.serialized_message_hash,
            attempt_id=message.attempt_id,
            attempt_generation=message.attempt_generation,
        ),
        lease_owner="owner-1",
        fencing_token="fence-1",
        recorded_before_external_io=True,
        authorization_consumed_atomically=True,
        outbound_io_started=True,
    )


def test_ready_package_is_manual_review_only_and_live_disabled() -> None:
    result = evaluate_submission_settlement_package(_package())

    assert result.state == SubmissionSettlementState.READY_FOR_MANUAL_INTEGRATION_REVIEW
    assert result.runtime_live_enabled is False
    assert result.supported_command_can_submit is False
    assert result.signer_reachable_from_network_runtime is False
    assert result.economically_successful is True
    assert result.blockers == ()
    assert "json-rpc ack is transport-only, not settlement" in result.warnings


def test_missing_upstream_verticals_block_c_start() -> None:
    package = _package()
    package = replace(
        package,
        upstream=replace(
            package.upstream,
            canonical_paper_vertical_merged=False,
            real_sender_free_soak_completed=False,
        ),
    )

    result = evaluate_submission_settlement_package(package)

    assert result.state == SubmissionSettlementState.BLOCKED
    assert "MEGA_PR_A_CANONICAL_PAPER_VERTICAL_REQUIRED" in result.blockers
    assert "REAL_SENDER_FREE_SOAK_REQUIRED" in result.blockers
    assert result.supported_command_can_submit is False


def test_network_runtime_key_access_blocks_submission_review() -> None:
    package = _package()
    package = replace(
        package,
        signer=replace(
            package.signer,
            network_runtime_private_key_absent=False,
            runtime_cannot_import_keypair=False,
        ),
    )

    result = evaluate_submission_settlement_package(package)

    assert "NETWORK_RUNTIME_PRIVATE_KEY_MUST_BE_ABSENT" in result.blockers
    assert "NETWORK_RUNTIME_KEYPAIR_IMPORT_MUST_BE_IMPOSSIBLE" in result.blockers


def test_standalone_tip_and_shotgun_policy_block_first_live_shape() -> None:
    package = _package()
    package = replace(
        package,
        message=replace(package.message, standalone_tip_transaction_allowed=True),
        transport_policy=replace(package.transport_policy, no_multiregion_shotgun=False),
    )

    result = evaluate_submission_settlement_package(package)

    assert "STANDALONE_TIP_TRANSACTION_FORBIDDEN" in result.blockers
    assert "MULTIREGION_SHOTGUN_SUBMISSION_FORBIDDEN" in result.blockers


def test_authorization_consumed_revoked_or_mismatched_blocks() -> None:
    package = _package()
    package = replace(
        package,
        authorization=replace(
            package.authorization,
            consumed=True,
            revoked=True,
            message_hash=H1,
        ),
    )

    result = evaluate_submission_settlement_package(package)

    assert "AUTHORIZATION_ALREADY_CONSUMED" in result.blockers
    assert "AUTHORIZATION_REVOKED" in result.blockers
    assert "AUTHORIZATION_MESSAGE_HASH_MISMATCH" in result.blockers


def test_submission_requires_pre_io_intent_and_no_blind_resend() -> None:
    package = _package()
    package = replace(
        package,
        submission_intent=replace(
            package.submission_intent,
            recorded_before_external_io=False,
            duplicate_send_possible=True,
            blind_resend_after_timeout_allowed=True,
        ),
    )

    result = evaluate_submission_settlement_package(package)

    assert "SUBMISSION_INTENT_MUST_PRECEDE_EXTERNAL_IO" in result.blockers
    assert "DUPLICATE_SEND_MUST_BE_IMPOSSIBLE" in result.blockers
    assert "BLIND_RESEND_AFTER_TIMEOUT_FORBIDDEN" in result.blockers


def test_transport_observation_cannot_be_economic_success() -> None:
    package = _package()
    package = replace(
        package,
        transport_observation=replace(
            package.transport_observation,
            timed_out_or_unknown=True,
            treated_as_economic_success=True,
        ),
    )

    result = evaluate_submission_settlement_package(package)

    assert "TRANSPORT_OBSERVATION_CANNOT_BE_ECONOMIC_SUCCESS" in result.blockers
    assert "UNKNOWN_TRANSPORT_OUTCOME_REQUIRES_DURABLE_RECONCILIATION" in result.blockers


def test_non_finalized_or_unreconciled_settlement_blocks_pnl() -> None:
    package = _package()
    package = replace(
        package,
        finalized_settlement=replace(
            package.finalized_settlement,
            finalized_get_transaction=False,
            marginfi_repayment_proven=False,
            pnl_booked_from_finalized_actuals_only=False,
            actual_net_lamports=None,
        ),
    )

    result = evaluate_submission_settlement_package(package)

    assert "FINALIZED_GET_TRANSACTION_REQUIRED" in result.blockers
    assert "MARGINFI_REPAYMENT_MUST_BE_PROVEN" in result.blockers
    assert "PNL_CAN_ONLY_BE_BOOKED_FROM_FINALIZED_ACTUALS" in result.blockers
    assert "ACTUAL_NET_LAMPORTS_REQUIRED" in result.blockers


def test_placeholder_hashes_fail_closed() -> None:
    package = _package()
    package = replace(
        package,
        message=replace(package.message, final_fee_hash="0" * 64),
        finalized_settlement=replace(package.finalized_settlement, evidence_hash="placeholder"),
    )

    result = evaluate_submission_settlement_package(package)

    assert "INVALID_FINAL_FEE_HASH" in result.blockers
    assert "FINALIZED_SETTLEMENT_EVIDENCE_HASH_INVALID" in result.blockers

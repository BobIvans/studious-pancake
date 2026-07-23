from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SRC = ROOT / "isolated_signer_service" / "src"
sys.path.insert(0, str(PACKAGE_SRC))

from flashloan_isolated_signer.pr199 import (  # noqa: E402
    PR198AcceptanceEvidence,
    PR199AdmissionPolicy,
    PR199AuthorizationRequest,
    PR199BoundaryError,
    PR199CanaryLimits,
    PR199Failure,
    PR199IntentState,
    PR199SubmissionBoundary,
    PR199SubmissionIntentStore,
    PR199TransportKind,
)
from flashloan_isolated_signer.pr199_followup import (  # noqa: E402
    PR199FinalityOutcome,
    PR199FinalizedChainEvidence,
    PR199OperatorCanaryGate,
    PR199SignedPayloadBinding,
    PR199SignerIsolationEvidence,
    PR199SignerRequestEnvelope,
    pr199_followup_status_payload,
    reconcile_finalized_attempt,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def accepted_pr198() -> PR198AcceptanceEvidence:
    return PR198AcceptanceEvidence(
        release_id="release-pr198",
        evidence_sha256=digest("accepted-real-shadow-evidence"),
        reviewer_id="reviewer-a",
        accepted=True,
        independently_reviewed=True,
        multi_day_shadow_soak=True,
        no_sender_modules=True,
        no_signing_keys=True,
        no_live_permit=True,
    )


def request(**overrides: object) -> PR199AuthorizationRequest:
    data: dict[str, object] = {
        "attempt_id": "attempt-pr199",
        "generation": 1,
        "plan_hash": digest("plan"),
        "message_sha256": digest("message"),
        "wallet": "wallet-primary",
        "provider": "jupiter-v2",
        "market": "marginfi-flashloan-sol-usdc",
        "reservation_id": "reservation-1",
        "session_id": "session-1",
        "nonce_digest": digest("nonce"),
        "config_generation_hash": digest("config-generation"),
        "release_id": "release-pr199",
        "policy_bundle_hash": digest("policy-bundle"),
        "program_ids": (digest("program-marginfi"), digest("program-jupiter")),
        "account_hashes": (digest("account-a"), digest("account-b")),
        "amount_hashes": (digest("amount-a"), digest("amount-b")),
        "principal_lamports": 100_000,
        "expected_debit_lamports": 150_000,
        "network_fee_lamports": 5_000,
        "priority_fee_lamports": 1_000,
        "jito_tip_lamports": 0,
        "expires_at_block_height": 1_100,
        "message_bytes_len": 800,
        "transport": PR199TransportKind.RPC,
    }
    data.update(overrides)
    return PR199AuthorizationRequest(**data)


def signer_isolation(**overrides: object) -> PR199SignerIsolationEvidence:
    data: dict[str, object] = {
        "release_id": "release-pr199",
        "config_generation_hash": digest("config-generation"),
        "signer_identity": "signer-pr199",
        "signer_policy_hash": digest("signer-policy"),
        "ipc_protocol_hash": digest("ipc-protocol"),
        "key_authority_hash": digest("key-authority"),
        "process_generation": 1,
        "separate_process": True,
        "runtime_holds_private_key": False,
        "signer_allows_general_network": False,
        "signer_allows_filesystem_wallet": False,
        "signer_allows_env_private_key": False,
        "signer_policy_enforced": True,
    }
    data.update(overrides)
    return PR199SignerIsolationEvidence(**data)


def boundary(tmp_path: Path, *, clock_ns: int = 10_000_000_000) -> PR199SubmissionBoundary:
    policy = PR199AdmissionPolicy(
        pr198_evidence=accepted_pr198(),
        canary_limits=PR199CanaryLimits(max_outstanding_intents=1),
    )
    return PR199SubmissionBoundary(
        policy=policy,
        store=PR199SubmissionIntentStore(tmp_path / "pr199.sqlite"),
        clock_ns=lambda: clock_ns,
    )


def prepared_bundle(tmp_path: Path):
    subject = boundary(tmp_path)
    auth = request()
    permit = subject.policy.issue_permit(
        auth,
        permit_id="permit-pr199",
        issued_at_block_height=1_000,
    )
    intent = subject.store.prepare(
        permit,
        signed_payload_sha256=digest("signed-payload"),
        max_outstanding_intents=subject.policy.canary_limits.max_outstanding_intents,
        now_ns=10_000_000_000,
    )
    isolation = signer_isolation()
    envelope = PR199SignerRequestEnvelope(
        authorization=auth,
        permit_hash=permit.permit_hash,
        signer_isolation_hash=isolation.isolation_hash,
        signer_session_id="signer-session-1",
        caller_identity_hash=digest("runtime-caller"),
        requested_at_block_height=1_001,
    )
    binding = PR199SignedPayloadBinding(
        signer_request_digest=envelope.signer_request_digest,
        authorization_digest=auth.authorization_digest,
        message_sha256=auth.message_sha256,
        signed_payload_sha256=intent.signed_payload_sha256,
        signature_set_hash=digest("signature-set"),
        signer_identity=isolation.signer_identity,
        signer_isolation_hash=isolation.isolation_hash,
        signed_at_block_height=1_002,
    )
    return subject, auth, intent, isolation, envelope, binding


def finality_for(intent, binding, **overrides: object) -> PR199FinalizedChainEvidence:
    data: dict[str, object] = {
        "attempt_id": intent.attempt_id,
        "authorization_digest": binding.authorization_digest,
        "message_sha256": binding.message_sha256,
        "signed_payload_sha256": binding.signed_payload_sha256,
        "signature_status_hash": digest("history-status"),
        "transaction_record_hash": digest("finalized-get-transaction"),
        "token_balance_delta_hash": digest("token-deltas"),
        "status_history_searched": True,
        "get_transaction_finalized": True,
        "landed_as_single_transaction": True,
        "flash_repayment_verified": True,
        "min_context_slot": 100,
        "landed_slot": 101,
        "finalized_slot": 133,
        "charged_fee_lamports": 5_000,
        "settled_native_delta_lamports": 25_000,
        "jito_ack_hash": digest("jito-ack"),
    }
    data.update(overrides)
    return PR199FinalizedChainEvidence(**data)


def test_pr199_signer_isolation_rejects_runtime_key_material() -> None:
    with pytest.raises(PR199BoundaryError) as error:
        signer_isolation(runtime_holds_private_key=True)
    assert error.value.failure is PR199Failure.POLICY_LIMIT

    with pytest.raises(PR199BoundaryError) as network:
        signer_isolation(signer_allows_general_network=True)
    assert network.value.failure is PR199Failure.POLICY_LIMIT


def test_pr199_signer_request_and_signed_payload_bind_exact_intent(
    tmp_path: Path,
) -> None:
    _, _, intent, isolation, envelope, binding = prepared_bundle(tmp_path)

    binding.assert_matches(intent=intent, envelope=envelope, isolation=isolation)

    changed = replace(binding, signed_payload_sha256=digest("different-payload"))
    with pytest.raises(PR199BoundaryError) as error:
        changed.assert_matches(intent=intent, envelope=envelope, isolation=isolation)
    assert error.value.failure is PR199Failure.AUTHORIZATION_BINDING


def test_pr199_finality_requires_history_search_and_finalized_transaction(
    tmp_path: Path,
) -> None:
    _, _, intent, _, _, binding = prepared_bundle(tmp_path)

    no_history = finality_for(intent, binding, status_history_searched=False)
    with pytest.raises(PR199BoundaryError) as history:
        no_history.assert_matches(intent=intent, binding=binding)
    assert history.value.failure is PR199Failure.ACK_NOT_FINALITY

    no_finalized_tx = finality_for(intent, binding, get_transaction_finalized=False)
    with pytest.raises(PR199BoundaryError) as finalized:
        no_finalized_tx.assert_matches(intent=intent, binding=binding)
    assert finalized.value.failure is PR199Failure.ACK_NOT_FINALITY


def test_pr199_reconcile_finalized_success_updates_durable_intent(
    tmp_path: Path,
) -> None:
    subject, _, intent, _, _, binding = prepared_bundle(tmp_path)
    acknowledged = subject.acknowledge_transport(intent, receipt_hash=digest("ack"))
    finality = finality_for(acknowledged, binding)

    report = reconcile_finalized_attempt(
        boundary=subject,
        intent=acknowledged,
        binding=binding,
        finality=finality,
    )

    assert report.outcome is PR199FinalityOutcome.FINALIZED_SUCCESS
    assert report.updated_state is PR199IntentState.FINALIZED
    assert report.charged_fee_lamports == 5_000
    assert report.settled_native_delta_lamports == 25_000
    assert report.requires_operator_escalation is False


def test_pr199_reconcile_failed_landed_transaction_accounts_fee(
    tmp_path: Path,
) -> None:
    subject, _, intent, _, _, binding = prepared_bundle(tmp_path)
    uncertain = subject.mark_uncertain(intent)
    finality = finality_for(
        uncertain,
        binding,
        transaction_error_code="InstructionError",
        flash_repayment_verified=False,
        charged_fee_lamports=7_500,
        settled_native_delta_lamports=-7_500,
    )

    report = reconcile_finalized_attempt(
        boundary=subject,
        intent=uncertain,
        binding=binding,
        finality=finality,
    )

    assert report.outcome is PR199FinalityOutcome.FINALIZED_FAILURE
    assert report.updated_state is PR199IntentState.FINALIZED
    assert report.charged_fee_lamports == 7_500
    assert report.settled_native_delta_lamports == -7_500
    assert report.requires_operator_escalation is True


def test_pr199_operator_canary_gate_blocks_unknown_and_expired_state() -> None:
    isolation = signer_isolation()
    ready = PR199OperatorCanaryGate(
        release_id="release-pr199",
        config_generation_hash=digest("config-generation"),
        policy_bundle_hash=digest("policy-bundle"),
        canary_limits_hash=digest("canary-limits"),
        signer_isolation_hash=isolation.isolation_hash,
        pr198_acceptance_hash=accepted_pr198().acceptance_hash,
        approval_digest=digest("approval"),
        approved_by_hash=digest("operator"),
        approval_expires_at_block_height=1_200,
        outstanding_intents=0,
        unknown_intents=0,
        emergency_latch_cleared=True,
    )
    ready.assert_ready(current_block_height=1_100)

    with pytest.raises(PR199BoundaryError) as outstanding:
        replace(ready, outstanding_intents=1).assert_ready(current_block_height=1_100)
    assert outstanding.value.failure is PR199Failure.CANARY_LIMIT

    with pytest.raises(PR199BoundaryError) as expired:
        ready.assert_ready(current_block_height=1_200)
    assert expired.value.failure is PR199Failure.CANARY_LIMIT


def test_pr199_followup_status_is_fail_closed() -> None:
    payload = pr199_followup_status_payload()
    assert payload["roadmap_pr"] == "PR-199"
    assert payload["compile_time_live_submission_enabled"] is False
    assert payload["signer_ipc_policy_evidence_required"] is True
    assert payload["finality_requires_history_search"] is True
    assert payload["ack_or_bundle_id_is_settlement"] is False
    assert payload["operator_canary_gate_required"] is True
    assert payload["live_transport_implementation_present"] is False

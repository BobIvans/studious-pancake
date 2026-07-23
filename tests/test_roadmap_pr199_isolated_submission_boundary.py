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
    COMPILE_TIME_LIVE_SUBMISSION_ENABLED,
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
    pr199_status_payload,
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


def prepare(tmp_path: Path, **overrides: object):
    return boundary(tmp_path).prepare_intent(
        request=request(**overrides),
        permit_id="permit-pr199",
        issued_at_block_height=1_000,
        signed_payload_sha256=digest("signed-payload"),
    )


def test_pr199_requires_accepted_pr198_evidence() -> None:
    with pytest.raises(PR199BoundaryError) as error:
        PR199AdmissionPolicy(
            pr198_evidence=replace(accepted_pr198(), multi_day_shadow_soak=False)
        )
    assert error.value.failure is PR199Failure.PR198_EVIDENCE


def test_pr199_authorization_digest_binds_live_semantics() -> None:
    original = request()
    changed_message = replace(original, message_sha256=digest("changed-message"))
    changed_reservation = replace(original, reservation_id="reservation-2")
    changed_nonce = replace(original, nonce_digest=digest("changed-nonce"))

    assert original.authorization_digest != changed_message.authorization_digest
    assert original.authorization_digest != changed_reservation.authorization_digest
    assert original.authorization_digest != changed_nonce.authorization_digest


def test_pr199_policy_enforces_canary_bounds_and_transport_semantics() -> None:
    policy = PR199AdmissionPolicy(
        pr198_evidence=accepted_pr198(),
        canary_limits=PR199CanaryLimits(max_principal_lamports=100_000),
    )
    with pytest.raises(PR199BoundaryError) as limit:
        policy.issue_permit(
            request(principal_lamports=100_001),
            permit_id="permit-pr199",
            issued_at_block_height=1_000,
        )
    assert limit.value.failure is PR199Failure.POLICY_LIMIT

    with pytest.raises(PR199BoundaryError) as rpc_tip:
        policy.issue_permit(
            request(jito_tip_lamports=1),
            permit_id="permit-pr199",
            issued_at_block_height=1_000,
        )
    assert rpc_tip.value.failure is PR199Failure.POLICY_LIMIT

    permit = policy.issue_permit(
        request(transport=PR199TransportKind.JITO_SINGLE, jito_tip_lamports=1),
        permit_id="permit-pr199-jito",
        issued_at_block_height=1_000,
    )
    assert permit.transport is PR199TransportKind.JITO_SINGLE


def test_pr199_exact_intent_replay_is_idempotent_and_conflict_rejected(
    tmp_path: Path,
) -> None:
    first = prepare(tmp_path)
    second = prepare(tmp_path)
    assert first == second
    assert first.state is PR199IntentState.PREPARED

    with pytest.raises(PR199BoundaryError) as conflict:
        boundary(tmp_path).prepare_intent(
            request=request(),
            permit_id="permit-pr199",
            issued_at_block_height=1_000,
            signed_payload_sha256=digest("different-signed-payload"),
        )
    assert conflict.value.failure is PR199Failure.REPLAY_CONFLICT


def test_pr199_canary_allows_only_one_outstanding_attempt(tmp_path: Path) -> None:
    first = prepare(tmp_path)
    assert first.state is PR199IntentState.PREPARED

    with pytest.raises(PR199BoundaryError) as blocked:
        boundary(tmp_path).prepare_intent(
            request=request(attempt_id="attempt-pr199-b", nonce_digest=digest("nonce-b")),
            permit_id="permit-pr199-b",
            issued_at_block_height=1_000,
            signed_payload_sha256=digest("signed-payload-b"),
        )
    assert blocked.value.failure is PR199Failure.CANARY_LIMIT


def test_pr199_dispatch_is_unreachable_while_compile_time_disabled(
    tmp_path: Path,
) -> None:
    intent = prepare(tmp_path)
    calls = 0

    class Transport:
        def send(self, **_: object):
            nonlocal calls
            calls += 1
            return {"accepted": True}

    assert COMPILE_TIME_LIVE_SUBMISSION_ENABLED is False
    with pytest.raises(PR199BoundaryError) as disabled:
        boundary(tmp_path).dispatch_once(
            intent=intent,
            signed_payload=b"signed-payload",
            transport=Transport(),
        )
    assert disabled.value.failure is PR199Failure.COMPILE_DISABLED
    assert calls == 0


def test_pr199_ack_is_not_finality_and_finality_requires_chain_evidence(
    tmp_path: Path,
) -> None:
    subject = boundary(tmp_path, clock_ns=10_000_000_000)
    intent = subject.prepare_intent(
        request=request(),
        permit_id="permit-pr199",
        issued_at_block_height=1_000,
        signed_payload_sha256=digest("signed-payload"),
    )
    acknowledged = subject.acknowledge_transport(intent, receipt_hash=digest("jito-ack"))
    assert acknowledged.state is PR199IntentState.ACKNOWLEDGED
    assert acknowledged.state is not PR199IntentState.FINALIZED

    with pytest.raises(PR199BoundaryError) as missing_finality:
        subject.store.transition(
            acknowledged.intent_id,
            expected=PR199IntentState.ACKNOWLEDGED,
            target=PR199IntentState.FINALIZED,
            now_ns=10_000_000_001,
        )
    assert missing_finality.value.failure is PR199Failure.ACK_NOT_FINALITY

    finalized = subject.finalize_from_chain(
        acknowledged,
        finality_evidence_hash=digest("finalized-get-transaction-evidence"),
    )
    assert finalized.state is PR199IntentState.FINALIZED


def test_pr199_status_is_fail_closed() -> None:
    payload = pr199_status_payload()
    assert payload["roadmap_pr"] == "PR-199"
    assert payload["compile_time_live_submission_enabled"] is False
    assert payload["private_key_loader_present"] is False
    assert payload["network_transport_implementation_present"] is False
    assert payload["requires_accepted_pr198_evidence"] is True
    assert payload["ack_is_finality"] is False

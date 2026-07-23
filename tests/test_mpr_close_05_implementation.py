from __future__ import annotations

import hashlib

import pytest

from isolated_signer_service.boundary import (
    InMemoryAuditLog,
    InMemoryNonceStore,
    IsolatedSignerService,
    SignerBoundaryError,
    SignerBoundaryFailure,
    SignerBoundaryRequest,
)
from src.execution.jito_settlement_semantics import (
    JitoSettlementEvidence,
    JitoSettlementState,
    evaluate_jito_settlement,
)
from src.release_gate.mpr_close_05_canary import (
    CanaryLatchEvidence,
    CanaryLatchState,
    HumanApproval,
    UpstreamEvidenceRef,
    evaluate_canary_latches,
)
from src.submission.outbox_mpr_close_05 import (
    DurableSubmissionOutbox,
    SubmissionOutboxError,
    SubmissionOutboxState,
)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


class _Backend:
    def __init__(self) -> None:
        self.messages: list[bytes] = []

    def sign_exact_message(self, message: bytes) -> bytes:
        self.messages.append(message)
        return hashlib.sha512(message).digest()


def _signer_request(message: bytes = b"v0-message", nonce: str = "nonce") -> SignerBoundaryRequest:
    return SignerBoundaryRequest(
        authorization_id="auth-1",
        opportunity_id="opp-1",
        message_sha256=hashlib.sha256(message).hexdigest(),
        policy_identity_hash=_hash("policy"),
        config_generation_hash=_hash("config"),
        reservation_hash=_hash("reservation"),
        requester_identity_hash=_hash("requester"),
        nonce_digest=_hash(nonce),
        issued_at_ns=10,
        not_before_ns=20,
        expires_at_ns=200,
    )


def test_isolated_signer_audits_before_signing_and_denies_replay() -> None:
    backend = _Backend()
    audit = InMemoryAuditLog()
    service = IsolatedSignerService(
        backend=backend,
        nonce_store=InMemoryNonceStore(),
        audit_log=audit,
        clock_ns=lambda: 100,
    )

    receipt = service.sign_authorized_message(
        _signer_request(),
        exact_message_bytes=b"v0-message",
    )

    assert receipt.message_sha256 == hashlib.sha256(b"v0-message").hexdigest()
    assert len(audit.events) == 1
    assert backend.messages == [b"v0-message"]
    with pytest.raises(SignerBoundaryError) as replay:
        service.sign_authorized_message(_signer_request(), exact_message_bytes=b"v0-message")
    assert replay.value.failure is SignerBoundaryFailure.REPLAY


def test_isolated_signer_signs_only_exact_message_bytes() -> None:
    service = IsolatedSignerService(backend=_Backend(), clock_ns=lambda: 100)
    with pytest.raises(SignerBoundaryError) as exc:
        service.sign_authorized_message(
            _signer_request(nonce="nonce-2"),
            exact_message_bytes=b"mutated-message",
        )
    assert exc.value.failure is SignerBoundaryFailure.BAD_MESSAGE_BYTES


def test_submission_outbox_requires_monotonic_non_ack_terminal_flow() -> None:
    outbox = DurableSubmissionOutbox(clock_ns=lambda: 100)
    message_hash = _hash("message")
    intent = outbox.create_intent(
        attempt_id="attempt-1",
        opportunity_id="opp-1",
        message_sha256=message_hash,
        exact_simulation_hash=message_hash,
        reservation_hash=_hash("reservation"),
    )

    assert intent.intent_hash
    outbox.advance("attempt-1", SubmissionOutboxState.SIGNED)
    outbox.record_transport_ack("attempt-1", ack_hash=_hash("ack"))
    assert outbox.state("attempt-1") is SubmissionOutboxState.SUBMITTED
    outbox.advance("attempt-1", SubmissionOutboxState.LANDED)
    outbox.advance("attempt-1", SubmissionOutboxState.CONFIRMED)
    outbox.advance("attempt-1", SubmissionOutboxState.FINALIZED)
    with pytest.raises(SubmissionOutboxError):
        outbox.advance("attempt-1", SubmissionOutboxState.REJECTED)


def _jito_evidence(**overrides: object) -> JitoSettlementEvidence:
    message_hash = _hash("message")
    values = {
        "attempt_id": "attempt-1",
        "message_sha256": message_hash,
        "exact_simulation_hash": message_hash,
        "local_simulation_passed": True,
        "skip_preflight": True,
        "transport_ack_received": True,
        "bundle_id": _hash("bundle"),
        "bundle_status": "Landed",
        "signature_status": "finalized",
        "finalized_reconciliation_hash": _hash("finalized"),
        "finalized_reconciliation_passed": True,
        "tip_lamports": 10_000,
        "minimum_tip_lamports": 1_000,
        "max_tip_lamports": 50_000,
        "tip_in_primary_transaction": True,
        "standalone_tip_transaction": False,
        "unbundling_protection_present": True,
        "uncled_block_protection_present": True,
    }
    values.update(overrides)
    return JitoSettlementEvidence(**values)


def test_jito_ack_and_bundle_id_are_not_settlement() -> None:
    report = evaluate_jito_settlement(
        _jito_evidence(
            signature_status="confirmed",
            finalized_reconciliation_hash=None,
            finalized_reconciliation_passed=False,
        )
    )

    assert report.state is JitoSettlementState.ACK_ONLY
    assert not report.finalized
    assert not report.ack_is_settlement
    assert not report.bundle_id_is_settlement


def test_jito_finalized_requires_exact_simulation_and_tip_safety() -> None:
    finalized = evaluate_jito_settlement(_jito_evidence())
    unsafe = evaluate_jito_settlement(
        _jito_evidence(
            local_simulation_passed=False,
            tip_lamports=100,
            tip_in_primary_transaction=False,
            standalone_tip_transaction=True,
        )
    )

    assert finalized.state is JitoSettlementState.FINALIZED
    assert finalized.finalized
    assert unsafe.state is JitoSettlementState.BLOCKED
    assert {item.code for item in unsafe.blockers} >= {
        "JITO_SKIP_PREFLIGHT_REQUIRES_LOCAL_SIMULATION",
        "JITO_TIP_BELOW_MINIMUM",
        "JITO_STANDALONE_TIP_FORBIDDEN",
    }


def _approval(principal: str, message_hash: str) -> HumanApproval:
    return HumanApproval(
        principal_id=principal,
        approval_hash=_hash("approval:" + principal),
        message_sha256=message_hash,
        issued_at_ns=100,
        expires_at_ns=1_000,
        independent=True,
        fresh=True,
    )


def _canary_evidence(**overrides: object) -> CanaryLatchEvidence:
    message_hash = _hash("message")
    values = {
        "upstream_evidence": tuple(
            UpstreamEvidenceRef(name, _hash(name), accepted=True, fresh=True)
            for name in (
                "MPR-CLOSE-01",
                "MPR-CLOSE-02",
                "MPR-CLOSE-03",
                "MPR-CLOSE-04",
            )
        ),
        "production_cutover_manifest_hash": _hash("cutover"),
        "provider_drift_report_hash": _hash("provider-drift"),
        "exact_message_sha256": message_hash,
        "exact_message_proof_hash": _hash("message-proof"),
        "canary_policy_hash": _hash("canary-policy"),
        "outstanding_attempts_unknown": False,
        "emergency_stop_clear": True,
        "second_human_approval_required": True,
        "approvals": (_approval("alice", message_hash), _approval("bob", message_hash)),
        "capital_cap_lamports": 10_000_000,
        "per_trade_cap_lamports": 1_000_000,
        "daily_loss_cap_lamports": 500_000,
        "requested_capital_lamports": 2_000_000,
        "requested_trade_lamports": 250_000,
        "realized_daily_loss_lamports": 0,
        "automatic_stop_after_first_failure": True,
        "automatic_stop_after_budget_exhausted": True,
        "canary_enabled_by_default": False,
        "unrestricted_live_requested": False,
    }
    values.update(overrides)
    return CanaryLatchEvidence(**values)


def test_canary_latches_allow_only_bounded_default_off_canary() -> None:
    ready = evaluate_canary_latches(_canary_evidence())
    unsafe = evaluate_canary_latches(
        _canary_evidence(canary_enabled_by_default=True, unrestricted_live_requested=True)
    )
    over_budget = evaluate_canary_latches(_canary_evidence(requested_trade_lamports=2_000_000))

    assert ready.state is CanaryLatchState.READY_FOR_BOUNDED_CANARY
    assert ready.canary_allowed
    assert not ready.unrestricted_live_allowed
    assert unsafe.state is CanaryLatchState.BLOCKED
    assert over_budget.state is CanaryLatchState.BLOCKED

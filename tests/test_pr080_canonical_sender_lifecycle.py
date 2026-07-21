from __future__ import annotations

from uuid import UUID

from src.durability import AttemptKey, DurableAttempt, RecoveryAction, RecoveryDecision
from src.execution.models import ExecutionState
from src.submission.canonical_sender import (
    CanonicalSenderSettings,
    CanonicalSubmissionStack,
)
from src.submission.lifecycle_integration import (
    CANONICAL_SUBMISSION_OUTBOX_TOPIC,
    CanonicalSenderAdmissionState,
    CanonicalSenderLifecycleGate,
)
from src.submission.permit_bound import (
    SignedPayload,
    SubmissionAck,
    SubmissionObservation,
    SubmissionPermit,
    SubmissionState,
    TransportKind,
)

HASH = "a" * 64
OTHER_HASH = "b" * 64
WIRE_DIGEST = "c" * 64
SIGNATURE = "1" * 64


class FakeSender:
    async def submit(self, permit, signed_payload, message_hash):
        raise AssertionError("PR-080 gate must not submit during admission")


def _key(generation: int = 1) -> AttemptKey:
    return AttemptKey("opportunity-pr080", HASH, generation)


def _attempt(
    *,
    state: ExecutionState = ExecutionState.SIGNED,
    revision: int = 7,
) -> DurableAttempt:
    key = _key()
    return DurableAttempt(
        attempt_id=key.attempt_id,
        key=key,
        state=state,
        revision=revision,
        message_hash=None,
        reservation_id="reservation-pr080",
        reserved_lamports=1_000_000,
        reservation_state=None,
        transport=None,
        submission_signature=None,
        jito_bundle_id=None,
        updated_at_ns=10,
    )


def _settings(
    *,
    transport: TransportKind = TransportKind.RPC,
    live: bool = False,
) -> CanonicalSenderSettings:
    return CanonicalSenderSettings(
        transport=transport,
        rpc_endpoint="https://api.mainnet-beta.solana.com",
        compile_time_enabled=live,
        config_enabled=live,
        jito_bundle_only=True,
    )


def _payload(*, message_hash: str = HASH) -> SignedPayload:
    return SignedPayload(
        transactions=(b"wire-transaction",),
        message_hashes=(message_hash,),
        signatures=(SIGNATURE,),
        transaction_digests=(WIRE_DIGEST,),
        tip_evidence=None,
    )


def _permit(
    settings: CanonicalSenderSettings,
    payload: SignedPayload,
    *,
    attempt_id: str | None = None,
    message_hash: str = HASH,
) -> SubmissionPermit:
    return SubmissionPermit(
        permit_id=UUID("00000000-0000-0000-0000-000000000080"),
        attempt_id=attempt_id or _key().attempt_id,
        transport=settings.transport,
        message_hash=message_hash,
        payload_digest=payload.payload_digest,
        message_hashes=payload.message_hashes,
        transaction_digests=payload.transaction_digests,
        expected_signatures=payload.signatures,
        issued_at_ns=1,
        expires_at_ns=10_000,
        last_valid_block_height=100,
        min_context_slot=50,
        policy_fingerprint=settings.live_policy().fingerprint,
        tip_evidence_hash=(
            payload.tip_evidence.evidence_hash if payload.tip_evidence else None
        ),
    )


def _stack(settings: CanonicalSenderSettings) -> CanonicalSubmissionStack:
    return CanonicalSubmissionStack(
        sender=FakeSender(),
        issuer=object(),
        status_client=object(),
        transport=settings.transport,
        endpoint_fingerprint=settings.endpoint_fingerprint,
    )


def test_live_gate_closed_by_default_validates_but_blocks_submission() -> None:
    settings = _settings(live=False)
    payload = _payload()
    permit = _permit(settings, payload)

    result = CanonicalSenderLifecycleGate().admit(
        attempt=_attempt(),
        expected_revision=7,
        settings=settings,
        stack=_stack(settings),
        permit=permit,
        signed_payload=payload,
        message_hash=HASH,
        exact_simulation_hash=HASH,
        idempotency_key="submit:pr080",
    )

    assert result.accepted is False
    assert result.state is CanonicalSenderAdmissionState.BLOCKED_LIVE_GATE_CLOSED
    assert result.invocation is None
    assert result.resend_same_payload_allowed is False
    assert result.outbox_topic == CANONICAL_SUBMISSION_OUTBOX_TOPIC


def test_opted_in_gate_returns_exact_sender_invocation_without_submit() -> None:
    settings = _settings(live=True)
    payload = _payload()
    permit = _permit(settings, payload)
    stack = _stack(settings)

    result = CanonicalSenderLifecycleGate(compile_time_live_enabled=True).admit(
        attempt=_attempt(),
        expected_revision=7,
        settings=settings,
        stack=stack,
        permit=permit,
        signed_payload=payload,
        message_hash=HASH,
        exact_simulation_hash=HASH,
        idempotency_key="submit:pr080",
    )

    assert result.accepted is True
    assert result.state is CanonicalSenderAdmissionState.READY_FOR_SENDER
    assert result.invocation is not None
    assert result.invocation.sender is stack.sender
    assert result.invocation.submit_args() == {
        "permit": permit,
        "signed_payload": payload,
        "message_hash": HASH,
    }
    assert result.invocation.to_redacted_dict()["message_hash"] == HASH


def test_identity_mismatch_blocks_before_sender_invocation() -> None:
    settings = _settings(live=True)
    payload = _payload(message_hash=OTHER_HASH)
    permit = _permit(settings, payload, message_hash=OTHER_HASH)

    result = CanonicalSenderLifecycleGate(compile_time_live_enabled=True).admit(
        attempt=_attempt(),
        expected_revision=7,
        settings=settings,
        stack=_stack(settings),
        permit=permit,
        signed_payload=payload,
        message_hash=OTHER_HASH,
        exact_simulation_hash=HASH,
        idempotency_key="submit:pr080",
    )

    assert result.accepted is False
    assert result.state is CanonicalSenderAdmissionState.BLOCKED_IDENTITY_MISMATCH
    assert "MESSAGE_HASH_NOT_EXACT_SIMULATION_HASH" in result.blockers
    assert result.invocation is None


def test_restart_unknown_submission_reconciles_without_resubmission() -> None:
    attempt = _attempt(state=ExecutionState.SUBMISSION_UNCERTAIN)
    decision = RecoveryDecision(
        attempt=attempt,
        action=RecoveryAction.RECONCILE_NO_RESUBMIT,
        reservation_active=True,
        reason="submission may have occurred",
    )

    result = CanonicalSenderLifecycleGate().classify_restart(decision)

    assert result.state is CanonicalSenderAdmissionState.RECONCILE_NO_RESUBMIT
    assert result.durable_state is ExecutionState.RECONCILING
    assert result.resend_same_payload_allowed is False
    assert "STARTUP_RECOVERY_RECONCILE_NO_RESUBMIT" in result.blockers


def test_may_have_submitted_attempt_never_builds_invocation() -> None:
    settings = _settings(live=True)
    payload = _payload()
    permit = _permit(settings, payload)

    result = CanonicalSenderLifecycleGate(compile_time_live_enabled=True).admit(
        attempt=_attempt(state=ExecutionState.ACCEPTED),
        expected_revision=7,
        settings=settings,
        stack=_stack(settings),
        permit=permit,
        signed_payload=payload,
        message_hash=HASH,
        exact_simulation_hash=HASH,
        idempotency_key="submit:pr080",
    )

    assert result.state is CanonicalSenderAdmissionState.RECONCILE_NO_RESUBMIT
    assert result.invocation is None
    assert result.resend_same_payload_allowed is False


def test_transport_ack_cannot_become_landed() -> None:
    ack = SubmissionAck(
        state=SubmissionState.LANDED,
        transport=TransportKind.RPC,
        request_id="ack-1",
        transaction_signatures=(SIGNATURE,),
        bundle_id=None,
        accepted_at_ns=100,
    )

    result = CanonicalSenderLifecycleGate().classify_ack(ack)

    assert (
        result.state is CanonicalSenderAdmissionState.BLOCKED_ACK_CANNOT_PROVE_LANDING
    )
    assert result.durable_state is ExecutionState.RECONCILING
    assert "TRANSPORT_ACK_CANNOT_BE_LANDED" in result.blockers


def test_status_observation_can_prove_landing_but_not_resend() -> None:
    observation = SubmissionObservation(
        state=SubmissionState.LANDED,
        source="getSignatureStatuses",
        observed_at_ns=100,
        slot=123,
        confirmation_status="finalized",
    )

    result = CanonicalSenderLifecycleGate().classify_observation(observation)

    assert result.state is CanonicalSenderAdmissionState.RECONCILE_NO_RESUBMIT
    assert result.durable_state is ExecutionState.LANDED
    assert result.resend_same_payload_allowed is False


def test_jito_sender_requires_bound_exactly_one_tip_evidence() -> None:
    settings = _settings(transport=TransportKind.JITO_SINGLE, live=True)
    payload = _payload()
    permit = _permit(settings, payload)

    result = CanonicalSenderLifecycleGate(compile_time_live_enabled=True).admit(
        attempt=_attempt(),
        expected_revision=7,
        settings=settings,
        stack=_stack(settings),
        permit=permit,
        signed_payload=payload,
        message_hash=HASH,
        exact_simulation_hash=HASH,
        idempotency_key="submit:pr080",
    )

    assert result.state is CanonicalSenderAdmissionState.BLOCKED_JITO_TIP_POLICY
    assert "JITO_REQUIRES_BOUND_EXACTLY_ONE_TIP" in result.blockers
    assert result.invocation is None


def test_stack_duplicate_or_fallback_policy_is_rejected() -> None:
    settings = _settings(live=True)
    payload = _payload()
    permit = _permit(settings, payload)
    unsafe_stack = CanonicalSubmissionStack(
        sender=FakeSender(),
        issuer=object(),
        status_client=object(),
        transport=settings.transport,
        endpoint_fingerprint=settings.endpoint_fingerprint,
        duplicate_submission_allowed=True,
        transport_fallback_allowed=True,
    )

    result = CanonicalSenderLifecycleGate(compile_time_live_enabled=True).admit(
        attempt=_attempt(),
        expected_revision=7,
        settings=settings,
        stack=unsafe_stack,
        permit=permit,
        signed_payload=payload,
        message_hash=HASH,
        exact_simulation_hash=HASH,
        idempotency_key="submit:pr080",
    )

    assert result.state is CanonicalSenderAdmissionState.BLOCKED_IDENTITY_MISMATCH
    assert "STACK_ALLOWS_DUPLICATE_SUBMISSION" in result.blockers
    assert "STACK_ALLOWS_TRANSPORT_FALLBACK" in result.blockers

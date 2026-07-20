"""PR-041 durable journal adapter for the PR-045 submission boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.durability import DurableAttempt, DurableLifecycleStore, LeaseToken
from src.execution.models import ExecutionState

from .permit_bound import (
    ErrorDisposition,
    Sender,
    SignedPayload,
    SubmissionAck,
    SubmissionError,
    SubmissionErrorCode,
    SubmissionObservation,
    SubmissionPermit,
    SubmissionState,
    TransportKind,
    validate_permit_payload,
)


class PermitConsumer(Protocol):
    def consume(self, permit: SubmissionPermit) -> None: ...


@dataclass(frozen=True, slots=True)
class DurableSubmissionResult:
    attempt: DurableAttempt
    ack: SubmissionAck | None
    ambiguous: bool


class PermitBoundSubmissionService:
    """Records intent before transport and never converts an ACK into landing."""

    def __init__(self, store: DurableLifecycleStore) -> None:
        self.store = store

    async def submit(
        self,
        *,
        attempt_id: str,
        expected_revision: int,
        lease: LeaseToken,
        permit: SubmissionPermit,
        payload: SignedPayload,
        message_hash: str,
        sender: Sender,
        idempotency_key: str,
    ) -> DurableSubmissionResult:
        validate_permit_payload(permit, payload, message_hash)
        if permit.transport in {TransportKind.JITO_SINGLE, TransportKind.JITO_BUNDLE}:
            if payload.tip_evidence is None or permit.tip_evidence_hash is None:
                raise SubmissionError(
                    SubmissionErrorCode.TIP_POLICY_INVALID,
                    ErrorDisposition.FATAL,
                    "Jito submission requires bound exactly-one-tip evidence",
                )
        self.store.record_submission_intent(
            attempt_id,
            expected_revision=expected_revision,
            message_hash=message_hash,
            transport=permit.transport.value,
            idempotency_key=f"{idempotency_key}:intent",
            lease=lease,
            submission_signature=payload.signatures[0],
        )
        try:
            ack = await sender.submit(permit, payload, message_hash)
        except SubmissionError as exc:
            target = ExecutionState.SUBMISSION_UNCERTAIN
            current = self.store.get_attempt(attempt_id)
            if current is None:
                raise RuntimeError("durable attempt disappeared") from exc
            updated = self.store.transition(
                attempt_id,
                expected_revision=current.revision,
                target=target,
                idempotency_key=f"{idempotency_key}:transport-error",
                lease=lease,
                reason_code=exc.code.value,
                payload={
                    "disposition": exc.disposition.value,
                    "transport": permit.transport.value,
                    "permit_id": str(permit.permit_id),
                },
            )
            if exc.disposition is ErrorDisposition.FATAL:
                raise
            return DurableSubmissionResult(updated, None, True)
        current = self.store.get_attempt(attempt_id)
        if current is None:
            raise RuntimeError("durable attempt disappeared")
        if ack.state is not SubmissionState.ACCEPTED or ack.landed:
            raise SubmissionError(
                SubmissionErrorCode.MALFORMED_RESPONSE,
                ErrorDisposition.AMBIGUOUS,
                "sender submit must return ACK-only accepted state",
            )
        updated = self.store.transition(
            attempt_id,
            expected_revision=current.revision,
            target=ExecutionState.ACCEPTED,
            idempotency_key=f"{idempotency_key}:ack",
            lease=lease,
            reason_code="TRANSPORT_ACK_ONLY",
            payload={
                "transport": ack.transport.value,
                "request_id": ack.request_id,
                "transaction_signatures": ack.transaction_signatures,
                "bundle_id": ack.bundle_id,
                "permit_id": str(permit.permit_id),
            },
        )
        return DurableSubmissionResult(updated, ack, False)

    def record_observation(
        self,
        *,
        attempt_id: str,
        expected_revision: int,
        lease: LeaseToken,
        observation: SubmissionObservation,
        idempotency_key: str,
    ) -> DurableAttempt:
        payload = {
            "source": observation.source,
            "slot": observation.slot,
            "confirmation_status": observation.confirmation_status,
            "provider_status": observation.provider_status,
            "reason": observation.reason,
        }
        current = self.store.get_attempt(attempt_id)
        if current is None:
            raise RuntimeError("durable attempt disappeared")
        if current.revision != expected_revision:
            raise RuntimeError("durable observation revision changed")
        if (
            observation.state is SubmissionState.LANDED
            and current.state is ExecutionState.ACCEPTED
        ):
            pending = self.store.transition(
                attempt_id,
                expected_revision=current.revision,
                target=ExecutionState.PENDING,
                idempotency_key=f"{idempotency_key}:observed",
                lease=lease,
                reason_code="SUBMISSION_OBSERVED",
                payload=payload,
            )
            return self.store.transition(
                attempt_id,
                expected_revision=pending.revision,
                target=ExecutionState.LANDED,
                idempotency_key=f"{idempotency_key}:landed",
                lease=lease,
                reason_code="SUBMISSION_LANDED",
                payload=payload,
            )
        target = _observation_target(observation)
        return self.store.transition(
            attempt_id,
            expected_revision=current.revision,
            target=target,
            idempotency_key=idempotency_key,
            lease=lease,
            reason_code=f"SUBMISSION_{observation.state.value.upper()}",
            payload=payload,
        )


def _observation_target(observation: SubmissionObservation) -> ExecutionState:
    if observation.state is SubmissionState.LANDED:
        return ExecutionState.LANDED
    if observation.state is SubmissionState.ACCEPTED:
        return ExecutionState.PENDING
    if observation.state is SubmissionState.UNKNOWN:
        return ExecutionState.RECONCILING
    if observation.state is SubmissionState.EXPIRED:
        return ExecutionState.RECONCILING
    if observation.state is SubmissionState.FAILED:
        return ExecutionState.RECONCILING
    raise AssertionError("unhandled observation state")


__all__ = ["DurableSubmissionResult", "PermitBoundSubmissionService"]

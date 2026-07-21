"""PR-080 canonical sender lifecycle integration boundary.

This module composes the existing PR-045/063 permit-bound sender primitives with
the PR-041 durable lifecycle. It is intentionally admission-only: it validates
the exact invocation that a later live runner may pass to ``sender.submit(...)``,
but it never performs network I/O or submits a transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.durability import DurableAttempt, RecoveryAction, RecoveryDecision
from src.execution.models import ExecutionState

from .canonical_sender import CanonicalSenderSettings, CanonicalSubmissionStack
from .permit_bound import (
    Sender,
    SignedPayload,
    SubmissionAck,
    SubmissionError,
    SubmissionObservation,
    SubmissionPermit,
    SubmissionState,
    TransportKind,
    validate_permit_payload,
)

SCHEMA_VERSION = "pr080.canonical-sender-lifecycle.v1"
PR080_LIVE_SENDER_COMPILE_TIME_ENABLED = False
CANONICAL_SUBMISSION_OUTBOX_TOPIC = "submission.reconcile"

_MAY_HAVE_SUBMITTED = frozenset(
    {
        ExecutionState.SUBMISSION_INTENT_RECORDED,
        ExecutionState.SUBMISSION_UNCERTAIN,
        ExecutionState.ACCEPTED,
        ExecutionState.PENDING,
        ExecutionState.LANDED,
        ExecutionState.RECONCILING,
        ExecutionState.SUBMITTED,
    }
)

_JITO_TRANSPORTS = frozenset({TransportKind.JITO_SINGLE, TransportKind.JITO_BUNDLE})


class CanonicalSenderAdmissionState(StrEnum):
    """Machine-readable PR-080 sender/lifecycle admission result."""

    READY_FOR_SENDER = "ready_for_sender"
    BLOCKED_LIVE_GATE_CLOSED = "blocked_live_gate_closed"
    BLOCKED_IDENTITY_MISMATCH = "blocked_identity_mismatch"
    BLOCKED_STACK_MISMATCH = "blocked_stack_mismatch"
    BLOCKED_UNSAFE_LIFECYCLE_STATE = "blocked_unsafe_lifecycle_state"
    BLOCKED_ACK_CANNOT_PROVE_LANDING = "blocked_ack_cannot_prove_landing"
    BLOCKED_JITO_TIP_POLICY = "blocked_jito_tip_policy"
    RECONCILE_NO_RESUBMIT = "reconcile_no_resubmit"


@dataclass(frozen=True, slots=True)
class CanonicalSenderInvocation:
    """Exact arguments that may be passed to the one canonical sender."""

    sender: Sender
    permit: SubmissionPermit
    signed_payload: SignedPayload
    message_hash: str
    attempt_id: str
    expected_revision: int
    idempotency_key: str
    transport: TransportKind
    endpoint_fingerprint: str

    def submit_args(self) -> dict[str, object]:
        return {
            "permit": self.permit,
            "signed_payload": self.signed_payload,
            "message_hash": self.message_hash,
        }

    def to_redacted_dict(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "expected_revision": self.expected_revision,
            "idempotency_key": self.idempotency_key,
            "transport": self.transport.value,
            "endpoint_fingerprint": self.endpoint_fingerprint,
            "permit_id": str(self.permit.permit_id),
            "message_hash": self.message_hash,
            "payload_digest": self.signed_payload.payload_digest,
            "signature_count": len(self.signed_payload.signatures),
        }


@dataclass(frozen=True, slots=True)
class CanonicalSenderAdmissionResult:
    """Offline PR-080 admission decision."""

    schema_version: str
    state: CanonicalSenderAdmissionState
    accepted: bool
    durable_state: ExecutionState
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    invocation: CanonicalSenderInvocation | None = None
    outbox_topic: str = CANONICAL_SUBMISSION_OUTBOX_TOPIC
    resend_same_payload_allowed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "accepted": self.accepted,
            "durable_state": self.durable_state.value,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "invocation": (
                None if self.invocation is None else self.invocation.to_redacted_dict()
            ),
            "outbox_topic": self.outbox_topic,
            "resend_same_payload_allowed": self.resend_same_payload_allowed,
        }


class CanonicalSenderLifecycleGate:
    """Validate the only allowed sender invocation for a durable attempt."""

    def __init__(
        self,
        *,
        compile_time_live_enabled: bool = PR080_LIVE_SENDER_COMPILE_TIME_ENABLED,
    ) -> None:
        self.compile_time_live_enabled = compile_time_live_enabled

    def admit(
        self,
        *,
        attempt: DurableAttempt,
        expected_revision: int,
        settings: CanonicalSenderSettings,
        stack: CanonicalSubmissionStack,
        permit: SubmissionPermit,
        signed_payload: SignedPayload,
        message_hash: str,
        exact_simulation_hash: str,
        idempotency_key: str,
    ) -> CanonicalSenderAdmissionResult:
        blockers: list[str] = []
        warnings: list[str] = []

        if attempt.state in _MAY_HAVE_SUBMITTED:
            return self._result(
                CanonicalSenderAdmissionState.RECONCILE_NO_RESUBMIT,
                ExecutionState.RECONCILING,
                ("DURABLE_ATTEMPT_MAY_HAVE_SUBMITTED",),
                ("restart/status polling must reconcile before any rebuild",),
            )

        if attempt.state is not ExecutionState.SIGNED:
            return self._result(
                CanonicalSenderAdmissionState.BLOCKED_UNSAFE_LIFECYCLE_STATE,
                attempt.state,
                (f"ATTEMPT_STATE_NOT_SIGNED:{attempt.state.value}",),
                (),
            )

        if attempt.revision != expected_revision:
            blockers.append("ATTEMPT_REVISION_MISMATCH")
        if attempt.attempt_id != permit.attempt_id:
            blockers.append("PERMIT_ATTEMPT_MISMATCH")
        if message_hash != exact_simulation_hash:
            blockers.append("MESSAGE_HASH_NOT_EXACT_SIMULATION_HASH")
        if settings.transport is not permit.transport:
            blockers.append("SETTINGS_PERMIT_TRANSPORT_MISMATCH")
        if stack.transport is not permit.transport:
            blockers.append("STACK_PERMIT_TRANSPORT_MISMATCH")
        if stack.endpoint_fingerprint != settings.endpoint_fingerprint:
            blockers.append("STACK_ENDPOINT_FINGERPRINT_MISMATCH")
        if stack.duplicate_submission_allowed:
            blockers.append("STACK_ALLOWS_DUPLICATE_SUBMISSION")
        if stack.transport_fallback_allowed:
            blockers.append("STACK_ALLOWS_TRANSPORT_FALLBACK")
        if not idempotency_key.strip():
            blockers.append("IDEMPOTENCY_KEY_MISSING")

        try:
            validate_permit_payload(permit, signed_payload, message_hash)
        except SubmissionError as exc:
            blockers.append(f"PERMIT_PAYLOAD_INVALID:{exc.code.value}")

        if permit.transport in _JITO_TRANSPORTS and (
            permit.tip_evidence_hash is None or signed_payload.tip_evidence is None
        ):
            return self._result(
                CanonicalSenderAdmissionState.BLOCKED_JITO_TIP_POLICY,
                attempt.state,
                ("JITO_REQUIRES_BOUND_EXACTLY_ONE_TIP", *tuple(blockers)),
                tuple(warnings),
            )

        if blockers:
            return self._result(
                CanonicalSenderAdmissionState.BLOCKED_IDENTITY_MISMATCH,
                attempt.state,
                tuple(blockers),
                tuple(warnings),
            )

        if not self.compile_time_live_enabled or not settings.live_policy().enabled:
            return self._result(
                CanonicalSenderAdmissionState.BLOCKED_LIVE_GATE_CLOSED,
                attempt.state,
                ("LIVE_SENDER_COMPILE_TIME_OR_CONFIG_GATE_CLOSED",),
                tuple(warnings),
            )

        invocation = CanonicalSenderInvocation(
            sender=stack.sender,
            permit=permit,
            signed_payload=signed_payload,
            message_hash=message_hash,
            attempt_id=attempt.attempt_id,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            transport=permit.transport,
            endpoint_fingerprint=stack.endpoint_fingerprint,
        )
        return CanonicalSenderAdmissionResult(
            schema_version=SCHEMA_VERSION,
            state=CanonicalSenderAdmissionState.READY_FOR_SENDER,
            accepted=True,
            durable_state=ExecutionState.SUBMISSION_INTENT_RECORDED,
            blockers=(),
            warnings=tuple(warnings),
            invocation=invocation,
        )

    def classify_ack(self, ack: SubmissionAck) -> CanonicalSenderAdmissionResult:
        """A transport ACK can only move to accepted/pending reconciliation."""

        if ack.landed or ack.state is SubmissionState.LANDED:
            return self._result(
                CanonicalSenderAdmissionState.BLOCKED_ACK_CANNOT_PROVE_LANDING,
                ExecutionState.RECONCILING,
                ("TRANSPORT_ACK_CANNOT_BE_LANDED",),
                (),
            )
        if ack.state is not SubmissionState.ACCEPTED:
            return self._result(
                CanonicalSenderAdmissionState.RECONCILE_NO_RESUBMIT,
                ExecutionState.RECONCILING,
                (f"ACK_STATE_REQUIRES_RECONCILIATION:{ack.state.value}",),
                (),
            )
        return CanonicalSenderAdmissionResult(
            schema_version=SCHEMA_VERSION,
            state=CanonicalSenderAdmissionState.RECONCILE_NO_RESUBMIT,
            accepted=False,
            durable_state=ExecutionState.ACCEPTED,
            blockers=(),
            warnings=("ack is not landing proof; continue status polling",),
        )

    def classify_observation(
        self,
        observation: SubmissionObservation,
    ) -> CanonicalSenderAdmissionResult:
        """Status polling may prove landing, but never permits same-payload resend."""

        if observation.state is SubmissionState.LANDED:
            durable_state = ExecutionState.LANDED
            warnings: tuple[str, ...] = ()
        else:
            durable_state = ExecutionState.RECONCILING
            warnings = ("non-landed status requires reconcile/no-resubmit",)
        return CanonicalSenderAdmissionResult(
            schema_version=SCHEMA_VERSION,
            state=CanonicalSenderAdmissionState.RECONCILE_NO_RESUBMIT,
            accepted=False,
            durable_state=durable_state,
            blockers=(),
            warnings=warnings,
        )

    def classify_restart(
        self,
        decision: RecoveryDecision,
    ) -> CanonicalSenderAdmissionResult:
        if decision.action is RecoveryAction.RECONCILE_NO_RESUBMIT:
            return self._result(
                CanonicalSenderAdmissionState.RECONCILE_NO_RESUBMIT,
                ExecutionState.RECONCILING,
                ("STARTUP_RECOVERY_RECONCILE_NO_RESUBMIT",),
                (decision.reason,),
            )
        return self._result(
            CanonicalSenderAdmissionState.BLOCKED_UNSAFE_LIFECYCLE_STATE,
            decision.attempt.state,
            (f"STARTUP_RECOVERY_ACTION_NOT_SENDER:{decision.action.value}",),
            (decision.reason,),
        )

    @staticmethod
    def _result(
        state: CanonicalSenderAdmissionState,
        durable_state: ExecutionState,
        blockers: tuple[str, ...],
        warnings: tuple[str, ...],
    ) -> CanonicalSenderAdmissionResult:
        return CanonicalSenderAdmissionResult(
            schema_version=SCHEMA_VERSION,
            state=state,
            accepted=False,
            durable_state=durable_state,
            blockers=blockers,
            warnings=warnings,
        )


__all__ = [
    "CANONICAL_SUBMISSION_OUTBOX_TOPIC",
    "PR080_LIVE_SENDER_COMPILE_TIME_ENABLED",
    "SCHEMA_VERSION",
    "CanonicalSenderAdmissionResult",
    "CanonicalSenderAdmissionState",
    "CanonicalSenderInvocation",
    "CanonicalSenderLifecycleGate",
]

"""Fail-closed isolated signer and submission coordination boundary."""

from __future__ import annotations

from collections.abc import Mapping
import time
from typing import Protocol

from .models import (
    COMPILE_TIME_SUBMISSION_ENABLED,
    ActivationBundle,
    ApprovalVerifier,
    BoundaryFailure,
    IntentRecord,
    KillSwitchState,
    MessageReview,
    PermitVerifier,
    PR08BoundaryError,
    SignerPolicy,
    SubmissionPermit,
    TransportKind,
    hash_json,
    sha256,
)
from .store import DurableSubmissionIntentStore


class SubmissionTransport(Protocol):
    def send(
        self, *, intent: IntentRecord, signed_wire: bytes
    ) -> Mapping[str, object]: ...


class IsolatedSignerBoundary:
    def __init__(
        self,
        store: DurableSubmissionIntentStore,
        *,
        approval_verifier: ApprovalVerifier,
        permit_verifier: PermitVerifier,
        clock_ns=time.time_ns,
    ) -> None:
        self.store = store
        self.approval_verifier = approval_verifier
        self.permit_verifier = permit_verifier
        self.clock_ns = clock_ns

    def prepare(
        self,
        *,
        activation: ActivationBundle,
        policy: SignerPolicy,
        kill_switch: KillSwitchState,
        permit: SubmissionPermit,
        review: MessageReview,
        signed_wire_sha256: str,
    ) -> IntentRecord:
        now_ns = int(self.clock_ns())
        activation.validate(self.approval_verifier)
        self._kill_switch(kill_switch, permit.signer_identity)
        self._bindings(activation, policy, permit, review, now_ns)
        self._limits(policy, permit.transport, review)
        if not self.permit_verifier(permit):
            raise PR08BoundaryError(
                BoundaryFailure.APPROVAL_INVALID,
                "one-time permit authority rejected permit",
            )
        sha256(signed_wire_sha256, "signed_wire_sha256")
        request_hash = hash_json(
            {
                "domain": "studious-pancake/pr08/send-request",
                "permit_hash": permit.permit_hash,
                "message_sha256": review.message_sha256,
                "signed_wire_sha256": signed_wire_sha256,
            }
        )
        return self.store.prepare(permit, request_hash=request_hash, now_ns=now_ns)

    def dispatch_once(
        self,
        *,
        intent: IntentRecord,
        signed_wire: bytes,
        transport: SubmissionTransport,
    ) -> Mapping[str, object]:
        del intent, signed_wire, transport
        if not COMPILE_TIME_SUBMISSION_ENABLED:
            raise PR08BoundaryError(
                BoundaryFailure.COMPILE_DISABLED,
                "roadmap PR-08 submission is compile-time disabled",
            )
        raise AssertionError("unreachable while submission is disabled")

    @staticmethod
    def _kill_switch(state: KillSwitchState, signer_identity: str) -> None:
        if state.active:
            raise PR08BoundaryError(
                BoundaryFailure.KILL_SWITCH, "submission kill switch is active"
            )
        if signer_identity in state.revoked_signers:
            raise PR08BoundaryError(
                BoundaryFailure.SIGNER_REVOKED, "signer identity is revoked"
            )

    @staticmethod
    def _bindings(
        activation: ActivationBundle,
        policy: SignerPolicy,
        permit: SubmissionPermit,
        review: MessageReview,
        now_ns: int,
    ) -> None:
        checks = (
            permit.signer_identity
            == activation.signer_identity
            == policy.signer_identity,
            permit.release_id == activation.release_id == review.release_id,
            permit.policy_bundle_hash
            == activation.policy_bundle_hash
            == review.policy_bundle_hash,
            permit.signer_policy_hash == policy.policy_hash,
            permit.activation_hash == activation.activation_hash,
            permit.attempt_id == review.attempt_id,
            permit.generation == review.generation,
            permit.message_sha256 == review.message_sha256,
            permit.review_hash == review.review_hash,
        )
        if not all(checks):
            raise PR08BoundaryError(
                BoundaryFailure.BINDING_INVALID,
                "permit, activation, policy and message identities differ",
            )
        if now_ns >= permit.expires_at_ns:
            raise PR08BoundaryError(
                BoundaryFailure.PERMIT_EXPIRED, "submission permit expired"
            )

    @staticmethod
    def _limits(
        policy: SignerPolicy, transport: TransportKind, review: MessageReview
    ) -> None:
        if transport not in policy.transports:
            raise PR08BoundaryError(
                BoundaryFailure.POLICY_LIMIT, "transport is not allowlisted"
            )
        if review.payer not in policy.payers:
            raise PR08BoundaryError(
                BoundaryFailure.POLICY_LIMIT, "payer is not allowlisted"
            )
        if not set(review.required_signers).issubset(policy.signers):
            raise PR08BoundaryError(
                BoundaryFailure.POLICY_LIMIT, "signers are not allowlisted"
            )
        if not set(review.program_ids).issubset(policy.programs):
            raise PR08BoundaryError(
                BoundaryFailure.POLICY_LIMIT, "programs are not allowlisted"
            )
        actual = (
            review.spend_lamports,
            review.network_fee_lamports,
            review.priority_fee_lamports,
            review.jito_tip_lamports,
            review.instruction_count,
            len(review.writable_accounts),
            review.wire_size_bytes,
        )
        if any(value > limit for value, limit in zip(actual, policy.limits)):
            raise PR08BoundaryError(
                BoundaryFailure.POLICY_LIMIT, "reviewed message exceeds signer limits"
            )
        if transport is TransportKind.JITO_SINGLE and review.jito_tip_lamports <= 0:
            raise PR08BoundaryError(
                BoundaryFailure.POLICY_LIMIT,
                "Jito transport requires a positive same-message tip",
            )
        if transport is TransportKind.RPC and review.jito_tip_lamports != 0:
            raise PR08BoundaryError(
                BoundaryFailure.POLICY_LIMIT,
                "RPC transport cannot carry a Jito tip",
            )

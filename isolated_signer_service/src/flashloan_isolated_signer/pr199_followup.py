"""PR-199 follow-up gates for signer IPC, finality and canary evidence.

This module extends the fail-closed PR-199 scaffold without adding a private-key
loader, signer implementation, Jito/RPC sender, or live activation.  It models
the evidence that must exist before a future production runtime is allowed to
hand a signed payload to any transport.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .pr199 import (
    COMPILE_TIME_LIVE_SUBMISSION_ENABLED,
    PR199AuthorizationRequest,
    PR199BoundaryError,
    PR199Failure,
    PR199IntentRecord,
    PR199IntentState,
    PR199SubmissionBoundary,
    hash_json,
    identifier,
    sha256,
)


class PR199FinalityOutcome(StrEnum):
    """Settlement outcomes after finalized-chain reconciliation."""

    FINALIZED_SUCCESS = "finalized_success"
    FINALIZED_FAILURE = "finalized_failure"


@dataclass(frozen=True, slots=True)
class PR199SignerIsolationEvidence:
    """Evidence that the signer is a policy service, not a key in runtime."""

    release_id: str
    config_generation_hash: str
    signer_identity: str
    signer_policy_hash: str
    ipc_protocol_hash: str
    key_authority_hash: str
    process_generation: int
    separate_process: bool
    runtime_holds_private_key: bool
    signer_allows_general_network: bool
    signer_allows_filesystem_wallet: bool
    signer_allows_env_private_key: bool
    signer_policy_enforced: bool

    def __post_init__(self) -> None:
        identifier(self.release_id, "release_id")
        identifier(self.signer_identity, "signer_identity")
        for value, field in (
            (self.config_generation_hash, "config_generation_hash"),
            (self.signer_policy_hash, "signer_policy_hash"),
            (self.ipc_protocol_hash, "ipc_protocol_hash"),
            (self.key_authority_hash, "key_authority_hash"),
        ):
            sha256(value, field)
        if self.process_generation < 1:
            raise ValueError("process_generation must be positive")
        unsafe = (
            not self.separate_process,
            self.runtime_holds_private_key,
            self.signer_allows_general_network,
            self.signer_allows_filesystem_wallet,
            self.signer_allows_env_private_key,
            not self.signer_policy_enforced,
        )
        if any(unsafe):
            raise PR199BoundaryError(
                PR199Failure.POLICY_LIMIT,
                "PR-199 signer isolation evidence is not fail-closed",
            )

    @property
    def isolation_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr199/signer-isolation-evidence",
                "release_id": self.release_id,
                "config_generation_hash": self.config_generation_hash,
                "signer_identity": self.signer_identity,
                "signer_policy_hash": self.signer_policy_hash,
                "ipc_protocol_hash": self.ipc_protocol_hash,
                "key_authority_hash": self.key_authority_hash,
                "process_generation": self.process_generation,
                "separate_process": self.separate_process,
                "runtime_holds_private_key": self.runtime_holds_private_key,
                "signer_allows_general_network": self.signer_allows_general_network,
                "signer_allows_filesystem_wallet": self.signer_allows_filesystem_wallet,
                "signer_allows_env_private_key": self.signer_allows_env_private_key,
                "signer_policy_enforced": self.signer_policy_enforced,
            }
        )


@dataclass(frozen=True, slots=True)
class PR199SignerRequestEnvelope:
    """IPC request digest that binds signer policy to the exact permit."""

    authorization: PR199AuthorizationRequest
    permit_hash: str
    signer_isolation_hash: str
    signer_session_id: str
    caller_identity_hash: str
    requested_at_block_height: int

    def __post_init__(self) -> None:
        sha256(self.permit_hash, "permit_hash")
        sha256(self.signer_isolation_hash, "signer_isolation_hash")
        sha256(self.caller_identity_hash, "caller_identity_hash")
        identifier(self.signer_session_id, "signer_session_id")
        if self.requested_at_block_height < 0:
            raise ValueError("requested_at_block_height must be non-negative")
        if self.requested_at_block_height >= self.authorization.expires_at_block_height:
            raise PR199BoundaryError(
                PR199Failure.AUTHORIZATION_BINDING,
                "signer request is already expired at requested block height",
            )

    @property
    def signer_request_digest(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr199/signer-request-envelope",
                "authorization_digest": self.authorization.authorization_digest,
                "permit_hash": self.permit_hash,
                "signer_isolation_hash": self.signer_isolation_hash,
                "signer_session_id": self.signer_session_id,
                "caller_identity_hash": self.caller_identity_hash,
                "requested_at_block_height": self.requested_at_block_height,
            }
        )


@dataclass(frozen=True, slots=True)
class PR199SignedPayloadBinding:
    """Signer response evidence before any sender is allowed to run."""

    signer_request_digest: str
    authorization_digest: str
    message_sha256: str
    signed_payload_sha256: str
    signature_set_hash: str
    signer_identity: str
    signer_isolation_hash: str
    signed_at_block_height: int

    def __post_init__(self) -> None:
        for value, field in (
            (self.signer_request_digest, "signer_request_digest"),
            (self.authorization_digest, "authorization_digest"),
            (self.message_sha256, "message_sha256"),
            (self.signed_payload_sha256, "signed_payload_sha256"),
            (self.signature_set_hash, "signature_set_hash"),
            (self.signer_isolation_hash, "signer_isolation_hash"),
        ):
            sha256(value, field)
        identifier(self.signer_identity, "signer_identity")
        if self.signed_at_block_height < 0:
            raise ValueError("signed_at_block_height must be non-negative")

    @property
    def binding_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr199/signed-payload-binding",
                "signer_request_digest": self.signer_request_digest,
                "authorization_digest": self.authorization_digest,
                "message_sha256": self.message_sha256,
                "signed_payload_sha256": self.signed_payload_sha256,
                "signature_set_hash": self.signature_set_hash,
                "signer_identity": self.signer_identity,
                "signer_isolation_hash": self.signer_isolation_hash,
                "signed_at_block_height": self.signed_at_block_height,
            }
        )

    def assert_matches(
        self,
        *,
        intent: PR199IntentRecord,
        envelope: PR199SignerRequestEnvelope,
        isolation: PR199SignerIsolationEvidence,
    ) -> None:
        if self.signer_request_digest != envelope.signer_request_digest:
            raise PR199BoundaryError(
                PR199Failure.AUTHORIZATION_BINDING,
                "signed payload is not bound to the reviewed signer request",
            )
        if self.authorization_digest != intent.authorization_digest:
            raise PR199BoundaryError(
                PR199Failure.AUTHORIZATION_BINDING,
                "signed payload authorization differs from durable intent",
            )
        if self.message_sha256 != intent.message_sha256:
            raise PR199BoundaryError(
                PR199Failure.AUTHORIZATION_BINDING,
                "signed payload message differs from durable intent",
            )
        if self.signed_payload_sha256 != intent.signed_payload_sha256:
            raise PR199BoundaryError(
                PR199Failure.AUTHORIZATION_BINDING,
                "signed payload hash differs from durable intent",
            )
        if self.signer_identity != isolation.signer_identity:
            raise PR199BoundaryError(
                PR199Failure.AUTHORIZATION_BINDING,
                "signed payload came from an unexpected signer identity",
            )
        if self.signer_isolation_hash != isolation.isolation_hash:
            raise PR199BoundaryError(
                PR199Failure.AUTHORIZATION_BINDING,
                "signed payload is not bound to current signer isolation evidence",
            )


@dataclass(frozen=True, slots=True)
class PR199FinalizedChainEvidence:
    """Finalized chain truth required before ACK/PENDING becomes settlement."""

    attempt_id: str
    authorization_digest: str
    message_sha256: str
    signed_payload_sha256: str
    signature_status_hash: str
    transaction_record_hash: str
    token_balance_delta_hash: str
    status_history_searched: bool
    get_transaction_finalized: bool
    landed_as_single_transaction: bool
    flash_repayment_verified: bool
    min_context_slot: int
    landed_slot: int
    finalized_slot: int
    charged_fee_lamports: int
    settled_native_delta_lamports: int
    transaction_error_code: str | None = None
    jito_ack_hash: str | None = None

    def __post_init__(self) -> None:
        identifier(self.attempt_id, "attempt_id")
        if self.transaction_error_code is not None:
            identifier(self.transaction_error_code, "transaction_error_code")
        for value, field in (
            (self.authorization_digest, "authorization_digest"),
            (self.message_sha256, "message_sha256"),
            (self.signed_payload_sha256, "signed_payload_sha256"),
            (self.signature_status_hash, "signature_status_hash"),
            (self.transaction_record_hash, "transaction_record_hash"),
            (self.token_balance_delta_hash, "token_balance_delta_hash"),
        ):
            sha256(value, field)
        if self.jito_ack_hash is not None:
            sha256(self.jito_ack_hash, "jito_ack_hash")
        if min(self.min_context_slot, self.landed_slot, self.finalized_slot) < 0:
            raise ValueError("slots must be non-negative")
        if self.finalized_slot < self.landed_slot:
            raise ValueError("finalized_slot must be >= landed_slot")
        if self.landed_slot < self.min_context_slot:
            raise ValueError("landed_slot must be >= min_context_slot")
        if self.charged_fee_lamports < 0:
            raise ValueError("charged_fee_lamports must be non-negative")

    @property
    def evidence_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr199/finalized-chain-evidence",
                "attempt_id": self.attempt_id,
                "authorization_digest": self.authorization_digest,
                "message_sha256": self.message_sha256,
                "signed_payload_sha256": self.signed_payload_sha256,
                "signature_status_hash": self.signature_status_hash,
                "transaction_record_hash": self.transaction_record_hash,
                "token_balance_delta_hash": self.token_balance_delta_hash,
                "status_history_searched": self.status_history_searched,
                "get_transaction_finalized": self.get_transaction_finalized,
                "landed_as_single_transaction": self.landed_as_single_transaction,
                "flash_repayment_verified": self.flash_repayment_verified,
                "min_context_slot": self.min_context_slot,
                "landed_slot": self.landed_slot,
                "finalized_slot": self.finalized_slot,
                "charged_fee_lamports": self.charged_fee_lamports,
                "settled_native_delta_lamports": self.settled_native_delta_lamports,
                "transaction_error_code": self.transaction_error_code,
                "jito_ack_hash": self.jito_ack_hash,
            }
        )

    def assert_matches(
        self, *, intent: PR199IntentRecord, binding: PR199SignedPayloadBinding
    ) -> None:
        if not self.status_history_searched or not self.get_transaction_finalized:
            raise PR199BoundaryError(
                PR199Failure.ACK_NOT_FINALITY,
                "finality requires history search and finalized getTransaction evidence",
            )
        if not self.landed_as_single_transaction:
            raise PR199BoundaryError(
                PR199Failure.ACK_NOT_FINALITY,
                "flash-loan settlement must reconcile one atomic transaction",
            )
        if self.attempt_id != intent.attempt_id:
            raise PR199BoundaryError(
                PR199Failure.AUTHORIZATION_BINDING,
                "finalized chain record belongs to a different attempt",
            )
        if self.authorization_digest != binding.authorization_digest:
            raise PR199BoundaryError(
                PR199Failure.AUTHORIZATION_BINDING,
                "finalized chain record has a different authorization digest",
            )
        if self.message_sha256 != binding.message_sha256:
            raise PR199BoundaryError(
                PR199Failure.AUTHORIZATION_BINDING,
                "finalized chain record has a different message hash",
            )
        if self.signed_payload_sha256 != binding.signed_payload_sha256:
            raise PR199BoundaryError(
                PR199Failure.AUTHORIZATION_BINDING,
                "finalized chain record has a different signed payload hash",
            )
        if self.transaction_error_code is None and not self.flash_repayment_verified:
            raise PR199BoundaryError(
                PR199Failure.ACK_NOT_FINALITY,
                "successful finalized settlement requires flash repayment evidence",
            )


@dataclass(frozen=True, slots=True)
class PR199ReconciliationReport:
    intent_id: str
    attempt_id: str
    outcome: PR199FinalityOutcome
    finality_evidence_hash: str
    updated_state: PR199IntentState
    charged_fee_lamports: int
    settled_native_delta_lamports: int
    requires_operator_escalation: bool
    jito_ack_hash: str | None


@dataclass(frozen=True, slots=True)
class PR199OperatorCanaryGate:
    """Manual operator gate for the first bounded canary intent."""

    release_id: str
    config_generation_hash: str
    policy_bundle_hash: str
    canary_limits_hash: str
    signer_isolation_hash: str
    pr198_acceptance_hash: str
    approval_digest: str
    approved_by_hash: str
    approval_expires_at_block_height: int
    outstanding_intents: int
    unknown_intents: int
    emergency_latch_cleared: bool

    def __post_init__(self) -> None:
        identifier(self.release_id, "release_id")
        for value, field in (
            (self.config_generation_hash, "config_generation_hash"),
            (self.policy_bundle_hash, "policy_bundle_hash"),
            (self.canary_limits_hash, "canary_limits_hash"),
            (self.signer_isolation_hash, "signer_isolation_hash"),
            (self.pr198_acceptance_hash, "pr198_acceptance_hash"),
            (self.approval_digest, "approval_digest"),
            (self.approved_by_hash, "approved_by_hash"),
        ):
            sha256(value, field)
        if self.approval_expires_at_block_height < 0:
            raise ValueError("approval expiry must be non-negative")
        if self.outstanding_intents < 0 or self.unknown_intents < 0:
            raise ValueError("intent counters must be non-negative")

    @property
    def gate_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr199/operator-canary-gate",
                "release_id": self.release_id,
                "config_generation_hash": self.config_generation_hash,
                "policy_bundle_hash": self.policy_bundle_hash,
                "canary_limits_hash": self.canary_limits_hash,
                "signer_isolation_hash": self.signer_isolation_hash,
                "pr198_acceptance_hash": self.pr198_acceptance_hash,
                "approval_digest": self.approval_digest,
                "approved_by_hash": self.approved_by_hash,
                "approval_expires_at_block_height": self.approval_expires_at_block_height,
                "outstanding_intents": self.outstanding_intents,
                "unknown_intents": self.unknown_intents,
                "emergency_latch_cleared": self.emergency_latch_cleared,
            }
        )

    def assert_ready(self, *, current_block_height: int) -> None:
        if current_block_height >= self.approval_expires_at_block_height:
            raise PR199BoundaryError(
                PR199Failure.CANARY_LIMIT,
                "operator canary approval is expired",
            )
        if self.outstanding_intents != 0 or self.unknown_intents != 0:
            raise PR199BoundaryError(
                PR199Failure.CANARY_LIMIT,
                "operator canary gate requires zero outstanding and UNKNOWN attempts",
            )
        if not self.emergency_latch_cleared:
            raise PR199BoundaryError(
                PR199Failure.CANARY_LIMIT,
                "operator canary gate is blocked by emergency latch",
            )


def reconcile_finalized_attempt(
    *,
    boundary: PR199SubmissionBoundary,
    intent: PR199IntentRecord,
    binding: PR199SignedPayloadBinding,
    finality: PR199FinalizedChainEvidence,
) -> PR199ReconciliationReport:
    """Move ACK/UNKNOWN to FINALIZED only from finalized chain evidence."""

    finality.assert_matches(intent=intent, binding=binding)
    updated = boundary.finalize_from_chain(
        intent, finality_evidence_hash=finality.evidence_hash
    )
    if finality.transaction_error_code is None:
        outcome = PR199FinalityOutcome.FINALIZED_SUCCESS
        escalation = False
    else:
        outcome = PR199FinalityOutcome.FINALIZED_FAILURE
        escalation = True
    return PR199ReconciliationReport(
        intent_id=updated.intent_id,
        attempt_id=updated.attempt_id,
        outcome=outcome,
        finality_evidence_hash=finality.evidence_hash,
        updated_state=updated.state,
        charged_fee_lamports=finality.charged_fee_lamports,
        settled_native_delta_lamports=finality.settled_native_delta_lamports,
        requires_operator_escalation=escalation,
        jito_ack_hash=finality.jito_ack_hash,
    )


def pr199_followup_status_payload() -> dict[str, object]:
    return {
        "schema_version": "roadmap-pr199.finality-reconciliation-followup.v1",
        "roadmap_pr": "PR-199",
        "compile_time_live_submission_enabled": COMPILE_TIME_LIVE_SUBMISSION_ENABLED,
        "signer_ipc_policy_evidence_required": True,
        "finality_requires_history_search": True,
        "finality_requires_get_transaction_finalized": True,
        "ack_or_bundle_id_is_settlement": False,
        "operator_canary_gate_required": True,
        "live_transport_implementation_present": False,
    }

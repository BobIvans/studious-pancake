"""PR-211 signer authorization, durable outbox and finality gate.

This module is intentionally offline. It does not import Solana RPC clients,
keypair/signing code or transaction senders. It models the Pass 6 PR-211
acceptance boundary so stale, hash-only or caller-supplied evidence cannot be
promoted as signer/outbox/finality truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Mapping

SCHEMA_VERSION = "pr211.signer-outbox-finality-gate.v1"
LIVE_EXECUTION_ALLOWED = False
SIGNER_IMPORT_ALLOWED = False
SENDER_IMPORT_ALLOWED = False

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=-]{0,127}$")


class PR211Blocker(StrEnum):
    """Stable blocker codes for the PR-211 acceptance gate."""

    PR210_NOT_ACCEPTED = "PR210_NOT_ACCEPTED"
    LIVE_OR_SENDER_REACHABLE = "LIVE_OR_SENDER_REACHABLE"
    SIGNED_AFTER_AUTHORIZATION_EXPIRY = "SIGNED_AFTER_AUTHORIZATION_EXPIRY"
    SIGNED_BEFORE_AUTHORIZATION_NOT_BEFORE = "SIGNED_BEFORE_AUTHORIZATION_NOT_BEFORE"
    CURRENT_HEIGHT_TOO_CLOSE_TO_EXPIRY = "CURRENT_HEIGHT_TOO_CLOSE_TO_EXPIRY"
    SIGNATURES_NOT_LOCALLY_VERIFIED = "SIGNATURES_NOT_LOCALLY_VERIFIED"
    SIGNATURE_SET_HASH_ONLY = "SIGNATURE_SET_HASH_ONLY"
    APPROVAL_NOT_CRYPTOGRAPHIC = "APPROVAL_NOT_CRYPTOGRAPHIC"
    APPROVAL_EXPIRED_OR_NOT_YET_VALID = "APPROVAL_EXPIRED_OR_NOT_YET_VALID"
    APPROVER_THRESHOLD_NOT_MET = "APPROVER_THRESHOLD_NOT_MET"
    OUTBOX_PROTOCOL_INCOMPLETE = "OUTBOX_PROTOCOL_INCOMPLETE"
    OUTBOX_ALLOWS_BLIND_RESEND = "OUTBOX_ALLOWS_BLIND_RESEND"
    FINALITY_NOT_MATERIALIZED = "FINALITY_NOT_MATERIALIZED"
    FINALITY_CONTEXT_MISMATCH = "FINALITY_CONTEXT_MISMATCH"
    LANDED_FEE_NOT_AUTHORITATIVE = "LANDED_FEE_NOT_AUTHORITATIVE"
    FINALITY_STATUS_CONTRADICTS_ERROR = "FINALITY_STATUS_CONTRADICTS_ERROR"
    CRASH_MATRIX_INCOMPLETE = "CRASH_MATRIX_INCOMPLETE"


class PR211EvidenceError(ValueError):
    """Raised when PR-211 evidence is malformed."""


@dataclass(frozen=True, slots=True)
class SignatureVerificationEvidence:
    """Local verification result over exact message bytes.

    A naked signature-set hash is not sufficient. Evidence must bind the exact
    message digest, signer identities, individual signature digests and a
    verifier provenance hash.
    """

    exact_message_sha256: str
    signature_verifier_sha256: str
    signer_public_key_hashes: tuple[str, ...]
    signature_sha256s: tuple[str, ...]
    all_signatures_verified: bool
    signature_set_hash_only: bool = False

    def __post_init__(self) -> None:
        _sha256(self.exact_message_sha256, "exact_message_sha256")
        _sha256(self.signature_verifier_sha256, "signature_verifier_sha256")
        _tuple_of_hashes(self.signer_public_key_hashes, "signer_public_key_hashes")
        _tuple_of_hashes(self.signature_sha256s, "signature_sha256s")
        if not self.signer_public_key_hashes:
            raise PR211EvidenceError("at least one signer public key hash is required")
        if len(self.signer_public_key_hashes) != len(self.signature_sha256s):
            raise PR211EvidenceError("one verified signature is required per signer")


@dataclass(frozen=True, slots=True)
class SignedPayloadAuthorization:
    """Authorization timeline for one exact signed payload."""

    request_id: str
    authorization_sha256: str
    exact_message_sha256: str
    not_before_block_height: int
    requested_block_height: int
    signed_at_block_height: int
    expires_at_block_height: int
    current_block_height: int
    safety_margin_blocks: int
    signature_verification: SignatureVerificationEvidence

    def __post_init__(self) -> None:
        _identifier(self.request_id, "request_id")
        _sha256(self.authorization_sha256, "authorization_sha256")
        _sha256(self.exact_message_sha256, "exact_message_sha256")
        _non_negative_int(self.not_before_block_height, "not_before_block_height")
        _non_negative_int(self.requested_block_height, "requested_block_height")
        _non_negative_int(self.signed_at_block_height, "signed_at_block_height")
        _non_negative_int(self.expires_at_block_height, "expires_at_block_height")
        _non_negative_int(self.current_block_height, "current_block_height")
        _non_negative_int(self.safety_margin_blocks, "safety_margin_blocks")


@dataclass(frozen=True, slots=True)
class ApprovalSignatureEvidence:
    """Cryptographic manual approval evidence for canary/live review."""

    approval_payload_sha256: str
    release_set_sha256: str
    policy_bundle_sha256: str
    canary_limits_sha256: str
    required_threshold: int
    verified_signature_count: int
    distinct_approver_principal_hashes: tuple[str, ...]
    approver_role_hashes: tuple[str, ...]
    threshold_signatures_verified: bool
    not_before_ms: int
    expires_at_ms: int
    evaluated_at_ms: int
    hash_only_approval: bool = False

    def __post_init__(self) -> None:
        _sha256(self.approval_payload_sha256, "approval_payload_sha256")
        _sha256(self.release_set_sha256, "release_set_sha256")
        _sha256(self.policy_bundle_sha256, "policy_bundle_sha256")
        _sha256(self.canary_limits_sha256, "canary_limits_sha256")
        _positive_int(self.required_threshold, "required_threshold")
        _non_negative_int(self.verified_signature_count, "verified_signature_count")
        _tuple_of_hashes(
            self.distinct_approver_principal_hashes,
            "distinct_approver_principal_hashes",
        )
        _tuple_of_hashes(self.approver_role_hashes, "approver_role_hashes")
        _non_negative_int(self.not_before_ms, "not_before_ms")
        _non_negative_int(self.expires_at_ms, "expires_at_ms")
        _non_negative_int(self.evaluated_at_ms, "evaluated_at_ms")
        if self.expires_at_ms <= self.not_before_ms:
            raise PR211EvidenceError("approval expiry must be after not-before time")


@dataclass(frozen=True, slots=True)
class DurableOutboxEvidence:
    """Atomic permit-consume, intent and dispatch-outbox evidence."""

    permit_consumed_and_intent_created_in_one_transaction: bool
    immutable_intent_sha256: str
    exact_message_sha256: str
    selected_transport_sha256: str
    outbox_row_sha256: str
    outbox_claim_fenced: bool
    dispatcher_received_only_opaque_intent_id: bool
    response_recorded_idempotently: bool
    finality_reconciled_idempotently: bool
    blind_resend_possible: bool
    crash_before_send_reconciled: bool
    crash_after_send_before_ack_reconciled: bool
    late_landing_freezes_descendants: bool

    def __post_init__(self) -> None:
        _sha256(self.immutable_intent_sha256, "immutable_intent_sha256")
        _sha256(self.exact_message_sha256, "exact_message_sha256")
        _sha256(self.selected_transport_sha256, "selected_transport_sha256")
        _sha256(self.outbox_row_sha256, "outbox_row_sha256")


@dataclass(frozen=True, slots=True)
class FinalizedSettlementEvidence:
    """Authoritative finalized-chain reconciliation evidence."""

    intent_sha256: str
    exact_message_sha256: str
    signature_sha256: str
    selected_transport_sha256: str
    genesis_hash_sha256: str
    commitment: str
    intent_min_context_slot: int
    compile_context_slot: int
    simulation_context_slot: int
    send_context_slot: int
    landed_slot: int
    raw_get_transaction_sha256: str
    transaction_meta_sha256: str
    pre_balances_sha256: str
    post_balances_sha256: str
    token_balance_delta_sha256: str
    landed: bool
    finalized: bool
    transaction_err: str | None
    charged_fee_lamports: int
    fee_from_get_transaction_meta: bool
    caller_supplied_hash_only: bool = False

    def __post_init__(self) -> None:
        for value, name in (
            (self.intent_sha256, "intent_sha256"),
            (self.exact_message_sha256, "exact_message_sha256"),
            (self.signature_sha256, "signature_sha256"),
            (self.selected_transport_sha256, "selected_transport_sha256"),
            (self.genesis_hash_sha256, "genesis_hash_sha256"),
            (self.raw_get_transaction_sha256, "raw_get_transaction_sha256"),
            (self.transaction_meta_sha256, "transaction_meta_sha256"),
            (self.pre_balances_sha256, "pre_balances_sha256"),
            (self.post_balances_sha256, "post_balances_sha256"),
            (self.token_balance_delta_sha256, "token_balance_delta_sha256"),
        ):
            _sha256(value, name)
        if self.commitment != "finalized":
            raise PR211EvidenceError("settlement commitment must be finalized")
        for value, name in (
            (self.intent_min_context_slot, "intent_min_context_slot"),
            (self.compile_context_slot, "compile_context_slot"),
            (self.simulation_context_slot, "simulation_context_slot"),
            (self.send_context_slot, "send_context_slot"),
            (self.landed_slot, "landed_slot"),
            (self.charged_fee_lamports, "charged_fee_lamports"),
        ):
            _non_negative_int(value, name)


@dataclass(frozen=True, slots=True)
class PR211SignerOutboxFinalityEvidence:
    """Top-level evidence envelope for Pass 6 PR-211."""

    pr210_evidence_accepted: bool
    pr210_report_sha256: str
    release_set_sha256: str
    signed_payload: SignedPayloadAuthorization
    approval: ApprovalSignatureEvidence
    outbox: DurableOutboxEvidence
    settlement: FinalizedSettlementEvidence
    live_execution_reachable: bool = False
    signer_import_reachable: bool = False
    sender_import_reachable: bool = False

    def __post_init__(self) -> None:
        _sha256(self.pr210_report_sha256, "pr210_report_sha256")
        _sha256(self.release_set_sha256, "release_set_sha256")


@dataclass(frozen=True, slots=True)
class PR211SignerOutboxFinalityReport:
    """Deterministic report emitted by the PR-211 gate."""

    schema_version: str
    ready: bool
    blockers: tuple[str, ...]
    evidence_hash: str
    live_execution_allowed: bool = LIVE_EXECUTION_ALLOWED
    signer_import_allowed: bool = SIGNER_IMPORT_ALLOWED
    sender_import_allowed: bool = SENDER_IMPORT_ALLOWED

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "ready": self.ready,
            "blockers": list(self.blockers),
            "evidence_hash": self.evidence_hash,
            "live_execution_allowed": self.live_execution_allowed,
            "signer_import_allowed": self.signer_import_allowed,
            "sender_import_allowed": self.sender_import_allowed,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def evaluate_pr211_signer_outbox_finality(
    evidence: PR211SignerOutboxFinalityEvidence,
) -> PR211SignerOutboxFinalityReport:
    """Evaluate PR-211 signer/outbox/finality acceptance evidence."""

    blockers: list[PR211Blocker] = []

    if not evidence.pr210_evidence_accepted:
        blockers.append(PR211Blocker.PR210_NOT_ACCEPTED)
    if (
        evidence.live_execution_reachable
        or evidence.signer_import_reachable
        or evidence.sender_import_reachable
    ):
        blockers.append(PR211Blocker.LIVE_OR_SENDER_REACHABLE)

    signed = evidence.signed_payload
    if signed.exact_message_sha256 != signed.signature_verification.exact_message_sha256:
        blockers.append(PR211Blocker.SIGNATURES_NOT_LOCALLY_VERIFIED)
    if signed.signed_at_block_height < signed.not_before_block_height:
        blockers.append(PR211Blocker.SIGNED_BEFORE_AUTHORIZATION_NOT_BEFORE)
    if signed.signed_at_block_height < signed.requested_block_height:
        blockers.append(PR211Blocker.SIGNED_BEFORE_AUTHORIZATION_NOT_BEFORE)
    if signed.signed_at_block_height >= signed.expires_at_block_height:
        blockers.append(PR211Blocker.SIGNED_AFTER_AUTHORIZATION_EXPIRY)
    if signed.current_block_height + signed.safety_margin_blocks >= signed.expires_at_block_height:
        blockers.append(PR211Blocker.CURRENT_HEIGHT_TOO_CLOSE_TO_EXPIRY)
    if not signed.signature_verification.all_signatures_verified:
        blockers.append(PR211Blocker.SIGNATURES_NOT_LOCALLY_VERIFIED)
    if signed.signature_verification.signature_set_hash_only:
        blockers.append(PR211Blocker.SIGNATURE_SET_HASH_ONLY)

    approval = evidence.approval
    if approval.hash_only_approval or not approval.threshold_signatures_verified:
        blockers.append(PR211Blocker.APPROVAL_NOT_CRYPTOGRAPHIC)
    if not (approval.not_before_ms <= approval.evaluated_at_ms < approval.expires_at_ms):
        blockers.append(PR211Blocker.APPROVAL_EXPIRED_OR_NOT_YET_VALID)
    if (
        approval.verified_signature_count < approval.required_threshold
        or len(set(approval.distinct_approver_principal_hashes))
        < approval.required_threshold
        or len(approval.approver_role_hashes) < approval.required_threshold
    ):
        blockers.append(PR211Blocker.APPROVER_THRESHOLD_NOT_MET)

    outbox = evidence.outbox
    if (
        not outbox.permit_consumed_and_intent_created_in_one_transaction
        or not outbox.outbox_claim_fenced
        or not outbox.dispatcher_received_only_opaque_intent_id
        or not outbox.response_recorded_idempotently
        or not outbox.finality_reconciled_idempotently
        or not outbox.late_landing_freezes_descendants
    ):
        blockers.append(PR211Blocker.OUTBOX_PROTOCOL_INCOMPLETE)
    if outbox.blind_resend_possible:
        blockers.append(PR211Blocker.OUTBOX_ALLOWS_BLIND_RESEND)
    if not (outbox.crash_before_send_reconciled and outbox.crash_after_send_before_ack_reconciled):
        blockers.append(PR211Blocker.CRASH_MATRIX_INCOMPLETE)
    if outbox.exact_message_sha256 != signed.exact_message_sha256:
        blockers.append(PR211Blocker.OUTBOX_PROTOCOL_INCOMPLETE)

    settlement = evidence.settlement
    if settlement.caller_supplied_hash_only or not settlement.finalized or not settlement.landed:
        blockers.append(PR211Blocker.FINALITY_NOT_MATERIALIZED)
    if (
        settlement.intent_sha256 != outbox.immutable_intent_sha256
        or settlement.exact_message_sha256 != signed.exact_message_sha256
        or settlement.selected_transport_sha256 != outbox.selected_transport_sha256
    ):
        blockers.append(PR211Blocker.FINALITY_CONTEXT_MISMATCH)
    if not (
        settlement.intent_min_context_slot
        <= settlement.compile_context_slot
        <= settlement.simulation_context_slot
        <= settlement.send_context_slot
        <= settlement.landed_slot
    ):
        blockers.append(PR211Blocker.FINALITY_CONTEXT_MISMATCH)
    if settlement.intent_min_context_slot == 0:
        blockers.append(PR211Blocker.FINALITY_CONTEXT_MISMATCH)
    if settlement.landed and (
        not settlement.fee_from_get_transaction_meta
        or settlement.charged_fee_lamports <= 0
    ):
        blockers.append(PR211Blocker.LANDED_FEE_NOT_AUTHORITATIVE)
    if settlement.finalized and not settlement.landed:
        blockers.append(PR211Blocker.FINALITY_STATUS_CONTRADICTS_ERROR)

    blocker_values = tuple(sorted({blocker.value for blocker in blockers}))
    return PR211SignerOutboxFinalityReport(
        schema_version=SCHEMA_VERSION,
        ready=not blocker_values,
        blockers=blocker_values,
        evidence_hash=_stable_hash(evidence_to_dict(evidence)),
    )


def evidence_to_dict(evidence: PR211SignerOutboxFinalityEvidence) -> dict[str, object]:
    """Return deterministic JSON-compatible evidence representation."""

    return {
        "pr210_evidence_accepted": evidence.pr210_evidence_accepted,
        "pr210_report_sha256": evidence.pr210_report_sha256,
        "release_set_sha256": evidence.release_set_sha256,
        "live_execution_reachable": evidence.live_execution_reachable,
        "signer_import_reachable": evidence.signer_import_reachable,
        "sender_import_reachable": evidence.sender_import_reachable,
        "signed_payload": {
            "request_id": evidence.signed_payload.request_id,
            "authorization_sha256": evidence.signed_payload.authorization_sha256,
            "exact_message_sha256": evidence.signed_payload.exact_message_sha256,
            "not_before_block_height": evidence.signed_payload.not_before_block_height,
            "requested_block_height": evidence.signed_payload.requested_block_height,
            "signed_at_block_height": evidence.signed_payload.signed_at_block_height,
            "expires_at_block_height": evidence.signed_payload.expires_at_block_height,
            "current_block_height": evidence.signed_payload.current_block_height,
            "safety_margin_blocks": evidence.signed_payload.safety_margin_blocks,
            "signature_verification": {
                "exact_message_sha256": evidence.signed_payload.signature_verification.exact_message_sha256,
                "signature_verifier_sha256": evidence.signed_payload.signature_verification.signature_verifier_sha256,
                "signer_public_key_hashes": list(evidence.signed_payload.signature_verification.signer_public_key_hashes),
                "signature_sha256s": list(evidence.signed_payload.signature_verification.signature_sha256s),
                "all_signatures_verified": evidence.signed_payload.signature_verification.all_signatures_verified,
                "signature_set_hash_only": evidence.signed_payload.signature_verification.signature_set_hash_only,
            },
        },
        "approval": {
            "approval_payload_sha256": evidence.approval.approval_payload_sha256,
            "release_set_sha256": evidence.approval.release_set_sha256,
            "policy_bundle_sha256": evidence.approval.policy_bundle_sha256,
            "canary_limits_sha256": evidence.approval.canary_limits_sha256,
            "required_threshold": evidence.approval.required_threshold,
            "verified_signature_count": evidence.approval.verified_signature_count,
            "distinct_approver_principal_hashes": list(evidence.approval.distinct_approver_principal_hashes),
            "approver_role_hashes": list(evidence.approval.approver_role_hashes),
            "threshold_signatures_verified": evidence.approval.threshold_signatures_verified,
            "not_before_ms": evidence.approval.not_before_ms,
            "expires_at_ms": evidence.approval.expires_at_ms,
            "evaluated_at_ms": evidence.approval.evaluated_at_ms,
            "hash_only_approval": evidence.approval.hash_only_approval,
        },
        "outbox": {
            "permit_consumed_and_intent_created_in_one_transaction": evidence.outbox.permit_consumed_and_intent_created_in_one_transaction,
            "immutable_intent_sha256": evidence.outbox.immutable_intent_sha256,
            "exact_message_sha256": evidence.outbox.exact_message_sha256,
            "selected_transport_sha256": evidence.outbox.selected_transport_sha256,
            "outbox_row_sha256": evidence.outbox.outbox_row_sha256,
            "outbox_claim_fenced": evidence.outbox.outbox_claim_fenced,
            "dispatcher_received_only_opaque_intent_id": evidence.outbox.dispatcher_received_only_opaque_intent_id,
            "response_recorded_idempotently": evidence.outbox.response_recorded_idempotently,
            "finality_reconciled_idempotently": evidence.outbox.finality_reconciled_idempotently,
            "blind_resend_possible": evidence.outbox.blind_resend_possible,
            "crash_before_send_reconciled": evidence.outbox.crash_before_send_reconciled,
            "crash_after_send_before_ack_reconciled": evidence.outbox.crash_after_send_before_ack_reconciled,
            "late_landing_freezes_descendants": evidence.outbox.late_landing_freezes_descendants,
        },
        "settlement": {
            "intent_sha256": evidence.settlement.intent_sha256,
            "exact_message_sha256": evidence.settlement.exact_message_sha256,
            "signature_sha256": evidence.settlement.signature_sha256,
            "selected_transport_sha256": evidence.settlement.selected_transport_sha256,
            "genesis_hash_sha256": evidence.settlement.genesis_hash_sha256,
            "commitment": evidence.settlement.commitment,
            "intent_min_context_slot": evidence.settlement.intent_min_context_slot,
            "compile_context_slot": evidence.settlement.compile_context_slot,
            "simulation_context_slot": evidence.settlement.simulation_context_slot,
            "send_context_slot": evidence.settlement.send_context_slot,
            "landed_slot": evidence.settlement.landed_slot,
            "raw_get_transaction_sha256": evidence.settlement.raw_get_transaction_sha256,
            "transaction_meta_sha256": evidence.settlement.transaction_meta_sha256,
            "pre_balances_sha256": evidence.settlement.pre_balances_sha256,
            "post_balances_sha256": evidence.settlement.post_balances_sha256,
            "token_balance_delta_sha256": evidence.settlement.token_balance_delta_sha256,
            "landed": evidence.settlement.landed,
            "finalized": evidence.settlement.finalized,
            "transaction_err": evidence.settlement.transaction_err,
            "charged_fee_lamports": evidence.settlement.charged_fee_lamports,
            "fee_from_get_transaction_meta": evidence.settlement.fee_from_get_transaction_meta,
            "caller_supplied_hash_only": evidence.settlement.caller_supplied_hash_only,
        },
    }


def _stable_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sha256(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise PR211EvidenceError(f"{name} must be a lowercase sha256 hex digest")
    if value in {"0" * 64, "f" * 64}:
        raise PR211EvidenceError(f"{name} must not be a placeholder digest")


def _tuple_of_hashes(value: tuple[str, ...], name: str) -> None:
    if not isinstance(value, tuple):
        raise PR211EvidenceError(f"{name} must be a tuple")
    for item in value:
        _sha256(item, name)


def _identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise PR211EvidenceError(f"{name} must be a stable identifier")


def _non_negative_int(value: int, name: str) -> None:
    if not isinstance(value, int) or value < 0:
        raise PR211EvidenceError(f"{name} must be a non-negative integer")


def _positive_int(value: int, name: str) -> None:
    if not isinstance(value, int) or value <= 0:
        raise PR211EvidenceError(f"{name} must be a positive integer")

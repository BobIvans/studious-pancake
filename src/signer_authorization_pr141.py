"""PR-141 signer authorization envelope primitives.

This module is deliberately side-effect free. It does not sign, submit, import a
wallet, or call RPC. It defines the fail-closed authorization checks that a later
isolated signer boundary must satisfy before any key backend is asked to sign an
exact Solana message.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re

SOLANA_FULL_TRANSACTION_LIMIT_BYTES = 1232
ED25519_SIGNATURE_BYTES = 64
_COMPACT_U16_MIN_BYTES = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AuthorizationFailure(StrEnum):
    BAD_HASH = "bad_hash"
    BAD_IDENTITY = "bad_identity"
    BAD_VERSION = "bad_version"
    BAD_WIRE_SIZE = "bad_wire_size"
    BAD_PROGRAM = "bad_program"
    BAD_PAYER = "bad_payer"
    BAD_SIGNER_SET = "bad_signer_set"
    BAD_ALT_EVIDENCE = "bad_alt_evidence"
    BAD_EXPIRY = "bad_expiry"
    BAD_NONCE = "bad_nonce"


class SignerAuthorizationError(ValueError):
    """Fail-closed PR-141 authorization error without secret-bearing fields."""

    def __init__(self, failure: AuthorizationFailure, message: str) -> None:
        super().__init__(message)
        self.failure = failure


@dataclass(frozen=True, slots=True)
class DecodedUnsignedMessage:
    """Signer-critical identity derived from serialized message bytes."""

    message_sha256: str
    version: str
    payer: str
    required_signers: tuple[str, ...]
    program_ids: tuple[str, ...]
    message_byte_count: int
    required_signature_count: int
    address_lookup_table_count: int = 0

    @property
    def estimated_signed_wire_bytes(self) -> int:
        return (
            self.message_byte_count
            + compact_u16_size(self.required_signature_count)
            + (ED25519_SIGNATURE_BYTES * self.required_signature_count)
        )


@dataclass(frozen=True, slots=True)
class SignerAuthorizationRequest:
    """One exact-message authorization request produced before signing."""

    authorization_id: str
    attempt_id: str
    attempt_generation: int
    logical_opportunity_id: str
    decoded_message: DecodedUnsignedMessage
    expected_payer: str
    expected_required_signers: tuple[str, ...]
    allowed_program_ids: frozenset[str]
    plan_hash: str
    policy_bundle_hash: str
    exact_simulation_hash: str
    cpi_call_graph_hash: str
    fee_compute_budget_hash: str
    blockhash_alt_fork_hash: str
    nonce_digest: str
    issued_at_ns: int
    expires_at_ns: int
    alt_evidence_hash: str | None = None


@dataclass(frozen=True, slots=True)
class TransactionAuthorization:
    """Redacted authorization envelope bound to one exact unsigned message."""

    authorization_id: str
    attempt_id: str
    attempt_generation: int
    logical_opportunity_id: str
    message_sha256: str
    payer: str
    required_signers: tuple[str, ...]
    program_ids: tuple[str, ...]
    policy_bundle_hash: str
    plan_hash: str
    exact_simulation_hash: str
    cpi_call_graph_hash: str
    fee_compute_budget_hash: str
    blockhash_alt_fork_hash: str
    nonce_digest: str
    issued_at_ns: int
    expires_at_ns: int
    max_signed_wire_bytes: int
    estimated_signed_wire_bytes: int
    signer_may_sign: bool
    live_submission_allowed: bool = False

    @property
    def envelope_hash(self) -> str:
        return sha256_json(
            {
                "domain": "flashloan-bot/pr141-transaction-authorization",
                "schema_version": "pr141.transaction-authorization.v1",
                "authorization_id": self.authorization_id,
                "attempt_id": self.attempt_id,
                "attempt_generation": self.attempt_generation,
                "logical_opportunity_id": self.logical_opportunity_id,
                "message_sha256": self.message_sha256,
                "payer": self.payer,
                "required_signers": list(self.required_signers),
                "program_ids": list(self.program_ids),
                "policy_bundle_hash": self.policy_bundle_hash,
                "plan_hash": self.plan_hash,
                "exact_simulation_hash": self.exact_simulation_hash,
                "cpi_call_graph_hash": self.cpi_call_graph_hash,
                "fee_compute_budget_hash": self.fee_compute_budget_hash,
                "blockhash_alt_fork_hash": self.blockhash_alt_fork_hash,
                "nonce_digest": self.nonce_digest,
                "issued_at_ns": self.issued_at_ns,
                "expires_at_ns": self.expires_at_ns,
                "max_signed_wire_bytes": self.max_signed_wire_bytes,
                "estimated_signed_wire_bytes": self.estimated_signed_wire_bytes,
                "signer_may_sign": self.signer_may_sign,
                "live_submission_allowed": self.live_submission_allowed,
            }
        )


def compact_u16_size(value: int) -> int:
    """Return the compact-u16 byte count used by the signature vector length."""

    if value < 0:
        raise SignerAuthorizationError(
            AuthorizationFailure.BAD_IDENTITY,
            "signature count cannot be negative",
        )
    size = 1
    while value >= 0x80:
        value >>= 7
        size += 1
    return size


def sha256_json(payload: object) -> str:
    """Stable JSON hash for redacted review evidence, not a secret MAC."""

    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def authorize_transaction(
    request: SignerAuthorizationRequest,
) -> TransactionAuthorization:
    """Authorize one exact unsigned message for an isolated signer boundary."""

    _validate_identity(request)
    _validate_hash_bindings(request)
    decoded = request.decoded_message
    if decoded.version != "v0":
        raise SignerAuthorizationError(
            AuthorizationFailure.BAD_VERSION,
            "only canonical v0 messages are accepted for PR-141",
        )
    if decoded.payer != request.expected_payer:
        raise SignerAuthorizationError(
            AuthorizationFailure.BAD_PAYER,
            "decoded payer does not match authorization request",
        )
    if decoded.required_signers != request.expected_required_signers:
        raise SignerAuthorizationError(
            AuthorizationFailure.BAD_SIGNER_SET,
            "decoded signer set does not match authorization request",
        )
    unknown_programs = sorted(
        set(decoded.program_ids) - set(request.allowed_program_ids)
    )
    if unknown_programs:
        raise SignerAuthorizationError(
            AuthorizationFailure.BAD_PROGRAM,
            "decoded message references a non-allowlisted program",
        )
    if decoded.address_lookup_table_count > 0:
        if request.alt_evidence_hash is None or not is_sha256_hex(
            request.alt_evidence_hash
        ):
            raise SignerAuthorizationError(
                AuthorizationFailure.BAD_ALT_EVIDENCE,
                "ALT usage requires bound resolved-account evidence hash",
            )
    estimated_wire = decoded.estimated_signed_wire_bytes
    if estimated_wire > SOLANA_FULL_TRANSACTION_LIMIT_BYTES:
        raise SignerAuthorizationError(
            AuthorizationFailure.BAD_WIRE_SIZE,
            "full signed transaction would exceed Solana wire limit",
        )
    if request.issued_at_ns < 0 or request.expires_at_ns <= request.issued_at_ns:
        raise SignerAuthorizationError(
            AuthorizationFailure.BAD_EXPIRY,
            "authorization expiry must be after issue time",
        )
    if not is_sha256_hex(request.nonce_digest) or is_placeholder_sha256(
        request.nonce_digest
    ):
        raise SignerAuthorizationError(
            AuthorizationFailure.BAD_NONCE,
            "authorization nonce digest must be a non-placeholder sha256 value",
        )
    return TransactionAuthorization(
        authorization_id=request.authorization_id,
        attempt_id=request.attempt_id,
        attempt_generation=request.attempt_generation,
        logical_opportunity_id=request.logical_opportunity_id,
        message_sha256=decoded.message_sha256,
        payer=decoded.payer,
        required_signers=decoded.required_signers,
        program_ids=tuple(sorted(set(decoded.program_ids))),
        policy_bundle_hash=request.policy_bundle_hash,
        plan_hash=request.plan_hash,
        exact_simulation_hash=request.exact_simulation_hash,
        cpi_call_graph_hash=request.cpi_call_graph_hash,
        fee_compute_budget_hash=request.fee_compute_budget_hash,
        blockhash_alt_fork_hash=request.blockhash_alt_fork_hash,
        nonce_digest=request.nonce_digest,
        issued_at_ns=request.issued_at_ns,
        expires_at_ns=request.expires_at_ns,
        max_signed_wire_bytes=SOLANA_FULL_TRANSACTION_LIMIT_BYTES,
        estimated_signed_wire_bytes=estimated_wire,
        signer_may_sign=True,
    )


def is_sha256_hex(value: str) -> bool:
    return bool(_SHA256_RE.fullmatch(value))


def is_placeholder_sha256(value: str) -> bool:
    """Reject obvious test/placeholder digests at legacy structural boundaries."""

    if not is_sha256_hex(value):
        return True
    if len(set(value)) == 1:
        return True
    for width in (2, 4, 8, 16):
        if value == value[:width] * (len(value) // width):
            return True
    return False


def _validate_identity(request: SignerAuthorizationRequest) -> None:
    if not request.authorization_id or not request.attempt_id:
        raise SignerAuthorizationError(
            AuthorizationFailure.BAD_IDENTITY,
            "authorization and attempt identifiers are required",
        )
    if request.attempt_generation < 0:
        raise SignerAuthorizationError(
            AuthorizationFailure.BAD_IDENTITY,
            "attempt generation cannot be negative",
        )
    if not request.logical_opportunity_id:
        raise SignerAuthorizationError(
            AuthorizationFailure.BAD_IDENTITY,
            "logical opportunity identifier is required",
        )
    if request.decoded_message.required_signature_count <= 0:
        raise SignerAuthorizationError(
            AuthorizationFailure.BAD_SIGNER_SET,
            "decoded message must require at least one signature",
        )


def _validate_hash_bindings(request: SignerAuthorizationRequest) -> None:
    bindings = {
        "message_sha256": request.decoded_message.message_sha256,
        "plan_hash": request.plan_hash,
        "policy_bundle_hash": request.policy_bundle_hash,
        "exact_simulation_hash": request.exact_simulation_hash,
        "cpi_call_graph_hash": request.cpi_call_graph_hash,
        "fee_compute_budget_hash": request.fee_compute_budget_hash,
        "blockhash_alt_fork_hash": request.blockhash_alt_fork_hash,
    }
    bad = [name for name, value in bindings.items() if not is_sha256_hex(value)]
    if bad:
        raise SignerAuthorizationError(
            AuthorizationFailure.BAD_HASH,
            "authorization hash bindings must be sha256 hex values",
        )

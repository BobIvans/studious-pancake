"""Identity and policy models for the fail-closed roadmap PR-08 boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re

SCHEMA_VERSION = "roadmap-pr08.isolated-signer-foundation.v1"
PRODUCT_ID = "studious-pancake.isolated-signer-intent"
COMPILE_TIME_SUBMISSION_ENABLED = False
REQUIRED_ROADMAP_PRS = tuple(range(1, 8))
MAX_PERMIT_TTL_NS = 5 * 60 * 1_000_000_000
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class TransportKind(StrEnum):
    RPC = "rpc"
    JITO_SINGLE = "jito_single"


class IntentState(StrEnum):
    PREPARED = "prepared"
    DISPATCHED = "dispatched"
    ACKNOWLEDGED = "acknowledged"
    INDETERMINATE = "indeterminate"
    REVOKED = "revoked"


class BoundaryFailure(StrEnum):
    PREREQUISITES = "prerequisites"
    APPROVAL_INVALID = "approval_invalid"
    BINDING_INVALID = "binding_invalid"
    POLICY_LIMIT = "policy_limit"
    KILL_SWITCH = "kill_switch"
    SIGNER_REVOKED = "signer_revoked"
    PERMIT_EXPIRED = "permit_expired"
    REPLAY_CONFLICT = "replay_conflict"
    INTENT_STATE = "intent_state"
    COMPILE_DISABLED = "compile_disabled"
    STORE_ERROR = "store_error"


class PR08BoundaryError(RuntimeError):
    def __init__(self, failure: BoundaryFailure, message: str) -> None:
        super().__init__(message)
        self.failure = failure


@dataclass(frozen=True, slots=True)
class ApprovalEvidence:
    roadmap_pr: int
    evidence_sha256: str
    release_id: str
    policy_bundle_hash: str
    reviewer_id: str
    approval_identity: str
    passed: bool
    independently_reviewed: bool

    def __post_init__(self) -> None:
        if self.roadmap_pr not in REQUIRED_ROADMAP_PRS:
            raise ValueError("roadmap_pr must be between PR-01 and PR-07")
        sha256(self.evidence_sha256, "evidence_sha256")
        identifier(self.release_id, "release_id")
        sha256(self.policy_bundle_hash, "policy_bundle_hash")
        identifier(self.reviewer_id, "reviewer_id")
        identifier(self.approval_identity, "approval_identity")

    def payload(self) -> dict[str, object]:
        return {
            "roadmap_pr": self.roadmap_pr,
            "evidence_sha256": self.evidence_sha256,
            "release_id": self.release_id,
            "policy_bundle_hash": self.policy_bundle_hash,
            "reviewer_id": self.reviewer_id,
            "approval_identity": self.approval_identity,
            "passed": self.passed,
            "independently_reviewed": self.independently_reviewed,
        }


ApprovalVerifier = Callable[[ApprovalEvidence], bool]


@dataclass(frozen=True, slots=True)
class ActivationBundle:
    release_id: str
    policy_bundle_hash: str
    signer_identity: str
    generation: int
    approvals: tuple[ApprovalEvidence, ...]

    def __post_init__(self) -> None:
        identifier(self.release_id, "release_id")
        sha256(self.policy_bundle_hash, "policy_bundle_hash")
        identifier(self.signer_identity, "signer_identity")
        if self.generation < 1:
            raise ValueError("generation must be positive")
        numbers = [item.roadmap_pr for item in self.approvals]
        if len(numbers) != len(set(numbers)):
            raise ValueError("roadmap approvals must be unique")

    @property
    def activation_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr08/activation",
                "release_id": self.release_id,
                "policy_bundle_hash": self.policy_bundle_hash,
                "signer_identity": self.signer_identity,
                "generation": self.generation,
                "approvals": [
                    item.payload()
                    for item in sorted(self.approvals, key=lambda item: item.roadmap_pr)
                ],
            }
        )

    def validate(self, verifier: ApprovalVerifier) -> None:
        by_pr = {item.roadmap_pr: item for item in self.approvals}
        if set(by_pr) != set(REQUIRED_ROADMAP_PRS):
            raise PR08BoundaryError(
                BoundaryFailure.PREREQUISITES,
                "PR-01 through PR-07 approvals are incomplete",
            )
        reviewers: set[str] = set()
        for number in REQUIRED_ROADMAP_PRS:
            item = by_pr[number]
            valid = (
                item.passed
                and item.independently_reviewed
                and item.release_id == self.release_id
                and item.policy_bundle_hash == self.policy_bundle_hash
                and verifier(item)
            )
            if not valid:
                raise PR08BoundaryError(
                    BoundaryFailure.APPROVAL_INVALID,
                    f"PR-{number:02d} approval is invalid",
                )
            reviewers.add(item.reviewer_id)
        if len(reviewers) < 2:
            raise PR08BoundaryError(
                BoundaryFailure.APPROVAL_INVALID,
                "at least two independent reviewers are required",
            )


@dataclass(frozen=True, slots=True)
class MessageReview:
    attempt_id: str
    generation: int
    release_id: str
    policy_bundle_hash: str
    message_sha256: str
    payer: str
    required_signers: tuple[str, ...]
    program_ids: tuple[str, ...]
    writable_accounts: tuple[str, ...]
    instruction_count: int
    wire_size_bytes: int
    spend_lamports: int
    network_fee_lamports: int
    priority_fee_lamports: int
    jito_tip_lamports: int
    proof_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        identifier(self.attempt_id, "attempt_id")
        identifier(self.release_id, "release_id")
        identifier(self.payer, "payer")
        sha256(self.policy_bundle_hash, "policy_bundle_hash")
        sha256(self.message_sha256, "message_sha256")
        if self.generation < 1:
            raise ValueError("generation must be positive")
        if not self.required_signers or not self.program_ids:
            raise ValueError("message signer and program identities are required")
        for values in (
            self.required_signers,
            self.program_ids,
            self.writable_accounts,
        ):
            if len(values) != len(set(values)):
                raise ValueError("message identity tuples must be unique")
        if len(self.proof_hashes) < 6:
            raise ValueError(
                "plan/simulation/CPI/fee/blockhash/ALT proofs are required"
            )
        for value in self.proof_hashes:
            sha256(value, "proof_hash")
        numbers = (
            self.instruction_count,
            self.wire_size_bytes,
            self.spend_lamports,
            self.network_fee_lamports,
            self.priority_fee_lamports,
            self.jito_tip_lamports,
        )
        if any(value < 0 for value in numbers):
            raise ValueError("message counts and lamports cannot be negative")

    @property
    def review_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr08/message-review",
                "attempt_id": self.attempt_id,
                "generation": self.generation,
                "release_id": self.release_id,
                "policy_bundle_hash": self.policy_bundle_hash,
                "message_sha256": self.message_sha256,
                "payer": self.payer,
                "required_signers": list(self.required_signers),
                "program_ids": list(self.program_ids),
                "writable_accounts": list(self.writable_accounts),
                "instruction_count": self.instruction_count,
                "wire_size_bytes": self.wire_size_bytes,
                "spend_lamports": self.spend_lamports,
                "network_fee_lamports": self.network_fee_lamports,
                "priority_fee_lamports": self.priority_fee_lamports,
                "jito_tip_lamports": self.jito_tip_lamports,
                "proof_hashes": list(self.proof_hashes),
            }
        )


@dataclass(frozen=True, slots=True)
class SignerPolicy:
    policy_id: str
    signer_identity: str
    payers: frozenset[str]
    signers: frozenset[str]
    programs: frozenset[str]
    transports: frozenset[TransportKind]
    limits: tuple[int, int, int, int, int, int, int]

    def __post_init__(self) -> None:
        identifier(self.policy_id, "policy_id")
        identifier(self.signer_identity, "signer_identity")
        if (
            not self.payers
            or not self.signers
            or not self.programs
            or not self.transports
        ):
            raise ValueError("policy allowlists cannot be empty")
        if len(self.limits) != 7 or any(value < 0 for value in self.limits):
            raise ValueError("policy requires seven non-negative limits")

    @property
    def policy_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr08/signer-policy",
                "policy_id": self.policy_id,
                "signer_identity": self.signer_identity,
                "payers": sorted(self.payers),
                "signers": sorted(self.signers),
                "programs": sorted(self.programs),
                "transports": sorted(item.value for item in self.transports),
                "limits": list(self.limits),
            }
        )


@dataclass(frozen=True, slots=True)
class SubmissionPermit:
    permit_id: str
    signer_identity: str
    transport: TransportKind
    release_id: str
    policy_bundle_hash: str
    signer_policy_hash: str
    activation_hash: str
    attempt_id: str
    generation: int
    message_sha256: str
    review_hash: str
    nonce_digest: str
    issued_at_ns: int
    expires_at_ns: int

    def __post_init__(self) -> None:
        for value, field in (
            (self.permit_id, "permit_id"),
            (self.signer_identity, "signer_identity"),
            (self.release_id, "release_id"),
            (self.attempt_id, "attempt_id"),
        ):
            identifier(value, field)
        for value, field in (
            (self.policy_bundle_hash, "policy_bundle_hash"),
            (self.signer_policy_hash, "signer_policy_hash"),
            (self.activation_hash, "activation_hash"),
            (self.message_sha256, "message_sha256"),
            (self.review_hash, "review_hash"),
            (self.nonce_digest, "nonce_digest"),
        ):
            sha256(value, field)
        if self.generation < 1:
            raise ValueError("generation must be positive")
        lifetime = self.expires_at_ns - self.issued_at_ns
        if self.issued_at_ns <= 0 or not 0 < lifetime <= MAX_PERMIT_TTL_NS:
            raise ValueError("permit lifetime must be positive and bounded")

    @property
    def permit_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr08/permit",
                "permit_id": self.permit_id,
                "signer_identity": self.signer_identity,
                "transport": self.transport.value,
                "release_id": self.release_id,
                "policy_bundle_hash": self.policy_bundle_hash,
                "signer_policy_hash": self.signer_policy_hash,
                "activation_hash": self.activation_hash,
                "attempt_id": self.attempt_id,
                "generation": self.generation,
                "message_sha256": self.message_sha256,
                "review_hash": self.review_hash,
                "nonce_digest": self.nonce_digest,
                "issued_at_ns": self.issued_at_ns,
                "expires_at_ns": self.expires_at_ns,
            }
        )

    @property
    def idempotency_key(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr08/idempotency",
                "permit_hash": self.permit_hash,
                "attempt_id": self.attempt_id,
                "generation": self.generation,
                "message_sha256": self.message_sha256,
            }
        )


PermitVerifier = Callable[[SubmissionPermit], bool]


@dataclass(frozen=True, slots=True)
class KillSwitchState:
    generation: int
    active: bool
    revoked_signers: frozenset[str]
    reason_sha256: str

    def __post_init__(self) -> None:
        if self.generation < 1:
            raise ValueError("kill-switch generation must be positive")
        sha256(self.reason_sha256, "reason_sha256")


@dataclass(frozen=True, slots=True)
class IntentRecord:
    intent_id: str
    idempotency_key: str
    permit_hash: str
    message_sha256: str
    attempt_id: str
    generation: int
    transport: TransportKind
    state: IntentState
    request_hash: str
    receipt_hash: str | None
    created_at_ns: int
    updated_at_ns: int


def identifier(value: str, field: str) -> str:
    if not _ID_RE.fullmatch(value):
        raise ValueError(f"{field} must be a bounded structured identifier")
    return value


def sha256(value: str, field: str) -> str:
    if not _SHA256_RE.fullmatch(value) or len(set(value)) == 1:
        raise ValueError(f"{field} must be a non-placeholder lowercase sha256")
    return value


def hash_json(payload: object) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode()).hexdigest()

"""PR-223 cryptographic trust, isolated signer, dispatch and settlement gate.

This module is intentionally sender-free and side-effect-free.  It does not read
private keys, contact providers, submit transactions or mutate runtime state.
It evaluates whether evidence for the PR-223 boundary is materially sufficient to
claim a trustworthy path from accepted PR-222 payload bytes to isolated signing,
durable dispatch and finalized settlement.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = "pr223.cryptographic-trust-signer-settlement.v1"
HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")


class PR223State(str, Enum):
    READY_FOR_PR223_FOUNDATION = "ready_for_pr223_foundation"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class PR223ApprovalEnvelope:
    principal_id: str
    role: str
    envelope_hash: str
    authorization_hash: str
    issued_at_ns: int
    expires_at_ns: int
    fresh_trusted_time: bool
    independent: bool


@dataclass(frozen=True)
class PR223Evidence:
    release_artifact_hash: str
    trust_bundle_hash: str
    signer_policy_hash: str
    authorization_schema_hash: str
    settlement_schema_hash: str
    archive_policy_hash: str
    findings_covered: tuple[str, ...]
    real_ed25519_verification: bool
    canonical_serialization: bool
    schema_domain_separated: bool
    key_rotation_supported: bool
    key_revocation_supported: bool
    not_before_enforced: bool
    exact_message_digest_bound: bool
    wallet_release_provider_market_bound: bool
    nonce_consumed_durably: bool
    authorization_issued_at_ns: int
    authorization_not_before_ns: int
    authorization_expires_at_ns: int
    evaluation_time_ns: int
    permit_consumed_with_intent: bool
    intent_outbox_atomic: bool
    dispatched_before_handoff: bool
    provider_idempotency_bound: bool
    unknown_reconciliation_owner: bool
    transport_payload_digest_match: bool
    min_context_slot_bound: bool
    blockhash_bound: bool
    ack_not_landing: bool
    bundle_id_not_landing: bool
    finalized_get_transaction_required: bool
    finalized_identity_matches_intent: bool
    fee_balance_token_deltas_materialized: bool
    archive_receipt_worm: bool
    archive_receipt_bytes_rehashed: bool
    archive_receipt_revision_immutable: bool
    aggregate_budget_verified: bool
    rollback_proof_bound: bool
    dual_approvals: tuple[PR223ApprovalEnvelope, ...]
    runtime_private_key_access: bool = False
    sender_requested: bool = False
    live_execution_requested: bool = False


@dataclass(frozen=True)
class PR223Violation:
    code: str
    message: str


@dataclass(frozen=True)
class PR223Report:
    schema_version: str
    state: PR223State
    blockers: tuple[PR223Violation, ...]
    evidence_hash: str
    covered_findings: tuple[str, ...]
    signer_allowed: bool
    sender_allowed: bool
    live_execution_allowed: bool


REQUIRED_FINDINGS: tuple[str, ...] = (
    "F-025",
    "F-045",
    "F-125",
    "F-126",
    "F-127",
    "F-128",
    "F-129",
    "F-130",
    "F-143",
    "F-144",
    "F-145",
    "F-146",
    "F-147",
    "F-148",
    "F-149",
    "F-150",
    "F-151",
    "F-152",
    "F-153",
    "F-154",
    "F-155",
    "F-156",
    "F-157",
    "F-158",
    "F-159",
    "F-160",
    "F-161",
    "F-162",
    "F-165",
    "F-169",
    "F-170",
    "F-172",
    "F-187",
    "F-188",
    "F-189",
    "F-190",
    "F-195",
    "F-196",
    "F-197",
    "F-198",
    "F-249",
    "F-250",
    "F-251",
    "F-252",
    "F-253",
    "F-254",
    "F-255",
)


TRUST_FLAGS = (
    "real_ed25519_verification",
    "canonical_serialization",
    "schema_domain_separated",
    "key_rotation_supported",
    "key_revocation_supported",
    "not_before_enforced",
)
AUTHORIZATION_FLAGS = (
    "exact_message_digest_bound",
    "wallet_release_provider_market_bound",
    "nonce_consumed_durably",
)
DISPATCH_FLAGS = (
    "permit_consumed_with_intent",
    "intent_outbox_atomic",
    "dispatched_before_handoff",
    "provider_idempotency_bound",
    "unknown_reconciliation_owner",
)
TRANSPORT_FLAGS = (
    "transport_payload_digest_match",
    "min_context_slot_bound",
    "blockhash_bound",
    "ack_not_landing",
    "bundle_id_not_landing",
)
SETTLEMENT_FLAGS = (
    "finalized_get_transaction_required",
    "finalized_identity_matches_intent",
    "fee_balance_token_deltas_materialized",
)
ARCHIVE_FLAGS = (
    "archive_receipt_worm",
    "archive_receipt_bytes_rehashed",
    "archive_receipt_revision_immutable",
)
PROMOTION_FLAGS = (
    "aggregate_budget_verified",
    "rollback_proof_bound",
)


def evaluate_pr223_evidence(evidence: PR223Evidence) -> PR223Report:
    blockers: list[PR223Violation] = []
    _validate_hashes(evidence, blockers)
    _validate_findings(evidence.findings_covered, blockers)
    _validate_runtime_surface(evidence, blockers)
    _validate_flag_group(evidence, TRUST_FLAGS, "PR223_TRUST_INCOMPLETE", blockers)
    _validate_authorization_window(evidence, blockers)
    _validate_flag_group(
        evidence,
        AUTHORIZATION_FLAGS,
        "PR223_AUTHORIZATION_NOT_EXACT",
        blockers,
    )
    _validate_flag_group(evidence, DISPATCH_FLAGS, "PR223_DISPATCH_NOT_ATOMIC", blockers)
    _validate_flag_group(
        evidence,
        TRANSPORT_FLAGS,
        "PR223_TRANSPORT_BINDING_INCOMPLETE",
        blockers,
    )
    _validate_flag_group(
        evidence,
        SETTLEMENT_FLAGS,
        "PR223_FINALITY_NOT_AUTHORITATIVE",
        blockers,
    )
    _validate_flag_group(
        evidence,
        ARCHIVE_FLAGS,
        "PR223_ARCHIVE_NOT_IMMUTABLE",
        blockers,
    )
    _validate_flag_group(
        evidence,
        PROMOTION_FLAGS,
        "PR223_PROMOTION_GOVERNANCE_INCOMPLETE",
        blockers,
    )
    _validate_dual_approvals(evidence.dual_approvals, evidence.evaluation_time_ns, blockers)
    unique = tuple(_dedupe(blockers))
    return PR223Report(
        schema_version=SCHEMA_VERSION,
        state=PR223State.BLOCKED if unique else PR223State.READY_FOR_PR223_FOUNDATION,
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        covered_findings=tuple(sorted(set(evidence.findings_covered))),
        signer_allowed=False,
        sender_allowed=False,
        live_execution_allowed=False,
    )


def _validate_hashes(evidence: PR223Evidence, blockers: list[PR223Violation]) -> None:
    for field_name in (
        "release_artifact_hash",
        "trust_bundle_hash",
        "signer_policy_hash",
        "authorization_schema_hash",
        "settlement_schema_hash",
        "archive_policy_hash",
    ):
        value = getattr(evidence, field_name)
        if not _is_hash(value):
            _add(blockers, "PR223_BAD_HASH", f"{field_name} must be strict sha256")


def _validate_findings(
    findings_covered: Sequence[str], blockers: list[PR223Violation]
) -> None:
    missing = [finding for finding in REQUIRED_FINDINGS if finding not in set(findings_covered)]
    if missing:
        _add(
            blockers,
            "PR223_FINDINGS_INCOMPLETE",
            "missing: " + ", ".join(missing),
        )


def _validate_runtime_surface(
    evidence: PR223Evidence, blockers: list[PR223Violation]
) -> None:
    if evidence.runtime_private_key_access:
        _add(
            blockers,
            "PR223_PRIVATE_KEY_EXPOSED",
            "runtime must not access private key material",
        )
    if evidence.sender_requested:
        _add(blockers, "PR223_SENDER_REQUESTED", "PR-223 cannot enable sender IO")
    if evidence.live_execution_requested:
        _add(
            blockers,
            "PR223_LIVE_REQUESTED",
            "PR-223 foundation cannot enable live execution",
        )


def _validate_authorization_window(
    evidence: PR223Evidence, blockers: list[PR223Violation]
) -> None:
    issued = evidence.authorization_issued_at_ns
    not_before = evidence.authorization_not_before_ns
    expires = evidence.authorization_expires_at_ns
    now = evidence.evaluation_time_ns
    if min(issued, not_before, expires, now) < 0:
        _add(blockers, "PR223_BAD_TIME", "authorization times must be non-negative")
        return
    if not_before < issued:
        _add(
            blockers,
            "PR223_NOT_BEFORE_REGRESSION",
            "not-before cannot be earlier than issued_at",
        )
    if issued > now:
        _add(
            blockers,
            "PR223_FUTURE_AUTHORIZATION",
            "authorization issued_at cannot be in the future",
        )
    if expires <= now:
        _add(blockers, "PR223_AUTHORIZATION_EXPIRED", "authorization is expired")
    if expires <= not_before:
        _add(
            blockers,
            "PR223_BAD_EXPIRY_WINDOW",
            "expires_at must be later than not-before",
        )


def _validate_flag_group(
    evidence: PR223Evidence,
    field_names: Sequence[str],
    code: str,
    blockers: list[PR223Violation],
) -> None:
    for field_name in field_names:
        if getattr(evidence, field_name) is not True:
            _add(blockers, code, f"{field_name} is required")


def _validate_dual_approvals(
    approvals: Sequence[PR223ApprovalEnvelope],
    evaluation_time_ns: int,
    blockers: list[PR223Violation],
) -> None:
    if len(approvals) < 2:
        _add(
            blockers,
            "PR223_DUAL_APPROVAL_MISSING",
            "two independent approvals are required",
        )
        return
    principals: set[str] = set()
    for approval in approvals:
        principals.add(approval.principal_id)
        if not approval.principal_id.strip():
            _add(blockers, "PR223_APPROVAL_PRINCIPAL_MISSING", "principal_id is required")
        if not approval.independent:
            _add(
                blockers,
                "PR223_APPROVAL_NOT_INDEPENDENT",
                "approval must be independently issued",
            )
        if not approval.fresh_trusted_time:
            _add(
                blockers,
                "PR223_APPROVAL_NOT_FRESH",
                "approval requires fresh trusted evaluation time",
            )
        if approval.issued_at_ns > evaluation_time_ns:
            _add(
                blockers,
                "PR223_APPROVAL_FUTURE_ISSUED",
                "approval issued_at cannot be in the future",
            )
        if approval.expires_at_ns <= evaluation_time_ns:
            _add(blockers, "PR223_APPROVAL_EXPIRED", "approval is expired")
        if approval.expires_at_ns <= approval.issued_at_ns:
            _add(
                blockers,
                "PR223_APPROVAL_BAD_WINDOW",
                "approval expiry must be later than issue time",
            )
        for field_name in ("envelope_hash", "authorization_hash"):
            if not _is_hash(getattr(approval, field_name)):
                _add(
                    blockers,
                    "PR223_APPROVAL_BAD_HASH",
                    f"{field_name} must be strict sha256",
                )
    if len(principals) < 2:
        _add(
            blockers,
            "PR223_DUAL_APPROVAL_NOT_DISTINCT",
            "approvals must come from two distinct principals",
        )


def _dedupe(blockers: Iterable[PR223Violation]) -> Iterable[PR223Violation]:
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        key = (blocker.code, blocker.message)
        if key not in seen:
            seen.add(key)
            yield blocker


def _add(blockers: list[PR223Violation], code: str, message: str) -> None:
    blockers.append(PR223Violation(code=code, message=message))


def _is_hash(value: str) -> bool:
    return bool(HEX_64_RE.fullmatch(value))


def _stable_hash(evidence: PR223Evidence) -> str:
    payload = asdict(evidence)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

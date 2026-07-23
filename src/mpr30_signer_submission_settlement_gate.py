"""MPR-30 cryptographic signer, one-shot permit, submission FSM and rooted settlement gate.

This module is intentionally default-off and side-effect-free. It does not load
private keys, open signer IPC, call RPC/Jito, submit transactions, or mutate the
active runtime. It evaluates whether evidence for the MPR-30 boundary is strong
enough to claim that a future live boundary could be wired safely.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Sequence


SCHEMA_VERSION = "mpr30.cryptographic-signer-submission-rooted-settlement.v1"
HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")


class MPR30State(str, Enum):
    READY_FOR_MPR30_FOUNDATION = "ready_for_mpr30_foundation"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class MPR30PermitEnvelope:
    reviewer_principal_id: str
    envelope_hash: str
    permit_hash: str
    exact_message_hash: str
    policy_generation_hash: str
    release_generation_hash: str
    config_generation_hash: str
    nonce_hash: str
    issued_at_ns: int
    not_before_ns: int
    expires_at_ns: int
    revocation_generation: int
    canonical_signed_envelope: bool
    independent_reviewer: bool
    fresh_trusted_time: bool


@dataclass(frozen=True)
class MPR30Evidence:
    signer_policy_hash: str
    submission_fsm_hash: str
    settlement_policy_hash: str
    archive_registry_hash: str
    findings_covered: tuple[str, ...]
    signer_decodes_message_bytes_internally: bool
    caller_metadata_not_trusted: bool
    byte_derived_programs_accounts_signers: bool
    alt_identity_derived_from_bytes: bool
    permit_envelope_cryptographically_signed: bool
    permit_binds_exact_bytes_identity: bool
    permit_binds_release_config_policy_generation: bool
    permit_binds_risk_limits_and_reviewer_identity: bool
    permit_nonce_revocation_ttl_enforced: bool
    permit_issue_consume_intent_atomic: bool
    sender_receives_only_opaque_intent_id: bool
    intent_contains_exact_signed_bytes: bool
    jito_bundle_identity_covers_all_members: bool
    every_bundle_member_reviewed: bool
    fsm_monotonic_and_terminal_immutable: bool
    stale_lower_finality_observations_advisory: bool
    transport_staged_evidence_materialized: bool
    ambiguous_retry_only_after_body_write: bool
    absence_proof_independent_and_registered: bool
    absence_proof_blockheight_deadline_freeze_bound: bool
    rooted_finalized_settlement_required: bool
    settlement_binds_exact_intent_identity: bool
    caller_booleans_or_hashes_cannot_finalize: bool
    default_live_off: bool
    default_signer_off: bool
    default_sender_off: bool
    permit: MPR30PermitEnvelope
    runtime_private_key_access: bool = False
    signer_ipc_reachable_without_permit: bool = False
    live_execution_requested: bool = False
    sender_requested: bool = False
    signer_requested: bool = False


@dataclass(frozen=True)
class MPR30Violation:
    code: str
    message: str


@dataclass(frozen=True)
class MPR30Report:
    schema_version: str
    state: MPR30State
    blockers: tuple[MPR30Violation, ...]
    evidence_hash: str
    covered_findings: tuple[str, ...]
    signer_allowed: bool
    sender_allowed: bool
    live_execution_allowed: bool


REQUIRED_FINDINGS: tuple[str, ...] = (
    "F-314",
    "F-315",
    "F-316",
    "F-317",
    "F-318",
    "F-319",
    "F-320",
    "F-321",
    "F-322",
    "F-323",
    "F-324",
    "F-325",
    "F-326",
    "F-464",
    "F-465",
    "F-466",
    "F-467",
    "F-468",
    "F-469",
    "F-470",
    "F-471",
    "F-472",
    "F-473",
    "F-474",
    "F-475",
)


BYTE_IDENTITY_FLAGS = (
    "signer_decodes_message_bytes_internally",
    "caller_metadata_not_trusted",
    "byte_derived_programs_accounts_signers",
    "alt_identity_derived_from_bytes",
)
PERMIT_FLAGS = (
    "permit_envelope_cryptographically_signed",
    "permit_binds_exact_bytes_identity",
    "permit_binds_release_config_policy_generation",
    "permit_binds_risk_limits_and_reviewer_identity",
    "permit_nonce_revocation_ttl_enforced",
)
INTENT_FLAGS = (
    "permit_issue_consume_intent_atomic",
    "sender_receives_only_opaque_intent_id",
    "intent_contains_exact_signed_bytes",
)
BUNDLE_FLAGS = (
    "jito_bundle_identity_covers_all_members",
    "every_bundle_member_reviewed",
)
FSM_FLAGS = (
    "fsm_monotonic_and_terminal_immutable",
    "stale_lower_finality_observations_advisory",
)
TRANSPORT_FLAGS = (
    "transport_staged_evidence_materialized",
    "ambiguous_retry_only_after_body_write",
)
ABSENCE_FLAGS = (
    "absence_proof_independent_and_registered",
    "absence_proof_blockheight_deadline_freeze_bound",
)
SETTLEMENT_FLAGS = (
    "rooted_finalized_settlement_required",
    "settlement_binds_exact_intent_identity",
    "caller_booleans_or_hashes_cannot_finalize",
)
DEFAULT_OFF_FLAGS = (
    "default_live_off",
    "default_signer_off",
    "default_sender_off",
)


def evaluate_mpr30_evidence(evidence: MPR30Evidence) -> MPR30Report:
    blockers: list[MPR30Violation] = []
    _validate_hashes(evidence, blockers)
    _validate_findings(evidence.findings_covered, blockers)
    _validate_runtime_surface(evidence, blockers)
    _validate_flag_group(evidence, BYTE_IDENTITY_FLAGS, "MPR30_BYTE_IDENTITY_INCOMPLETE", blockers)
    _validate_flag_group(evidence, PERMIT_FLAGS, "MPR30_PERMIT_NOT_CRYPTOGRAPHIC", blockers)
    _validate_permit_window(evidence.permit, blockers)
    _validate_flag_group(evidence, INTENT_FLAGS, "MPR30_INTENT_NOT_ONESHOT", blockers)
    _validate_flag_group(evidence, BUNDLE_FLAGS, "MPR30_BUNDLE_IDENTITY_INCOMPLETE", blockers)
    _validate_flag_group(evidence, FSM_FLAGS, "MPR30_FSM_NOT_MONOTONIC", blockers)
    _validate_flag_group(evidence, TRANSPORT_FLAGS, "MPR30_TRANSPORT_EVIDENCE_INCOMPLETE", blockers)
    _validate_flag_group(evidence, ABSENCE_FLAGS, "MPR30_ABSENCE_PROOF_UNSAFE", blockers)
    _validate_flag_group(evidence, SETTLEMENT_FLAGS, "MPR30_SETTLEMENT_NOT_ROOTED", blockers)
    _validate_flag_group(evidence, DEFAULT_OFF_FLAGS, "MPR30_DEFAULT_OFF_BROKEN", blockers)
    unique = tuple(_dedupe(blockers))
    return MPR30Report(
        schema_version=SCHEMA_VERSION,
        state=MPR30State.BLOCKED if unique else MPR30State.READY_FOR_MPR30_FOUNDATION,
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        covered_findings=tuple(sorted(set(evidence.findings_covered))),
        signer_allowed=False,
        sender_allowed=False,
        live_execution_allowed=False,
    )


def _validate_hashes(evidence: MPR30Evidence, blockers: list[MPR30Violation]) -> None:
    for field_name in (
        "signer_policy_hash",
        "submission_fsm_hash",
        "settlement_policy_hash",
        "archive_registry_hash",
    ):
        value = getattr(evidence, field_name)
        if not _is_hash(value):
            _add(blockers, "MPR30_BAD_HASH", f"{field_name} must be strict sha256")
    for field_name in (
        "envelope_hash",
        "permit_hash",
        "exact_message_hash",
        "policy_generation_hash",
        "release_generation_hash",
        "config_generation_hash",
        "nonce_hash",
    ):
        value = getattr(evidence.permit, field_name)
        if not _is_hash(value):
            _add(blockers, "MPR30_BAD_PERMIT_HASH", f"{field_name} must be strict sha256")


def _validate_findings(findings_covered: Sequence[str], blockers: list[MPR30Violation]) -> None:
    missing = [finding for finding in REQUIRED_FINDINGS if finding not in set(findings_covered)]
    if missing:
        _add(blockers, "MPR30_FINDINGS_INCOMPLETE", "missing: " + ", ".join(missing))


def _validate_runtime_surface(evidence: MPR30Evidence, blockers: list[MPR30Violation]) -> None:
    if evidence.runtime_private_key_access:
        _add(blockers, "MPR30_PRIVATE_KEY_EXPOSED", "runtime must not access private key material")
    if evidence.signer_ipc_reachable_without_permit:
        _add(blockers, "MPR30_SIGNER_IPC_BYPASS", "signer IPC reachable without approved permit")
    if evidence.live_execution_requested:
        _add(blockers, "MPR30_LIVE_REQUESTED", "MPR-30 must stay default-off")
    if evidence.sender_requested:
        _add(blockers, "MPR30_SENDER_REQUESTED", "sender remains disabled by default")
    if evidence.signer_requested:
        _add(blockers, "MPR30_SIGNER_REQUESTED", "signer remains disabled by default")


def _validate_permit_window(permit: MPR30PermitEnvelope, blockers: list[MPR30Violation]) -> None:
    issued = permit.issued_at_ns
    not_before = permit.not_before_ns
    expires = permit.expires_at_ns
    if min(issued, not_before, expires) < 0:
        _add(blockers, "MPR30_BAD_TIME", "permit times must be non-negative")
        return
    if not_before < issued:
        _add(blockers, "MPR30_NOT_BEFORE_REGRESSION", "not-before cannot be earlier than issued_at")
    if expires <= not_before or expires <= issued:
        _add(blockers, "MPR30_BAD_EXPIRY_WINDOW", "expires_at must be later than issued_at and not_before")
    if permit.revocation_generation < 1:
        _add(blockers, "MPR30_BAD_REVOCATION_GENERATION", "revocation generation must be positive")
    if not permit.canonical_signed_envelope:
        _add(blockers, "MPR30_ENVELOPE_NOT_CANONICAL", "permit envelope must be canonical")
    if not permit.independent_reviewer:
        _add(blockers, "MPR30_REVIEWER_NOT_INDEPENDENT", "reviewer must be independent")
    if not permit.fresh_trusted_time:
        _add(blockers, "MPR30_TRUSTED_TIME_NOT_FRESH", "permit must use fresh trusted time")
    if not permit.reviewer_principal_id.strip():
        _add(blockers, "MPR30_REVIEWER_MISSING", "reviewer principal is required")


def _validate_flag_group(
    evidence: MPR30Evidence,
    field_names: Sequence[str],
    code: str,
    blockers: list[MPR30Violation],
) -> None:
    for field_name in field_names:
        if getattr(evidence, field_name) is not True:
            _add(blockers, code, f"{field_name} is required")


def _dedupe(blockers: Iterable[MPR30Violation]) -> Iterable[MPR30Violation]:
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        key = (blocker.code, blocker.message)
        if key not in seen:
            seen.add(key)
            yield blocker


def _add(blockers: list[MPR30Violation], code: str, message: str) -> None:
    blockers.append(MPR30Violation(code=code, message=message))


def _is_hash(value: str) -> bool:
    return bool(HEX_64_RE.fullmatch(value))


def _stable_hash(evidence: MPR30Evidence) -> str:
    payload = asdict(evidence)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

"""MPR-04 isolated signer, Jito semantics and live-canary boundary gate.

This module is intentionally side-effect-free. It does not load private keys,
open network transports, submit transactions, or enable live trading. It
validates whether evidence for the MPR-04 boundary is sufficient to claim that
an isolated signer and reviewed live-canary boundary could be admitted without
opening unrestricted live execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Sequence


SCHEMA_VERSION = "mpr04.isolated-signer-jito-canary-boundary.v1"
HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_DEBT_IDS: tuple[str, ...] = (
    "runtime.live-entrypoint",
    "external.jito-low-latency",
    "submission.jito-unbundling-protection",
    "security.signer-isolation",
    "canary.permit-budget-latches",
    "canary.second-human-approval",
)


class MPR04State(str, Enum):
    READY_FOR_MPR04_FOUNDATION = "ready_for_mpr04_foundation"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class MPR04Approval:
    principal_id: str
    approval_hash: str
    issued_at_ns: int
    expires_at_ns: int
    fresh: bool
    independent: bool


@dataclass(frozen=True)
class MPR04Evidence:
    release_manifest_hash: str
    signer_policy_hash: str
    authorization_policy_hash: str
    jito_contract_hash: str
    canary_policy_hash: str
    debt_ids_covered: tuple[str, ...]
    runtime_private_key_access: bool
    isolated_signer_process_required: bool
    exact_message_hash_bound: bool
    policy_hash_bound: bool
    config_generation_bound: bool
    reservation_id_bound: bool
    wallet_reference_bound: bool
    market_provider_bound: bool
    nonce_bound: bool
    expiry_enforced: bool
    durable_submission_intent_written_before_transport: bool
    replay_denied: bool
    stale_config_denied: bool
    stale_shadow_evidence_denied: bool
    stale_human_approval_denied: bool
    ack_not_settlement: bool
    bundle_id_not_settlement: bool
    finalized_settlement_required: bool
    tip_budget_enforced: bool
    rate_limit_enforced: bool
    unbundling_protection_present: bool
    transaction_local_safety_assertions_present: bool
    production_cutover_manifest_fresh: bool
    mpr01_evidence_present: bool
    mpr02_evidence_present: bool
    mpr03_evidence_present: bool
    no_unknown_outstanding_attempts: bool
    capital_budget_cap_enforced: bool
    max_attempt_day_cap_enforced: bool
    max_loss_cap_enforced: bool
    emergency_stop_clear_required: bool
    exact_message_proof_required: bool
    final_human_approval_bound_to_message_hash: bool
    dual_approvals: tuple[MPR04Approval, ...]
    unrestricted_live_available: bool = False
    live_canary_available_by_default: bool = False


@dataclass(frozen=True)
class MPR04Violation:
    code: str
    message: str


@dataclass(frozen=True)
class MPR04Report:
    schema_version: str
    state: MPR04State
    blockers: tuple[MPR04Violation, ...]
    evidence_hash: str
    covered_debt_ids: tuple[str, ...]
    signer_allowed: bool
    sender_allowed: bool
    live_execution_allowed: bool
    live_canary_allowed: bool


def evaluate_mpr04_evidence(evidence: MPR04Evidence) -> MPR04Report:
    blockers: list[MPR04Violation] = []
    _validate_hashes(evidence, blockers)
    _validate_debt_ids(evidence.debt_ids_covered, blockers)
    _validate_runtime_key_isolation(evidence, blockers)
    _validate_flag_group(
        evidence,
        (
            "isolated_signer_process_required",
            "exact_message_hash_bound",
            "policy_hash_bound",
            "config_generation_bound",
            "reservation_id_bound",
            "wallet_reference_bound",
            "market_provider_bound",
            "nonce_bound",
            "expiry_enforced",
        ),
        "MPR04_SIGNER_AUTHORIZATION_INCOMPLETE",
        blockers,
    )
    _validate_flag_group(
        evidence,
        (
            "durable_submission_intent_written_before_transport",
            "replay_denied",
            "stale_config_denied",
            "stale_shadow_evidence_denied",
            "stale_human_approval_denied",
        ),
        "MPR04_REPLAY_PROTECTION_INCOMPLETE",
        blockers,
    )
    _validate_flag_group(
        evidence,
        (
            "ack_not_settlement",
            "bundle_id_not_settlement",
            "finalized_settlement_required",
            "tip_budget_enforced",
            "rate_limit_enforced",
            "unbundling_protection_present",
            "transaction_local_safety_assertions_present",
        ),
        "MPR04_JITO_SEMANTICS_INCOMPLETE",
        blockers,
    )
    _validate_flag_group(
        evidence,
        (
            "production_cutover_manifest_fresh",
            "mpr01_evidence_present",
            "mpr02_evidence_present",
            "mpr03_evidence_present",
            "no_unknown_outstanding_attempts",
            "capital_budget_cap_enforced",
            "max_attempt_day_cap_enforced",
            "max_loss_cap_enforced",
            "emergency_stop_clear_required",
            "exact_message_proof_required",
            "final_human_approval_bound_to_message_hash",
        ),
        "MPR04_CANARY_LATCHES_INCOMPLETE",
        blockers,
    )
    _validate_dual_approvals(evidence.dual_approvals, blockers)
    if evidence.unrestricted_live_available:
        _add(blockers, "MPR04_UNRESTRICTED_LIVE_FORBIDDEN", "unrestricted live must remain unavailable")
    if evidence.live_canary_available_by_default:
        _add(blockers, "MPR04_CANARY_DEFAULT_FORBIDDEN", "live canary must not be available by default")
    unique = tuple(_dedupe(blockers))
    return MPR04Report(
        schema_version=SCHEMA_VERSION,
        state=MPR04State.BLOCKED if unique else MPR04State.READY_FOR_MPR04_FOUNDATION,
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        covered_debt_ids=tuple(sorted(set(evidence.debt_ids_covered))),
        signer_allowed=False,
        sender_allowed=False,
        live_execution_allowed=False,
        live_canary_allowed=False,
    )


def _validate_hashes(evidence: MPR04Evidence, blockers: list[MPR04Violation]) -> None:
    for field_name in (
        "release_manifest_hash",
        "signer_policy_hash",
        "authorization_policy_hash",
        "jito_contract_hash",
        "canary_policy_hash",
    ):
        if not _is_hash(getattr(evidence, field_name)):
            _add(blockers, "MPR04_BAD_HASH", f"{field_name} must be strict sha256")


def _validate_debt_ids(debt_ids: Sequence[str], blockers: list[MPR04Violation]) -> None:
    missing = [item for item in REQUIRED_DEBT_IDS if item not in set(debt_ids)]
    if missing:
        _add(blockers, "MPR04_DEBT_IDS_INCOMPLETE", "missing: " + ", ".join(missing))


def _validate_runtime_key_isolation(
    evidence: MPR04Evidence, blockers: list[MPR04Violation]
) -> None:
    if evidence.runtime_private_key_access:
        _add(blockers, "MPR04_PRIVATE_KEY_EXPOSED", "runtime must not access private key material")


def _validate_flag_group(
    evidence: MPR04Evidence,
    field_names: Sequence[str],
    code: str,
    blockers: list[MPR04Violation],
) -> None:
    for field_name in field_names:
        if getattr(evidence, field_name) is not True:
            _add(blockers, code, f"{field_name} is required")


def _validate_dual_approvals(
    approvals: Sequence[MPR04Approval], blockers: list[MPR04Violation]
) -> None:
    if len(approvals) < 2:
        _add(blockers, "MPR04_DUAL_APPROVAL_MISSING", "two independent approvals are required")
        return
    principals: set[str] = set()
    for approval in approvals:
        principals.add(approval.principal_id)
        if not approval.principal_id.strip():
            _add(blockers, "MPR04_APPROVAL_PRINCIPAL_MISSING", "principal_id is required")
        if not _is_hash(approval.approval_hash):
            _add(blockers, "MPR04_APPROVAL_BAD_HASH", "approval_hash must be strict sha256")
        if approval.issued_at_ns < 0 or approval.expires_at_ns < 0:
            _add(blockers, "MPR04_APPROVAL_BAD_TIME", "approval timestamps must be non-negative")
        if approval.expires_at_ns <= approval.issued_at_ns:
            _add(blockers, "MPR04_APPROVAL_BAD_WINDOW", "approval expiry must be later than issue time")
        if not approval.fresh:
            _add(blockers, "MPR04_APPROVAL_NOT_FRESH", "approval must be fresh")
        if not approval.independent:
            _add(blockers, "MPR04_APPROVAL_NOT_INDEPENDENT", "approval must be independent")
    if len(principals) < 2:
        _add(blockers, "MPR04_DUAL_APPROVAL_NOT_DISTINCT", "approvals must come from two distinct principals")


def _add(blockers: list[MPR04Violation], code: str, message: str) -> None:
    blockers.append(MPR04Violation(code=code, message=message))


def _dedupe(blockers: Iterable[MPR04Violation]) -> Iterable[MPR04Violation]:
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        key = (blocker.code, blocker.message)
        if key not in seen:
            seen.add(key)
            yield blocker


def _is_hash(value: str) -> bool:
    return bool(HEX_64_RE.fullmatch(value))


def _stable_hash(evidence: MPR04Evidence) -> str:
    payload = asdict(evidence)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

"""MPR-CLOSE-05 bounded canary latches.

This evaluator is the last default-off gate before any reviewed canary can be
armed.  It requires accepted upstream MPR-CLOSE-01..04 evidence, fresh provider
and cutover reports, exact-message proof, strict budgets, emergency stop clear
and two independent human approvals.  It never enables unrestricted live.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Iterable, Sequence

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CanaryLatchState(StrEnum):
    BLOCKED = "blocked"
    READY_FOR_BOUNDED_CANARY = "ready_for_bounded_canary"


@dataclass(frozen=True, slots=True)
class UpstreamEvidenceRef:
    name: str
    evidence_hash: str
    accepted: bool
    fresh: bool


@dataclass(frozen=True, slots=True)
class HumanApproval:
    principal_id: str
    approval_hash: str
    message_sha256: str
    issued_at_ns: int
    expires_at_ns: int
    independent: bool
    fresh: bool


@dataclass(frozen=True, slots=True)
class CanaryLatchEvidence:
    upstream_evidence: tuple[UpstreamEvidenceRef, ...]
    production_cutover_manifest_hash: str
    provider_drift_report_hash: str
    exact_message_sha256: str
    exact_message_proof_hash: str
    canary_policy_hash: str
    outstanding_attempts_unknown: bool
    emergency_stop_clear: bool
    second_human_approval_required: bool
    approvals: tuple[HumanApproval, ...]
    capital_cap_lamports: int
    per_trade_cap_lamports: int
    daily_loss_cap_lamports: int
    requested_capital_lamports: int
    requested_trade_lamports: int
    realized_daily_loss_lamports: int
    automatic_stop_after_first_failure: bool
    automatic_stop_after_budget_exhausted: bool
    canary_enabled_by_default: bool = False
    unrestricted_live_requested: bool = False


@dataclass(frozen=True, slots=True)
class CanaryLatchViolation:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class CanaryLatchReport:
    schema_version: str
    state: CanaryLatchState
    canary_allowed: bool
    unrestricted_live_allowed: bool
    blockers: tuple[CanaryLatchViolation, ...]
    evidence_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "canary_allowed": self.canary_allowed,
            "unrestricted_live_allowed": self.unrestricted_live_allowed,
            "blockers": [asdict(item) for item in self.blockers],
            "evidence_hash": self.evidence_hash,
        }


REQUIRED_UPSTREAM_EVIDENCE: tuple[str, ...] = (
    "MPR-CLOSE-01",
    "MPR-CLOSE-02",
    "MPR-CLOSE-03",
    "MPR-CLOSE-04",
)


class CanaryLatchError(ValueError):
    """Raised when canary latch evidence is malformed."""


def evaluate_canary_latches(evidence: CanaryLatchEvidence) -> CanaryLatchReport:
    blockers: list[CanaryLatchViolation] = []
    _validate_hashes(evidence, blockers)
    _validate_upstream_evidence(evidence.upstream_evidence, blockers)
    _validate_budget_latches(evidence, blockers)
    _validate_approval_latches(evidence, blockers)
    if evidence.outstanding_attempts_unknown:
        _add(
            blockers,
            "CANARY_UNKNOWN_ATTEMPTS_OPEN",
            "canary cannot arm with unknown outstanding attempts",
        )
    if not evidence.emergency_stop_clear:
        _add(blockers, "CANARY_EMERGENCY_STOP_NOT_CLEAR", "emergency stop must be clear")
    if not evidence.automatic_stop_after_first_failure:
        _add(
            blockers,
            "CANARY_FAILURE_AUTOSTOP_MISSING",
            "canary must stop after first failure",
        )
    if not evidence.automatic_stop_after_budget_exhausted:
        _add(
            blockers,
            "CANARY_BUDGET_AUTOSTOP_MISSING",
            "canary must stop after budget exhaustion",
        )
    if evidence.canary_enabled_by_default:
        _add(blockers, "CANARY_DEFAULT_ON_FORBIDDEN", "canary must be default-off")
    if evidence.unrestricted_live_requested:
        _add(
            blockers,
            "UNRESTRICTED_LIVE_FORBIDDEN",
            "MPR-CLOSE-05 may allow only bounded reviewed canary",
        )
    unique = tuple(_dedupe(blockers))
    return CanaryLatchReport(
        schema_version="mpr-close-05.canary-latch-report.v1",
        state=CanaryLatchState.BLOCKED
        if unique
        else CanaryLatchState.READY_FOR_BOUNDED_CANARY,
        canary_allowed=not unique,
        unrestricted_live_allowed=False,
        blockers=unique,
        evidence_hash=_hash_dataclass(evidence),
    )


def _validate_hashes(
    evidence: CanaryLatchEvidence,
    blockers: list[CanaryLatchViolation],
) -> None:
    for field_name in (
        "production_cutover_manifest_hash",
        "provider_drift_report_hash",
        "exact_message_sha256",
        "exact_message_proof_hash",
        "canary_policy_hash",
    ):
        if not _is_hash(getattr(evidence, field_name)):
            _add(blockers, "CANARY_BAD_HASH", f"{field_name} must be sha256")
    for item in evidence.upstream_evidence:
        if not _is_hash(item.evidence_hash):
            _add(blockers, "CANARY_BAD_UPSTREAM_HASH", f"{item.name} hash must be sha256")
    for approval in evidence.approvals:
        if not _is_hash(approval.approval_hash):
            _add(blockers, "CANARY_BAD_APPROVAL_HASH", "approval_hash must be sha256")
        if approval.message_sha256 != evidence.exact_message_sha256:
            _add(
                blockers,
                "CANARY_APPROVAL_NOT_BOUND_TO_MESSAGE",
                "human approval must bind the exact message hash",
            )


def _validate_upstream_evidence(
    upstream: Sequence[UpstreamEvidenceRef],
    blockers: list[CanaryLatchViolation],
) -> None:
    refs = {item.name: item for item in upstream}
    for required in REQUIRED_UPSTREAM_EVIDENCE:
        item = refs.get(required)
        if item is None:
            _add(blockers, "CANARY_UPSTREAM_MISSING", f"{required} evidence is missing")
            continue
        if not item.accepted:
            _add(blockers, "CANARY_UPSTREAM_NOT_ACCEPTED", f"{required} is not accepted")
        if not item.fresh:
            _add(blockers, "CANARY_UPSTREAM_STALE", f"{required} evidence is stale")


def _validate_budget_latches(
    evidence: CanaryLatchEvidence,
    blockers: list[CanaryLatchViolation],
) -> None:
    for field_name in (
        "capital_cap_lamports",
        "per_trade_cap_lamports",
        "daily_loss_cap_lamports",
        "requested_capital_lamports",
        "requested_trade_lamports",
        "realized_daily_loss_lamports",
    ):
        value = getattr(evidence, field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            _add(blockers, "CANARY_BAD_BUDGET", f"{field_name} must be non-negative int")
    if evidence.capital_cap_lamports <= 0 or evidence.per_trade_cap_lamports <= 0:
        _add(blockers, "CANARY_ZERO_CAP", "capital and trade caps must be positive")
    if evidence.requested_capital_lamports > evidence.capital_cap_lamports:
        _add(blockers, "CANARY_CAPITAL_CAP_EXCEEDED", "requested capital exceeds cap")
    if evidence.requested_trade_lamports > evidence.per_trade_cap_lamports:
        _add(blockers, "CANARY_TRADE_CAP_EXCEEDED", "requested trade exceeds cap")
    if evidence.realized_daily_loss_lamports >= evidence.daily_loss_cap_lamports:
        _add(blockers, "CANARY_DAILY_LOSS_CAP_HIT", "daily loss cap is exhausted")


def _validate_approval_latches(
    evidence: CanaryLatchEvidence,
    blockers: list[CanaryLatchViolation],
) -> None:
    if not evidence.second_human_approval_required:
        _add(
            blockers,
            "CANARY_SECOND_APPROVAL_NOT_REQUIRED",
            "second human approval must be required",
        )
    if len(evidence.approvals) < 2:
        _add(blockers, "CANARY_APPROVALS_MISSING", "two approvals are required")
        return
    principals: set[str] = set()
    for approval in evidence.approvals:
        if not approval.principal_id.strip():
            _add(blockers, "CANARY_APPROVAL_PRINCIPAL_MISSING", "principal is required")
        principals.add(approval.principal_id)
        if approval.expires_at_ns <= approval.issued_at_ns:
            _add(blockers, "CANARY_APPROVAL_WINDOW_INVALID", "approval expiry is invalid")
        if not approval.independent:
            _add(blockers, "CANARY_APPROVAL_NOT_INDEPENDENT", "approval must be independent")
        if not approval.fresh:
            _add(blockers, "CANARY_APPROVAL_STALE", "approval must be fresh")
    if len(principals) < 2:
        _add(blockers, "CANARY_APPROVALS_NOT_DISTINCT", "approvals must be distinct")


def _add(blockers: list[CanaryLatchViolation], code: str, message: str) -> None:
    blockers.append(CanaryLatchViolation(code=code, message=message))


def _dedupe(blockers: Iterable[CanaryLatchViolation]) -> Iterable[CanaryLatchViolation]:
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        key = (blocker.code, blocker.message)
        if key in seen:
            continue
        seen.add(key)
        yield blocker


def _is_hash(value: str) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value)) and len(set(value)) > 1


def _hash_dataclass(value: object) -> str:
    raw = json.dumps(asdict(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = [
    "CanaryLatchError",
    "CanaryLatchEvidence",
    "CanaryLatchReport",
    "CanaryLatchState",
    "CanaryLatchViolation",
    "HumanApproval",
    "REQUIRED_UPSTREAM_EVIDENCE",
    "UpstreamEvidenceRef",
    "evaluate_canary_latches",
]

"""MPR-CLOSE-05 conservative Jito settlement semantics.

Jito transport ACKs and bundle IDs are useful correlation evidence only.  They
are never final settlement.  A canary attempt can be considered finalized only
when the exact locally simulated message is reconciled against finalized on-chain
evidence and the tip policy stays inside the configured budget.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class JitoSettlementState(StrEnum):
    BLOCKED = "blocked"
    ACK_ONLY = "ack_only_not_settlement"
    PENDING = "pending_finalized_reconciliation"
    FINALIZED = "finalized"


@dataclass(frozen=True, slots=True)
class JitoSettlementViolation:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class JitoSettlementEvidence:
    attempt_id: str
    message_sha256: str
    exact_simulation_hash: str
    local_simulation_passed: bool
    skip_preflight: bool
    transport_ack_received: bool
    bundle_id: str | None
    bundle_status: str | None
    signature_status: str | None
    finalized_reconciliation_hash: str | None
    finalized_reconciliation_passed: bool
    tip_lamports: int
    minimum_tip_lamports: int
    max_tip_lamports: int
    tip_in_primary_transaction: bool
    standalone_tip_transaction: bool
    unbundling_protection_present: bool
    uncled_block_protection_present: bool
    same_transaction_tip_required: bool = True

    @property
    def evidence_hash(self) -> str:
        return _hash_json(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "mpr-close-05.jito-settlement-evidence.v1",
            "attempt_id": self.attempt_id,
            "message_sha256": self.message_sha256,
            "exact_simulation_hash": self.exact_simulation_hash,
            "local_simulation_passed": self.local_simulation_passed,
            "skip_preflight": self.skip_preflight,
            "transport_ack_received": self.transport_ack_received,
            "bundle_id": self.bundle_id,
            "bundle_status": self.bundle_status,
            "signature_status": self.signature_status,
            "finalized_reconciliation_hash": self.finalized_reconciliation_hash,
            "finalized_reconciliation_passed": self.finalized_reconciliation_passed,
            "tip_lamports": self.tip_lamports,
            "minimum_tip_lamports": self.minimum_tip_lamports,
            "max_tip_lamports": self.max_tip_lamports,
            "tip_in_primary_transaction": self.tip_in_primary_transaction,
            "standalone_tip_transaction": self.standalone_tip_transaction,
            "unbundling_protection_present": self.unbundling_protection_present,
            "uncled_block_protection_present": self.uncled_block_protection_present,
            "same_transaction_tip_required": self.same_transaction_tip_required,
        }


@dataclass(frozen=True, slots=True)
class JitoSettlementReport:
    schema_version: str
    state: JitoSettlementState
    finalized: bool
    blockers: tuple[JitoSettlementViolation, ...]
    evidence_hash: str
    ack_is_settlement: bool = False
    bundle_id_is_settlement: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "finalized": self.finalized,
            "blockers": [item.__dict__ for item in self.blockers],
            "evidence_hash": self.evidence_hash,
            "ack_is_settlement": self.ack_is_settlement,
            "bundle_id_is_settlement": self.bundle_id_is_settlement,
        }


class JitoSettlementError(ValueError):
    """Raised for malformed Jito settlement evidence."""


def evaluate_jito_settlement(
    evidence: JitoSettlementEvidence,
) -> JitoSettlementReport:
    blockers: list[JitoSettlementViolation] = []
    _validate_shape(evidence, blockers)
    if evidence.message_sha256 != evidence.exact_simulation_hash:
        _add(
            blockers,
            "JITO_EXACT_SIMULATION_HASH_MISMATCH",
            "Jito send must be bound to the exact locally simulated message",
        )
    if evidence.skip_preflight and not evidence.local_simulation_passed:
        _add(
            blockers,
            "JITO_SKIP_PREFLIGHT_REQUIRES_LOCAL_SIMULATION",
            "skip_preflight=true requires a passing exact local simulation",
        )
    if evidence.tip_lamports < evidence.minimum_tip_lamports:
        _add(blockers, "JITO_TIP_BELOW_MINIMUM", "Jito tip is below policy minimum")
    if evidence.tip_lamports > evidence.max_tip_lamports:
        _add(blockers, "JITO_TIP_BUDGET_EXCEEDED", "Jito tip exceeds budget")
    if evidence.same_transaction_tip_required:
        if not evidence.tip_in_primary_transaction or evidence.standalone_tip_transaction:
            _add(
                blockers,
                "JITO_STANDALONE_TIP_FORBIDDEN",
                "Jito tip must be inside the primary transaction for first canary",
            )
    if not evidence.unbundling_protection_present:
        _add(
            blockers,
            "JITO_UNBUNDLING_PROTECTION_MISSING",
            "unbundling protection evidence is required",
        )
    if not evidence.uncled_block_protection_present:
        _add(
            blockers,
            "JITO_UNCLED_BLOCK_PROTECTION_MISSING",
            "uncled-block protection evidence is required",
        )
    if blockers:
        state = JitoSettlementState.BLOCKED
    elif evidence.finalized_reconciliation_passed and evidence.signature_status == "finalized":
        state = JitoSettlementState.FINALIZED
    elif evidence.transport_ack_received or evidence.bundle_id:
        state = JitoSettlementState.ACK_ONLY
    else:
        state = JitoSettlementState.PENDING
    finalized = state is JitoSettlementState.FINALIZED
    return JitoSettlementReport(
        schema_version="mpr-close-05.jito-settlement-report.v1",
        state=state,
        finalized=finalized,
        blockers=tuple(_dedupe(blockers)),
        evidence_hash=evidence.evidence_hash,
    )


def _validate_shape(
    evidence: JitoSettlementEvidence,
    blockers: list[JitoSettlementViolation],
) -> None:
    if not evidence.attempt_id.strip():
        _add(blockers, "JITO_ATTEMPT_ID_MISSING", "attempt_id is required")
    for field_name in ("message_sha256", "exact_simulation_hash"):
        if not _is_hash(getattr(evidence, field_name)):
            _add(blockers, "JITO_BAD_HASH", f"{field_name} must be sha256")
    if evidence.finalized_reconciliation_hash is not None and not _is_hash(
        evidence.finalized_reconciliation_hash
    ):
        _add(
            blockers,
            "JITO_BAD_FINALIZED_RECONCILIATION_HASH",
            "finalized reconciliation hash must be sha256 when present",
        )
    if evidence.bundle_id is not None and not _is_hash(evidence.bundle_id):
        _add(blockers, "JITO_BAD_BUNDLE_ID", "bundle_id must be sha256 when present")
    if evidence.tip_lamports < 0 or evidence.minimum_tip_lamports < 0:
        _add(blockers, "JITO_BAD_TIP", "tip values must be non-negative")
    if evidence.max_tip_lamports <= 0:
        _add(blockers, "JITO_BAD_TIP_BUDGET", "max_tip_lamports must be positive")


def _add(blockers: list[JitoSettlementViolation], code: str, message: str) -> None:
    blockers.append(JitoSettlementViolation(code=code, message=message))


def _dedupe(blockers: list[JitoSettlementViolation]) -> tuple[JitoSettlementViolation, ...]:
    seen: set[tuple[str, str]] = set()
    unique: list[JitoSettlementViolation] = []
    for blocker in blockers:
        key = (blocker.code, blocker.message)
        if key not in seen:
            seen.add(key)
            unique.append(blocker)
    return tuple(unique)


def _is_hash(value: str) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value)) and len(set(value)) > 1


def _hash_json(payload: Mapping[str, object]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = [
    "JitoSettlementError",
    "JitoSettlementEvidence",
    "JitoSettlementReport",
    "JitoSettlementState",
    "JitoSettlementViolation",
    "evaluate_jito_settlement",
]

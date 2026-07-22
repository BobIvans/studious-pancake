"""PR-138 finalized post-landing settlement boundary.

This module is deliberately offline and side-effect free. It consumes already
fetched finalized transaction/account evidence and classifies whether the
attempt may become economically successful. Confirmation, transport ACKs, bundle
status, and simulation success never become economic success here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Any

from .models import ExecutionState

PR138_SCHEMA_VERSION = "pr138.finalized-actual-settlement.v1"
FINALIZED_COMMITMENT = "finalized"


class PR138SettlementError(ValueError):
    """Raised when settlement evidence is malformed or non-canonical."""


class SettlementPhase(str, Enum):
    """Durable settlement phases separated from transport observations."""

    SUBMITTED = "submitted"
    PROCESSED = "processed"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"
    SETTLEMENT_FETCHED = "settlement_fetched"
    RECONCILED = "reconciled"
    INDETERMINATE_MANUAL_REVIEW = "indeterminate_manual_review"


class SettlementOutcome(str, Enum):
    """Machine-readable PR-138 economic outcome."""

    PENDING = "pending"
    RECONCILED_SUCCESS = "reconciled_success"
    RECONCILED_FAILURE = "reconciled_failure"
    INDETERMINATE_MANUAL_REVIEW = "indeterminate_manual_review"


@dataclass(frozen=True, slots=True)
class FinalizedTransactionEvidence:
    """Redacted actual transaction evidence from finalized getTransaction data."""

    signature: str
    confirmation_status: str
    transaction_message_hash: str
    finalized_slot: int
    raw_transaction_hash: str
    meta_err: object | None
    fee_lamports: int
    pre_balances_hash: str
    post_balances_hash: str
    pre_token_balances_hash: str
    post_token_balances_hash: str
    loaded_addresses_hash: str
    inner_instructions_hash: str
    logs_hash: str
    return_data_hash: str | None
    compute_units_consumed: int | None
    marginfi_repayment_proven: bool
    actual_network_fee_lamports: int
    actual_priority_fee_lamports: int
    actual_tip_lamports: int
    actual_rent_lamports: int
    actual_token_transfer_fee_lamports: int
    finalized_account_state_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        token_transfer_fee = self.actual_token_transfer_fee_lamports
        return {
            "signature": self.signature,
            "confirmation_status": self.confirmation_status,
            "transaction_message_hash": self.transaction_message_hash,
            "finalized_slot": self.finalized_slot,
            "raw_transaction_hash": self.raw_transaction_hash,
            "meta_err": self.meta_err,
            "fee_lamports": self.fee_lamports,
            "pre_balances_hash": self.pre_balances_hash,
            "post_balances_hash": self.post_balances_hash,
            "pre_token_balances_hash": self.pre_token_balances_hash,
            "post_token_balances_hash": self.post_token_balances_hash,
            "loaded_addresses_hash": self.loaded_addresses_hash,
            "inner_instructions_hash": self.inner_instructions_hash,
            "logs_hash": self.logs_hash,
            "return_data_hash": self.return_data_hash,
            "compute_units_consumed": self.compute_units_consumed,
            "marginfi_repayment_proven": self.marginfi_repayment_proven,
            "actual_network_fee_lamports": self.actual_network_fee_lamports,
            "actual_priority_fee_lamports": self.actual_priority_fee_lamports,
            "actual_tip_lamports": self.actual_tip_lamports,
            "actual_rent_lamports": self.actual_rent_lamports,
            "actual_token_transfer_fee_lamports": token_transfer_fee,
            "finalized_account_state_hash": self.finalized_account_state_hash,
        }


@dataclass(frozen=True, slots=True)
class SettlementComparison:
    """Predicted/simulated vs actual cost and settlement comparison."""

    predicted_fee_lamports: int
    simulated_fee_lamports: int
    actual_fee_lamports: int
    predicted_net_lamports: int | None
    simulated_net_lamports: int | None
    actual_net_lamports: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "predicted_fee_lamports": self.predicted_fee_lamports,
            "simulated_fee_lamports": self.simulated_fee_lamports,
            "actual_fee_lamports": self.actual_fee_lamports,
            "predicted_net_lamports": self.predicted_net_lamports,
            "simulated_net_lamports": self.simulated_net_lamports,
            "actual_net_lamports": self.actual_net_lamports,
        }


@dataclass(frozen=True, slots=True)
class FinalizedSettlementDecision:
    """PR-138 final classification; success is possible only after actuals."""

    schema_version: str
    phase: SettlementPhase
    outcome: SettlementOutcome
    durable_state: ExecutionState
    economically_successful: bool
    evidence_hash: str | None
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    comparison: SettlementComparison | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "phase": self.phase.value,
            "outcome": self.outcome.value,
            "durable_state": self.durable_state.value,
            "economically_successful": self.economically_successful,
            "evidence_hash": self.evidence_hash,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "comparison": _comparison_to_dict(self.comparison),
        }


def classify_transaction_status_observation(
    *,
    signature: str,
    message_hash: str,
    confirmation_status: str | None,
    transport_status: str | None = None,
) -> FinalizedSettlementDecision:
    """Classify polling/transport status without pretending it is settlement."""

    _require_nonempty(signature, "signature")
    _require_hash(message_hash, "message_hash")
    normalized_status = (confirmation_status or "").strip().lower()
    warnings: list[str] = []
    if transport_status:
        warnings.append("transport status is not economic settlement proof")

    if normalized_status == "processed":
        phase = SettlementPhase.PROCESSED
        durable_state = ExecutionState.PENDING
    elif normalized_status == "confirmed":
        phase = SettlementPhase.CONFIRMED
        durable_state = ExecutionState.RECONCILING
    elif normalized_status == FINALIZED_COMMITMENT:
        phase = SettlementPhase.FINALIZED
        durable_state = ExecutionState.RECONCILING
    else:
        return _decision(
            phase=SettlementPhase.INDETERMINATE_MANUAL_REVIEW,
            outcome=SettlementOutcome.INDETERMINATE_MANUAL_REVIEW,
            durable_state=ExecutionState.AMBIGUOUS_MANUAL_REVIEW,
            economically_successful=False,
            evidence_hash=None,
            blockers=("SIGNATURE_STATUS_MISSING_OR_UNKNOWN",),
            warnings=tuple(warnings),
        )

    return _decision(
        phase=phase,
        outcome=SettlementOutcome.PENDING,
        durable_state=durable_state,
        economically_successful=False,
        evidence_hash=None,
        blockers=("FINALIZED_ACTUAL_SETTLEMENT_REQUIRED",),
        warnings=tuple(warnings),
    )


def classify_finalized_actual_settlement(
    evidence: FinalizedTransactionEvidence,
    *,
    expected_message_hash: str,
    expected_signature: str | None = None,
    require_marginfi_repayment: bool = True,
    comparison: SettlementComparison | None = None,
) -> FinalizedSettlementDecision:
    """Classify finalized actual evidence into a terminal economic outcome."""

    _validate_evidence(evidence)
    _require_hash(expected_message_hash, "expected_message_hash")
    blockers: list[str] = []
    warnings: list[str] = []
    confirmation_status = evidence.confirmation_status.strip().lower()

    if expected_signature is not None:
        if evidence.signature != expected_signature:
            blockers.append("SIGNATURE_MISMATCH")
    if confirmation_status != FINALIZED_COMMITMENT:
        blockers.append("FINALIZED_GET_TRANSACTION_REQUIRED")
    if evidence.transaction_message_hash != expected_message_hash:
        blockers.append("MESSAGE_HASH_MISMATCH")
    if require_marginfi_repayment and not evidence.marginfi_repayment_proven:
        blockers.append("MARGINFI_REPAYMENT_NOT_PROVEN")
    if evidence.finalized_account_state_hash is None:
        warnings.append("finalized account state was not separately fetched")

    evidence_hash = _hash_json(
        {
            "schema_version": PR138_SCHEMA_VERSION,
            "evidence": evidence.to_dict(),
            "comparison": _comparison_to_dict(comparison),
            "expected_message_hash": expected_message_hash,
            "expected_signature": expected_signature,
        }
    )

    if blockers:
        return _decision(
            phase=SettlementPhase.INDETERMINATE_MANUAL_REVIEW,
            outcome=SettlementOutcome.INDETERMINATE_MANUAL_REVIEW,
            durable_state=ExecutionState.AMBIGUOUS_MANUAL_REVIEW,
            economically_successful=False,
            evidence_hash=evidence_hash,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            comparison=comparison,
        )

    if evidence.meta_err is not None:
        return _decision(
            phase=SettlementPhase.RECONCILED,
            outcome=SettlementOutcome.RECONCILED_FAILURE,
            durable_state=ExecutionState.RECONCILED_FAILURE,
            economically_successful=False,
            evidence_hash=evidence_hash,
            blockers=("FINALIZED_TRANSACTION_META_ERR",),
            warnings=tuple(warnings),
            comparison=comparison,
        )

    return _decision(
        phase=SettlementPhase.RECONCILED,
        outcome=SettlementOutcome.RECONCILED_SUCCESS,
        durable_state=ExecutionState.RECONCILED_SUCCESS,
        economically_successful=True,
        evidence_hash=evidence_hash,
        blockers=(),
        warnings=tuple(warnings),
        comparison=comparison,
    )


def assert_economic_success_requires_finalized_actual(
    decision: FinalizedSettlementDecision,
) -> None:
    """Fail closed if a caller tries to promote non-finalized evidence."""

    if decision.economically_successful and (
        decision.phase != SettlementPhase.RECONCILED
        or decision.outcome != SettlementOutcome.RECONCILED_SUCCESS
        or decision.evidence_hash is None
    ):
        raise PR138SettlementError(
            "economic success requires finalized actual settlement evidence"
        )


def _decision(
    *,
    phase: SettlementPhase,
    outcome: SettlementOutcome,
    durable_state: ExecutionState,
    economically_successful: bool,
    evidence_hash: str | None,
    blockers: tuple[str, ...],
    warnings: tuple[str, ...],
    comparison: SettlementComparison | None = None,
) -> FinalizedSettlementDecision:
    return FinalizedSettlementDecision(
        schema_version=PR138_SCHEMA_VERSION,
        phase=phase,
        outcome=outcome,
        durable_state=durable_state,
        economically_successful=economically_successful,
        evidence_hash=evidence_hash,
        blockers=blockers,
        warnings=warnings,
        comparison=comparison,
    )


def _validate_evidence(evidence: FinalizedTransactionEvidence) -> None:
    _require_nonempty(evidence.signature, "signature")
    _require_hash(evidence.transaction_message_hash, "transaction_message_hash")
    _require_hash(evidence.raw_transaction_hash, "raw_transaction_hash")
    _require_hash(evidence.pre_balances_hash, "pre_balances_hash")
    _require_hash(evidence.post_balances_hash, "post_balances_hash")
    _require_hash(evidence.pre_token_balances_hash, "pre_token_balances_hash")
    _require_hash(evidence.post_token_balances_hash, "post_token_balances_hash")
    _require_hash(evidence.loaded_addresses_hash, "loaded_addresses_hash")
    _require_hash(evidence.inner_instructions_hash, "inner_instructions_hash")
    _require_hash(evidence.logs_hash, "logs_hash")
    if evidence.return_data_hash is not None:
        _require_hash(evidence.return_data_hash, "return_data_hash")
    if evidence.finalized_account_state_hash is not None:
        _require_hash(
            evidence.finalized_account_state_hash,
            "finalized_account_state_hash",
        )
    if evidence.confirmation_status.strip().lower() not in {
        "processed",
        "confirmed",
        FINALIZED_COMMITMENT,
    }:
        raise PR138SettlementError("unsupported confirmation_status")

    _require_nonnegative_int(evidence.finalized_slot, "finalized_slot")
    _require_nonnegative_int(evidence.fee_lamports, "fee_lamports")
    _require_nonnegative_int(
        evidence.actual_network_fee_lamports,
        "actual_network_fee_lamports",
    )
    _require_nonnegative_int(
        evidence.actual_priority_fee_lamports,
        "actual_priority_fee_lamports",
    )
    _require_nonnegative_int(evidence.actual_tip_lamports, "actual_tip_lamports")
    _require_nonnegative_int(evidence.actual_rent_lamports, "actual_rent_lamports")
    _require_nonnegative_int(
        evidence.actual_token_transfer_fee_lamports,
        "actual_token_transfer_fee_lamports",
    )
    if evidence.compute_units_consumed is not None:
        _require_nonnegative_int(
            evidence.compute_units_consumed,
            "compute_units_consumed",
        )


def _comparison_to_dict(
    comparison: SettlementComparison | None,
) -> dict[str, Any] | None:
    if comparison is None:
        return None
    return comparison.to_dict()


def _require_nonempty(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PR138SettlementError(f"{label} is required")


def _require_hash(value: object, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise PR138SettlementError(f"{label} must be sha256 hex")
    try:
        int(value, 16)
    except ValueError as exc:
        raise PR138SettlementError(f"{label} must be sha256 hex") from exc


def _require_nonnegative_int(value: object, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PR138SettlementError(f"{label} must be a non-negative integer")


def _hash_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_json(value: Any) -> bytes:
    try:
        payload = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise PR138SettlementError(
            "settlement evidence is not canonical JSON"
        ) from exc
    return payload.encode("utf-8")


__all__ = [
    "FINALIZED_COMMITMENT",
    "PR138_SCHEMA_VERSION",
    "FinalizedSettlementDecision",
    "FinalizedTransactionEvidence",
    "PR138SettlementError",
    "SettlementComparison",
    "SettlementOutcome",
    "SettlementPhase",
    "assert_economic_success_requires_finalized_actual",
    "classify_finalized_actual_settlement",
    "classify_transaction_status_observation",
]

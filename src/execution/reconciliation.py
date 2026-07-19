from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .models import ExecutionState

class ReconciliationOutcome(str, Enum):
    SUCCESS="reconciled_success"
    FAILURE="reconciled_failure"
    INCOMPLETE="reconciliation_incomplete"

@dataclass(frozen=True, slots=True)
class ReconciliationEvidence:
    signatures_ok: bool
    repayment_ok: bool
    final_balances_ok: bool
    read_slot: int
    min_required_slot: int
    reason: str = ""

def classify_reconciliation(e: ReconciliationEvidence) -> tuple[ReconciliationOutcome, ExecutionState]:
    if e.read_slot < e.min_required_slot:
        return ReconciliationOutcome.INCOMPLETE, ExecutionState.AMBIGUOUS_MANUAL_REVIEW
    if e.signatures_ok and e.repayment_ok and e.final_balances_ok:
        return ReconciliationOutcome.SUCCESS, ExecutionState.RECONCILED_SUCCESS
    if not e.signatures_ok or not e.repayment_ok or not e.final_balances_ok:
        return ReconciliationOutcome.FAILURE, ExecutionState.RECONCILED_FAILURE
    return ReconciliationOutcome.INCOMPLETE, ExecutionState.AMBIGUOUS_MANUAL_REVIEW

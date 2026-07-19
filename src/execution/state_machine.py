from __future__ import annotations
from .models import ExecutionState

RETRY_BLOCKING_STATES = {
    ExecutionState.SUBMISSION_INTENT_RECORDED,
    ExecutionState.SUBMISSION_UNCERTAIN,
    ExecutionState.ACCEPTED,
    ExecutionState.PENDING,
    ExecutionState.LANDED,
    ExecutionState.RECONCILING,
    ExecutionState.RECONCILED_SUCCESS,
    ExecutionState.RECONCILED_FAILURE,
    ExecutionState.AMBIGUOUS_MANUAL_REVIEW,
}
TERMINAL_STATES = {ExecutionState.REJECTED_PRE_SEND, ExecutionState.RECONCILED_SUCCESS, ExecutionState.RECONCILED_FAILURE, ExecutionState.AMBIGUOUS_MANUAL_REVIEW, ExecutionState.RECONCILED, ExecutionState.FAILED, ExecutionState.EXPIRED}

ALLOWED_TRANSITIONS: dict[ExecutionState, set[ExecutionState]] = {
    ExecutionState.CREATED: {ExecutionState.PLANNED, ExecutionState.FAILED},
    ExecutionState.PLANNED: {ExecutionState.COMPILED, ExecutionState.REJECTED_PRE_SEND, ExecutionState.REJECTED, ExecutionState.FAILED},
    ExecutionState.COMPILED: {ExecutionState.STRUCTURALLY_VALIDATED, ExecutionState.SIMULATED, ExecutionState.REJECTED_PRE_SEND, ExecutionState.REJECTED, ExecutionState.PROVEN_EXPIRED},
    ExecutionState.STRUCTURALLY_VALIDATED: {ExecutionState.SIMULATED, ExecutionState.REJECTED_PRE_SEND, ExecutionState.REJECTED},
    ExecutionState.SIMULATED: {ExecutionState.APPROVED, ExecutionState.REJECTED_PRE_SEND, ExecutionState.REJECTED},
    ExecutionState.APPROVED: {ExecutionState.SIGNED, ExecutionState.PROVEN_EXPIRED, ExecutionState.REJECTED_PRE_SEND},
    ExecutionState.SIGNED: {ExecutionState.SUBMISSION_INTENT_RECORDED, ExecutionState.PROVEN_EXPIRED, ExecutionState.REJECTED_PRE_SEND, ExecutionState.FAILED},
    ExecutionState.SUBMISSION_INTENT_RECORDED: {ExecutionState.SUBMISSION_UNCERTAIN, ExecutionState.ACCEPTED, ExecutionState.REJECTED_PRE_SEND},
    ExecutionState.SUBMISSION_UNCERTAIN: {ExecutionState.RECONCILING, ExecutionState.AMBIGUOUS_MANUAL_REVIEW},
    ExecutionState.ACCEPTED: {ExecutionState.PENDING, ExecutionState.RECONCILING},
    ExecutionState.PENDING: {ExecutionState.LANDED, ExecutionState.RECONCILING, ExecutionState.AMBIGUOUS_MANUAL_REVIEW},
    ExecutionState.LANDED: {ExecutionState.RECONCILING, ExecutionState.RECONCILED},
    ExecutionState.RECONCILING: {ExecutionState.RECONCILED_SUCCESS, ExecutionState.RECONCILED_FAILURE, ExecutionState.AMBIGUOUS_MANUAL_REVIEW},
    ExecutionState.PROVEN_EXPIRED: {ExecutionState.REBUILD_ELIGIBLE},
    ExecutionState.REBUILD_ELIGIBLE: set(),
    ExecutionState.REJECTED_PRE_SEND: set(),
    ExecutionState.RECONCILED_SUCCESS: set(),
    ExecutionState.RECONCILED_FAILURE: set(),
    ExecutionState.AMBIGUOUS_MANUAL_REVIEW: set(),
    # legacy
    ExecutionState.SUBMITTED: {ExecutionState.PENDING, ExecutionState.LANDED, ExecutionState.FAILED, ExecutionState.EXPIRED},
    ExecutionState.REJECTED: set(), ExecutionState.FAILED: set(), ExecutionState.EXPIRED: set(), ExecutionState.RECONCILED: set(),
}

class ExecutionStateMachine:
    def can_transition(self, current: ExecutionState, target: ExecutionState) -> bool:
        return target in ALLOWED_TRANSITIONS[current]
    def transition(self, current: ExecutionState, target: ExecutionState) -> ExecutionState:
        if not self.can_transition(current, target):
            raise ValueError(f"invalid execution transition: {current.value}->{target.value}")
        return target
    def can_submit(self, state: ExecutionState) -> bool:
        return state == ExecutionState.SIGNED
    def retry_blocked(self, state: ExecutionState) -> bool:
        return state in RETRY_BLOCKING_STATES

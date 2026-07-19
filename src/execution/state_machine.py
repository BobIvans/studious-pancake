from __future__ import annotations
from .models import ExecutionState

TERMINAL_STATES = {ExecutionState.LANDED, ExecutionState.FAILED, ExecutionState.EXPIRED, ExecutionState.RECONCILED}

ALLOWED_TRANSITIONS: dict[ExecutionState, set[ExecutionState]] = {
    ExecutionState.CREATED: {ExecutionState.PLANNED, ExecutionState.FAILED},
    ExecutionState.PLANNED: {ExecutionState.COMPILED, ExecutionState.REJECTED, ExecutionState.FAILED},
    ExecutionState.COMPILED: {ExecutionState.STRUCTURALLY_VALIDATED, ExecutionState.REJECTED, ExecutionState.EXPIRED},
    ExecutionState.STRUCTURALLY_VALIDATED: {ExecutionState.SIMULATED, ExecutionState.REJECTED},
    ExecutionState.SIMULATED: {ExecutionState.APPROVED, ExecutionState.REJECTED},
    ExecutionState.APPROVED: {ExecutionState.SIGNED, ExecutionState.EXPIRED},
    ExecutionState.SIGNED: {ExecutionState.SUBMITTED, ExecutionState.EXPIRED, ExecutionState.FAILED},
    ExecutionState.SUBMITTED: {ExecutionState.PENDING, ExecutionState.LANDED, ExecutionState.FAILED, ExecutionState.EXPIRED},
    ExecutionState.PENDING: {ExecutionState.LANDED, ExecutionState.FAILED, ExecutionState.EXPIRED},
    ExecutionState.LANDED: {ExecutionState.RECONCILED},
    ExecutionState.REJECTED: set(),
    ExecutionState.FAILED: set(),
    ExecutionState.EXPIRED: set(),
    ExecutionState.RECONCILED: set(),
}

class ExecutionStateMachine:
    def can_transition(self, current: ExecutionState, target: ExecutionState) -> bool:
        return target in ALLOWED_TRANSITIONS[current]

    def transition(self, current: ExecutionState, target: ExecutionState) -> ExecutionState:
        if not self.can_transition(current, target):
            raise ValueError(f"invalid execution transition: {current.value}->{target.value}")
        return target

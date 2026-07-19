from __future__ import annotations
from dataclasses import dataclass
from .models import ExecutionErrorCode

@dataclass(frozen=True, slots=True)
class GateDecision:
    allowed: bool
    reason: ExecutionErrorCode | None = None

class LiveSubmissionGate:
    """PR-014 hard-disabled live gate; PR-018 must replace this policy."""
    def check(self) -> GateDecision:
        return GateDecision(False, ExecutionErrorCode.LIVE_GATE_NOT_OPEN)

"""Terminal opportunity processing results for the PR-007 runtime slice."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from .interfaces import StrategyMode

logger = logging.getLogger(__name__)


class OpportunityResultStatus(str, Enum):
    SHADOW_NOT_EXECUTED = "shadow_not_executed"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class OpportunityResult:
    opportunity_id: str
    strategy_name: str
    mode: StrategyMode
    status: OpportunityResultStatus
    executed: bool
    reason_code: str
    started_at: float
    completed_at: float
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))
        if self.executed:
            raise ValueError("PR-007 terminal results must not report executed trades")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must be >= started_at")


class OpportunityResultSink(Protocol):
    async def record(self, result: OpportunityResult) -> None: ...


class InMemoryOpportunityResultSink:
    def __init__(self) -> None:
        self.results: list[OpportunityResult] = []

    async def record(self, result: OpportunityResult) -> None:
        self.results.append(result)
        logger.info("opportunity_terminal", extra={"strategy": result.strategy_name, "status": result.status.value})


def make_result(*, opportunity_id: str, strategy_name: str, mode: StrategyMode,
                status: OpportunityResultStatus, reason_code: str, started_at: float,
                details: Mapping[str, Any] | None = None) -> OpportunityResult:
    return OpportunityResult(
        opportunity_id=opportunity_id,
        strategy_name=strategy_name,
        mode=mode,
        status=status,
        executed=False,
        reason_code=reason_code,
        started_at=started_at,
        completed_at=time.time(),
        details=details or {},
    )

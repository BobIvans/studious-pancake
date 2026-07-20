"""Public strategy and execution boundaries."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Mapping, Protocol

from .domain import Opportunity


class StrategyMode(str, Enum):
    DISABLED = "disabled"
    SHADOW = "shadow"
    LIVE = "live"


@dataclass(slots=True)
class StrategyContext:
    """Read-only detector services; intentionally excludes transaction senders."""

    config: Any = None
    market_state: Any = None
    protocol_state: Any = None
    capital_precheck: Any = None
    metrics: dict[str, Any] = field(default_factory=dict)


class Strategy(Protocol):
    name: str
    mode: StrategyMode
    disabled_reason: str | None

    async def start(self, context: StrategyContext) -> None: ...
    async def opportunities(self) -> AsyncIterator[Opportunity]: ...
    async def stop(self) -> None: ...


class OpportunityRanker(Protocol):
    async def priority(self, opportunity: Opportunity) -> float: ...


class ExecutionEngine(Protocol):
    """Only implementations of this boundary may execute transactions."""

    async def execute(self, opportunity: Opportunity) -> Mapping[str, Any]: ...

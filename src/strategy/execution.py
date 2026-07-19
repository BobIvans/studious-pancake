"""Execution engine boundary and non-resubmitting post-processing."""
from __future__ import annotations

from typing import Any, Mapping

from .domain import Opportunity


class LegacyExecutionEngine:
    """Temporary adapter: all transaction execution must pass through this boundary."""

    def __init__(self, executor: Any) -> None:
        self.executor = executor

    async def execute(self, opportunity: Opportunity) -> Mapping[str, Any]:
        return await self.executor(opportunity)


async def post_send_processing(result: Mapping[str, Any]) -> Mapping[str, Any]:
    """Record terminal status only; never resubmit transactions from callbacks."""
    return {"status": result.get("status", "unknown"), "resubmitted": False}

from __future__ import annotations
from typing import Protocol, Any
from src.execution.models import ExecutionAttempt, SubmissionResult

class TransactionSender(Protocol):
    async def submit(self, signed_transactions: tuple[Any, ...], attempt: ExecutionAttempt) -> SubmissionResult: ...

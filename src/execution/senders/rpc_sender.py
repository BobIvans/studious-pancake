from __future__ import annotations
import base64
from typing import Any
from src.execution.models import ExecutionAttempt, SubmissionResult, RpcClient

class RpcTransactionSender:
    def __init__(self, rpc: RpcClient): self.rpc = rpc
    async def submit(self, signed_transactions: tuple[Any, ...], attempt: ExecutionAttempt) -> SubmissionResult:
        sigs=[]
        for tx in signed_transactions:
            raw = bytes(tx) if not isinstance(tx, (bytes, bytearray)) else bytes(tx)
            sigs.append(await self.rpc.call("sendTransaction", [base64.b64encode(raw).decode(), {"encoding":"base64"}]))
        return SubmissionResult(True, "rpc", transaction_signatures=tuple(map(str, sigs)), accepted=True)

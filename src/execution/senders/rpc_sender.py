from __future__ import annotations
import base64
from typing import Any
from src.execution.models import ExecutionAttempt, SubmissionResult, RpcClient

class RpcTransactionSender:
    def __init__(self, rpc: RpcClient, *, commitment: str="confirmed", max_retries: int=0): self.rpc = rpc; self.commitment=commitment; self.max_retries=max_retries
    async def submit(self, signed_transactions: tuple[Any, ...], attempt: ExecutionAttempt) -> SubmissionResult:
        sigs=[]
        min_slot=getattr(getattr(attempt, "blockhash_context", None), "source_slot", None)
        for tx in signed_transactions:
            raw = bytes(tx) if not isinstance(tx, (bytes, bytearray)) else bytes(tx)
            cfg={"encoding":"base64","preflightCommitment":self.commitment,"maxRetries":self.max_retries}
            if min_slot is not None: cfg["minContextSlot"] = min_slot
            sigs.append(await self.rpc.call("sendTransaction", [base64.b64encode(raw).decode(), cfg]))
        return SubmissionResult(True, "rpc", transaction_signatures=tuple(map(str, sigs)), accepted=True, landed=False)

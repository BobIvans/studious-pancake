from __future__ import annotations
import base64
from typing import Any
from src.execution.models import ExecutionAttempt, SubmissionResult

class JitoSingleTransactionSender:
    endpoint_path = "/api/v1/transactions"
    def __init__(self, http, base_url: str, auth_token: str | None = None): self.http=http; self.base_url=base_url.rstrip('/'); self.auth_token=auth_token
    async def submit(self, signed_transactions: tuple[Any, ...], attempt: ExecutionAttempt) -> SubmissionResult:
        if len(signed_transactions) != 1: raise ValueError("single sender requires exactly one transaction")
        raw = bytes(signed_transactions[0]) if not isinstance(signed_transactions[0], (bytes, bytearray)) else bytes(signed_transactions[0])
        headers = {"x-jito-auth": self.auth_token} if self.auth_token else {}
        payload={"jsonrpc":"2.0","id":1,"method":"sendTransaction","params":[base64.b64encode(raw).decode(), {"encoding":"base64", "bundleOnly": True}]}
        data = await self.http.post_json(self.base_url + self.endpoint_path, payload, headers=headers)
        return SubmissionResult(True, "jito_single", bundle_id=(data.get("result") if isinstance(data, dict) else None), accepted=True, landed=False)

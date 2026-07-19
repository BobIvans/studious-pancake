from __future__ import annotations
import base64
from typing import Any
from src.execution.models import ExecutionAttempt, SubmissionResult

class JitoSingleTransactionSender:
    endpoint_path = "/api/v1/transactions"
    def __init__(self, http, base_url: str, auth_token: str | None = None, *, bundle_only: bool = True):
        self.http=http; self.base_url=base_url.rstrip('/'); self.auth_token=auth_token; self.bundle_only=bundle_only
    async def submit(self, signed_transactions: tuple[Any, ...], attempt: ExecutionAttempt) -> SubmissionResult:
        if len(signed_transactions) != 1: raise ValueError("single sender requires exactly one transaction")
        raw = bytes(signed_transactions[0]) if not isinstance(signed_transactions[0], (bytes, bytearray)) else bytes(signed_transactions[0])
        headers = {"x-jito-auth": self.auth_token} if self.auth_token else {}
        url = self.base_url + self.endpoint_path + ("?bundleOnly=true" if self.bundle_only else "")
        payload={"jsonrpc":"2.0","id":1,"method":"sendTransaction","params":[base64.b64encode(raw).decode(), {"encoding":"base64"}]}
        data = await self.http.post_json(url, payload, headers=headers)
        body, response_headers = (data if isinstance(data, tuple) else (data, {}))
        sig = body.get("result") if isinstance(body, dict) else None
        bundle_id = None
        for k,v in dict(response_headers or {}).items():
            if k.lower() == "x-bundle-id": bundle_id = str(v)
        return SubmissionResult(True, "jito_single", bundle_id=bundle_id, transaction_signatures=((str(sig),) if sig else ()), accepted=bool(sig), landed=False, headers={str(k):str(v) for k,v in dict(response_headers or {}).items()})

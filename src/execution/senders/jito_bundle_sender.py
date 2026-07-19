from __future__ import annotations
import base64
from typing import Any
from src.execution.models import ExecutionAttempt, SubmissionResult

class JitoBundleSender:
    endpoint_path = "/api/v1/bundles"
    def __init__(self, http, base_url: str, auth_token: str | None = None): self.http=http; self.base_url=base_url.rstrip('/'); self.auth_token=auth_token
    async def submit(self, signed_transactions: tuple[Any, ...], attempt: ExecutionAttempt) -> SubmissionResult:
        if not 1 <= len(signed_transactions) <= 5: raise ValueError("Jito bundle must contain one to five transactions")
        encoded=[base64.b64encode(bytes(tx) if not isinstance(tx,(bytes,bytearray)) else bytes(tx)).decode() for tx in signed_transactions]
        headers={"x-jito-auth": self.auth_token} if self.auth_token else {}
        data=await self.http.post_json(self.base_url+self.endpoint_path,{"jsonrpc":"2.0","id":1,"method":"sendBundle","params":[encoded,{"encoding":"base64"}]},headers=headers)
        return SubmissionResult(True,"jito_bundle",bundle_id=(data.get("result") if isinstance(data,dict) else None),accepted=True,landed=False)

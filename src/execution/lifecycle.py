from __future__ import annotations
import hashlib, json
from dataclasses import dataclass
from typing import Any
from .journal import SQLiteAttemptJournal
from .live_gate import LiveSubmissionGate
from .models import BlockhashContext, ExecutionState, SubmissionResult

@dataclass(frozen=True, slots=True)
class SubmissionEnvelope:
    logical_opportunity_id: str
    plan_hash: str
    attempt_generation: int
    signed_transactions: tuple[bytes, ...]
    signatures: tuple[str, ...]
    message_digest: str
    blockhash_context: BlockhashContext
    transport: str

class TransactionLifecycleService:
    """Transport-neutral lifecycle: records intent before any sender call and treats acknowledgements as non-landed."""
    def __init__(self, journal: SQLiteAttemptJournal, gate: LiveSubmissionGate | None = None):
        self.journal=journal; self.gate=gate or LiveSubmissionGate()
    async def submit_live(self, env: SubmissionEnvelope, sender: Any, *, owner: str="worker", lease_seconds: float=30) -> SubmissionResult:
        gate=self.gate.check()
        if not gate.allowed:
            return SubmissionResult(False, env.transport, gate.reason.value if gate.reason else "blocked")
        signed_digest=hashlib.sha256(b''.join(env.signed_transactions)).hexdigest()
        ok=await self.journal.record_submission_intent((env.logical_opportunity_id,env.plan_hash,env.attempt_generation), owner=owner, lease_seconds=lease_seconds, transport=env.transport, signatures=env.signatures, message_digest=env.message_digest, signed_transaction_digest=signed_digest, blockhash_context=env.blockhash_context)
        if not ok:
            return SubmissionResult(False, env.transport, "SUBMISSION_ALREADY_CLAIMED_OR_NOT_SIGNED")
        try:
            res=await sender.submit(env.signed_transactions, env)
        except Exception as exc:
            rec=await self.journal.get(env.logical_opportunity_id, env.plan_hash, env.attempt_generation)
            await self.journal.transition((env.logical_opportunity_id,env.plan_hash,env.attempt_generation), rec.revision if rec else 0, ExecutionState.SUBMISSION_UNCERTAIN, reason_code="TRANSPORT_EXCEPTION", error=str(exc))
            return SubmissionResult(True, env.transport, "AMBIGUOUS_TRANSPORT_EXCEPTION", accepted=False)
        rec=await self.journal.get(env.logical_opportunity_id, env.plan_hash, env.attempt_generation)
        target=ExecutionState.ACCEPTED if res.accepted else ExecutionState.SUBMISSION_UNCERTAIN
        await self.journal.transition((env.logical_opportunity_id,env.plan_hash,env.attempt_generation), rec.revision if rec else 0, target, reason_code="TRANSPORT_ACK_ONLY", evidence={"bundle_id":res.bundle_id,"signatures":res.transaction_signatures,"headers":res.headers})
        return res

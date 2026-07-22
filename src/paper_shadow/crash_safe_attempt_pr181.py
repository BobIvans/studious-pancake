"""PR-181 crash-safe wrapper for the exact sender-free paper attempt."""

from __future__ import annotations

from dataclasses import dataclass, replace
import sqlite3
import time
from typing import Callable

from src.durability.canonical_idempotency import (
    CanonicalIdempotencyStore,
    CanonicalOperationIdentity,
    IdempotencyConflict,
    PaperHandoffReceipt,
    canonical_digest,
)
from src.paper_shadow.exact_attempt_pr152 import (
    AtomicVerticalPort,
    ExactAttemptRequest,
    ExactAttemptResult,
    ExactPaperAttemptOrchestrator,
)


@dataclass(frozen=True, slots=True)
class CrashSafeExactAttemptResult:
    exact_attempt: ExactAttemptResult
    handoff: PaperHandoffReceipt | None
    blockers: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.exact_attempt.ready and self.handoff is not None

    @property
    def result_hash(self) -> str:
        return canonical_digest(
            {
                "exact_attempt_result_hash": self.exact_attempt.result_hash,
                "handoff_id": None if self.handoff is None else self.handoff.handoff_id,
                "handoff_result_digest": (
                    None if self.handoff is None else self.handoff.result_digest
                ),
                "blockers": self.blockers,
            }
        )


class CrashSafeExactPaperAttemptOrchestrator:
    """Derive operation keys internally and require atomic paper handoff."""

    def __init__(
        self,
        *,
        coordinator: object,
        vertical: AtomicVerticalPort,
        policy_generation: str,
        handoff_owner_id: str = "durable-paper-outcome-writer",
        handoff_lease_ttl_ns: int = 30_000_000_000,
        handoff_max_age_ns: int = 300_000_000_000,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        if not policy_generation or not handoff_owner_id:
            raise ValueError("policy_generation and handoff_owner_id are required")
        if handoff_lease_ttl_ns <= 0 or handoff_max_age_ns < handoff_lease_ttl_ns:
            raise ValueError("invalid handoff lease/max-age")
        self.coordinator = coordinator
        self.policy_generation = policy_generation
        self.handoff_owner_id = handoff_owner_id
        self.handoff_lease_ttl_ns = handoff_lease_ttl_ns
        self.handoff_max_age_ns = handoff_max_age_ns
        self.clock_ns = clock_ns
        self.base = ExactPaperAttemptOrchestrator(
            coordinator=coordinator,
            vertical=vertical,
            clock_ns=clock_ns,
        )

    async def run(
        self,
        request: ExactAttemptRequest,
    ) -> CrashSafeExactAttemptResult:
        normalized = replace(
            request,
            reserve_idempotency_key=self._operation_key(
                request,
                operation="reserve_capital",
                payload={
                    "candidate": request.capital_candidate.to_json(),
                    "wallet_snapshot": request.wallet_snapshot.to_json(),
                    "provider_evidence_hash": request.provider_evidence.evidence_hash,
                    "discovery_slot": request.discovery_slot,
                },
            ),
            release_idempotency_key=self._operation_key(
                request,
                operation="release_pre_submission_reservation",
                payload={
                    "candidate_id": request.capital_candidate.candidate_id,
                    "provider_evidence_hash": request.provider_evidence.evidence_hash,
                    "release_scope": "pre_submission_failure",
                },
            ),
            final_fee_idempotency_key=self._operation_key(
                request,
                operation="finalize_exact_message_fee",
                payload={
                    "candidate_id": request.capital_candidate.candidate_id,
                    "provider_evidence_hash": request.provider_evidence.evidence_hash,
                    "wallet_snapshot": request.wallet_snapshot.to_json(),
                },
            ),
        )
        exact = await self.base.run(normalized)
        if not exact.ready:
            return CrashSafeExactAttemptResult(exact, None, exact.blockers)

        db = getattr(getattr(self.coordinator, "store", None), "db", None)
        if not isinstance(db, sqlite3.Connection):
            return CrashSafeExactAttemptResult(
                exact,
                None,
                ("PR181_CANONICAL_SQLITE_STORE_REQUIRED",),
            )
        if (
            exact.attempt_id is None
            or exact.message_hash is None
            or exact.reconciliation_hash is None
            or exact.capital is None
        ):
            return CrashSafeExactAttemptResult(
                exact,
                None,
                ("PR181_EXACT_RESULT_IDENTITY_INCOMPLETE",),
            )
        reservation_id = exact.capital.decision.reservation_id
        if not reservation_id:
            return CrashSafeExactAttemptResult(
                exact,
                None,
                ("PR181_RESERVATION_ID_MISSING",),
            )

        result_payload = {
            "exact_attempt_result_hash": exact.result_hash,
            "attempt_id": exact.attempt_id,
            "attempt_generation": request.attempt_key.generation,
            "provider_evidence_hash": exact.provider_evidence_hash,
            "message_hash": exact.message_hash,
            "planner_digest": exact.planner_digest,
            "reconciliation_hash": exact.reconciliation_hash,
            "reservation_id": reservation_id,
        }
        identity = CanonicalOperationIdentity.derive(
            domain="paper-runtime",
            attempt_id=exact.attempt_id,
            attempt_generation=request.attempt_key.generation,
            operation="paper_handoff",
            request_payload=result_payload,
            policy_generation=self.policy_generation,
        )
        try:
            receipt = CanonicalIdempotencyStore(
                db,
                clock_ns=self.clock_ns,
            ).commit_paper_handoff(
                identity=identity,
                reservation_id=reservation_id,
                result=result_payload,
                owner_id=self.handoff_owner_id,
                lease_ttl_ns=self.handoff_lease_ttl_ns,
                max_age_ns=self.handoff_max_age_ns,
            )
        except (IdempotencyConflict, sqlite3.DatabaseError, ValueError):
            return CrashSafeExactAttemptResult(
                exact,
                None,
                ("PR181_ATOMIC_HANDOFF_BLOCKED",),
            )
        return CrashSafeExactAttemptResult(exact, receipt, ())

    def _operation_key(
        self,
        request: ExactAttemptRequest,
        *,
        operation: str,
        payload: dict[str, object],
    ) -> str:
        return CanonicalOperationIdentity.derive(
            domain="exact-paper-attempt",
            attempt_id=request.attempt_key.attempt_id,
            attempt_generation=request.attempt_key.generation,
            operation=operation,
            request_payload=payload,
            policy_generation=self.policy_generation,
        ).operation_id


__all__ = [
    "CrashSafeExactAttemptResult",
    "CrashSafeExactPaperAttemptOrchestrator",
]

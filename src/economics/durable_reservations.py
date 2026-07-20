"""Durable PR-057 capital reservation integration.

This module connects the PR-032 integer capital engine to the PR-041
SQLite lifecycle store without enabling live submission.  It is intentionally
small and side-effect bounded: callers must provide an already-captured
wallet balance snapshot and already-compiled/estimated candidate economics.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.durability import (
    AttemptKey,
    DurableAttempt,
    DurableLifecycleStore,
)
from src.economics.capital import (
    AtomicCapitalLedger,
    CapitalCandidate,
    CapitalDecision,
    CapitalEngineError,
    CapitalPolicy,
    NoTradeReason,
    _strict_lamports,
)
from src.execution.models import ExecutionState


@dataclass(frozen=True, slots=True)
class WalletBalanceSnapshot:
    """Native SOL balance observed before a capital decision."""

    wallet_pubkey: str
    native_lamports: int
    context_slot: int | None
    source: str = "rpc.getBalance"
    captured_at_ns: int | None = None

    def __post_init__(self) -> None:
        if not self.wallet_pubkey:
            raise CapitalEngineError("wallet_pubkey is required")
        _strict_lamports(self.native_lamports, field="native_lamports")
        if self.context_slot is not None:
            _strict_lamports(self.context_slot, field="context_slot", upper=2**63 - 1)
        if self.captured_at_ns is not None:
            _strict_lamports(
                self.captured_at_ns,
                field="captured_at_ns",
                upper=2**63 - 1,
            )
        if not self.source:
            raise CapitalEngineError("balance snapshot source is required")

    def to_json(self) -> dict[str, object]:
        return {
            "wallet_pubkey": self.wallet_pubkey,
            "native_lamports": str(self.native_lamports),
            "context_slot": self.context_slot,
            "source": self.source,
            "captured_at_ns": self.captured_at_ns,
        }


@dataclass(frozen=True, slots=True)
class DurableCapitalReservationResult:
    """Capital decision plus optional durable lifecycle attempt."""

    decision: CapitalDecision
    wallet_snapshot: WalletBalanceSnapshot
    active_durable_reserved_lamports: int
    attempt: DurableAttempt | None = None
    recovery_attempt_ids: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "decision": self.decision.to_json(),
            "wallet_snapshot": self.wallet_snapshot.to_json(),
            "active_durable_reserved_lamports": str(
                self.active_durable_reserved_lamports
            ),
            "attempt_id": None if self.attempt is None else self.attempt.attempt_id,
            "recovery_attempt_ids": list(self.recovery_attempt_ids),
        }


@dataclass(frozen=True, slots=True)
class BoundedAmountSearchResult:
    """Result of a monotonic bounded flash-loan amount search."""

    selected_amount_lamports: int | None
    decision: CapitalDecision
    evaluations: int

    @property
    def allowed(self) -> bool:
        return self.selected_amount_lamports is not None and self.decision.allowed


class DurableCapitalCoordinator:
    """Bridge PR-032 capital policy with PR-041 durable reservations.

    The coordinator fail-closes by subtracting active durable reservations found
    during startup recovery from the provided wallet balance before invoking the
    in-process PR-032 ledger.  This keeps restarts from reusing lamports that
    are still reserved by pre-submission attempts.
    """

    def __init__(
        self,
        *,
        store: DurableLifecycleStore,
        policy: CapitalPolicy,
        owner_id: str = "capital-coordinator",
    ) -> None:
        if not owner_id:
            raise CapitalEngineError("owner_id is required")
        self.store = store
        self.policy = policy
        self.owner_id = owner_id

    def active_durable_reserved_lamports(self) -> int:
        return sum(
            decision.attempt.reserved_lamports
            for decision in self.store.scan_startup_recovery()
            if decision.reservation_active
        )

    def recovery_attempt_ids(self) -> tuple[str, ...]:
        return tuple(
            decision.attempt.attempt_id
            for decision in self.store.scan_startup_recovery()
            if decision.reservation_active
        )

    def _ledger_for_snapshot(
        self,
        wallet_snapshot: WalletBalanceSnapshot,
    ) -> tuple[AtomicCapitalLedger, int, tuple[str, ...]]:
        active_reserved = self.active_durable_reserved_lamports()
        recovery_ids = self.recovery_attempt_ids()
        effective_wallet = max(0, wallet_snapshot.native_lamports - active_reserved)
        return (
            AtomicCapitalLedger(
                wallet_lamports=effective_wallet,
                policy=self.policy,
            ),
            active_reserved,
            recovery_ids,
        )

    def evaluate(
        self,
        candidate: CapitalCandidate,
        *,
        wallet_snapshot: WalletBalanceSnapshot,
    ) -> DurableCapitalReservationResult:
        ledger, active_reserved, recovery_ids = self._ledger_for_snapshot(
            wallet_snapshot
        )
        return DurableCapitalReservationResult(
            decision=ledger.evaluate(candidate),
            wallet_snapshot=wallet_snapshot,
            active_durable_reserved_lamports=active_reserved,
            recovery_attempt_ids=recovery_ids,
        )

    def reserve(
        self,
        candidate: CapitalCandidate,
        *,
        wallet_snapshot: WalletBalanceSnapshot,
        attempt_key: AttemptKey,
        idempotency_key: str,
    ) -> DurableCapitalReservationResult:
        """Evaluate, reserve in-memory, then persist the lifecycle attempt.

        If persistence fails after the PR-032 ledger admits the candidate, the
        temporary in-process reservation is released before the exception is
        re-raised.  The resulting durable attempt owns the reservation id used by
        future recovery scans.
        """

        ledger, active_reserved, recovery_ids = self._ledger_for_snapshot(
            wallet_snapshot
        )
        decision = ledger.reserve(candidate)
        if not decision.allowed or decision.reservation_id is None:
            return DurableCapitalReservationResult(
                decision=decision,
                wallet_snapshot=wallet_snapshot,
                active_durable_reserved_lamports=active_reserved,
                recovery_attempt_ids=recovery_ids,
            )

        try:
            attempt = self.store.create_attempt(
                attempt_key,
                idempotency_key=idempotency_key,
                state=ExecutionState.PLANNED,
                reservation_id=decision.reservation_id,
                candidate_id=candidate.candidate_id,
                reserved_lamports=decision.required_native_lamports,
                payload={
                    "pr": "PR-057",
                    "candidate_id": candidate.candidate_id,
                    "capital_decision": decision.to_json(),
                    "wallet_snapshot": wallet_snapshot.to_json(),
                    "message_hash": candidate.message_hash,
                    "active_durable_reserved_lamports": str(active_reserved),
                    "recovery_attempt_ids": list(recovery_ids),
                },
            )
        except Exception:
            ledger.release(decision.reservation_id)
            raise

        return DurableCapitalReservationResult(
            decision=decision,
            wallet_snapshot=wallet_snapshot,
            active_durable_reserved_lamports=active_reserved,
            attempt=attempt,
            recovery_attempt_ids=recovery_ids,
        )

    def release_pre_submission_reservation(
        self,
        attempt_id: str,
        *,
        idempotency_key: str,
        reason: str = "PR057_PRE_SUBMISSION_RELEASE",
        ttl_ns: int = 30_000_000_000,
    ) -> bool:
        lease = self.store.acquire_lease(
            f"attempt:{attempt_id}",
            owner_id=self.owner_id,
            ttl_ns=ttl_ns,
        )
        return self.store.release_abandoned_reservation(
            attempt_id,
            idempotency_key=idempotency_key,
            lease=lease,
            reason=reason,
        )

    def bounded_amount_search(
        self,
        *,
        lower_lamports: int,
        upper_lamports: int,
        wallet_snapshot: WalletBalanceSnapshot,
        candidate_factory: Callable[[int], CapitalCandidate],
    ) -> BoundedAmountSearchResult:
        """Find the highest admissible amount for a monotonic candidate factory."""

        _strict_lamports(
            lower_lamports,
            field="lower_lamports",
            upper=2**128 - 1,
        )
        _strict_lamports(
            upper_lamports,
            field="upper_lamports",
            upper=2**128 - 1,
        )
        if lower_lamports > upper_lamports:
            raise CapitalEngineError("lower_lamports exceeds upper_lamports")

        best_amount: int | None = None
        best_decision: CapitalDecision | None = None
        first_rejection: CapitalDecision | None = None
        evaluations = 0
        low, high = lower_lamports, upper_lamports

        while low <= high:
            midpoint = (low + high) // 2
            result = self.evaluate(
                candidate_factory(midpoint),
                wallet_snapshot=wallet_snapshot,
            )
            evaluations += 1
            if result.decision.allowed:
                best_amount = midpoint
                best_decision = result.decision
                low = midpoint + 1
            else:
                if first_rejection is None:
                    first_rejection = result.decision
                high = midpoint - 1

        if best_amount is not None and best_decision is not None:
            return BoundedAmountSearchResult(
                selected_amount_lamports=best_amount,
                decision=best_decision,
                evaluations=evaluations,
            )

        fallback = first_rejection or CapitalDecision(
            allowed=False,
            reason=NoTradeReason.NO_CANDIDATES,
            candidate_id=None,
            available_native_lamports=0,
            required_native_lamports=0,
            conservative_net_profit_lamports=0,
            policy_fingerprint=self.policy.fingerprint,
        )
        return BoundedAmountSearchResult(
            selected_amount_lamports=None,
            decision=fallback,
            evaluations=evaluations,
        )

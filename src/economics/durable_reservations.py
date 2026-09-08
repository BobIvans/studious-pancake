"""Durable PR-057 capital reservation integration.

This module connects the PR-032 integer capital engine to the PR-041
SQLite lifecycle store without enabling live submission.  It is intentionally
small and side-effect bounded: callers must provide an already-captured
wallet balance snapshot and already-compiled/estimated candidate economics.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, replace
import json
from typing import Any

from src.durability import (
    AttemptKey,
    DurableAttempt,
    DurableLifecycleStore,
    ReservationState,
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
from src.kernel import canonical_json_bytes, domain_sha256


@dataclass(frozen=True, slots=True)
class WalletBalanceSnapshot:
    """Native SOL balance observed before a capital decision."""

    wallet_pubkey: str
    native_lamports: int
    context_slot: int | None
    source: str = "rpc.getBalance"
    captured_at_ns: int | None = None
    cluster_genesis: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.wallet_pubkey, str) or not self.wallet_pubkey.strip():
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
        if self.cluster_genesis is not None and (
            not isinstance(self.cluster_genesis, str)
            or not self.cluster_genesis.strip()
        ):
            raise CapitalEngineError("cluster_genesis must be nonblank text")
        if not isinstance(self.source, str) or not self.source.strip():
            raise CapitalEngineError("balance snapshot source is required")

    def to_json(self) -> dict[str, object]:
        return {
            "wallet_pubkey": self.wallet_pubkey,
            "native_lamports": str(self.native_lamports),
            "context_slot": self.context_slot,
            "source": self.source,
            "captured_at_ns": self.captured_at_ns,
            "cluster_genesis": self.cluster_genesis,
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
        max_snapshot_age_ns: int = 30_000_000_000,
    ) -> None:
        if not owner_id:
            raise CapitalEngineError("owner_id is required")
        self.store = store
        self.policy = policy
        self.owner_id = owner_id
        if type(max_snapshot_age_ns) is not int or max_snapshot_age_ns <= 0:
            raise CapitalEngineError("max_snapshot_age_ns must be positive")
        self.max_snapshot_age_ns = max_snapshot_age_ns

    @staticmethod
    def _excluded_attempt_ids(
        exclude_attempt_ids: Iterable[str] | None,
    ) -> frozenset[str]:
        return frozenset(exclude_attempt_ids or ())

    def _active_attempts(self) -> tuple[DurableAttempt, ...]:
        """Include frozen terminal commitments; terminal status is not release."""
        self.store.integrity_check()
        rows = self.store.db.execute(
            "SELECT a.* FROM durable_attempts a LEFT JOIN durable_reservations r "
            "ON r.attempt_id=a.attempt_id WHERE r.state='active' OR a.reservation_state='active' "
            "ORDER BY a.created_at_ns,a.attempt_id"
        ).fetchall()
        attempts = []
        for row in rows:
            reservation = self.store.db.execute(
                "SELECT * FROM durable_reservations WHERE attempt_id=?",
                (row["attempt_id"],),
            ).fetchone()
            if (
                reservation is None
                or reservation["state"] != row["reservation_state"]
                or reservation["amount_lamports"] != row["reserved_lamports"]
                or reservation["reservation_id"] != row["reservation_id"]
            ):
                raise CapitalEngineError("DURABLE_RESERVATION_INCONSISTENT")
            attempt = self.store.get_attempt(row["attempt_id"])
            if attempt is None:
                raise CapitalEngineError("DURABLE_RESERVATION_INCONSISTENT")
            attempts.append(attempt)
        return tuple(attempts)

    def active_durable_reserved_lamports(
        self,
        *,
        exclude_attempt_ids: Iterable[str] | None = None,
    ) -> int:
        excluded = self._excluded_attempt_ids(exclude_attempt_ids)
        return sum(
            a.reserved_lamports
            for a in self._active_attempts()
            if a.attempt_id not in excluded
        )

    def recovery_attempt_ids(
        self,
        *,
        exclude_attempt_ids: Iterable[str] | None = None,
    ) -> tuple[str, ...]:
        excluded = self._excluded_attempt_ids(exclude_attempt_ids)
        return tuple(
            a.attempt_id
            for a in self._active_attempts()
            if a.attempt_id not in excluded
        )

    def _creation_payload(self, attempt_id: str) -> dict[str, Any]:
        row = self.store.db.execute(
            "SELECT payload_json FROM durable_events WHERE attempt_id=? "
            "AND event_type='attempt_created' AND sequence_no=0",
            (attempt_id,),
        ).fetchone()
        if row is None:
            raise CapitalEngineError("DURABLE_RESERVATION_LINEAGE_MISSING")
        return json.loads(row["payload_json"])

    def _validate_snapshot(self, snapshot: WalletBalanceSnapshot) -> None:
        if (
            snapshot.cluster_genesis is None
            or snapshot.captured_at_ns is None
            or snapshot.context_slot is None
        ):
            raise CapitalEngineError("WALLET_SNAPSHOT_SCOPE_OR_TIME_UNKNOWN")
        age = self.store.clock_ns() - snapshot.captured_at_ns
        if not 0 <= age <= self.max_snapshot_age_ns:
            raise CapitalEngineError("WALLET_SNAPSHOT_STALE")
        identity_table = self.store.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='database_identity_pr195'"
        ).fetchone()
        if identity_table:
            identity = self.store.db.execute(
                "SELECT cluster_genesis FROM database_identity_pr195 WHERE singleton=1"
            ).fetchone()
            if identity is None or identity[0] != snapshot.cluster_genesis:
                raise CapitalEngineError("WALLET_SNAPSHOT_CLUSTER_MISMATCH")
        # Context slot is the existing snapshot generation; do not invent a
        # second authoritative counter. Check all historical reservations too.
        rows = self.store.db.execute(
            "SELECT r.attempt_id,r.state,r.updated_at_ns FROM durable_reservations r"
        ).fetchall()
        for row in rows:
            prior = self._creation_payload(row["attempt_id"]).get("wallet_snapshot")
            if not isinstance(prior, dict) or not prior.get("cluster_genesis"):
                raise CapitalEngineError("DURABLE_RESERVATION_SCOPE_UNKNOWN")
            if (prior.get("wallet_pubkey"), prior.get("cluster_genesis")) != (
                snapshot.wallet_pubkey,
                snapshot.cluster_genesis,
            ):
                continue
            slot = prior.get("context_slot")
            if type(slot) is not int or snapshot.context_slot < slot:
                raise CapitalEngineError("WALLET_SNAPSHOT_GENERATION_STALE")
            if (
                snapshot.context_slot == slot
                and int(prior["native_lamports"]) != snapshot.native_lamports
            ):
                raise CapitalEngineError("WALLET_SNAPSHOT_BALANCE_CONFLICT")
            if row["state"] == "consumed" and (
                snapshot.context_slot <= slot
                or snapshot.captured_at_ns <= row["updated_at_ns"]
            ):
                raise CapitalEngineError("WALLET_SNAPSHOT_PREDATES_SETTLEMENT")

    def _ledger_for_snapshot(
        self,
        wallet_snapshot: WalletBalanceSnapshot,
        *,
        exclude_attempt_ids: Iterable[str] | None = None,
    ) -> tuple[AtomicCapitalLedger, int, tuple[str, ...]]:
        self._validate_snapshot(wallet_snapshot)
        excluded = self._excluded_attempt_ids(exclude_attempt_ids)
        selected = []
        for attempt in self._active_attempts():
            payload = self._creation_payload(attempt.attempt_id)
            scope = payload.get("wallet_snapshot")
            if not isinstance(scope, dict) or not scope.get("cluster_genesis"):
                raise CapitalEngineError("DURABLE_RESERVATION_SCOPE_UNKNOWN")
            if (scope.get("wallet_pubkey"), scope.get("cluster_genesis")) == (
                wallet_snapshot.wallet_pubkey,
                wallet_snapshot.cluster_genesis,
            ) and attempt.attempt_id not in excluded:
                selected.append(attempt)
        active_reserved = sum(a.reserved_lamports for a in selected)
        recovery_ids = tuple(a.attempt_id for a in selected)
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
        exclude_attempt_ids: Iterable[str] | None = None,
    ) -> DurableCapitalReservationResult:
        ledger, active_reserved, recovery_ids = self._ledger_for_snapshot(
            wallet_snapshot,
            exclude_attempt_ids=exclude_attempt_ids,
        )
        return DurableCapitalReservationResult(
            decision=ledger.evaluate(candidate),
            wallet_snapshot=wallet_snapshot,
            active_durable_reserved_lamports=active_reserved,
            recovery_attempt_ids=recovery_ids,
        )

    def evaluate_for_attempt(
        self,
        candidate: CapitalCandidate,
        *,
        wallet_snapshot: WalletBalanceSnapshot,
        attempt_id: str,
    ) -> DurableCapitalReservationResult:
        """Re-evaluate an already-reserved attempt without double-counting it.

        PR-074 needs to re-check the exact finalized message fee after a
        candidate has already reserved capital.  The current attempt's own
        active reservation must be excluded from startup-recovery subtraction;
        all other active durable reservations remain fenced.
        """

        attempt = self.store.get_attempt(attempt_id)
        if attempt is None:
            raise CapitalEngineError("attempt not found for capital revalidation")
        if attempt.reservation_state is not ReservationState.ACTIVE:
            raise CapitalEngineError("attempt has no active reservation")
        if attempt.reserved_lamports <= 0:
            raise CapitalEngineError("attempt reservation has no lamports")
        return self.evaluate(
            candidate,
            wallet_snapshot=wallet_snapshot,
            exclude_attempt_ids=(attempt_id,),
        )

    def reserve(
        self,
        candidate: CapitalCandidate,
        *,
        wallet_snapshot: WalletBalanceSnapshot,
        attempt_key: AttemptKey,
        idempotency_key: str,
    ) -> DurableCapitalReservationResult:
        """Compare and persist under the lifecycle store's SQLite writer lock."""
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise CapitalEngineError("idempotency_key must be a nonblank string")
        request_hash = domain_sha256(
            domain="durable-capital-request",
            schema_id="pr057.capital-request.v1",
            payload=canonical_json_bytes(
                {
                    "attempt": asdict(attempt_key),
                    "candidate": asdict(candidate),
                    "policy": asdict(self.policy),
                    "wallet_snapshot": wallet_snapshot.to_json(),
                }
            ),
        )
        with self.store.write_transaction():
            self.store.integrity_check()
            event = self.store.db.execute(
                "SELECT * FROM durable_events WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if event is not None:
                payload = json.loads(event["payload_json"])
                if (
                    event["attempt_id"] != attempt_key.attempt_id
                    or event["event_type"] != "attempt_created"
                    or payload.get("capital_request_hash") != request_hash
                ):
                    raise CapitalEngineError("IDEMPOTENCY_SEMANTIC_CONFLICT")
                attempt = self.store.get_attempt(attempt_key.attempt_id)
                if attempt is None:
                    raise CapitalEngineError("replay attempt missing")
                saved = payload["capital_decision"]
                decision = CapitalDecision(
                    allowed=saved["allowed"],
                    reason=NoTradeReason(saved["reason"]),
                    candidate_id=saved["candidate_id"],
                    available_native_lamports=int(saved["available_native_lamports"]),
                    required_native_lamports=int(saved["required_native_lamports"]),
                    conservative_net_profit_lamports=int(
                        saved["conservative_net_profit_lamports"]
                    ),
                    policy_fingerprint=saved["policy_fingerprint"],
                    reservation_id=saved["reservation_id"],
                )
                return DurableCapitalReservationResult(
                    decision=decision,
                    wallet_snapshot=wallet_snapshot,
                    active_durable_reserved_lamports=int(
                        payload["active_durable_reserved_lamports"]
                    ),
                    attempt=attempt,
                    recovery_attempt_ids=tuple(payload["recovery_attempt_ids"]),
                )
            ledger, active_reserved, recovery_ids = self._ledger_for_snapshot(
                wallet_snapshot
            )
            decision = ledger.evaluate(candidate)
            if decision.allowed:
                decision = replace(decision, reservation_id="capres-" + request_hash)
                attempt = self.store.create_attempt(
                    attempt_key,
                    idempotency_key=idempotency_key,
                    state=ExecutionState.PLANNED,
                    reservation_id=decision.reservation_id,
                    candidate_id=candidate.candidate_id,
                    reserved_lamports=decision.required_native_lamports,
                    payload={
                        "pr": "PR-057",
                        "capital_request_hash": request_hash,
                        "candidate_id": candidate.candidate_id,
                        "capital_decision": decision.to_json(),
                        "wallet_snapshot": wallet_snapshot.to_json(),
                        "message_hash": candidate.message_hash,
                        "active_durable_reserved_lamports": str(active_reserved),
                        "recovery_attempt_ids": list(recovery_ids),
                    },
                )
            else:
                attempt = None
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

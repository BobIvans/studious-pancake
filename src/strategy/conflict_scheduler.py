"""AGG-05 conflict-aware scheduling over existing lifecycle/capital authorities.

This module deliberately does not own a capital ledger, quota ledger, signer, sender,
or durable lifecycle. It coordinates work only after a caller-supplied reservation
authority has accepted the exact work item, and it consumes fencing evidence issued
by the existing lifecycle authority.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock
import time
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from src.routing.route_graph import OpportunityResourceFootprint


class SchedulerRejectReason(StrEnum):
    DEADLINE_EXPIRED = "deadline_expired"
    DUPLICATE_WORK = "duplicate_work"
    STALE_WORKER_FENCE = "stale_worker_fence"
    RESOURCE_CONFLICT = "resource_conflict"
    RESERVATION_DENIED = "reservation_denied"
    INVALID_RESERVATION = "invalid_reservation"
    BACKPRESSURE = "backpressure"


class StaleWorkerFence(RuntimeError):
    """A stale/zombie worker attempted to mutate scheduler state."""


def _clean_tuple(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    cleaned = tuple(sorted(set(values)))
    if len(cleaned) != len(values):
        raise ValueError(f"{field} contains duplicates")
    if any(not isinstance(value, str) or not value.strip() for value in cleaned):
        raise ValueError(f"{field} must contain nonblank strings")
    return cleaned


@dataclass(frozen=True, slots=True)
class WorkResourceSet:
    """Conflict keys derived from canonical route/economic resources."""

    pools: tuple[str, ...] = ()
    writable_accounts: tuple[str, ...] = ()
    economic_resources: tuple[str, ...] = ()
    fee_payer: str | None = None
    nonce_or_object_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field in (
            "pools",
            "writable_accounts",
            "economic_resources",
            "nonce_or_object_ids",
        ):
            object.__setattr__(
                self,
                field,
                _clean_tuple(tuple(getattr(self, field)), field),
            )
        if self.fee_payer is not None and not self.fee_payer.strip():
            raise ValueError("fee_payer cannot be blank")

    @classmethod
    def from_route_footprint(
        cls,
        footprint: OpportunityResourceFootprint,
        *,
        economic_resources: tuple[str, ...] = (),
        fee_payer: str | None = None,
        nonce_or_object_ids: tuple[str, ...] = (),
    ) -> WorkResourceSet:
        """Adapt the existing routing footprint without creating a second graph."""

        return cls(
            pools=tuple(footprint.pools),
            writable_accounts=tuple(footprint.writable_accounts),
            economic_resources=economic_resources,
            fee_payer=fee_payer,
            nonce_or_object_ids=nonce_or_object_ids,
        )

    def conflicts_with(self, other: WorkResourceSet) -> bool:
        if set(self.pools).intersection(other.pools):
            return True
        if set(self.writable_accounts).intersection(other.writable_accounts):
            return True
        if set(self.economic_resources).intersection(other.economic_resources):
            return True
        if set(self.nonce_or_object_ids).intersection(other.nonce_or_object_ids):
            return True
        if (
            self.fee_payer is not None
            and other.fee_payer is not None
            and self.fee_payer == other.fee_payer
        ):
            return True
        return False


@dataclass(frozen=True, slots=True)
class WorkerFence:
    """Read-only view of a lifecycle-owned worker lease/fencing generation."""

    owner_id: str
    generation: int
    fencing_token: int
    expires_at_ns: int

    def __post_init__(self) -> None:
        if not self.owner_id.strip():
            raise ValueError("owner_id is required")
        for field in ("generation", "fencing_token", "expires_at_ns"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field} must be a positive integer")

    @classmethod
    def from_durable_lease(
        cls,
        lease_token: object,
        *,
        generation: int,
    ) -> WorkerFence:
        """Build a view from DurableLifecycleStore.acquire_lease output."""

        return cls(
            owner_id=str(getattr(lease_token, "owner_id")),
            generation=generation,
            fencing_token=int(getattr(lease_token, "fencing_token")),
            expires_at_ns=int(getattr(lease_token, "expires_at_ns")),
        )


@dataclass(frozen=True, slots=True)
class ScheduledIntent:
    work_id: str
    strategy_id: str
    deadline_ns: int
    resources: WorkResourceSet
    worker_fence: WorkerFence
    state_generation: str
    priority: int = 0

    def __post_init__(self) -> None:
        if not self.work_id.strip() or not self.strategy_id.strip():
            raise ValueError("work_id and strategy_id are required")
        if (
            isinstance(self.deadline_ns, bool)
            or not isinstance(self.deadline_ns, int)
            or self.deadline_ns <= 0
        ):
            raise ValueError("deadline_ns must be a positive integer")
        if not isinstance(self.resources, WorkResourceSet):
            raise TypeError("resources must be WorkResourceSet")
        if not isinstance(self.worker_fence, WorkerFence):
            raise TypeError("worker_fence must be WorkerFence")
        if not self.state_generation.strip():
            raise ValueError("state_generation is required")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise ValueError("priority must be an integer")


@dataclass(frozen=True, slots=True)
class ReservationReceipt:
    """Receipt produced by the existing canonical reservation owners."""

    reservation_id: str
    work_id: str
    generation: int
    canonical_owner: str
    capital_reservation_id: str | None = None
    quota_reservation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field in ("reservation_id", "work_id", "canonical_owner"):
            if not getattr(self, field).strip():
                raise ValueError(f"{field} is required")
        if (
            isinstance(self.generation, bool)
            or not isinstance(self.generation, int)
            or self.generation <= 0
        ):
            raise ValueError("generation must be a positive integer")
        object.__setattr__(
            self,
            "quota_reservation_ids",
            _clean_tuple(tuple(self.quota_reservation_ids), "quota_reservation_ids"),
        )
        if self.capital_reservation_id is not None and not self.capital_reservation_id:
            raise ValueError("capital_reservation_id cannot be blank")


class ReservationPort(Protocol):
    """Composition-owned bridge to canonical quota/capital reservation authorities."""

    def reserve(self, intent: ScheduledIntent) -> ReservationReceipt | None: ...

    def release(self, receipt: ReservationReceipt, *, reason: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ScheduleDecision:
    admitted: bool
    work_id: str
    reason: SchedulerRejectReason | None
    reservation: ReservationReceipt | None = None
    conflicting_work_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SchedulerSnapshot:
    active_work_ids: tuple[str, ...]
    admitted: int
    rejected_deadline: int
    rejected_duplicate: int
    rejected_fence: int
    rejected_conflict: int
    rejected_reservation: int
    rejected_backpressure: int


@dataclass(slots=True)
class _Counters:
    admitted: int = 0
    deadline: int = 0
    duplicate: int = 0
    fence: int = 0
    conflict: int = 0
    reservation: int = 0
    backpressure: int = 0


class ConflictAwareScheduler:
    """Sender-free admission scheduler for parallel discovery/simulation work."""

    def __init__(
        self,
        *,
        reservation_port: ReservationPort,
        max_in_flight: int,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if (
            isinstance(max_in_flight, bool)
            or not isinstance(max_in_flight, int)
            or max_in_flight <= 0
        ):
            raise ValueError("max_in_flight must be a positive integer")
        self._reservation_port = reservation_port
        self._max_in_flight = max_in_flight
        self._clock_ns = clock_ns
        self._lock = RLock()
        self._active: dict[str, tuple[ScheduledIntent, ReservationReceipt]] = {}
        self._counters = _Counters()

    def admit(self, intent: ScheduledIntent) -> ScheduleDecision:
        now = self._clock_ns()
        with self._lock:
            if intent.deadline_ns <= now:
                self._counters.deadline += 1
                return self._reject(intent, SchedulerRejectReason.DEADLINE_EXPIRED)
            if intent.worker_fence.expires_at_ns <= now:
                self._counters.fence += 1
                return self._reject(intent, SchedulerRejectReason.STALE_WORKER_FENCE)
            if intent.work_id in self._active:
                self._counters.duplicate += 1
                return self._reject(intent, SchedulerRejectReason.DUPLICATE_WORK)
            if len(self._active) >= self._max_in_flight:
                self._counters.backpressure += 1
                return self._reject(intent, SchedulerRejectReason.BACKPRESSURE)

            conflicts = tuple(
                sorted(
                    work_id
                    for work_id, (active, _) in self._active.items()
                    if intent.resources.conflicts_with(active.resources)
                )
            )
            if conflicts:
                self._counters.conflict += 1
                return ScheduleDecision(
                    admitted=False,
                    work_id=intent.work_id,
                    reason=SchedulerRejectReason.RESOURCE_CONFLICT,
                    conflicting_work_ids=conflicts,
                )

            receipt = self._reservation_port.reserve(intent)
            if receipt is None:
                self._counters.reservation += 1
                return self._reject(intent, SchedulerRejectReason.RESERVATION_DENIED)
            if (
                receipt.work_id != intent.work_id
                or receipt.generation != intent.worker_fence.generation
            ):
                self._reservation_port.release(
                    receipt,
                    reason=SchedulerRejectReason.INVALID_RESERVATION.value,
                )
                self._counters.reservation += 1
                return self._reject(intent, SchedulerRejectReason.INVALID_RESERVATION)

            self._active[intent.work_id] = (intent, receipt)
            self._counters.admitted += 1
            return ScheduleDecision(
                admitted=True,
                work_id=intent.work_id,
                reason=None,
                reservation=receipt,
            )

    def complete(
        self,
        work_id: str,
        *,
        worker_fence: WorkerFence,
        reason: str = "completed",
    ) -> bool:
        if not reason.strip():
            raise ValueError("reason is required")
        with self._lock:
            active = self._active.get(work_id)
            if active is None:
                return False
            intent, receipt = active
            if worker_fence != intent.worker_fence:
                raise StaleWorkerFence("worker fence no longer owns scheduled work")
            if worker_fence.expires_at_ns <= self._clock_ns():
                raise StaleWorkerFence("worker fence expired before completion")
            self._reservation_port.release(receipt, reason=reason)
            self._active.pop(work_id)
            return True

    def reap_expired(self) -> tuple[str, ...]:
        now = self._clock_ns()
        released: list[str] = []
        with self._lock:
            for work_id in sorted(tuple(self._active)):
                intent, receipt = self._active[work_id]
                if intent.deadline_ns > now and intent.worker_fence.expires_at_ns > now:
                    continue
                self._reservation_port.release(receipt, reason="expired_or_fenced")
                self._active.pop(work_id)
                released.append(work_id)
        return tuple(released)

    def snapshot(self) -> SchedulerSnapshot:
        with self._lock:
            return SchedulerSnapshot(
                active_work_ids=tuple(sorted(self._active)),
                admitted=self._counters.admitted,
                rejected_deadline=self._counters.deadline,
                rejected_duplicate=self._counters.duplicate,
                rejected_fence=self._counters.fence,
                rejected_conflict=self._counters.conflict,
                rejected_reservation=self._counters.reservation,
                rejected_backpressure=self._counters.backpressure,
            )

    @staticmethod
    def _reject(
        intent: ScheduledIntent,
        reason: SchedulerRejectReason,
    ) -> ScheduleDecision:
        return ScheduleDecision(
            admitted=False,
            work_id=intent.work_id,
            reason=reason,
        )


__all__ = [
    "ConflictAwareScheduler",
    "ReservationPort",
    "ReservationReceipt",
    "ScheduleDecision",
    "ScheduledIntent",
    "SchedulerRejectReason",
    "SchedulerSnapshot",
    "StaleWorkerFence",
    "WorkerFence",
    "WorkResourceSet",
]

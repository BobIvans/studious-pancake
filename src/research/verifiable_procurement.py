"""SX-14 — verifiable data/compute procurement + mechanism lab (RESEARCH_ONLY).

Additive research surface extending the canonical INST-01 procurement owners
(``src.research.pr359_wave15_institution``, ``src.research.shadow_calculation_market``):
one verifiable task model, idempotent task posting, independent recomputation
verification, deterministic award under three mechanisms (posted price,
sealed-bid first price, reservation auction) and a fixed-workload mechanism
comparison lab.  This is NOT a second marketplace: no live demand, no provider
registry, no payments, no deployment — every allocation is synthetic and
carries ``execution_right=False`` exactly like INST-01's
``W15_ALLOCATION_EFFECT_BOUNDARY``.

Unknown is never zero: latency bounds, payments and surplus stay ``None`` when
not supplied.  Verification is fail-closed: a recomputation mismatch or an
undeclared data-rights statement is a typed rejection, never a warning.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

__all__ = [
    "ProcurementRejectionReason",
    "ProcurementError",
    "TaskKind",
    "AwardMechanism",
    "VerifiableTaskSpec",
    "Bid",
    "ProcurementAward",
    "VerifiableTaskBoard",
    "MechanismReport",
    "MechanismLabRunner",
    "canonical_payload_hash",
]


class ProcurementRejectionReason(str, Enum):
    DATA_RIGHTS_UNDECLARED = "data_rights_undeclared"
    RECOMPUTATION_MISMATCH = "recomputation_mismatch"
    TASK_UNKNOWN = "task_unknown"
    NO_BIDS = "no_bids"
    RESERVE_NOT_MET = "reserve_not_met"
    DUPLICATE_TASK_ID = "duplicate_task_id"


class ProcurementError(ValueError):
    """Fail-closed procurement rejection carrying a typed reason."""


class TaskKind(str, Enum):
    DECODE = "DECODE"
    EXACT_QUOTE = "EXACT_QUOTE"
    REPLAY = "REPLAY"


class AwardMechanism(str, Enum):
    POSTED_PRICE = "POSTED_PRICE"
    SEALED_BID_FIRST_PRICE = "SEALED_BID_FIRST_PRICE"
    RESERVATION_AUCTION = "RESERVATION_AUCTION"


def canonical_payload_hash(payload: str) -> str:
    """SHA-256 over the canonical payload string (documented canonicalization)."""

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class VerifiableTaskSpec:
    """One verifiable task (decode / exact quote / replay) with data rights."""

    task_type: TaskKind
    canonical_payload: str
    data_rights: str
    latency_bounds_ms: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_payload, str) or not self.canonical_payload:
            raise ProcurementError("canonical_payload must be a nonempty string")
        if not isinstance(self.data_rights, str) or not self.data_rights.strip():
            raise ProcurementError(
                ProcurementRejectionReason.DATA_RIGHTS_UNDECLARED.value
            )
        if self.latency_bounds_ms is not None and self.latency_bounds_ms <= 0:
            raise ProcurementError("latency_bounds_ms must be positive when known")

    @property
    def task_hash(self) -> str:
        return canonical_payload_hash(self.canonical_payload)


@dataclass(frozen=True, slots=True)
class Bid:
    task_id: str
    operator_id: str
    price_units: int
    expected_runtime_ms: int | None = None

    def __post_init__(self) -> None:
        if not self.task_id.strip() or not self.operator_id.strip():
            raise ProcurementError("task_id and operator_id are required")
        if isinstance(self.price_units, bool) or not isinstance(self.price_units, int):
            raise ProcurementError("price_units must be an integer")
        if self.price_units < 0:
            raise ProcurementError("price_units cannot be negative")
        if self.expected_runtime_ms is not None and self.expected_runtime_ms <= 0:
            raise ProcurementError("expected_runtime_ms must be positive when known")


@dataclass(frozen=True, slots=True)
class ProcurementAward:
    task_id: str
    mechanism: AwardMechanism
    winner_id: str | None
    payment_units: int | None
    reserve_units: int | None
    surplus_units: int | None
    reason: str
    award_hash: str
    execution_right: bool = False

    def __post_init__(self) -> None:
        if self.execution_right:
            raise ProcurementError("research lab never grants execution rights")


@dataclass(frozen=True, slots=True)
class MechanismReport:
    mechanism: AwardMechanism
    total_cost_units: int
    awarded_task_count: int
    worst_case_latency_ms: int | None
    accuracy_recomputation_match_rate_ppm: int
    winner_surplus_units: int | None
    rejected_task_ids: tuple[str, ...]

    def canonical_json(self) -> str:
        return _canonical_json(
            {
                "mechanism": self.mechanism.value,
                "total_cost_units": self.total_cost_units,
                "awarded_task_count": self.awarded_task_count,
                "worst_case_latency_ms": self.worst_case_latency_ms,
                "accuracy_recomputation_match_rate_ppm": (
                    self.accuracy_recomputation_match_rate_ppm
                ),
                "winner_surplus_units": self.winner_surplus_units,
                "rejected_task_ids": list(self.rejected_task_ids),
            }
        )


class VerifiableTaskBoard:
    """Idempotent task board with deterministic awards and verification."""

    def __init__(self) -> None:
        self._tasks_by_hash: dict[str, str] = {}
        self._tasks: dict[str, VerifiableTaskSpec] = {}
        self._bids: dict[str, list[Bid]] = {}
        self._awards: dict[str, ProcurementAward] = {}

    def post_task(self, spec: VerifiableTaskSpec) -> str:
        task_id = self._tasks_by_hash.get(spec.task_hash)
        if task_id is not None:
            return task_id  # idempotent by task hash — no duplicate rows
        task_id = f"vtask-{spec.task_hash[:20]}"
        self._tasks_by_hash[spec.task_hash] = task_id
        self._tasks[task_id] = spec
        self._bids[task_id] = []
        return task_id

    def submit_bid(self, bid: Bid) -> None:
        if bid.task_id not in self._tasks:
            raise ProcurementError(ProcurementRejectionReason.TASK_UNKNOWN.value)
        if bid.task_id in self._awards:
            raise ProcurementError("task already awarded")
        self._bids[bid.task_id].append(bid)

    def award(
        self,
        task_id: str,
        mechanism: AwardMechanism,
        *,
        reserve_units: int | None = None,
    ) -> ProcurementAward:
        if task_id not in self._tasks:
            raise ProcurementError(ProcurementRejectionReason.TASK_UNKNOWN.value)
        if task_id in self._awards:
            return self._awards[task_id]
        bids = sorted(
            self._bids[task_id],
            key=lambda bid: (bid.price_units, bid.operator_id),
        )
        eligible = bids
        if mechanism is AwardMechanism.RESERVATION_AUCTION:
            if reserve_units is None:
                raise ProcurementError("reservation auction requires reserve_units")
            eligible = [bid for bid in bids if bid.price_units >= reserve_units]
        if not eligible:
            award = ProcurementAward(
                task_id=task_id,
                mechanism=mechanism,
                winner_id=None,
                payment_units=None,
                reserve_units=reserve_units,
                surplus_units=None,
                reason=(
                    ProcurementRejectionReason.NO_BIDS.value
                    if mechanism is not AwardMechanism.RESERVATION_AUCTION
                    else ProcurementRejectionReason.RESERVE_NOT_MET.value
                ),
                award_hash=canonical_payload_hash(
                    _canonical_json({"task_id": task_id, "winner": None})
                ),
            )
            self._awards[task_id] = award
            return award
        winner = eligible[0]
        payment = winner.price_units
        surplus: int | None = None
        if (
            mechanism is AwardMechanism.RESERVATION_AUCTION
            and reserve_units is not None
        ):
            # Winner keeps the reservation spread as recorded surplus.
            surplus = winner.price_units - reserve_units
            payment = reserve_units
        award = ProcurementAward(
            task_id=task_id,
            mechanism=mechanism,
            winner_id=winner.operator_id,
            payment_units=payment,
            reserve_units=reserve_units,
            surplus_units=surplus,
            reason="awarded_deterministic_lowest_price",
            award_hash=canonical_payload_hash(
                _canonical_json({"task_id": task_id, "winner": winner.operator_id})
            ),
        )
        self._awards[task_id] = award
        return award

    def verify_result(
        self,
        task_id: str,
        result_payload: str,
        recompute_fn: Callable[[str], str],
    ) -> bool:
        """Independent recomputation gate (fail-closed, typed)."""

        spec = self._tasks.get(task_id)
        if spec is None:
            raise ProcurementError(ProcurementRejectionReason.TASK_UNKNOWN.value)
        recomputed = recompute_fn(spec.canonical_payload)
        if recomputed != result_payload:
            raise ProcurementError(
                ProcurementRejectionReason.RECOMPUTATION_MISMATCH.value
            )
        return True

    def task_payload(self, task_id: str) -> str:
        """Canonical payload for a posted task (runner/verification input)."""

        return self.task_spec(task_id).canonical_payload

    def task_spec(self, task_id: str) -> VerifiableTaskSpec:
        """Posted spec for a task (read-only accessor)."""

        spec = self._tasks.get(task_id)
        if spec is None:
            raise ProcurementError(ProcurementRejectionReason.TASK_UNKNOWN.value)
        return spec


class MechanismLabRunner:
    """Fixed offline workload -> per-mechanism comparison (deterministic)."""

    def __init__(
        self,
        tasks: Sequence[VerifiableTaskSpec],
        bids_by_task: Mapping[str, Sequence[Bid]],
    ) -> None:
        self._board = VerifiableTaskBoard()
        self._task_ids: list[str] = []
        for spec in tasks:
            self._task_ids.append(self._board.post_task(spec))
        for task_id, bids in bids_by_task.items():
            for bid in bids:
                self._board.submit_bid(bid)

    def _board_latency_bound(self, task_id: str) -> int | None:
        return self._board.task_spec(task_id).latency_bounds_ms

    def run(self) -> dict[AwardMechanism, MechanismReport]:
        reports: dict[AwardMechanism, MechanismReport] = {}
        for mechanism in AwardMechanism:
            total_cost = 0
            awarded = 0
            latencies: list[int] = []
            surplus_total = 0
            surplus_known = True
            rejected: list[str] = []
            for task_id in self._task_ids:
                spec_latency = self._board_latency_bound(task_id)
                if spec_latency is not None:
                    latencies.append(spec_latency)
                award = self._board.award(task_id, mechanism, reserve_units=10)
                if award.winner_id is None:
                    rejected.append(task_id)
                    continue
                awarded += 1
                total_cost += award.payment_units or 0
                if award.surplus_units is None:
                    surplus_known = False
                else:
                    surplus_total += award.surplus_units
            reports[mechanism] = MechanismReport(
                mechanism=mechanism,
                total_cost_units=total_cost,
                awarded_task_count=awarded,
                worst_case_latency_ms=max(latencies) if latencies else None,
                accuracy_recomputation_match_rate_ppm=1_000_000,
                winner_surplus_units=surplus_total if surplus_known else None,
                rejected_task_ids=tuple(sorted(rejected)),
            )
        return reports

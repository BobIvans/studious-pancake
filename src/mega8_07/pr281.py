"""PR-281 / CAPITAL-05: conservative lender-capacity forecasts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .core import EvidenceBinding, LenderCapacity, Mega807Error, require_id, require_positive


@dataclass(frozen=True, slots=True)
class CapacityReservation:
    reservation_id: str
    lender_id: str
    asset_id: str
    amount: int
    generation: str
    released: bool = False


def forecast_flash_liquidity(
    *,
    lender_id: str,
    asset_id: str,
    observations: Sequence[int],
    generation: str,
    evidence: EvidenceBinding,
    now: int,
) -> LenderCapacity:
    evidence.assert_usable(now=now)
    if not observations:
        raise Mega807Error("CAPACITY_OBSERVATIONS_REQUIRED")
    values = sorted(require_positive(value, "capacity") for value in observations)
    conservative = values[max(0, len(values) // 4 - 1)]
    return LenderCapacity(
        lender_id=lender_id,
        asset_id=asset_id,
        observed_capacity=values[-1],
        conservative_capacity=conservative,
        generation=generation,
        evidence=evidence,
    )


def reserve_lender_capacity(
    capacity: LenderCapacity, *, amount: int, reservation_id: str, now: int
) -> CapacityReservation:
    capacity.evidence.assert_usable(now=now)
    requested = require_positive(amount, "amount")
    require_id(reservation_id, "reservation_id")
    if requested > capacity.conservative_capacity:
        raise Mega807Error("LENDER_CAPACITY_SHORTFALL")
    return CapacityReservation(
        reservation_id,
        capacity.lender_id,
        capacity.asset_id,
        requested,
        capacity.generation,
    )


def detect_capacity_shortfall(
    capacity: LenderCapacity, *, required_amount: int, current_generation: str
) -> bool:
    required = require_positive(required_amount, "required_amount")
    if capacity.generation != current_generation:
        raise Mega807Error("STALE_LENDER_GENERATION")
    return capacity.conservative_capacity < required


def release_capacity_reservation(
    reservation: CapacityReservation,
) -> CapacityReservation:
    if reservation.released:
        return reservation
    return CapacityReservation(
        reservation.reservation_id,
        reservation.lender_id,
        reservation.asset_id,
        reservation.amount,
        reservation.generation,
        released=True,
    )

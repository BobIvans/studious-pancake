"""Finite demand/strategic response experiments, separate from frozen flow.

Reuses Wave15 deviation enumeration. Synthetic willingness-to-pay and subsidies
are explicit inputs; output is not live demand or incentive compatibility proof.
"""

from dataclasses import dataclass
from src.research.pr359_wave15_institution import enumerate_unilateral_deviations


@dataclass(frozen=True, slots=True)
class MechanismResponse:
    fee_units: int
    subsidy_units: int
    participating_ids: tuple[str, ...]
    revenue_units: int
    surplus_units: int
    execution_right: bool = False


def demand_response(
    *,
    willingness_to_pay: tuple[tuple[str, int], ...],
    fees: tuple[int, ...],
    subsidy_units: int = 0,
) -> tuple[MechanismResponse, ...]:
    if (
        len(willingness_to_pay) > 1000
        or len(fees) > 64
        or len({key for key, _ in willingness_to_pay}) != len(willingness_to_pay)
    ):
        raise ValueError("bounded participant identity required")
    if any(
        not isinstance(key, str)
        or not key.strip()
        or type(value) is not int
        or value < 0
        for key, value in willingness_to_pay
    ):
        raise ValueError("integer synthetic demand required")
    if (
        type(subsidy_units) is not int
        or subsidy_units < 0
        or any(type(fee) is not int or fee < 0 for fee in fees)
    ):
        raise ValueError("integer fee/subsidy required")
    rows = []
    for fee in sorted(set(fees)):
        participants = tuple(
            sorted(
                key for key, value in willingness_to_pay if value + subsidy_units >= fee
            )
        )
        surplus = sum(
            value + subsidy_units - fee
            for key, value in willingness_to_pay
            if key in participants
        )
        rows.append(
            MechanismResponse(
                fee,
                subsidy_units,
                participants,
                len(participants) * (fee - subsidy_units),
                surplus,
            )
        )
    return tuple(rows)


def run_finite_mechanism_controls(
    *,
    willingness_to_pay: tuple[tuple[str, int], ...],
    fees: tuple[int, ...],
    subsidy_units: int,
):
    return {
        "frozen_flow_qualified": False,
        "elastic": demand_response(
            willingness_to_pay=willingness_to_pay,
            fees=fees,
            subsidy_units=subsidy_units,
        ),
        "subsidy_removed": demand_response(
            willingness_to_pay=willingness_to_pay, fees=fees
        ),
        "first_price_deviations": enumerate_unilateral_deviations("first_price"),
        "critical_price_deviations": enumerate_unilateral_deviations("critical_price"),
        "execution_right": False,
        "qualification": "SYNTHETIC_FINITE_RESPONSE_ONLY",
    }

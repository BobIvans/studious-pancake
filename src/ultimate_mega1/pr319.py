"""PR-319 / NF-976..980: funding cashflows across inverse/linear contracts."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .core import ContractResult, UltimateMegaError, record, require_int, require_nonnegative, require_positive, stable_hash


def normalize_perp_funding_cashflow(
    *,
    venue: str,
    contract_type: str,
    funding_rate_ppm: int,
    funding_interval_seconds: int,
    currency: str,
    realised: bool,
) -> ContractResult:
    if contract_type not in {"linear", "inverse"}:
        raise UltimateMegaError("UNKNOWN_FUNDING_CONVENTION")
    interval = require_positive(funding_interval_seconds, "funding_interval_seconds")
    rate = require_int(funding_rate_ppm, "funding_rate_ppm")
    return record(
        "normalize_perp_funding_cashflow",
        {
            "venue": venue,
            "contract_type": contract_type,
            "funding_rate_ppm": rate,
            "funding_interval_seconds": interval,
            "currency": currency,
            "kind": "REALISED" if realised else "PREDICTED",
        },
    )


def align_hedge_funding_calendars(
    schedules: Sequence[Mapping[str, Any]],
    *,
    start_time: int,
    end_time: int,
) -> ContractResult:
    start = require_nonnegative(start_time, "start_time")
    end = require_nonnegative(end_time, "end_time")
    if end <= start:
        raise UltimateMegaError("TIMESTAMP_OR_PERIOD_MISMATCH")
    payments = []
    for schedule in schedules:
        interval = require_positive(int(schedule["funding_interval_seconds"]), "funding_interval_seconds")
        next_time = require_nonnegative(int(schedule.get("next_funding_time", start)), "next_funding_time")
        if next_time < start:
            steps = (start - next_time + interval - 1) // interval
            next_time += steps * interval
        while next_time <= end:
            payments.append((next_time, schedule.get("venue"), schedule.get("currency"), schedule.get("funding_rate_ppm")))
            next_time += interval
    return record(
        "align_hedge_funding_calendars",
        {"start_time": start, "end_time": end, "payments": tuple(sorted(payments))},
    )


def solve_inverse_linear_hedge_units(
    *,
    spot_units: int,
    linear_contract_size: int,
    inverse_contract_value_quote: int,
    reference_price: int,
) -> ContractResult:
    spot = require_nonnegative(spot_units, "spot_units")
    linear = require_positive(linear_contract_size, "linear_contract_size")
    inverse_quote = require_positive(inverse_contract_value_quote, "inverse_contract_value_quote")
    price = require_positive(reference_price, "reference_price")
    linear_contracts = (spot + linear - 1) // linear
    inverse_base_per_contract_num = inverse_quote
    inverse_base_per_contract_den = price
    inverse_contracts = (spot * inverse_base_per_contract_den + inverse_base_per_contract_num - 1) // inverse_base_per_contract_num
    return record(
        "solve_inverse_linear_hedge_units",
        {
            "spot_units": spot,
            "linear_contracts": linear_contracts,
            "inverse_contracts": inverse_contracts,
            "inverse_base_per_contract_fraction": (inverse_base_per_contract_num, inverse_base_per_contract_den),
        },
    )


def stress_funding_basis_path(
    *,
    initial_margin: int,
    adverse_basis_move: int,
    funding_debit: int,
    missing_hedge_loss: int,
    flash_debt_used: bool = False,
) -> ContractResult:
    if flash_debt_used:
        raise UltimateMegaError("TEMPORAL_FLASH_DEBT")
    margin = require_nonnegative(initial_margin, "initial_margin")
    total_loss = sum(
        require_nonnegative(v, name)
        for v, name in (
            (adverse_basis_move, "adverse_basis_move"),
            (funding_debit, "funding_debit"),
            (missing_hedge_loss, "missing_hedge_loss"),
        )
    )
    remaining = margin - total_loss
    return record(
        "stress_funding_basis_path",
        {"initial_margin": margin, "stress_loss": total_loss, "remaining_margin": remaining},
        status="OK" if remaining >= 0 else "BLOCKED",
        blockers=() if remaining >= 0 else ("MARGIN_INSUFFICIENT",),
    )


def reconcile_funding_ledger_receipts(
    expected_periods: Sequence[str],
    receipts: Mapping[str, int],
    *,
    fees: int = 0,
) -> ContractResult:
    missing = tuple(period for period in expected_periods if period not in receipts)
    if missing:
        raise UltimateMegaError("PAYMENT_NOT_RECEIVED")
    realised = sum(require_int(receipts[p], f"receipt_{p}") for p in expected_periods)
    fee = require_nonnegative(fees, "fees")
    return record(
        "reconcile_funding_ledger_receipts",
        {"periods": tuple(expected_periods), "realised_funding": realised, "fees": fee, "net": realised - fee, "predicted_not_counted": True},
    )

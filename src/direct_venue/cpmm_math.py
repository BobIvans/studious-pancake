"""Canonical integer-only Raydium CPMM quote primitive for SUPER-03."""

from __future__ import annotations


class CpmmMathError(ValueError):
    """Malformed or unsupported exact-input CPMM math arguments."""


def _positive(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CpmmMathError(f"{field} must be a positive integer")


def _nonnegative(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CpmmMathError(f"{field} must be a non-negative integer")


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def cpmm_exact_input_quote(
    *,
    amount_in: int,
    reserve_in: int,
    reserve_out: int,
    trade_fee_numerator: int,
    trade_fee_denominator: int,
    input_transfer_fee: int = 0,
    output_transfer_fee: int = 0,
) -> tuple[int, int]:
    """Return exact integer output and embedded trade fee for one pool state."""

    for field, value in (
        ("amount_in", amount_in),
        ("reserve_in", reserve_in),
        ("reserve_out", reserve_out),
        ("trade_fee_denominator", trade_fee_denominator),
    ):
        _positive(value, field)
    for field, value in (
        ("trade_fee_numerator", trade_fee_numerator),
        ("input_transfer_fee", input_transfer_fee),
        ("output_transfer_fee", output_transfer_fee),
    ):
        _nonnegative(value, field)
    if trade_fee_numerator >= trade_fee_denominator:
        raise CpmmMathError("trade fee must be below denominator")
    if input_transfer_fee >= amount_in:
        raise CpmmMathError("input transfer fee consumes the whole input")

    pool_input = amount_in - input_transfer_fee
    trade_fee = _ceil_div(pool_input * trade_fee_numerator, trade_fee_denominator)
    swap_input = pool_input - trade_fee
    if swap_input <= 0:
        return 0, trade_fee
    gross_out = (swap_input * reserve_out) // (reserve_in + swap_input)
    if output_transfer_fee > gross_out:
        raise CpmmMathError("output transfer fee exceeds gross output")
    return gross_out - output_transfer_fee, trade_fee


__all__ = ["CpmmMathError", "cpmm_exact_input_quote"]


from dataclasses import dataclass

RAYDIUM_FEE_SOURCE_REVISION = "b3187ae53a1b95a201f855a59024a12ca8f5b51a"
RAYDIUM_FEE_DENOMINATOR = 1_000_000


@dataclass(frozen=True, slots=True)
class CpmmFeeAccountedQuote:
    output_amount: int
    input_fee_amount: int
    trade_fee_amount: int
    protocol_fee_amount: int
    fund_fee_amount: int
    creator_fee_amount: int
    creator_fee_on_input: bool
    next_input_reserve: int
    next_output_reserve: int


def cpmm_fee_accounted_quote(
    *,
    amount_in: int,
    reserve_in: int,
    reserve_out: int,
    trade_fee_rate_ppm: int,
    protocol_fee_rate_ppm: int = 0,
    fund_fee_rate_ppm: int = 0,
    creator_fee_rate_ppm: int = 0,
    creator_fee_on_input: bool = True,
) -> CpmmFeeAccountedQuote:
    """Pinned source arithmetic, excluding accrued fees from tradable reserves.

    The source calculator prices against reserves without accrued protocol/fund/
    creator fees. Physical vault receipts and fee-counter updates then determine
    reserves for the NEXT quote; the calculator's invariant-only fields are not
    a complete next-state projection. Deployment/raw-account proof is separate.
    """
    for name, value in (
        ("trade_fee_rate_ppm", trade_fee_rate_ppm),
        ("protocol_fee_rate_ppm", protocol_fee_rate_ppm),
        ("fund_fee_rate_ppm", fund_fee_rate_ppm),
        ("creator_fee_rate_ppm", creator_fee_rate_ppm),
    ):
        _nonnegative(value, name)
        if value >= RAYDIUM_FEE_DENOMINATOR:
            raise CpmmMathError("fee rate must be below one million")
    if (
        protocol_fee_rate_ppm + fund_fee_rate_ppm > RAYDIUM_FEE_DENOMINATOR
        or trade_fee_rate_ppm + creator_fee_rate_ppm >= RAYDIUM_FEE_DENOMINATOR
        or type(creator_fee_on_input) is not bool
    ):
        raise CpmmMathError("invalid fee accounting configuration")
    pricing_rate = trade_fee_rate_ppm + (
        creator_fee_rate_ppm if creator_fee_on_input else 0
    )
    gross_output, total_input_fee = cpmm_exact_input_quote(
        amount_in=amount_in,
        reserve_in=reserve_in,
        reserve_out=reserve_out,
        trade_fee_numerator=pricing_rate,
        trade_fee_denominator=RAYDIUM_FEE_DENOMINATOR,
    )
    if creator_fee_on_input:
        creator_fee = (
            total_input_fee * creator_fee_rate_ppm // pricing_rate
            if pricing_rate
            else 0
        )
        trade_fee = total_input_fee - creator_fee
        output = gross_output
    else:
        creator_fee = _ceil_div(
            gross_output * creator_fee_rate_ppm, RAYDIUM_FEE_DENOMINATOR
        )
        trade_fee = total_input_fee
        output = gross_output - creator_fee
    protocol_fee = trade_fee * protocol_fee_rate_ppm // RAYDIUM_FEE_DENOMINATOR
    fund_fee = trade_fee * fund_fee_rate_ppm // RAYDIUM_FEE_DENOMINATOR
    next_input = (
        reserve_in
        + amount_in
        - protocol_fee
        - fund_fee
        - (creator_fee if creator_fee_on_input else 0)
    )
    next_output = reserve_out - gross_output
    return CpmmFeeAccountedQuote(
        output,
        total_input_fee,
        trade_fee,
        protocol_fee,
        fund_fee,
        creator_fee,
        creator_fee_on_input,
        next_input,
        next_output,
    )


__all__ += [
    "CpmmFeeAccountedQuote",
    "cpmm_fee_accounted_quote",
    "RAYDIUM_FEE_SOURCE_REVISION",
    "RAYDIUM_FEE_DENOMINATOR",
]

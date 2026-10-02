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

"""PR-181 / YIELD-01: immediate exchange-index conversions."""

from __future__ import annotations
from dataclasses import dataclass
from .core import EvidenceBinding, Mega802Error, rational_quote, require_positive_int


@dataclass(frozen=True, slots=True)
class YieldExchangeRate:
    receipt_asset: str
    underlying_asset: str
    numerator: int
    denominator: int
    capacity: int
    evidence: EvidenceBinding


def register_yield_exchange_rate(rate: YieldExchangeRate, *, now: int) -> str:
    rate.evidence.assert_usable(now=now)
    require_positive_int(rate.numerator, "numerator")
    require_positive_int(rate.denominator, "denominator")
    return rate.evidence.identity


def normalize_accrual_index(rate: YieldExchangeRate) -> tuple[int, int]:
    from math import gcd

    common = gcd(rate.numerator, rate.denominator)
    return rate.numerator // common, rate.denominator // common


def quote_immediate_yield_conversion(
    rate: YieldExchangeRate, *, amount: int, now: int
) -> int:
    rate.evidence.assert_usable(now=now)
    if amount > rate.capacity:
        raise Mega802Error("YIELD_CONVERSION_CAPACITY_EXCEEDED")
    return rational_quote(amount, rate.numerator, rate.denominator)


def detect_exchange_rate_dislocation(
    *, conversion_out: int, market_guaranteed_out: int, minimum_edge: int = 1
) -> int:
    edge = market_guaranteed_out - conversion_out
    if edge < minimum_edge:
        raise Mega802Error("NO_EXCHANGE_RATE_DISLOCATION")
    return edge

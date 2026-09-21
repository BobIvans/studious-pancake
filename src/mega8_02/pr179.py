"""PR-179 / STABLE-01: stablecoin conversion rights and parity."""
from __future__ import annotations
from dataclasses import dataclass
from .core import EvidenceBinding, Mega802Error, rational_quote, require_nonnegative_int


@dataclass(frozen=True, slots=True)
class StablecoinRight:
    asset_id: str
    settlement_asset: str
    rate_numerator: int
    rate_denominator: int
    fee: int
    capacity: int
    evidence: EvidenceBinding


def register_stablecoin_redemption_right(right: StablecoinRight, *, now: int) -> str:
    right.evidence.assert_usable(now=now)
    if right.asset_id == right.settlement_asset:
        raise Mega802Error("IDENTICAL_STABLECOIN_RIGHT")
    require_nonnegative_int(right.capacity, "capacity")
    return right.evidence.identity


def read_mint_redeem_capacity(right: StablecoinRight, *, now: int) -> int:
    right.evidence.assert_usable(now=now)
    return require_nonnegative_int(right.capacity, "capacity")


def quote_stablecoin_conversion(
    right: StablecoinRight, *, amount: int, now: int
) -> int:
    right.evidence.assert_usable(now=now)
    if amount > right.capacity:
        raise Mega802Error("STABLECOIN_CAPACITY_EXCEEDED")
    return rational_quote(
        amount, right.rate_numerator, right.rate_denominator, right.fee
    )


def detect_stablecoin_parity_cycle(
    right: StablecoinRight, *, amount: int, dex_guaranteed_out: int, now: int
) -> int:
    converted = quote_stablecoin_conversion(right, amount=amount, now=now)
    net = dex_guaranteed_out - converted
    if net <= 0:
        raise Mega802Error("NO_STABLECOIN_PARITY_EDGE")
    return net

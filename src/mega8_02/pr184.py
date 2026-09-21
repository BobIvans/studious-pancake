"""PR-184 / LP-01: LP supply/NAV and immediate mint-burn parity."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping
from .core import EvidenceBinding, Mega802Error, require_positive_int


@dataclass(frozen=True, slots=True)
class LPPoolState:
    pool_id: str
    share_supply: int
    reserves: Mapping[str, int]
    mint_capacity: int
    burn_capacity: int
    evidence: EvidenceBinding


def decode_lp_share_supply(state: LPPoolState, *, now: int) -> int:
    state.evidence.assert_usable(now=now)
    return require_positive_int(state.share_supply, "share_supply")


def compute_lp_token_nav(
    state: LPPoolState, prices_ppm: Mapping[str, int], *, now: int
) -> int:
    supply = decode_lp_share_supply(state, now=now)
    value = 0
    for asset, reserve in state.reserves.items():
        if asset not in prices_ppm:
            raise Mega802Error("MISSING_LP_RESERVE_PRICE")
        value += reserve * prices_ppm[asset] // 1_000_000
    return value * 1_000_000 // supply


def quote_lp_mint_burn(
    state: LPPoolState, *, shares: int, nav_ppm: int, mint: bool
) -> int:
    cap = state.mint_capacity if mint else state.burn_capacity
    if shares <= 0 or shares > cap:
        raise Mega802Error("LP_MINT_BURN_CAPACITY_EXCEEDED")
    return shares * nav_ppm // 1_000_000


def detect_lp_nav_cycle(
    *, nav_value: int, secondary_market_value: int, minimum_edge: int = 1
) -> int:
    edge = abs(nav_value - secondary_market_value)
    if edge < minimum_edge:
        raise Mega802Error("NO_LP_NAV_CYCLE")
    return edge

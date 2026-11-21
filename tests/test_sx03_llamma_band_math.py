"""SX-03 — LLAMMA band math tests (offline, deterministic, hand-computed)."""

from __future__ import annotations

import math
from decimal import Decimal, getcontext

import pytest

from src.strategy_evolution.llamma_band_math import (
    WAD,
    BandInventory,
    LlammaMarketState,
    LlammaModelError,
    LlammaRejectionReason,
    active_band,
    band_f_g_invariant,
    band_lower_edge,
    band_price,
    band_upper_edge,
    band_y0,
    constant_product_price,
    oracle_cross_transition,
)

getcontext().prec = 60

E18 = 10**18


def _state(
    p_oracle: int = 2850 * E18,
    base_price: int = 3000 * E18,
    a: int = 10,
    oracle_age_s: int = 0,
    state_generation: str = "gen-1",
    revision: str = "curvefi/curve-stablecoin@master AMM.vy (research re-derivation)",
) -> LlammaMarketState:
    return LlammaMarketState(
        market_id="crvusd-eth",
        collateral_token="0xCOLL",
        borrowed_token="0xCRVUSD",
        amm_revision_pin=revision,
        a_parameter=a,
        base_price=base_price,
        p_oracle=p_oracle,
        oracle_age_s=oracle_age_s,
        state_generation=state_generation,
    )


def test_band_edges_exact_geometric() -> None:
    state = _state()
    assert band_upper_edge(state, 0) == 3000 * E18
    assert band_upper_edge(state, 1) == 2700 * E18
    assert band_upper_edge(state, 2) == 2430 * E18
    assert band_lower_edge(state, 0) == 2700 * E18
    assert band_lower_edge(state, 1) == 2430 * E18
    # lower(n) equals upper(n+1): adjacent bands share edges exactly.
    for band in range(5):
        assert band_lower_edge(state, band) == band_upper_edge(state, band + 1)


def test_band_edges_strictly_decreasing() -> None:
    state = _state()
    previous = band_upper_edge(state, 0)
    for band in range(1, 20):
        current = band_upper_edge(state, band)
        assert current < previous
        previous = current


def test_active_band_determination() -> None:
    assert active_band(_state(p_oracle=2850 * E18)) == 0
    assert active_band(_state(p_oracle=2600 * E18)) == 1
    assert active_band(_state(p_oracle=2431 * E18)) == 1
    assert active_band(_state(p_oracle=2429 * E18)) == 2
    assert active_band(_state(p_oracle=3100 * E18)) == -1


def test_y0_matches_independent_decimal_implementation() -> None:
    state = _state()
    inventory = BandInventory(band=0, x=2 * E18, y=3 * E18)
    y0 = band_y0(state, inventory, 0)

    # Independent high-precision re-derivation of the pinned quadratic.
    # Band 0's upper edge is p_base = 3000 (WAD-scaled).
    a = Decimal(10)
    aminus1 = Decimal(9)
    p_o = Decimal(2850 * E18)
    p_up = Decimal(3000 * E18)
    x = Decimal(2 * E18)
    y = Decimal(3 * E18)
    wad = Decimal(WAD)
    b = p_up * aminus1 * x / p_o + a * (p_o * p_o / p_up) * y / wad
    d = b * b + (4 * a * p_o * y / wad) * x
    expected = (b + d.sqrt()) * wad / (2 * a * p_o)
    relative_error = abs(Decimal(y0) - expected) / expected
    assert relative_error < Decimal("1e-9")


def test_invariant_close_to_p_constant() -> None:
    state = _state()
    inventory = BandInventory(band=0, x=2 * E18, y=3 * E18)
    f, g, inv = band_f_g_invariant(state, inventory, 0)
    product = (f + inventory.x) * (g + inventory.y)
    # Both forms truncate independently; require 1 ppm agreement.
    assert abs(product - inv) * 10**6 <= inv


def test_band_price_monotonicity() -> None:
    state = _state(p_oracle=2850 * E18)
    base = BandInventory(band=0, x=2 * E18, y=3 * E18)
    price_base = band_price(state, base, 0)
    price_more_x = band_price(state, BandInventory(band=0, x=3 * E18, y=3 * E18), 0)
    price_more_y = band_price(state, BandInventory(band=0, x=2 * E18, y=4 * E18), 0)
    assert price_more_x > price_base
    assert price_more_y < price_base


def test_band_price_pinned_edge_cases() -> None:
    state = _state(p_oracle=2850 * E18)
    # x == 0 (pinned form): p_o^2 // p_up * p_o // p_up with p_up = upper(0) = p_base.
    expected_x0 = (
        (2850 * E18) * (2850 * E18) // (3000 * E18) * (2850 * E18) // (3000 * E18)
    )
    assert band_price(state, BandInventory(band=0, x=0, y=5 * E18), 0) == expected_x0
    # y == 0 (pinned form with p_up' = p_up*(A-1)/A): p_o^2 // p_up' * p_o // p_up'.
    edge = (3000 * E18) * 9 // 10
    expected_y0 = (2850 * E18) * (2850 * E18) // edge * (2850 * E18) // edge
    assert band_price(state, BandInventory(band=0, x=5 * E18, y=0), 0) == expected_y0


def test_oracle_cross_transition_exact_hand_vector() -> None:
    # Oracle falls from 2900 (band 0 active) to 2500 (band 1 active):
    # band 0 is crossed and its 2 collateral tokens convert at the crossed
    # boundary 2700 -> 5400 stable (fee 0); LLAMMA spread = 200/token.
    state = _state(p_oracle=2500 * E18)
    inventories = (BandInventory(band=0, x=2 * E18, y=0),)
    steps, updated = oracle_cross_transition(
        state, inventories, previous_p_oracle=2900 * E18, fee=0
    )
    assert active_band(state) == 1
    assert len(steps) == 1
    step = steps[0]
    assert step.band == 0
    assert step.boundary_price == 2700 * E18
    assert step.direction == "COLLATERAL_TO_STABLE"
    assert step.collateral_converted == 2 * E18
    assert step.stable_received == 5400 * E18
    assert step.markout_loss == 400 * E18
    assert updated[0].x == 0
    assert updated[0].y == 5400 * E18


def test_oracle_cross_transition_fee_reduces_received() -> None:
    state = _state(p_oracle=2500 * E18)
    inventories = (BandInventory(band=0, x=2 * E18, y=0),)
    steps, updated = oracle_cross_transition(
        state, inventories, previous_p_oracle=2900 * E18, fee=WAD // 100
    )
    assert steps[0].stable_received == 5400 * E18 - 54 * E18
    assert updated[0].y == 5346 * E18


def test_oracle_cross_transition_typed_failures() -> None:
    state = _state(p_oracle=2800 * E18)
    inventories = (BandInventory(band=0, x=1 * E18, y=0),)
    with pytest.raises(LlammaModelError):
        oracle_cross_transition(state, inventories, previous_p_oracle=2700 * E18, fee=0)
    with pytest.raises(LlammaModelError):
        oracle_cross_transition(
            state, inventories, previous_p_oracle=2900 * E18, fee=WAD
        )


def test_typed_rejections_fail_closed() -> None:
    with pytest.raises(LlammaModelError) as stale:
        _ = band_upper_edge(_state(oracle_age_s=31), 0)
    assert stale.value.args[0] == LlammaRejectionReason.ORACLE_STALE.value
    with pytest.raises(LlammaModelError) as missing:
        _ = band_upper_edge(_state(state_generation="  "), 0)
    assert missing.value.args[0] == LlammaRejectionReason.STATE_GENERATION_MISSING.value
    with pytest.raises(LlammaModelError) as unpinned:
        _ = band_upper_edge(_state(revision=""), 0)
    assert unpinned.value.args[0] == LlammaRejectionReason.MARKET_NOT_PINNED.value
    with pytest.raises(LlammaModelError) as invalid_band:
        _ = band_upper_edge(_state(), -1)
    assert invalid_band.value.args[0] == LlammaRejectionReason.INVALID_BAND.value


def test_non_constant_product_guard() -> None:
    state = _state(p_oracle=2850 * E18)
    inventory = BandInventory(band=0, x=2 * E18, y=3 * E18)
    llamma_price = band_price(state, inventory, 0)
    cpmm_price = constant_product_price(inventory)
    # The LLAMMA band price is not the constant-product price of the same
    # reserve pair (no CPMM approximation is embedded).
    assert llamma_price != cpmm_price


def test_determinism() -> None:
    state = _state()
    inventory = BandInventory(band=0, x=2 * E18, y=3 * E18)
    first = (
        band_y0(state, inventory, 0),
        band_f_g_invariant(state, inventory, 0),
        band_price(state, inventory, 0),
    )
    second = (
        band_y0(state, inventory, 0),
        band_f_g_invariant(state, inventory, 0),
        band_price(state, inventory, 0),
    )
    assert first == second
    assert math.isqrt(16) == 4  # isqrt determinism sanity

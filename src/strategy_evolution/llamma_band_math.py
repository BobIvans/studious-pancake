"""SX-03 — Curve LLAMMA banded-collateral math (independent research model).

Research/shadow only; execution class ``CONDITIONAL_HYPEREDGE``.  This module
re-derives the documented LLAMMA relations (geometric band edges, the
``(f+x)(g+y)=Inv`` band invariant with the pinned ``y0`` quadratic, mid-band
price and its edge cases, oracle-crossing soft-liquidation transitions) as an
independent implementation.  **No third-party code is reused**: the official
``curvefi/curve-stablecoin`` repository is proprietary ("(c) Swiss Stake AG,
all rights reserved" — see
``docs/strategy-expansion/2026-11-14/dossiers/SX03_CURVE_LLAMMA_DOSSIER.md``);
only the mathematical relations were used, re-expressed from scratch here.

Research-model simplifications (documented in the dossier): exact rational
band edges instead of the on-chain WAD-exp approximation; swap fee applied on
the input leg; single-user per-band inventory; oracle transitions convert the
full crossed-band inventory at the crossed boundary price.

Unknown is never zero: missing state generation, a stale oracle or an
unpinned market fail closed with typed reasons.  Oracle values are state
inputs for band determination, never executable quotes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

WAD = 10**18
MAX_ORACLE_AGE_S_DEFAULT = 30

__all__ = [
    "WAD",
    "LlammaRejectionReason",
    "LlammaModelError",
    "LlammaMarketState",
    "BandInventory",
    "BandTransitionStep",
    "band_upper_edge",
    "band_lower_edge",
    "active_band",
    "band_y0",
    "band_f_g_invariant",
    "band_price",
    "oracle_cross_transition",
    "constant_product_price",
]


class LlammaRejectionReason(str, Enum):
    ORACLE_STALE = "oracle_stale"
    STATE_GENERATION_MISSING = "state_generation_missing"
    MARKET_NOT_PINNED = "market_not_pinned"
    INVALID_BAND = "invalid_band"
    INVALID_FEE = "invalid_fee"


class LlammaModelError(ValueError):
    """Fail-closed rejection carrying a typed reason."""


def _validate_context(state: "LlammaMarketState") -> None:
    if not state.state_generation.strip():
        raise LlammaModelError(LlammaRejectionReason.STATE_GENERATION_MISSING.value)
    if not state.amm_revision_pin.strip():
        raise LlammaModelError(LlammaRejectionReason.MARKET_NOT_PINNED.value)
    if state.oracle_age_s > state.max_oracle_age_s:
        raise LlammaModelError(LlammaRejectionReason.ORACLE_STALE.value)
    if state.a_parameter <= 1:
        raise LlammaModelError("A must be greater than 1")
    if state.base_price <= 0 or state.p_oracle <= 0:
        raise LlammaModelError("prices must be positive WAD integers")


@dataclass(frozen=True, slots=True)
class LlammaMarketState:
    """Per-market pinned state (research inputs; none are live evidence)."""

    market_id: str
    collateral_token: str
    borrowed_token: str
    amm_revision_pin: str
    a_parameter: int
    base_price: int
    p_oracle: int
    oracle_age_s: int
    state_generation: str
    max_oracle_age_s: int = MAX_ORACLE_AGE_S_DEFAULT


@dataclass(frozen=True, slots=True)
class BandInventory:
    """Single-user band inventory (raw 18-decimal token units)."""

    band: int
    x: int  # collateral
    y: int  # stable

    def __post_init__(self) -> None:
        if self.x < 0 or self.y < 0:
            raise LlammaModelError("inventory amounts cannot be negative")


@dataclass(frozen=True, slots=True)
class BandTransitionStep:
    band: int
    boundary_price: int
    direction: str
    collateral_converted: int
    stable_received: int
    markout_loss: int


def _a_minus_1(state: LlammaMarketState) -> int:
    return state.a_parameter - 1


def band_upper_edge(state: LlammaMarketState, band: int) -> int:
    """``p_up(n) = p_base * ((A-1)/A)**n`` — exact iterative integer form.

    On-chain uses a WAD-exp approximation of this relation; the research model
    uses the exact rational geometric sequence with the contract's floor
    division direction (multiply by (A-1), divide by A per step).
    """

    _validate_context(state)
    if band < 0:
        raise LlammaModelError(LlammaRejectionReason.INVALID_BAND.value)
    edge = state.base_price
    ratio_num = _a_minus_1(state)
    ratio_den = state.a_parameter
    for _ in range(band):
        edge = edge * ratio_num // ratio_den
    return edge


def band_lower_edge(state: LlammaMarketState, band: int) -> int:
    """``p_down(n) = p_up(n) * (A-1)/A`` (equals ``p_up(n+1)``)."""

    upper = band_upper_edge(state, band)
    return upper * _a_minus_1(state) // state.a_parameter


def active_band(state: LlammaMarketState) -> int:
    """Band active for the pinned oracle price (``-1`` = above all bands).

    Band ``n`` is active when ``p_down(n) <= p_oracle < p_up(n)``.
    """

    _validate_context(state)
    if state.p_oracle >= band_upper_edge(state, 0):
        return -1
    band = 0
    while state.p_oracle < band_lower_edge(state, band):
        band += 1
        if band > 10000:  # bounded; A-structure guarantees fast termination
            raise LlammaModelError("active band search exceeded bound")
    return band


def band_y0(state: LlammaMarketState, inventory: BandInventory, band: int) -> int:
    """Pinned ``y0`` quadratic for the band (independent implementation)."""

    _validate_context(state)
    p_o = state.p_oracle
    p_o_up = band_upper_edge(state, band)
    a = state.a_parameter
    aminus1 = _a_minus_1(state)
    x = inventory.x
    y = inventory.y
    b = p_o_up * aminus1 * x // p_o
    b += a * p_o * p_o // p_o_up * y // WAD
    d = b * b + (4 * a * p_o * y // WAD) * x
    return (b + math.isqrt(d)) * WAD // (2 * a * p_o)


def band_f_g_invariant(
    state: LlammaMarketState, inventory: BandInventory, band: int
) -> tuple[int, int, int]:
    """``(f, g, Inv)`` with ``Inv = (f+x)*(g+y)`` and ``Inv = p_o*A^2*y0^2``."""

    _validate_context(state)
    p_o = state.p_oracle
    p_o_up = band_upper_edge(state, band)
    a = state.a_parameter
    y0 = band_y0(state, inventory, band)
    f = a * y0 * p_o // p_o_up * p_o // WAD
    g = _a_minus_1(state) * y0 * p_o_up // p_o
    inv = p_o * a * a * y0 * y0 // WAD
    return f, g, inv


def band_price(state: LlammaMarketState, inventory: BandInventory, band: int) -> int:
    """Mid-band price model ``p = (f + x) * WAD // (g + y)`` with pinned edge cases.

    Unit model (documented research simplification): ``x``/``y`` are raw
    18-decimal token amounts and ``f``/``g`` are expressed in the same
    band-converted unit system derived from the pinned quadratic.  The exact
    on-chain scaling of the mid-band form (the contract multiplies ``x`` by
    WAD inside ``get_p``) must be reconciled against rooted per-market state
    before any qualification-tier use — recorded as a typed pending item in
    the dossier.  Monotonicity in ``x``/``y`` and the pinned ``x=0``/``y=0``
    edge forms are unit-independent and tested exactly.
    """

    _validate_context(state)
    x = inventory.x
    y = inventory.y
    p_o = state.p_oracle
    p_o_up = band_upper_edge(state, band)
    aminus1 = _a_minus_1(state)
    if x == 0 and y == 0:
        reference_up = p_o_up
        return p_o * p_o // reference_up * p_o // reference_up
    if x == 0:
        return p_o * p_o // p_o_up * p_o // p_o_up
    if y == 0:
        edge = p_o_up * aminus1 // state.a_parameter
        return p_o * p_o // edge * p_o // edge
    f, g, _ = band_f_g_invariant(state, inventory, band)
    return (f + x) * WAD // (g + y)


def oracle_cross_transition(
    state: LlammaMarketState,
    inventories: tuple[BandInventory, ...],
    previous_p_oracle: int,
    fee: int,
) -> tuple[tuple[BandTransitionStep, ...], tuple[BandInventory, ...]]:
    """Soft-liquidation transitions when the oracle falls across band edges.

    Every band whose inventory still holds collateral and whose lower edge is
    strictly above the new oracle is crossed: its collateral converts to
    stable at the crossed boundary price (LLAMMA converts collateral to
    stable so bands below the oracle hold stable).  Deterministic; conserves
    collateral/stable per band; records the LLAMMA spread as markout loss
    versus the new oracle.
    """

    _validate_context(state)
    if not 0 <= fee < WAD:
        raise LlammaModelError(LlammaRejectionReason.INVALID_FEE.value)
    if previous_p_oracle < state.p_oracle:
        raise LlammaModelError("transitions require a falling oracle price")
    new_active = active_band(state)
    steps: list[BandTransitionStep] = []
    updated: list[BandInventory] = []
    for inventory in inventories:
        band = inventory.band
        lower = band_lower_edge(state, band)
        if inventory.x == 0 or lower <= state.p_oracle:
            # Bands at or below the new oracle already hold stable.
            updated.append(inventory)
            continue
        collateral = inventory.x
        gross = collateral * lower // WAD
        stable_received = gross * (WAD - fee) // WAD
        markout_loss = collateral * (lower - state.p_oracle) // WAD
        steps.append(
            BandTransitionStep(
                band=band,
                boundary_price=lower,
                direction="COLLATERAL_TO_STABLE",
                collateral_converted=collateral,
                stable_received=stable_received,
                markout_loss=markout_loss,
            )
        )
        updated.append(BandInventory(band=band, x=0, y=inventory.y + stable_received))
    return tuple(steps), tuple(updated)


def constant_product_price(inventory: BandInventory) -> int:
    """Constant-product reference price for the non-CPMM guard (WAD)."""

    if inventory.x == 0 or inventory.y == 0:
        raise LlammaModelError("cpmm reference requires positive reserves")
    return inventory.y * WAD // inventory.x

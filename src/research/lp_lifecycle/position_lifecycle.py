"""LP position lifecycle state machine and fee/IL harvesting economics (SX-09).

Research-only, offline, deterministic, venue-agnostic, integer math.  This
module models persistent LP inventory as pure state transitions with exact
per-asset token conservation:

- ``mint_position`` / ``add_liquidity`` / ``remove_liquidity`` / ``accrue_fees``
  / ``collect_fees`` / ``compound_fees`` / ``shift_range`` each return a new
  :class:`LPPositionState` plus a :class:`TransitionReceipt` and assert that
  assets are never invented or destroyed across the transition.  Receipts
  record per-asset deltas, gross inflows/outflows, and costs; a cost that is
  not known exactly stays ``None`` (never invented as zero).
- :class:`ImpermanentLossEvaluator` compares a hold baseline against LP value
  on a pinned price path.  No AMM curve is invented: LP value comes either
  from supplied position valuations or from a v2-style constant-product curve
  only when the caller explicitly flags ``valuation_model="cpmm"``.  Any
  other valuation model raises :class:`ValuationModelUnproven` (typed
  exclusion) instead of guessing.
- :class:`FeeHarvestSummary` checks fees-collected vs fees-accrued
  conservation and reports markout-after-fees at provided horizons.
- :class:`PersistentCapitalLock` enforces the capital classification: LP
  capital is persistent inventory, so attaching any flash financing terms to
  an LP transition raises :class:`PersistentLpNotFlashFinancable`.

Boundary guarantees: no venue wiring, no signing, no submission, no NFT or
position-rights claims (``position_right`` is opaque carried data), no live
evidence.  Fixtures and synthetic paths are research vectors, never market
truth.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from math import isqrt
from types import MappingProxyType
from typing import Any

from src.research.common import hash_json

CAPITAL_CLASS_PERSISTENT = "PERSISTENT_INVENTORY"
DEFAULT_PRICE_SCALE = 10**18
_MINT_TRANSITION = "mint_position"
_RANGE_DESCRIPTOR_HASH_DOMAIN = "lp_lifecycle.range_descriptor"
_ACCRUAL_PROVENANCE_HASH_DOMAIN = "lp_lifecycle.fee_accrual_provenance"


class LpLifecycleError(Exception):
    """Base class for LP lifecycle research-model errors."""


class InvalidLpLifecycleInput(LpLifecycleError):
    """A transition or evaluation received invalid or contradictory input."""


class TokenConservationError(LpLifecycleError):
    """Per-asset token conservation failed across a transition."""


class StateGenerationMismatch(LpLifecycleError):
    """A receipt does not continue the exact state generation it was given."""


class InexactReinvestment(LpLifecycleError):
    """compound_fees was asked to reinvest an amount other than the fees held."""


class PersistentLpNotFlashFinancable(LpLifecycleError):
    """LP capital is persistent inventory; flash principal cannot finance it."""


class ValuationModelUnproven(LpLifecycleError):
    """The requested valuation model is not proven for IL evaluation."""


class FeeConservationError(LpLifecycleError):
    """Fees collected plus unclaimed do not equal fees accrued for an asset."""


class MarkoutHorizonUnavailable(LpLifecycleError):
    """A requested markout horizon is outside the pinned price path."""


def _require_int(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidLpLifecycleInput(f"{field} must be an integer")
    if value < minimum:
        raise InvalidLpLifecycleInput(f"{field} must be >= {minimum}, got {value}")
    return value


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidLpLifecycleInput(f"{field} must be a non-empty string")
    return value


def _require_assets(value: object, field: str = "assets") -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise InvalidLpLifecycleInput(f"{field} must be a tuple of asset ids")
    assets = tuple(
        _require_text(asset, f"{field}[{i}]") for i, asset in enumerate(value)
    )
    if not assets:
        raise InvalidLpLifecycleInput(f"{field} must be non-empty")
    if len(set(assets)) != len(assets):
        raise InvalidLpLifecycleInput(f"{field} must be unique")
    return assets


def _require_amounts(value: object, field: str, length: int) -> tuple[int, ...]:
    if not isinstance(value, tuple):
        raise InvalidLpLifecycleInput(f"{field} must be a tuple of per-asset integers")
    amounts = tuple(
        _require_int(amount, f"{field}[{i}]") for i, amount in enumerate(value)
    )
    if len(amounts) != length:
        raise InvalidLpLifecycleInput(
            f"{field} must have one entry per asset ({length}), got {len(amounts)}"
        )
    return amounts


def _require_costs(value: object, field: str, length: int) -> tuple[int | None, ...]:
    """Validate a per-asset cost tuple; unknown costs stay None (never 0)."""
    if value is None:
        return tuple(None for _ in range(length))
    if not isinstance(value, tuple):
        raise InvalidLpLifecycleInput(f"{field} must be a tuple of int-or-None")
    costs = tuple(value)
    if len(costs) != length:
        raise InvalidLpLifecycleInput(
            f"{field} must have one entry per asset ({length}), got {len(costs)}"
        )
    validated: list[int | None] = []
    for i, cost in enumerate(costs):
        if cost is None:
            validated.append(None)
        else:
            validated.append(_require_int(cost, f"{field}[{i}]"))
    return tuple(validated)


def _validated_provenance(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidLpLifecycleInput(f"{field} must be a mapping")
    if not value:
        raise InvalidLpLifecycleInput(f"{field} must be non-empty")
    return MappingProxyType(dict(value))


def _validated_range_descriptor(value: object) -> Mapping[str, Any]:
    """Keep the range/bins descriptor opaque; only provenance is inspected."""
    descriptor = _validated_provenance(value, "range_descriptor")
    if "provenance" not in descriptor:
        raise InvalidLpLifecycleInput(
            "range_descriptor requires a 'provenance' entry (source, schema, capture)"
        )
    _validated_provenance(descriptor["provenance"], "range_descriptor['provenance']")
    return descriptor


def _provenance_hash(domain: str, provenance: Mapping[str, Any]) -> str:
    return hash_json(domain, dict(provenance))


@dataclass(frozen=True, slots=True)
class FlashFinancingTerms:
    """Opaque flash-financing terms; never attachable to an LP transition."""

    provider: str
    principal_asset: str
    principal_amount: int
    fee_amount: int
    atomic_repayment: bool = True

    def __post_init__(self) -> None:
        _require_text(self.provider, "provider")
        _require_text(self.principal_asset, "principal_asset")
        _require_int(self.principal_amount, "principal_amount", minimum=1)
        _require_int(self.fee_amount, "fee_amount")


def reject_flash_financing(
    transition: str, financing: FlashFinancingTerms | None
) -> None:
    """Persistent-capital guard: refuse any flash terms on an LP transition."""
    if financing is None:
        return
    raise PersistentLpNotFlashFinancable(
        f"{transition} cannot be flash-financed: LP capital is persistent "
        f"inventory (provider={financing.provider!r}, "
        f"principal_asset={financing.principal_asset!r}, "
        f"principal_amount={financing.principal_amount}); persistent capital "
        "lock refuses all flash financing terms"
    )


@dataclass(frozen=True, slots=True)
class PersistentCapitalLock:
    """Guard asserting LP capital is persistent, never flash-financed."""

    position_id: str
    venue: str
    capital_class: str = CAPITAL_CLASS_PERSISTENT

    @staticmethod
    def for_position(state: LPPositionState) -> PersistentCapitalLock:
        return PersistentCapitalLock(position_id=state.position_id, venue=state.venue)

    def ensure_transition_financable(
        self, transition: str, financing: FlashFinancingTerms | None
    ) -> None:
        reject_flash_financing(transition, financing)


@dataclass(frozen=True, slots=True)
class LPPositionState:
    """Venue-agnostic LP position state (integer amounts, opaque descriptor).

    ``range_descriptor`` is opaque provenance-carrying data (CLMM tick range,
    DLMM bin set, ...) and is never interpreted here.  ``position_right`` is
    the venue's NFT/mint reference if the venue models one; no ownership
    claim is made by this research model.
    """

    position_id: str
    venue: str
    pool_key: str
    assets: tuple[str, ...]
    range_descriptor: Mapping[str, Any]
    liquidity: int
    amounts: tuple[int, ...]
    unclaimed_fees: tuple[int, ...]
    position_right: str | None
    state_generation: int

    def __post_init__(self) -> None:
        _require_text(self.position_id, "position_id")
        _require_text(self.venue, "venue")
        _require_text(self.pool_key, "pool_key")
        object.__setattr__(self, "assets", _require_assets(self.assets))
        object.__setattr__(
            self, "range_descriptor", _validated_range_descriptor(self.range_descriptor)
        )
        _require_int(self.liquidity, "liquidity")
        object.__setattr__(
            self, "amounts", _require_amounts(self.amounts, "amounts", len(self.assets))
        )
        object.__setattr__(
            self,
            "unclaimed_fees",
            _require_amounts(self.unclaimed_fees, "unclaimed_fees", len(self.assets)),
        )
        if self.position_right is not None:
            _require_text(self.position_right, "position_right")
        _require_int(self.state_generation, "state_generation")

    def domain_balances(self) -> tuple[int, ...]:
        """Per-asset tokens inside the tracked domain (principal + fees)."""
        return tuple(
            amount + fee for amount, fee in zip(self.amounts, self.unclaimed_fees)
        )

    def range_descriptor_hash(self) -> str:
        return _provenance_hash(
            _RANGE_DESCRIPTOR_HASH_DOMAIN, MappingProxyType(dict(self.range_descriptor))
        )


@dataclass(frozen=True, slots=True)
class TransitionReceipt:
    """Immutable evidence receipt for one lifecycle transition.

    Conservation identity per asset:
    ``delta_domain == inflow - outflow`` where ``delta_domain`` is the change
    in (amounts + unclaimed fees).  ``costs`` are per-asset economics recorded
    for the receipt (gas, close fees, ...); they are paid outside the tracked
    position domain, never silently folded into flows, and an unknown cost
    stays ``None``.
    """

    transition: str
    position_id: str
    venue: str
    assets: tuple[str, ...]
    from_generation: int
    to_generation: int
    before_amounts: tuple[int, ...]
    after_amounts: tuple[int, ...]
    before_unclaimed_fees: tuple[int, ...]
    after_unclaimed_fees: tuple[int, ...]
    inflows: tuple[int, ...]
    outflows: tuple[int, ...]
    costs: tuple[int | None, ...]
    range_descriptor_hash_before: str | None
    range_descriptor_hash_after: str
    capital_class: str
    flash_financed: bool
    detail: Mapping[str, Any]

    @property
    def amount_deltas(self) -> tuple[int, ...]:
        return tuple(
            after - before
            for after, before in zip(self.after_amounts, self.before_amounts)
        )

    @property
    def unclaimed_fees_deltas(self) -> tuple[int, ...]:
        return tuple(
            after - before
            for after, before in zip(
                self.after_unclaimed_fees, self.before_unclaimed_fees
            )
        )

    @property
    def domain_deltas(self) -> tuple[int, ...]:
        return tuple(
            amount + fee
            for amount, fee in zip(self.amount_deltas, self.unclaimed_fees_deltas)
        )

    def conservation_holds(self) -> bool:
        return all(
            domain_delta == inflow - outflow
            for domain_delta, inflow, outflow in zip(
                self.domain_deltas, self.inflows, self.outflows
            )
        )


def _assert_token_conservation(
    transition: str,
    assets: tuple[str, ...],
    before_amounts: tuple[int, ...],
    before_unclaimed: tuple[int, ...],
    after_amounts: tuple[int, ...],
    after_unclaimed: tuple[int, ...],
    inflows: tuple[int, ...],
    outflows: tuple[int, ...],
) -> None:
    for i, asset in enumerate(assets):
        before_domain = before_amounts[i] + before_unclaimed[i]
        after_domain = after_amounts[i] + after_unclaimed[i]
        net_external = inflows[i] - outflows[i]
        if after_domain - before_domain != net_external:
            raise TokenConservationError(
                f"{transition} violates token conservation for asset {asset!r}: "
                f"domain delta {after_domain - before_domain} != "
                f"inflow {inflows[i]} - outflow {outflows[i]} = {net_external}"
            )


def _build_receipt(
    transition: str,
    before: LPPositionState | None,
    after: LPPositionState,
    *,
    inflows: tuple[int, ...],
    outflows: tuple[int, ...],
    costs: tuple[int | None, ...],
    detail: Mapping[str, Any],
) -> TransitionReceipt:
    if before is None:
        before_amounts = tuple(0 for _ in after.assets)
        before_unclaimed = tuple(0 for _ in after.assets)
        from_generation = 0
        descriptor_hash_before = None
    else:
        before_amounts = before.amounts
        before_unclaimed = before.unclaimed_fees
        from_generation = before.state_generation
        descriptor_hash_before = before.range_descriptor_hash()
        if before.position_id != after.position_id or before.venue != after.venue:
            raise InvalidLpLifecycleInput(
                f"{transition} cannot change position identity or venue"
            )
        if before.assets != after.assets:
            raise InvalidLpLifecycleInput(
                f"{transition} cannot change the per-asset tuple identity"
            )
    _assert_token_conservation(
        transition,
        after.assets,
        before_amounts,
        before_unclaimed,
        after.amounts,
        after.unclaimed_fees,
        inflows,
        outflows,
    )
    return TransitionReceipt(
        transition=transition,
        position_id=after.position_id,
        venue=after.venue,
        assets=after.assets,
        from_generation=from_generation,
        to_generation=after.state_generation,
        before_amounts=before_amounts,
        after_amounts=after.amounts,
        before_unclaimed_fees=before_unclaimed,
        after_unclaimed_fees=after.unclaimed_fees,
        inflows=inflows,
        outflows=outflows,
        costs=costs,
        range_descriptor_hash_before=descriptor_hash_before,
        range_descriptor_hash_after=after.range_descriptor_hash(),
        capital_class=CAPITAL_CLASS_PERSISTENT,
        flash_financed=False,
        detail=MappingProxyType(dict(detail)),
    )


def mint_position(
    *,
    position_id: str,
    venue: str,
    pool_key: str,
    assets: tuple[str, ...],
    range_descriptor: Mapping[str, Any],
    liquidity: int,
    amounts: tuple[int, ...],
    unclaimed_fees: tuple[int, ...] | None = None,
    position_right: str | None = None,
    financing: FlashFinancingTerms | None = None,
) -> tuple[LPPositionState, TransitionReceipt]:
    """Open a position from an external persistent deposit (generation 0 -> 1)."""
    reject_flash_financing("mint_position", financing)
    validated_assets = _require_assets(assets)
    _require_text(position_id, "position_id")
    _require_text(venue, "venue")
    _require_text(pool_key, "pool_key")
    _require_int(liquidity, "liquidity", minimum=1)
    validated_amounts = _require_amounts(amounts, "amounts", len(validated_assets))
    if not any(validated_amounts):
        raise InvalidLpLifecycleInput("mint_position requires a non-zero deposit")
    validated_fees = (
        tuple(0 for _ in validated_assets)
        if unclaimed_fees is None
        else _require_amounts(unclaimed_fees, "unclaimed_fees", len(validated_assets))
    )
    if position_right is not None:
        _require_text(position_right, "position_right")
    state = LPPositionState(
        position_id=position_id,
        venue=venue,
        pool_key=pool_key,
        assets=validated_assets,
        range_descriptor=range_descriptor,
        liquidity=liquidity,
        amounts=validated_amounts,
        unclaimed_fees=validated_fees,
        position_right=position_right,
        state_generation=1,
    )
    receipt = _build_receipt(
        _MINT_TRANSITION,
        None,
        state,
        inflows=state.domain_balances(),
        outflows=tuple(0 for _ in state.assets),
        costs=tuple(None for _ in state.assets),
        detail={
            "pool_key": pool_key,
            "position_right": position_right,
            "note": "initial persistent deposit into the tracked domain",
        },
    )
    return state, receipt


def add_liquidity(
    state: LPPositionState,
    *,
    liquidity_delta: int,
    amount_deltas: tuple[int, ...],
    position_right: str | None = None,
    financing: FlashFinancingTerms | None = None,
) -> tuple[LPPositionState, TransitionReceipt]:
    """Add principal from external inventory (inflows == amount_deltas)."""
    reject_flash_financing("add_liquidity", financing)
    _require_int(liquidity_delta, "liquidity_delta", minimum=1)
    deltas = _require_amounts(amount_deltas, "amount_deltas", len(state.assets))
    if not any(deltas):
        raise InvalidLpLifecycleInput("add_liquidity requires a non-zero deposit")
    new_state = replace(
        state,
        liquidity=state.liquidity + liquidity_delta,
        amounts=tuple(amount + delta for amount, delta in zip(state.amounts, deltas)),
        position_right=(
            state.position_right if position_right is None else position_right
        ),
        state_generation=state.state_generation + 1,
    )
    receipt = _build_receipt(
        "add_liquidity",
        state,
        new_state,
        inflows=deltas,
        outflows=tuple(0 for _ in state.assets),
        costs=tuple(None for _ in state.assets),
        detail={"liquidity_delta": liquidity_delta},
    )
    return new_state, receipt


def remove_liquidity(
    state: LPPositionState,
    *,
    liquidity_delta: int,
    amount_deltas: tuple[int, ...],
    financing: FlashFinancingTerms | None = None,
) -> tuple[LPPositionState, TransitionReceipt]:
    """Withdraw principal to external inventory (outflows == amount_deltas)."""
    reject_flash_financing("remove_liquidity", financing)
    _require_int(liquidity_delta, "liquidity_delta", minimum=1)
    if liquidity_delta > state.liquidity:
        raise InvalidLpLifecycleInput(
            f"liquidity_delta {liquidity_delta} exceeds position liquidity {state.liquidity}"
        )
    deltas = _require_amounts(amount_deltas, "amount_deltas", len(state.assets))
    if not any(deltas):
        raise InvalidLpLifecycleInput("remove_liquidity requires a non-zero withdrawal")
    for i, asset in enumerate(state.assets):
        if deltas[i] > state.amounts[i]:
            raise InvalidLpLifecycleInput(
                f"removal of {deltas[i]} exceeds {asset!r} principal {state.amounts[i]}"
            )
    new_state = replace(
        state,
        liquidity=state.liquidity - liquidity_delta,
        amounts=tuple(amount - delta for amount, delta in zip(state.amounts, deltas)),
        state_generation=state.state_generation + 1,
    )
    receipt = _build_receipt(
        "remove_liquidity",
        state,
        new_state,
        inflows=tuple(0 for _ in state.assets),
        outflows=deltas,
        costs=tuple(None for _ in state.assets),
        detail={"liquidity_delta": liquidity_delta},
    )
    return new_state, receipt


def accrue_fees(
    state: LPPositionState,
    *,
    fee_deltas: tuple[int, ...],
    accrual_provenance: Mapping[str, Any],
    financing: FlashFinancingTerms | None = None,
) -> tuple[LPPositionState, TransitionReceipt]:
    """Record venue-reported fee accrual into unclaimed fees (exact update).

    This is a research replay of venue accounting (fees owed to the position
    per its fee-growth state); it is never invented here and must carry
    provenance.  It moves tokens into the tracked domain, so inflows equal
    the accrual deltas.
    """
    reject_flash_financing("accrue_fees", financing)
    deltas = _require_amounts(fee_deltas, "fee_deltas", len(state.assets))
    if not any(deltas):
        raise InvalidLpLifecycleInput("accrue_fees requires a non-zero accrual")
    provenance = _validated_provenance(accrual_provenance, "accrual_provenance")
    new_state = replace(
        state,
        unclaimed_fees=tuple(
            fee + delta for fee, delta in zip(state.unclaimed_fees, deltas)
        ),
        state_generation=state.state_generation + 1,
    )
    receipt = _build_receipt(
        "accrue_fees",
        state,
        new_state,
        inflows=deltas,
        outflows=tuple(0 for _ in state.assets),
        costs=tuple(None for _ in state.assets),
        detail={
            "accrual_provenance_hash": _provenance_hash(
                _ACCRUAL_PROVENANCE_HASH_DOMAIN, provenance
            ),
            "note": "venue-reported accrual; research replay, not live evidence",
        },
    )
    return new_state, receipt


def collect_fees(
    state: LPPositionState,
    *,
    claimed_amounts: tuple[int, ...],
    financing: FlashFinancingTerms | None = None,
) -> tuple[LPPositionState, TransitionReceipt]:
    """Claim unclaimed fees out of the domain (outflows == claimed_amounts)."""
    reject_flash_financing("collect_fees", financing)
    claimed = _require_amounts(claimed_amounts, "claimed_amounts", len(state.assets))
    if not any(claimed):
        raise InvalidLpLifecycleInput("collect_fees requires a non-zero claim")
    for i, asset in enumerate(state.assets):
        if claimed[i] > state.unclaimed_fees[i]:
            raise InvalidLpLifecycleInput(
                f"claim of {claimed[i]} exceeds {asset!r} unclaimed fees "
                f"{state.unclaimed_fees[i]}"
            )
    new_state = replace(
        state,
        unclaimed_fees=tuple(
            fee - claim for fee, claim in zip(state.unclaimed_fees, claimed)
        ),
        state_generation=state.state_generation + 1,
    )
    receipt = _build_receipt(
        "collect_fees",
        state,
        new_state,
        inflows=tuple(0 for _ in state.assets),
        outflows=claimed,
        costs=tuple(None for _ in state.assets),
        detail={"fees_claimed": claimed},
    )
    return new_state, receipt


def compound_fees(
    state: LPPositionState,
    *,
    liquidity_delta: int,
    reinvest_amounts: tuple[int, ...] | None = None,
    financing: FlashFinancingTerms | None = None,
) -> tuple[LPPositionState, TransitionReceipt]:
    """Collect fees and re-add them exactly (fees never leave the domain).

    The reinvested amounts must equal the unclaimed fees exactly; anything
    else raises :class:`InexactReinvestment` rather than inventing dust.
    """
    reject_flash_financing("compound_fees", financing)
    _require_int(liquidity_delta, "liquidity_delta", minimum=1)
    if reinvest_amounts is None:
        reinvested = state.unclaimed_fees
    else:
        reinvested = _require_amounts(
            reinvest_amounts, "reinvest_amounts", len(state.assets)
        )
        if reinvested != state.unclaimed_fees:
            raise InexactReinvestment(
                f"compound_fees requires exact reinvestment: requested "
                f"{reinvested} != unclaimed fees {state.unclaimed_fees}"
            )
    if not any(reinvested):
        raise InvalidLpLifecycleInput("compound_fees requires unclaimed fees")
    new_state = replace(
        state,
        liquidity=state.liquidity + liquidity_delta,
        amounts=tuple(
            amount + reinvest for amount, reinvest in zip(state.amounts, reinvested)
        ),
        unclaimed_fees=tuple(0 for _ in state.assets),
        state_generation=state.state_generation + 1,
    )
    receipt = _build_receipt(
        "compound_fees",
        state,
        new_state,
        inflows=tuple(0 for _ in state.assets),
        outflows=tuple(0 for _ in state.assets),
        costs=tuple(None for _ in state.assets),
        detail={
            "fees_collected": state.unclaimed_fees,
            "fees_reinvested": reinvested,
            "reinvestment_dust": tuple(0 for _ in state.assets),
            "liquidity_delta": liquidity_delta,
        },
    )
    return new_state, receipt


def shift_range(
    state: LPPositionState,
    *,
    new_range_descriptor: Mapping[str, Any],
    new_liquidity: int,
    new_amounts: tuple[int, ...],
    costs: tuple[int | None, ...] | None = None,
    financing: FlashFinancingTerms | None = None,
) -> tuple[LPPositionState, TransitionReceipt]:
    """Close the current range and open a new one in one pure transition.

    Gross flows are recorded: the old range is closed (``outflows`` equal the
    released principal) and the new range is opened (``inflows`` equal the
    deployed principal); the net difference is the externally settled part.
    Unclaimed fees are untouched (claim them explicitly with collect_fees).
    ``costs`` records per-asset close/open costs; unknown costs stay ``None``.
    """
    reject_flash_financing("shift_range", financing)
    _require_int(new_liquidity, "new_liquidity", minimum=1)
    deployed = _require_amounts(new_amounts, "new_amounts", len(state.assets))
    descriptor = _validated_range_descriptor(new_range_descriptor)
    validated_costs = _require_costs(costs, "costs", len(state.assets))
    released = state.amounts
    new_state = replace(
        state,
        range_descriptor=descriptor,
        liquidity=new_liquidity,
        amounts=deployed,
        state_generation=state.state_generation + 1,
    )
    receipt = _build_receipt(
        "shift_range",
        state,
        new_state,
        inflows=deployed,
        outflows=released,
        costs=validated_costs,
        detail={
            "closed_amounts": released,
            "opened_amounts": deployed,
            "reused_amounts": tuple(
                min(release, deploy) for release, deploy in zip(released, deployed)
            ),
            "note": "close-then-open; costs recorded, not folded into flows",
        },
    )
    return new_state, receipt


def verify_receipt(state: LPPositionState, receipt: TransitionReceipt) -> bool:
    """Check a receipt continues the exact state generation and conserves.

    Raises :class:`StateGenerationMismatch` when the receipt was built against
    a different generation/state and :class:`TokenConservationError` when its
    recorded flows do not explain its recorded deltas.
    """
    if (
        receipt.position_id != state.position_id
        or receipt.venue != state.venue
        or receipt.assets != state.assets
    ):
        raise StateGenerationMismatch(
            f"receipt for {receipt.position_id!r}@{receipt.venue!r} does not "
            f"describe state {state.position_id!r}@{state.venue!r}"
        )
    if (
        receipt.from_generation != state.state_generation - 1
        or receipt.to_generation != state.state_generation
    ):
        raise StateGenerationMismatch(
            f"receipt generations ({receipt.from_generation} -> "
            f"{receipt.to_generation}) do not produce state generation "
            f"{state.state_generation}"
        )
    if receipt.transition == _MINT_TRANSITION and (
        any(receipt.before_amounts) or any(receipt.before_unclaimed_fees)
    ):
        raise StateGenerationMismatch(
            "mint receipt must start from empty pre-state balances"
        )
    if (
        receipt.after_amounts != state.amounts
        or receipt.after_unclaimed_fees != state.unclaimed_fees
    ):
        raise StateGenerationMismatch(
            "receipt after-balances do not match the given state balances"
        )
    _assert_token_conservation(
        receipt.transition,
        state.assets,
        receipt.before_amounts,
        receipt.before_unclaimed_fees,
        receipt.after_amounts,
        receipt.after_unclaimed_fees,
        receipt.inflows,
        receipt.outflows,
    )
    return True


class ValuationModel(StrEnum):
    CPMM = "cpmm"
    SUPPLIED = "supplied"


@dataclass(frozen=True, slots=True)
class PriceStep:
    """One pinned point of a price path (price of asset 0 in asset 1 units)."""

    t: int
    price_scaled: int


def _validated_price_path(
    price_path: Sequence[tuple[int, int] | PriceStep],
) -> tuple[PriceStep, ...]:
    steps: list[PriceStep] = []
    previous_t: int | None = None
    for i, item in enumerate(price_path):
        if isinstance(item, PriceStep):
            raw_t: object = item.t
            raw_price: object = item.price_scaled
        elif isinstance(item, tuple) and len(item) == 2:
            raw_t = item[0]
            raw_price = item[1]
        else:
            raise InvalidLpLifecycleInput(
                f"price_path[{i}] must be a (t, price_scaled) tuple or PriceStep"
            )
        t = _require_int(raw_t, f"price_path[{i}].t")
        price = _require_int(raw_price, f"price_path[{i}].price_scaled", minimum=1)
        if previous_t is not None and t <= previous_t:
            raise InvalidLpLifecycleInput(
                "price_path timestamps must be strictly increasing (pinned)"
            )
        previous_t = t
        steps.append(PriceStep(t=t, price_scaled=price))
    if not steps:
        raise InvalidLpLifecycleInput("price_path must be non-empty")
    return tuple(steps)


@dataclass(frozen=True, slots=True)
class IlStep:
    """One IL evaluation step in scaled quote units (exact integers)."""

    step_index: int
    t: int
    price_scaled: int
    hold_value_scaled: int
    lp_value_scaled: int
    impermanent_loss_scaled: int


def constant_product_lp_value_scaled(
    x0: int,
    y0: int,
    price_scaled: int,
    price_scale: int = DEFAULT_PRICE_SCALE,
) -> int:
    """LP value of a v2 constant-product pool at a price, exact integer floor.

    With k = x0*y0, price p = price_scaled/price_scale: x = sqrt(k/p),
    y = sqrt(k*p), so the quote-unit value is 2*sqrt(k*p) scaled by
    price_scale: ``2*isqrt(k*price_scaled*price_scale)/price_scale``.  This is
    the only curve used, and only when explicitly flagged CPMM.
    """
    _require_int(x0, "x0", minimum=1)
    _require_int(y0, "y0", minimum=1)
    _require_int(price_scaled, "price_scaled", minimum=1)
    _require_int(price_scale, "price_scale", minimum=1)
    k = x0 * y0
    return 2 * isqrt(k * price_scaled * price_scale)


def _resolve_valuation_model(valuation_model: ValuationModel | str) -> ValuationModel:
    try:
        return ValuationModel(valuation_model)
    except ValueError:
        raise ValuationModelUnproven(
            f"valuation_model={valuation_model!r} is not proven for IL "
            "evaluation; only supplied position valuations ('supplied') or an "
            "explicitly flagged v2 constant-product ('cpmm') are admissible"
        ) from None


def evaluate_impermanent_loss(
    price_path: Sequence[tuple[int, int] | PriceStep],
    initial_amounts: tuple[int, int],
    *,
    valuation_model: ValuationModel | str,
    price_scale: int = DEFAULT_PRICE_SCALE,
    lp_values_scaled: tuple[int, ...] | None = None,
) -> tuple[IlStep, ...]:
    """Hold baseline vs LP value per step; IL = LP - hold (exact integers).

    The hold baseline is exact for any model: the initial amounts are simply
    held and marked at each pinned price.  LP values come from the chosen
    model only; any other model raises :class:`ValuationModelUnproven`.
    """
    steps = _validated_price_path(price_path)
    _require_int(price_scale, "price_scale", minimum=1)
    amounts = _require_amounts(initial_amounts, "initial_amounts", 2)
    x0, y0 = amounts
    model = _resolve_valuation_model(valuation_model)
    if model is ValuationModel.CPMM:
        if lp_values_scaled is not None:
            raise InvalidLpLifecycleInput(
                "lp_values_scaled must not be supplied when valuation_model='cpmm'"
            )
        if x0 <= 0 or y0 <= 0:
            raise InvalidLpLifecycleInput(
                "cpmm IL evaluation requires positive initial amounts"
            )
        lp_values = tuple(
            constant_product_lp_value_scaled(x0, y0, step.price_scaled, price_scale)
            for step in steps
        )
    else:
        if lp_values_scaled is None:
            raise InvalidLpLifecycleInput(
                "valuation_model='supplied' requires lp_values_scaled"
            )
        lp_values = _require_amounts(lp_values_scaled, "lp_values_scaled", len(steps))
    evaluated: list[IlStep] = []
    for index, step in enumerate(steps):
        hold_value_scaled = x0 * step.price_scaled + y0 * price_scale
        lp_value_scaled = lp_values[index]
        evaluated.append(
            IlStep(
                step_index=index,
                t=step.t,
                price_scaled=step.price_scaled,
                hold_value_scaled=hold_value_scaled,
                lp_value_scaled=lp_value_scaled,
                impermanent_loss_scaled=lp_value_scaled - hold_value_scaled,
            )
        )
    return tuple(evaluated)


class ImpermanentLossEvaluator:
    """Typed facade over IL evaluation with explicit valuation gating.

    Constructs the exact per-step IL vector once (pure, deterministic); an
    unproven valuation model is rejected at construction time.
    """

    def __init__(
        self,
        price_path: Sequence[tuple[int, int] | PriceStep],
        initial_amounts: tuple[int, int],
        *,
        valuation_model: ValuationModel | str,
        price_scale: int = DEFAULT_PRICE_SCALE,
        lp_values_scaled: tuple[int, ...] | None = None,
    ) -> None:
        self._model = _resolve_valuation_model(valuation_model)
        self._steps = evaluate_impermanent_loss(
            price_path,
            initial_amounts,
            valuation_model=self._model,
            price_scale=price_scale,
            lp_values_scaled=lp_values_scaled,
        )

    @property
    def valuation_model(self) -> ValuationModel:
        return self._model

    @property
    def steps(self) -> tuple[IlStep, ...]:
        return self._steps

    def impermanent_loss_scaled(self) -> tuple[int, ...]:
        return tuple(step.impermanent_loss_scaled for step in self._steps)

    def step(self, index: int) -> IlStep:
        _require_int(index, "index")
        if index >= len(self._steps):
            raise InvalidLpLifecycleInput(
                f"step index {index} outside evaluated path ({len(self._steps)} steps)"
            )
        return self._steps[index]


@dataclass(frozen=True, slots=True)
class FeeMarkout:
    """Markout of collected fees over one horizon, in scaled quote units."""

    horizon_steps: int
    collection_step_index: int
    from_t: int
    to_t: int
    base_price_scaled: int
    horizon_price_scaled: int
    markout_scaled: int


@dataclass(frozen=True, slots=True)
class FeeHarvestSummary:
    """Fees collected vs fees accrued (conservation) plus fee markouts."""

    assets: tuple[str, ...]
    accrued_fees: tuple[int, ...]
    collected_fees: tuple[int, ...]
    unclaimed_after: tuple[int, ...]
    conservation_ok: bool
    markouts: tuple[FeeMarkout, ...]


def build_fee_harvest_summary(
    accrued_fees: tuple[int, ...],
    collected_fees: tuple[int, ...],
    unclaimed_after: tuple[int, ...],
    *,
    assets: tuple[str, ...],
    price_path: Sequence[tuple[int, int] | PriceStep],
    collection_step_index: int,
    horizons: Sequence[int],
    price_scale: int = DEFAULT_PRICE_SCALE,
) -> FeeHarvestSummary:
    """Build a fee-harvest summary with exact conservation and markouts.

    Conservation: per asset, ``collected + unclaimed_after == accrued``; any
    mismatch raises :class:`FeeConservationError` (fees are neither invented
    nor destroyed).  Markouts value collected base-asset fees at the horizon
    price minus the collection price, in scaled quote units (asset 0 is the
    base asset priced in asset 1, the quote numeraire).
    """
    validated_assets = _require_assets(assets)
    if len(validated_assets) != 2:
        raise InvalidLpLifecycleInput(
            "fee markout requires exactly two assets (base, quote numeraire)"
        )
    n = len(validated_assets)
    accrued = _require_amounts(accrued_fees, "accrued_fees", n)
    collected = _require_amounts(collected_fees, "collected_fees", n)
    unclaimed = _require_amounts(unclaimed_after, "unclaimed_after", n)
    for i, asset in enumerate(validated_assets):
        if collected[i] + unclaimed[i] != accrued[i]:
            raise FeeConservationError(
                f"fees must conserve for asset {asset!r}: collected "
                f"{collected[i]} + unclaimed {unclaimed[i]} != accrued {accrued[i]}"
            )
    steps = _validated_price_path(price_path)
    _require_int(price_scale, "price_scale", minimum=1)
    _require_int(collection_step_index, "collection_step_index")
    if collection_step_index >= len(steps):
        raise MarkoutHorizonUnavailable(
            f"collection_step_index {collection_step_index} is outside the "
            f"pinned price path ({len(steps)} steps)"
        )
    base_step = steps[collection_step_index]
    markouts: list[FeeMarkout] = []
    for horizon in horizons:
        _require_int(horizon, "horizon", minimum=1)
        horizon_index = collection_step_index + horizon
        if horizon_index >= len(steps):
            raise MarkoutHorizonUnavailable(
                f"horizon {horizon} from step {collection_step_index} is outside "
                f"the pinned price path ({len(steps)} steps)"
            )
        horizon_step = steps[horizon_index]
        markouts.append(
            FeeMarkout(
                horizon_steps=horizon,
                collection_step_index=collection_step_index,
                from_t=base_step.t,
                to_t=horizon_step.t,
                base_price_scaled=base_step.price_scaled,
                horizon_price_scaled=horizon_step.price_scaled,
                markout_scaled=collected[0]
                * (horizon_step.price_scaled - base_step.price_scaled),
            )
        )
    return FeeHarvestSummary(
        assets=validated_assets,
        accrued_fees=accrued,
        collected_fees=collected,
        unclaimed_after=unclaimed,
        conservation_ok=True,
        markouts=tuple(markouts),
    )

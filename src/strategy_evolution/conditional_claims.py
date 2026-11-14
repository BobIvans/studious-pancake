"""SX-07 typed conditional outcome-vector claims (research, CONDITIONAL_HYPEREDGE).

Family ``CLAIM-COMPLETE-SET`` (prediction-market complete sets) from
``docs/strategy-expansion/2026-11-14/STRATEGY_ACCEPTANCE_MATRIX.json``:
typed vector claims, split/merge conservation, adversarial settlement
and redemption cases. This module is a research model only.

Scope and gates
---------------
- Research only: no market data providers, no protocol wiring, no executable
  rights claims, no signing/sending/borrowing, no live promotion. Nothing here
  creates, holds or transfers anything.
- One-protocol-dossier gate: no specific prediction-market protocol is claimed
  or named anywhere in this module. Before ANY market wiring, a protocol-
  specific settlement-semantics dossier is required (exact version, commit,
  blob hash, license, retrieval time, added as an immutable versioned dossier).
  Until that dossier exists, oracle identity, dispute-window length, split /
  merge fee schedules and settlement ratio reconciliation remain typed UNKNOWN,
  never zero and never assumed.
- Unknown is not zero: a missing ask price (``PRICE_UNKNOWN``) is a typed
  rejection and is never substituted with ``0``; an unknown per-set collateral
  (``OutcomeVectorClaim.collateral_per_set is None``) blocks the complete-set
  evaluator instead of being defaulted.
- Conservation is per-asset/claim and never scalarized: the split rule is
  exactly 1 collateral unit -> 1 share of EVERY outcome, merge requires one
  share of every outcome, and every conservation check inspects each asset key
  independently. Summing magnitudes across different assets ("scalar fake
  swap") always fails the check.
- Settlement is NON_ATOMIC: resolution waiting, dispute windows and
  redemption are inventory-time activities. They are never a same-transaction
  flashloan leg, and the classification is enforced via a class constant and
  a typed guard (``require_non_atomic``).
- ``OutcomeVectorClaim.collateral_per_set`` is carried as an exact protocol
  parameter for the complete-set evaluator. The 1:1 split atom<->share
  conservation identity is asserted independently of it; reconciling the two
  ratios (real collateral decimals / set denominators) is part of the
  protocol-dossier gate above.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from .core import EvolutionError, stable_hash

NON_ATOMIC: Final[str] = "NON_ATOMIC"

REDEMPTION_ATOMICITY: Final[str] = NON_ATOMIC

PROTOCOL_DOSSIER_GATE: Final[str] = (
    "No prediction-market protocol is claimed. Before any market wiring a "
    "protocol-specific settlement-semantics dossier must exist: exact source "
    "version, commit, blob hash, license and retrieval time, pinned as an "
    "immutable versioned dossier. Until then oracle identity, dispute-window "
    "length, split/merge fees and settlement ratios stay typed UNKNOWN."
)


class ClaimRejectionReason(StrEnum):
    """Typed rejection vocabulary for conditional/complete-set claims."""

    INCOMPLETE_OUTCOME_VECTOR = "incomplete_outcome_vector"
    PRICE_UNKNOWN = "price_unknown"
    OUTCOME_SET_INCOMPLETE = "outcome_set_incomplete"
    DISPUTE_WINDOW_OPEN = "dispute_window_open"
    ALREADY_REDEEMED = "already_redeemed"
    NOT_WINNING_SHARE = "not_winning_share"
    MERGE_AFTER_RESOLUTION = "merge_after_resolution"
    COLLATERAL_UNKNOWN = "collateral_unknown"
    OUTCOME_UNKNOWN = "outcome_unknown"
    OUTCOME_VECTOR_EMPTY = "outcome_vector_empty"
    DUPLICATE_OUTCOME_ID = "duplicate_outcome_id"
    OUTCOME_SET_FLAGS_INVALID = "outcome_set_flags_invalid"
    MARKET_ID_REQUIRED = "market_id_required"
    COLLATERAL_ASSET_REQUIRED = "collateral_asset_required"
    SETTLEMENT_RIGHTS_REQUIRED = "settlement_rights_required"
    INVALID_COLLATERAL_AMOUNT = "invalid_collateral_amount"
    INVALID_SHARE_COUNT = "invalid_share_count"
    INVALID_PRICE = "invalid_price"
    INVALID_SLOT = "invalid_slot"
    INVALID_DISPUTE_WINDOW = "invalid_dispute_window"
    SETTLEMENT_ORACLE_REQUIRED = "settlement_oracle_required"
    ATOMICITY_MISCLASSIFIED = "atomicity_misclassified"
    CONSERVATION_VIOLATED = "conservation_violated"


class ConditionalClaimError(EvolutionError):
    """Typed rejection for conditional/complete-set claim research operations.

    Subclasses the existing strategy-evolution error owner; ``code`` and
    ``reason_code`` carry the exact lowercase reason from
    ``ClaimRejectionReason``.
    """

    def __init__(
        self, reason: ClaimRejectionReason, message: str | None = None
    ) -> None:
        self.reason = reason
        self.reason_code = reason.value
        super().__init__(
            reason.value if message is None else f"{reason.value}: {message}"
        )


def _require_id(value: object, reason: ClaimRejectionReason) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConditionalClaimError(reason)
    return value


def _require_slot(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConditionalClaimError(ClaimRejectionReason.INVALID_SLOT)
    return value


def _require_share_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConditionalClaimError(ClaimRejectionReason.INVALID_SHARE_COUNT)
    return value


@dataclass(frozen=True, slots=True)
class ResolutionEvent:
    """Typed settlement resolution for one market (research model).

    ``finalized`` is the oracle/resolution finalization flag. Redemption
    additionally requires the dispute window to have fully elapsed
    (strictly: ``at_slot > dispute_window_end_slot``; the conservative
    reading, because the end slot itself is still inside the window).
    """

    settlement_oracle: str
    resolution_slot: int
    dispute_window_end_slot: int
    finalized: bool = False

    def __post_init__(self) -> None:
        _require_id(
            self.settlement_oracle, ClaimRejectionReason.SETTLEMENT_ORACLE_REQUIRED
        )
        _require_slot(self.resolution_slot)
        _require_slot(self.dispute_window_end_slot)
        if self.dispute_window_end_slot < self.resolution_slot:
            raise ConditionalClaimError(
                ClaimRejectionReason.INVALID_DISPUTE_WINDOW,
                "dispute window cannot end before resolution slot",
            )
        if not isinstance(self.finalized, bool):
            raise ConditionalClaimError(ClaimRejectionReason.OUTCOME_SET_FLAGS_INVALID)

    def dispute_window_elapsed(self, at_slot: int) -> bool:
        return _require_slot(at_slot) > self.dispute_window_end_slot


@dataclass(frozen=True, slots=True)
class OutcomeVectorClaim:
    """Typed vector claim over one conditional market.

    ``collateral_per_set`` is ``None`` exactly when the per-set redemption
    collateral is UNKNOWN (never zero, never assumed). ``settlement_rights``
    is a non-empty summary string of the researched redemption rights.
    """

    market_id: str
    outcome_ids: tuple[str, ...]
    mutually_exclusive: bool
    exhaustive: bool
    collateral_asset: str
    collateral_per_set: int | None
    settlement_rights: str

    def __post_init__(self) -> None:
        _require_id(self.market_id, ClaimRejectionReason.MARKET_ID_REQUIRED)
        if not isinstance(self.outcome_ids, tuple):
            raise ConditionalClaimError(ClaimRejectionReason.OUTCOME_VECTOR_EMPTY)
        if len(self.outcome_ids) < 2:
            raise ConditionalClaimError(
                ClaimRejectionReason.OUTCOME_VECTOR_EMPTY,
                "a complete set needs at least two outcomes",
            )
        for outcome_id in self.outcome_ids:
            _require_id(outcome_id, ClaimRejectionReason.OUTCOME_VECTOR_EMPTY)
        if len(set(self.outcome_ids)) != len(self.outcome_ids):
            raise ConditionalClaimError(ClaimRejectionReason.DUPLICATE_OUTCOME_ID)
        if not isinstance(self.mutually_exclusive, bool) or not isinstance(
            self.exhaustive, bool
        ):
            raise ConditionalClaimError(ClaimRejectionReason.OUTCOME_SET_FLAGS_INVALID)
        _require_id(
            self.collateral_asset, ClaimRejectionReason.COLLATERAL_ASSET_REQUIRED
        )
        if self.collateral_per_set is not None:
            if (
                isinstance(self.collateral_per_set, bool)
                or not isinstance(self.collateral_per_set, int)
                or self.collateral_per_set <= 0
            ):
                raise ConditionalClaimError(
                    ClaimRejectionReason.INVALID_COLLATERAL_AMOUNT
                )
        _require_id(
            self.settlement_rights, ClaimRejectionReason.SETTLEMENT_RIGHTS_REQUIRED
        )

    @property
    def outcome_set_complete(self) -> bool:
        """True only when the outcome set is proven mutually exclusive AND exhaustive.

        Fail closed: an unproven flag blocks settlement-side operations.
        """
        return self.mutually_exclusive and self.exhaustive


def claims_conserved(
    claim: OutcomeVectorClaim, collateral_delta: int, share_deltas: Mapping[str, int]
) -> bool:
    """Per-asset vector conservation for a split/merge exchange vector.

    True iff every outcome of ``claim`` appears in ``share_deltas`` with an
    absolute delta exactly equal to ``abs(collateral_delta)``. Each asset key
    is checked independently: magnitudes are never summed across assets, so a
    scalar fake swap (e.g. two shares of A compensating zero of B with the
    same total) is always rejected.
    """
    if isinstance(collateral_delta, bool) or not isinstance(collateral_delta, int):
        return False
    magnitude = abs(collateral_delta)
    if magnitude == 0 or len(share_deltas) != len(claim.outcome_ids):
        return False
    for outcome_id in claim.outcome_ids:
        delta = share_deltas.get(outcome_id)
        if delta is None or isinstance(delta, bool) or not isinstance(delta, int):
            return False
        if abs(delta) != magnitude:
            return False
    return True


def require_non_atomic(atomicity: str) -> str:
    """Guard: only the NON_ATOMIC classification is accepted for settlement.

    Any attempt to classify settlement/redemption waiting as same-transaction
    atomic is a typed rejection.
    """
    if atomicity != NON_ATOMIC:
        raise ConditionalClaimError(
            ClaimRejectionReason.ATOMICITY_MISCLASSIFIED,
            f"settlement waiting is inventory-time, got {atomicity!r}",
        )
    return NON_ATOMIC


@dataclass(frozen=True, slots=True)
class SplitReceipt:
    """Exact split result: 1 collateral unit -> 1 share of EVERY outcome.

    ``atomicity`` stays ``None`` (UNKNOWN): split atomicity is protocol-
    specific and blocked behind the protocol-dossier gate. The conservation
    proof is per-asset and asserted at construction.
    """

    market_id: str
    collateral_asset: str
    collateral_amount: int
    shares: Mapping[str, int]
    conservation_proof: tuple[tuple[str, int], ...]
    atomicity: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.market_id, ClaimRejectionReason.MARKET_ID_REQUIRED)
        _require_id(
            self.collateral_asset, ClaimRejectionReason.COLLATERAL_ASSET_REQUIRED
        )
        if (
            isinstance(self.collateral_amount, bool)
            or not isinstance(self.collateral_amount, int)
            or self.collateral_amount <= 0
        ):
            raise ConditionalClaimError(ClaimRejectionReason.INVALID_COLLATERAL_AMOUNT)
        shares = dict(self.shares)
        for outcome_id, count in shares.items():
            if (
                isinstance(count, bool)
                or not isinstance(count, int)
                or count != self.collateral_amount
            ):
                raise ConditionalClaimError(
                    ClaimRejectionReason.CONSERVATION_VIOLATED,
                    "split mints exactly collateral_amount shares of every outcome",
                )
        expected_proof: tuple[tuple[str, int], ...] = (
            (self.collateral_asset, -self.collateral_amount),
            *tuple((outcome_id, self.collateral_amount) for outcome_id in shares),
        )
        if tuple(self.conservation_proof) != expected_proof:
            raise ConditionalClaimError(
                ClaimRejectionReason.CONSERVATION_VIOLATED,
                "split conservation proof must record the exact per-asset vector",
            )


@dataclass(frozen=True, slots=True)
class MergeReceipt:
    """Exact merge result: one share of EVERY outcome -> 1 collateral unit."""

    market_id: str
    collateral_asset: str
    collateral_minted: int
    shares_burned: Mapping[str, int]
    conservation_proof: tuple[tuple[str, int], ...]
    atomicity: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.market_id, ClaimRejectionReason.MARKET_ID_REQUIRED)
        _require_id(
            self.collateral_asset, ClaimRejectionReason.COLLATERAL_ASSET_REQUIRED
        )
        if (
            isinstance(self.collateral_minted, bool)
            or not isinstance(self.collateral_minted, int)
            or self.collateral_minted <= 0
        ):
            raise ConditionalClaimError(ClaimRejectionReason.INVALID_COLLATERAL_AMOUNT)
        burned = dict(self.shares_burned)
        for outcome_id, count in burned.items():
            if (
                isinstance(count, bool)
                or not isinstance(count, int)
                or count != -self.collateral_minted
            ):
                raise ConditionalClaimError(
                    ClaimRejectionReason.CONSERVATION_VIOLATED,
                    "merge burns exactly collateral_minted shares of every outcome",
                )
        expected_proof: tuple[tuple[str, int], ...] = (
            (self.collateral_asset, self.collateral_minted),
            *tuple((outcome_id, -self.collateral_minted) for outcome_id in burned),
        )
        if tuple(self.conservation_proof) != expected_proof:
            raise ConditionalClaimError(
                ClaimRejectionReason.CONSERVATION_VIOLATED,
                "merge conservation proof must record the exact per-asset vector",
            )


@dataclass(frozen=True, slots=True)
class RedemptionReceipt:
    """Exact redemption of winning shares; classified NON_ATOMIC by guard.

    Maturity/settlement waiting is inventory-time: the payout is realized
    only after resolution finalization and dispute-window elapse, and is
    never a same-transaction flashloan leg.
    """

    market_id: str
    collateral_asset: str
    winning_outcome_id: str
    share_amount: int
    payout_amount: int
    at_slot: int
    dispute_window_end_slot: int
    conservation_proof: tuple[tuple[str, int], ...]
    atomicity: str = NON_ATOMIC

    def __post_init__(self) -> None:
        _require_id(self.market_id, ClaimRejectionReason.MARKET_ID_REQUIRED)
        _require_id(
            self.collateral_asset, ClaimRejectionReason.COLLATERAL_ASSET_REQUIRED
        )
        _require_id(self.winning_outcome_id, ClaimRejectionReason.OUTCOME_VECTOR_EMPTY)
        if (
            isinstance(self.share_amount, bool)
            or not isinstance(self.share_amount, int)
            or self.share_amount <= 0
            or isinstance(self.payout_amount, bool)
            or not isinstance(self.payout_amount, int)
            or self.payout_amount <= 0
        ):
            raise ConditionalClaimError(ClaimRejectionReason.INVALID_SHARE_COUNT)
        if self.payout_amount != self.share_amount:
            raise ConditionalClaimError(
                ClaimRejectionReason.CONSERVATION_VIOLATED,
                "redemption pays exactly one collateral unit per winning share",
            )
        _require_slot(self.at_slot)
        _require_slot(self.dispute_window_end_slot)
        require_non_atomic(self.atomicity)


def split_outcome_vector(
    claim: OutcomeVectorClaim, collateral_amount: int
) -> SplitReceipt:
    """Split exact collateral into one share of EVERY outcome (1:1, exact ints).

    Vector conservation is asserted per-asset before the receipt is returned.
    """
    if (
        isinstance(collateral_amount, bool)
        or not isinstance(collateral_amount, int)
        or collateral_amount <= 0
    ):
        raise ConditionalClaimError(ClaimRejectionReason.INVALID_COLLATERAL_AMOUNT)
    shares: dict[str, int] = {
        outcome_id: collateral_amount for outcome_id in claim.outcome_ids
    }
    if not claims_conserved(claim, -collateral_amount, shares):
        raise ConditionalClaimError(ClaimRejectionReason.CONSERVATION_VIOLATED)
    proof: tuple[tuple[str, int], ...] = (
        (claim.collateral_asset, -collateral_amount),
        *tuple((outcome_id, collateral_amount) for outcome_id in claim.outcome_ids),
    )
    return SplitReceipt(
        market_id=claim.market_id,
        collateral_asset=claim.collateral_asset,
        collateral_amount=collateral_amount,
        shares=MappingProxyType(shares),
        conservation_proof=proof,
        atomicity=None,
    )


def _normalize_share_vector(
    claim: OutcomeVectorClaim, shares: Mapping[str, int]
) -> dict[str, int]:
    """Validate an explicit per-outcome share vector (complete, ints, known keys)."""
    normalized: dict[str, int] = {}
    for key, value in shares.items():
        if not isinstance(key, str) or key not in claim.outcome_ids:
            raise ConditionalClaimError(ClaimRejectionReason.OUTCOME_UNKNOWN)
        normalized[key] = _require_share_count(value)
    for outcome_id in claim.outcome_ids:
        if outcome_id not in normalized or normalized[outcome_id] <= 0:
            raise ConditionalClaimError(
                ClaimRejectionReason.INCOMPLETE_OUTCOME_VECTOR,
                "merge requires one (positive) share of every outcome",
            )
    return normalized


def merge_outcome_vector(
    claim: OutcomeVectorClaim,
    shares: Mapping[str, int],
    *,
    resolution: ResolutionEvent | None = None,
) -> MergeReceipt:
    """Merge one share of EVERY outcome back into exact collateral (reverse split).

    A missing share, an unknown outcome key, a non-positive count or an
    unequal vector is the typed rejection ``incomplete_outcome_vector``
    (partial merging is not performed implicitly; callers must trim to the
    common floor first). Merge after a resolution event exists is a typed
    policy rejection: post-resolution mint/merge rights are protocol-specific
    and fail closed.
    """
    if resolution is not None:
        raise ConditionalClaimError(
            ClaimRejectionReason.MERGE_AFTER_RESOLUTION,
            "merge policy fails closed once resolution exists",
        )
    normalized = _normalize_share_vector(claim, shares)
    counts = {normalized[outcome_id] for outcome_id in claim.outcome_ids}
    if len(counts) != 1:
        raise ConditionalClaimError(
            ClaimRejectionReason.INCOMPLETE_OUTCOME_VECTOR,
            "complete-set merge needs equal shares of every outcome",
        )
    amount = counts.pop()
    if not claims_conserved(
        claim,
        amount,
        {outcome_id: -normalized[outcome_id] for outcome_id in claim.outcome_ids},
    ):
        raise ConditionalClaimError(ClaimRejectionReason.CONSERVATION_VIOLATED)
    proof: tuple[tuple[str, int], ...] = (
        (claim.collateral_asset, amount),
        *tuple(
            (outcome_id, -normalized[outcome_id]) for outcome_id in claim.outcome_ids
        ),
    )
    return MergeReceipt(
        market_id=claim.market_id,
        collateral_asset=claim.collateral_asset,
        collateral_minted=amount,
        shares_burned=MappingProxyType(
            {outcome_id: -normalized[outcome_id] for outcome_id in claim.outcome_ids}
        ),
        conservation_proof=proof,
        atomicity=None,
    )


def redeem_winning_shares(
    claim: OutcomeVectorClaim,
    shares: Mapping[str, int],
    *,
    winning_outcome_id: str,
    resolution: ResolutionEvent,
    at_slot: int,
    already_redeemed: Sequence[str] = (),
) -> RedemptionReceipt:
    """Redeem winning shares for exactly one collateral unit per share.

    Requires ``resolution.finalized`` AND the dispute window fully elapsed;
    before that the typed rejection is ``dispute_window_open`` (fail closed).
    Classified NON_ATOMIC via guard: settlement waiting is inventory-time and
    never a same-transaction flashloan leg. Double redemption, redemption of
    a non-winning share and unknown winning outcomes are typed rejections.
    """
    _require_id(winning_outcome_id, ClaimRejectionReason.OUTCOME_UNKNOWN)
    if winning_outcome_id not in claim.outcome_ids:
        raise ConditionalClaimError(ClaimRejectionReason.OUTCOME_UNKNOWN)
    if not claim.outcome_set_complete:
        raise ConditionalClaimError(
            ClaimRejectionReason.OUTCOME_SET_INCOMPLETE,
            "settlement requires proven mutually-exclusive and exhaustive outcomes",
        )
    if not resolution.finalized or not resolution.dispute_window_elapsed(at_slot):
        raise ConditionalClaimError(
            ClaimRejectionReason.DISPUTE_WINDOW_OPEN,
            "redemption requires finalized resolution and elapsed dispute window",
        )
    for prior in already_redeemed:
        if not isinstance(prior, str) or prior not in claim.outcome_ids:
            raise ConditionalClaimError(ClaimRejectionReason.OUTCOME_UNKNOWN)
    if winning_outcome_id in already_redeemed:
        raise ConditionalClaimError(
            ClaimRejectionReason.ALREADY_REDEEMED,
            "winning outcome already redeemed",
        )
    normalized: dict[str, int] = {}
    for key, value in shares.items():
        if not isinstance(key, str) or key not in claim.outcome_ids:
            raise ConditionalClaimError(ClaimRejectionReason.OUTCOME_UNKNOWN)
        normalized[key] = _require_share_count(value)
        if normalized[key] < 0:
            raise ConditionalClaimError(ClaimRejectionReason.INVALID_SHARE_COUNT)
    for outcome_id, count in normalized.items():
        if outcome_id != winning_outcome_id and count > 0:
            raise ConditionalClaimError(
                ClaimRejectionReason.NOT_WINNING_SHARE,
                f"outcome {outcome_id} did not win and is not redeemable",
            )
    share_amount = normalized.get(winning_outcome_id, 0)
    if share_amount <= 0:
        raise ConditionalClaimError(
            ClaimRejectionReason.INCOMPLETE_OUTCOME_VECTOR,
            "redemption request holds no winning share",
        )
    proof: tuple[tuple[str, int], ...] = (
        (winning_outcome_id, -share_amount),
        (claim.collateral_asset, share_amount),
    )
    return RedemptionReceipt(
        market_id=claim.market_id,
        collateral_asset=claim.collateral_asset,
        winning_outcome_id=winning_outcome_id,
        share_amount=share_amount,
        payout_amount=share_amount,
        at_slot=_require_slot(at_slot),
        dispute_window_end_slot=resolution.dispute_window_end_slot,
        conservation_proof=proof,
        atomicity=require_non_atomic(REDEMPTION_ATOMICITY),
    )


@dataclass(frozen=True, slots=True)
class CompleteSetArbCandidate:
    """Vector arbitrage candidate: buy the complete set, redeem post-dispute.

    Per-asset conservation is asserted at construction from the exact legs:
    every outcome must net exactly 0 and the collateral asset must net
    exactly ``profit_per_set``. Scalar netting across assets cannot pass.
    """

    market_id: str
    outcome_ids: tuple[str, ...]
    collateral_asset: str
    asks: Mapping[str, int]
    total_ask_cost: int
    collateral_per_set: int
    profit_per_set: int
    profit_vector: tuple[tuple[str, int], ...]
    legs: tuple[tuple[str, tuple[tuple[str, int], ...]], ...]
    conservation_proof: tuple[tuple[str, int], ...]
    atomicity: str = NON_ATOMIC

    def __post_init__(self) -> None:
        _require_id(self.market_id, ClaimRejectionReason.MARKET_ID_REQUIRED)
        _require_id(
            self.collateral_asset, ClaimRejectionReason.COLLATERAL_ASSET_REQUIRED
        )
        if len(self.outcome_ids) < 2:
            raise ConditionalClaimError(ClaimRejectionReason.OUTCOME_VECTOR_EMPTY)
        if (
            isinstance(self.total_ask_cost, bool)
            or not isinstance(self.total_ask_cost, int)
            or self.total_ask_cost < 0
        ):
            raise ConditionalClaimError(ClaimRejectionReason.INVALID_PRICE)
        if self.profit_per_set != self.collateral_per_set - self.total_ask_cost:
            raise ConditionalClaimError(
                ClaimRejectionReason.CONSERVATION_VIOLATED,
                "profit must equal collateral_per_set minus total ask cost",
            )
        if self.profit_per_set <= 0:
            raise ConditionalClaimError(
                ClaimRejectionReason.CONSERVATION_VIOLATED,
                "non-positive profit is not an arbitrage candidate",
            )
        nets: dict[str, int] = {}
        for _leg_name, leg_flows in self.legs:
            for asset, delta in leg_flows:
                nets[asset] = nets.get(asset, 0) + delta
        expected = dict(self.profit_vector)
        if nets != expected:
            raise ConditionalClaimError(
                ClaimRejectionReason.CONSERVATION_VIOLATED,
                f"per-asset nets {nets} do not match profit vector {expected}",
            )
        for asset, net in nets.items():
            if asset == self.collateral_asset:
                continue
            if net != 0:
                raise ConditionalClaimError(
                    ClaimRejectionReason.CONSERVATION_VIOLATED,
                    f"outcome asset {asset} must net exactly 0, got {net}",
                )
        if nets.get(self.collateral_asset) != self.profit_per_set:
            raise ConditionalClaimError(
                ClaimRejectionReason.CONSERVATION_VIOLATED,
                "collateral net must equal the exact profit",
            )
        if dict(self.conservation_proof) != nets:
            raise ConditionalClaimError(
                ClaimRejectionReason.CONSERVATION_VIOLATED,
                "conservation proof must record the exact per-asset nets",
            )
        require_non_atomic(self.atomicity)

    def digest(self) -> str:
        """Deterministic offline digest of the exact candidate vector."""
        return stable_hash(
            "sx07.complete_set_arb_candidate",
            {
                "market_id": self.market_id,
                "outcome_ids": list(self.outcome_ids),
                "collateral_asset": self.collateral_asset,
                "asks": {key: self.asks[key] for key in sorted(self.asks)},
                "total_ask_cost": self.total_ask_cost,
                "collateral_per_set": self.collateral_per_set,
                "profit_per_set": self.profit_per_set,
                "profit_vector": [list(item) for item in self.profit_vector],
                "legs": [
                    [name, [list(flow) for flow in flows]] for name, flows in self.legs
                ],
                "atomicity": self.atomicity,
            },
        )


class CompleteSetArbEvaluator:
    """Evaluate complete-set vector arbitrage from exact per-outcome asks.

    Fail-closed order (deterministic):
    1. ``collateral_per_set`` UNKNOWN -> ``collateral_unknown`` (never zero).
    2. outcome set not proven mutually exclusive + exhaustive ->
       ``outcome_set_incomplete``.
    3. any per-outcome ask missing/None -> ``price_unknown`` (never treated
       as 0); malformed or negative price -> ``invalid_price``; unknown
       outcome keys -> ``outcome_unknown``.
    4. ``sum(asks) < collateral_per_set`` -> exact vector candidate; otherwise
       ``None`` (a no-trade, not an error).

    Settlement waiting is NON_ATOMIC by class constant; the redemption leg
    realizes only after resolution finalization and dispute-window elapse.
    """

    REDEMPTION_ATOMICITY: Final[str] = NON_ATOMIC

    def __init__(self, claim: OutcomeVectorClaim) -> None:
        self._claim = claim

    @property
    def claim(self) -> OutcomeVectorClaim:
        return self._claim

    def redemption_atomicity(self) -> str:
        return require_non_atomic(self.REDEMPTION_ATOMICITY)

    def evaluate(
        self, asks: Mapping[str, int | None]
    ) -> CompleteSetArbCandidate | None:
        claim = self._claim
        if claim.collateral_per_set is None:
            raise ConditionalClaimError(
                ClaimRejectionReason.COLLATERAL_UNKNOWN,
                "per-set collateral is UNKNOWN; it is never defaulted to zero",
            )
        if not claim.outcome_set_complete:
            raise ConditionalClaimError(
                ClaimRejectionReason.OUTCOME_SET_INCOMPLETE,
                "arbitrage requires proven mutually-exclusive and exhaustive outcomes",
            )
        known_asks: dict[str, int] = {}
        for key, value in asks.items():
            if not isinstance(key, str) or key not in claim.outcome_ids:
                raise ConditionalClaimError(ClaimRejectionReason.OUTCOME_UNKNOWN)
            if value is None:
                raise ConditionalClaimError(
                    ClaimRejectionReason.PRICE_UNKNOWN,
                    f"ask for {key} is unknown; unknown is never treated as 0",
                )
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ConditionalClaimError(ClaimRejectionReason.INVALID_PRICE)
            known_asks[key] = value
        for outcome_id in claim.outcome_ids:
            if outcome_id not in known_asks:
                raise ConditionalClaimError(
                    ClaimRejectionReason.PRICE_UNKNOWN,
                    f"ask for {outcome_id} is missing; unknown is never treated as 0",
                )
        total_ask_cost = sum(known_asks[outcome_id] for outcome_id in claim.outcome_ids)
        collateral_per_set = claim.collateral_per_set
        if total_ask_cost >= collateral_per_set:
            return None
        profit_per_set = collateral_per_set - total_ask_cost
        buy_flows: tuple[tuple[str, int], ...] = (
            (claim.collateral_asset, -total_ask_cost),
            *tuple((outcome_id, 1) for outcome_id in claim.outcome_ids),
        )
        redeem_flows: tuple[tuple[str, int], ...] = (
            (claim.collateral_asset, collateral_per_set),
            *tuple((outcome_id, -1) for outcome_id in claim.outcome_ids),
        )
        legs: tuple[tuple[str, tuple[tuple[str, int], ...]], ...] = (
            ("buy_complete_set", buy_flows),
            ("redeem_complete_set_non_atomic", redeem_flows),
        )
        profit_vector: tuple[tuple[str, int], ...] = (
            (claim.collateral_asset, profit_per_set),
            *tuple((outcome_id, 0) for outcome_id in claim.outcome_ids),
        )
        return CompleteSetArbCandidate(
            market_id=claim.market_id,
            outcome_ids=claim.outcome_ids,
            collateral_asset=claim.collateral_asset,
            asks=MappingProxyType(dict(known_asks)),
            total_ask_cost=total_ask_cost,
            collateral_per_set=collateral_per_set,
            profit_per_set=profit_per_set,
            profit_vector=profit_vector,
            legs=legs,
            conservation_proof=profit_vector,
            atomicity=require_non_atomic(self.REDEMPTION_ATOMICITY),
        )


__all__ = [
    "NON_ATOMIC",
    "PROTOCOL_DOSSIER_GATE",
    "REDEMPTION_ATOMICITY",
    "ClaimRejectionReason",
    "CompleteSetArbCandidate",
    "CompleteSetArbEvaluator",
    "ConditionalClaimError",
    "MergeReceipt",
    "OutcomeVectorClaim",
    "RedemptionReceipt",
    "ResolutionEvent",
    "SplitReceipt",
    "claims_conserved",
    "merge_outcome_vector",
    "redeem_winning_shares",
    "require_non_atomic",
    "split_outcome_vector",
]

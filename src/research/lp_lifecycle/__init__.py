"""LP position lifecycle and fee/inventory harvesting research model (SX-09).

Research-only, offline, deterministic.  This package models the *lifecycle
economics* of persistent LP inventory (mint, add, remove, fee accrual/claim,
compound, range shift) as pure integer-math state transitions with exact
per-asset token conservation.  It is deliberately venue-agnostic: the
range/bins descriptor is opaque provenance-carrying data, never interpreted
as executable venue state.

Capital classification: LP positions are PERSISTENT INVENTORY.  LP capital
is locked while deployed and cannot be repaid within one transaction, so
flash principal can never finance an LP transition.  Attaching any
:class:`FlashFinancingTerms` to a transition raises
:class:`PersistentLpNotFlashFinancable`.

Boundary guarantees:
- research model only; no venue wiring, no signing, no submission;
- no NFT/position-rights claims are made (``position_right`` is opaque data);
- no AMM curve is invented: impermanent-loss evaluation runs only on supplied
  position valuations or a v2-style constant-product curve when *explicitly*
  flagged ``cpmm``; any other valuation model raises
  :class:`ValuationModelUnproven` (typed exclusion);
- unknown costs stay ``None``; fixtures are never live evidence.
"""

from src.research.lp_lifecycle.position_lifecycle import (
    FeeHarvestSummary,
    FeeMarkout,
    FlashFinancingTerms,
    IlStep,
    ImpermanentLossEvaluator,
    LPPositionState,
    PersistentCapitalLock,
    PriceStep,
    TransitionReceipt,
    ValuationModel,
    accrue_fees,
    add_liquidity,
    build_fee_harvest_summary,
    collect_fees,
    compound_fees,
    constant_product_lp_value_scaled,
    evaluate_impermanent_loss,
    FeeConservationError,
    InexactReinvestment,
    InvalidLpLifecycleInput,
    LpLifecycleError,
    MarkoutHorizonUnavailable,
    PersistentLpNotFlashFinancable,
    StateGenerationMismatch,
    TokenConservationError,
    ValuationModelUnproven,
    mint_position,
    remove_liquidity,
    shift_range,
    verify_receipt,
)

__all__ = [
    "FeeConservationError",
    "FeeHarvestSummary",
    "FeeMarkout",
    "FlashFinancingTerms",
    "IlStep",
    "ImpermanentLossEvaluator",
    "InexactReinvestment",
    "InvalidLpLifecycleInput",
    "LPPositionState",
    "LpLifecycleError",
    "MarkoutHorizonUnavailable",
    "PersistentCapitalLock",
    "PersistentLpNotFlashFinancable",
    "PriceStep",
    "StateGenerationMismatch",
    "TokenConservationError",
    "TransitionReceipt",
    "ValuationModel",
    "ValuationModelUnproven",
    "accrue_fees",
    "add_liquidity",
    "build_fee_harvest_summary",
    "collect_fees",
    "compound_fees",
    "constant_product_lp_value_scaled",
    "evaluate_impermanent_loss",
    "mint_position",
    "remove_liquidity",
    "shift_range",
    "verify_receipt",
]

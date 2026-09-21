"""PR-308 / NF-921..925: conservative orderbook queue and fill envelopes."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .core import ContractResult, UltimateMegaError, record, require_nonnegative, require_positive


def classify_orderbook_observability(
    *,
    feed_level: str,
    sequence_contiguous: bool,
    depth_levels: int,
) -> ContractResult:
    if feed_level not in {"L2", "L3"}:
        raise UltimateMegaError("UNKNOWN_FEED_LEVEL")
    depth = require_positive(depth_levels, "depth_levels")
    return record(
        "classify_orderbook_observability",
        {
            "feed_level": feed_level,
            "sequence_contiguous": sequence_contiguous,
            "depth_levels": depth,
            "order_ids_observable": feed_level == "L3",
            "queue_exact": feed_level == "L3" and sequence_contiguous,
        },
        status="OK" if sequence_contiguous else "INCOMPLETE",
        blockers=() if sequence_contiguous else ("SEQUENCE_GAP",),
    )


def propagate_queue_position_bounds(
    *,
    initial_quantity_ahead: int,
    events: Sequence[Mapping[str, Any]],
    l3_exact: bool = False,
) -> ContractResult:
    optimistic = pessimistic = require_nonnegative(
        initial_quantity_ahead, "initial_quantity_ahead"
    )
    gaps = 0
    for event in events:
        kind = event.get("kind")
        qty = require_nonnegative(int(event.get("quantity", 0)), "quantity")
        if kind == "trade":
            optimistic = max(0, optimistic - qty)
            pessimistic = max(0, pessimistic - qty)
        elif kind == "add_ahead":
            optimistic += qty
            pessimistic += qty
        elif kind == "cancel_ahead":
            optimistic = max(0, optimistic - qty)
            if l3_exact:
                pessimistic = max(0, pessimistic - qty)
        elif kind == "cancel_unknown":
            if l3_exact:
                raise UltimateMegaError("UNIDENTIFIED_CANCEL_POSITION")
            pessimistic += qty
        elif kind == "gap":
            gaps += 1
            pessimistic += qty
        else:
            raise UltimateMegaError("UNKNOWN_BOOK_EVENT")
    return record(
        "propagate_queue_position_bounds",
        {
            "optimistic_quantity_ahead": optimistic,
            "pessimistic_quantity_ahead": pessimistic,
            "sequence_gaps": gaps,
        },
        status="INCOMPLETE" if gaps else "OK",
        blockers=("SEQUENCE_GAP",) if gaps else (),
    )


def replay_partial_fill_envelopes(
    *,
    order_quantity: int,
    traded_at_level: int,
    optimistic_quantity_ahead: int,
    pessimistic_quantity_ahead: int,
    lot_size: int = 1,
) -> ContractResult:
    quantity = require_nonnegative(order_quantity, "order_quantity")
    traded = require_nonnegative(traded_at_level, "traded_at_level")
    lot = require_positive(lot_size, "lot_size")
    if quantity % lot:
        raise UltimateMegaError("LOT_MISMATCH")
    optimistic_fill = min(quantity, max(0, traded - optimistic_quantity_ahead))
    pessimistic_fill = min(quantity, max(0, traded - pessimistic_quantity_ahead))
    if pessimistic_fill > optimistic_fill:
        raise UltimateMegaError("IMPOSSIBLE_FILL")
    return record(
        "replay_partial_fill_envelopes",
        {
            "min_fill": pessimistic_fill,
            "max_fill": optimistic_fill,
            "min_residual": quantity - optimistic_fill,
            "max_residual": quantity - pessimistic_fill,
        },
    )


def separate_replay_and_impact_models(
    replay_fill: Mapping[str, Any],
    *,
    candidate_size: int,
    impact_bound: int | None,
) -> ContractResult:
    size = require_nonnegative(candidate_size, "candidate_size")
    if impact_bound is None and size > 0:
        return record(
            "separate_replay_and_impact_models",
            {"replay_fill": dict(replay_fill), "candidate_size": size, "impact_modeled": False},
            status="INCOMPLETE",
            blockers=("COUNTERFACTUAL_IMPACT_UNMODELED",),
        )
    bound = require_nonnegative(int(impact_bound or 0), "impact_bound")
    return record(
        "separate_replay_and_impact_models",
        {"replay_fill": dict(replay_fill), "candidate_size": size, "impact_bound": bound, "impact_modeled": True},
    )


def compare_fill_envelope_to_settlement(
    *,
    min_fill: int,
    max_fill: int,
    actual_fill: int | None,
) -> ContractResult:
    low = require_nonnegative(min_fill, "min_fill")
    high = require_nonnegative(max_fill, "max_fill")
    if low > high:
        raise UltimateMegaError("IMPOSSIBLE_FILL")
    if actual_fill is None:
        return record(
            "compare_fill_envelope_to_settlement",
            {"min_fill": low, "max_fill": high, "actual_fill": None, "covered": None},
            status="UNKNOWN",
            blockers=("ACTUAL_LABEL_UNAVAILABLE",),
        )
    actual = require_nonnegative(actual_fill, "actual_fill")
    covered = low <= actual <= high
    return record(
        "compare_fill_envelope_to_settlement",
        {
            "min_fill": low,
            "max_fill": high,
            "actual_fill": actual,
            "covered": covered,
            "optimistic_bias": max(0, high - actual),
        },
        status="OK" if covered else "BLOCKED",
        blockers=() if covered else ("FILL_ENVELOPE_MISS",),
    )

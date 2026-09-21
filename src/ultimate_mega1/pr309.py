"""PR-309 / NF-926..930: JIT auction-clock qualification."""

from __future__ import annotations

from typing import Any, Mapping

from .core import ContractResult, UltimateMegaError, record, require_int, require_nonnegative, require_positive, stable_hash


def decode_jit_auction_envelope(
    order: Mapping[str, Any],
    *,
    expected_program: str,
    expected_market: str,
) -> ContractResult:
    if order.get("program_id") != expected_program:
        raise UltimateMegaError("UNKNOWN_PROGRAM_VERSION")
    if order.get("market") != expected_market:
        raise UltimateMegaError("ORDER_AUTH_INVALID")
    start = require_nonnegative(int(order.get("auction_start_slot", -1)), "auction_start_slot")
    duration = require_positive(int(order.get("duration_slots", 0)), "duration_slots")
    return record(
        "decode_jit_auction_envelope",
        {
            "market": expected_market,
            "order_id": order.get("order_id"),
            "auction_start_slot": start,
            "duration_slots": duration,
            "start_price": require_positive(int(order.get("start_price", 0)), "start_price"),
            "end_price": require_positive(int(order.get("end_price", 0)), "end_price"),
            "signed_message_domain": order.get("signed_message_domain"),
            "order_hash": stable_hash("jit-order", order),
        },
    )


def evaluate_jit_price_at_slot(
    envelope: Mapping[str, Any],
    *,
    observed_slot: int,
    oracle_fresh: bool,
    tick_size: int = 1,
) -> ContractResult:
    if not oracle_fresh:
        raise UltimateMegaError("ORACLE_STALE")
    slot = require_nonnegative(observed_slot, "observed_slot")
    start = require_nonnegative(int(envelope["auction_start_slot"]), "auction_start_slot")
    duration = require_positive(int(envelope["duration_slots"]), "duration_slots")
    if not start <= slot <= start + duration:
        raise UltimateMegaError("AUCTION_NOT_ACTIVE")
    start_price = require_positive(int(envelope["start_price"]), "start_price")
    end_price = require_positive(int(envelope["end_price"]), "end_price")
    elapsed = slot - start
    raw = start_price + (end_price - start_price) * elapsed // duration
    tick = require_positive(tick_size, "tick_size")
    price = raw // tick * tick
    return record(
        "evaluate_jit_price_at_slot",
        {"slot": slot, "price": price, "tick_size": tick, "remaining_slots": start + duration - slot},
    )


def plan_jit_fill_and_hedge(
    *,
    requested_fill: int,
    max_inventory: int,
    current_inventory: int,
    hedge_capacity: int,
    margin_available: int,
    required_margin: int,
    hedge_atomic: bool,
) -> ContractResult:
    fill = require_nonnegative(requested_fill, "requested_fill")
    max_inv = require_nonnegative(max_inventory, "max_inventory")
    current = require_int(current_inventory, "current_inventory")
    hedge = require_nonnegative(hedge_capacity, "hedge_capacity")
    margin = require_nonnegative(margin_available, "margin_available")
    needed = require_nonnegative(required_margin, "required_margin")
    if margin < needed:
        raise UltimateMegaError("INSUFFICIENT_MARGIN")
    worst_inventory = abs(current + fill - min(fill, hedge))
    if worst_inventory > max_inv:
        raise UltimateMegaError("HEDGE_NOT_EXECUTABLE")
    return record(
        "plan_jit_fill_and_hedge",
        {
            "fill": fill,
            "hedge": min(fill, hedge),
            "worst_inventory": worst_inventory,
            "atomic": bool(hedge_atomic and hedge >= fill),
            "execution_domain": "ATOMIC" if hedge_atomic and hedge >= fill else "NON_ATOMIC",
        },
    )


def build_unsigned_jit_variant(
    intent: Mapping[str, Any],
    *,
    sdk_program_id: str,
    expected_program_id: str,
    signed_message_qualified: bool,
) -> ContractResult:
    if sdk_program_id != expected_program_id:
        raise UltimateMegaError("SDK_PROGRAM_MISMATCH")
    if intent.get("uses_signed_message") and not signed_message_qualified:
        raise UltimateMegaError("UNQUALIFIED_SIGNED_MESSAGE")
    return record(
        "build_unsigned_jit_variant",
        {
            "intent_hash": stable_hash("jit-intent", intent),
            "program_id": sdk_program_id,
            "unsigned": True,
            "signer_access": False,
            "submission": False,
        },
    )


def score_jit_counterfactual_quality(
    *,
    jit_net: int,
    no_fill_net: int,
    simple_quote_net: int,
    competition_observed: bool,
    markout_complete: bool,
) -> ContractResult:
    if not competition_observed:
        raise UltimateMegaError("COMPETITION_UNOBSERVED")
    if not markout_complete:
        raise UltimateMegaError("MARKOUT_INCOMPLETE")
    jit = require_int(jit_net, "jit_net")
    no_fill = require_int(no_fill_net, "no_fill_net")
    simple = require_int(simple_quote_net, "simple_quote_net")
    return record(
        "score_jit_counterfactual_quality",
        {
            "jit_net": jit,
            "incremental_vs_no_fill": jit - no_fill,
            "incremental_vs_simple": jit - simple,
            "profitability_claim": False,
        },
    )

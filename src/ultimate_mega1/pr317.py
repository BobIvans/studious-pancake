"""PR-317 / NF-966..970: outcome partitions and negative-risk packages."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .core import ContractResult, UltimateMegaError, record, require_nonnegative, require_positive, stable_hash


def normalize_outcome_partition_contract(
    *,
    condition_id: str,
    collateral: str,
    parent_collection: str,
    outcome_count: int,
    rules_hash: str,
) -> ContractResult:
    count = require_positive(outcome_count, "outcome_count")
    if count > 256:
        raise UltimateMegaError("RULES_UNVERIFIED")
    if not condition_id or not collateral or not rules_hash:
        raise UltimateMegaError("RULES_UNVERIFIED")
    return record(
        "normalize_outcome_partition_contract",
        {"condition_id": condition_id, "collateral": collateral, "parent_collection": parent_collection, "outcome_count": count, "rules_hash": rules_hash},
    )


def verify_disjoint_complete_partition(
    *,
    outcome_count: int,
    bitsets: Sequence[int],
    require_complete: bool = True,
) -> ContractResult:
    count = require_positive(outcome_count, "outcome_count")
    universe = (1 << count) - 1
    seen = 0
    for bitset in bitsets:
        value = require_nonnegative(bitset, "bitset")
        if value == 0 or value & ~universe:
            raise UltimateMegaError("MISSING_OUTCOME")
        if seen & value:
            raise UltimateMegaError("OVERLAPPING_PARTITION")
        seen |= value
    complete = seen == universe
    if require_complete and not complete:
        raise UltimateMegaError("MISSING_OUTCOME")
    return record("verify_disjoint_complete_partition", {"union_bits": seen, "universe_bits": universe, "complete": complete})


def derive_negative_risk_payoff_map(
    *,
    outcomes: Sequence[str],
    conversions: Mapping[str, Mapping[str, int]],
    protocol_fee: int = 0,
) -> ContractResult:
    if not outcomes:
        raise UltimateMegaError("UNMODELED_OUTCOME")
    fee = require_nonnegative(protocol_fee, "protocol_fee")
    rows = {}
    for source, payoff in conversions.items():
        missing = [outcome for outcome in outcomes if outcome not in payoff]
        if missing:
            raise UltimateMegaError("UNMODELED_OUTCOME")
        rows[source] = {outcome: int(payoff[outcome]) for outcome in outcomes}
    if not rows:
        raise UltimateMegaError("ADAPTER_UNKNOWN")
    return record("derive_negative_risk_payoff_map", {"outcomes": tuple(outcomes), "payoffs": rows, "protocol_fee": fee})


def price_executable_outcome_package(
    *,
    asks: Mapping[str, tuple[int, int]],
    required_units: Mapping[str, int],
    fees: int = 0,
) -> ContractResult:
    total = require_nonnegative(fees, "fees")
    legs = []
    for instrument, units in required_units.items():
        units = require_nonnegative(units, f"units_{instrument}")
        if instrument not in asks:
            raise UltimateMegaError("BOOK_NOT_EXECUTABLE")
        price, depth = asks[instrument]
        price = require_nonnegative(price, f"price_{instrument}")
        depth = require_nonnegative(depth, f"depth_{instrument}")
        if depth < units:
            raise UltimateMegaError("INCOMPLETE_SET_FILL")
        total += price * units
        legs.append((instrument, units, price))
    return record("price_executable_outcome_package", {"legs": tuple(legs), "total_cost": total})


def emit_outcome_package_witness(
    quote: Mapping[str, Any],
    *,
    resolution_rights_match: bool,
    atomicity_proven: bool,
    downside_states: Mapping[str, int],
) -> ContractResult:
    if not resolution_rights_match:
        raise UltimateMegaError("RESOLUTION_RIGHTS_MISMATCH")
    blockers = () if atomicity_proven else ("ATOMICITY_UNPROVEN",)
    return record(
        "emit_outcome_package_witness",
        {"quote_hash": stable_hash("outcome-package", quote), "downside_states": dict(downside_states), "atomic": atomicity_proven},
        status="OK" if atomicity_proven else "INCOMPLETE",
        blockers=blockers,
    )

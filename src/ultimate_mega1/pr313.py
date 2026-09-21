"""PR-313 / NF-946..950: TWAMM lazy virtual-order replay."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .core import ContractResult, UltimateMegaError, record, require_int, require_nonnegative, require_positive, stable_hash


def load_virtual_order_checkpoint(
    *,
    pool: str,
    last_virtual_block: int,
    sales_rates: Mapping[str, int],
    expirations: Sequence[int],
    active_order_accounting_present: bool,
) -> ContractResult:
    if not active_order_accounting_present:
        raise UltimateMegaError("MISSING_ORDER_STATE")
    return record(
        "load_virtual_order_checkpoint",
        {
            "pool": pool,
            "last_virtual_block": require_nonnegative(last_virtual_block, "last_virtual_block"),
            "sales_rates": {k: require_nonnegative(v, f"rate_{k}") for k, v in sales_rates.items()},
            "expirations": tuple(sorted(require_nonnegative(x, "expiration") for x in expirations)),
        },
    )


def advance_virtual_orders_to_block(
    checkpoint: Mapping[str, Any],
    *,
    target_block: int,
    reserve0: int,
    reserve1: int,
) -> ContractResult:
    last = require_nonnegative(int(checkpoint["last_virtual_block"]), "last_virtual_block")
    target = require_nonnegative(target_block, "target_block")
    if target < last:
        raise UltimateMegaError("TARGET_BEFORE_CHECKPOINT")
    r0 = require_positive(reserve0, "reserve0")
    r1 = require_positive(reserve1, "reserve1")
    rates = checkpoint.get("sales_rates", {})
    rate0 = require_nonnegative(int(rates.get("0", 0)), "rate0")
    rate1 = require_nonnegative(int(rates.get("1", 0)), "rate1")
    blocks = target - last
    sold0 = rate0 * blocks
    sold1 = rate1 * blocks
    # Conservative deterministic approximation: each side's virtual sale is
    # bounded by current opposing reserve, preserving non-negative reserves.
    new0 = max(1, r0 + sold0 - min(sold1, r0 - 1))
    new1 = max(1, r1 + sold1 - min(sold0, r1 - 1))
    return record(
        "advance_virtual_orders_to_block",
        {"target_block": target, "reserve0": new0, "reserve1": new1, "sold0": sold0, "sold1": sold1},
    )


def quote_post_virtual_order_swap(
    *,
    amount_in: int,
    reserve_in: int,
    reserve_out: int,
    fee_ppm: int = 0,
    paused: bool = False,
) -> ContractResult:
    if paused:
        raise UltimateMegaError("PAUSED_POOL")
    amount = require_nonnegative(amount_in, "amount_in")
    rin = require_positive(reserve_in, "reserve_in")
    rout = require_positive(reserve_out, "reserve_out")
    fee = amount * require_nonnegative(fee_ppm, "fee_ppm") // 1_000_000
    effective = max(0, amount - fee)
    out = rout * effective // (rin + effective) if effective else 0
    return record(
        "quote_post_virtual_order_swap",
        {"amount_in": amount, "fee": fee, "amount_out": out, "post_virtual": True},
    )


def assemble_twamm_residual_cycle(
    quote: Mapping[str, Any],
    *,
    callable_path_attested: bool,
    all_outputs_same_transaction: bool,
) -> ContractResult:
    if not callable_path_attested or not all_outputs_same_transaction:
        raise UltimateMegaError("NO_ATTESTED_CALLABLE_PATH")
    return record(
        "assemble_twamm_residual_cycle",
        {"quote_hash": stable_hash("twamm-quote", quote), "atomic": True, "unsigned": True},
    )


def test_lazy_execution_equivalence(
    local_state: Mapping[str, Any],
    vm_state: Mapping[str, Any],
    *,
    deployment_attested: bool,
) -> ContractResult:
    if not deployment_attested:
        raise UltimateMegaError("REFERENCE_ONLY_NO_DEPLOYMENT")
    local_hash = stable_hash("twamm-state", local_state)
    vm_hash = stable_hash("twamm-state", vm_state)
    if local_hash != vm_hash:
        raise UltimateMegaError("VIRTUAL_ORDER_DIVERGENCE")
    return record("test_lazy_execution_equivalence", {"state_hash": local_hash, "equivalent": True})

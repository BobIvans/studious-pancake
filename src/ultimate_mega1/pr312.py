"""PR-312 / NF-941..945: Uniswap-v4 hook-aware accounting contracts."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from .core import ContractResult, UltimateMegaError, record, require_id, require_int, require_nonnegative, stable_hash


def attest_v4_hook_behavior_scope(
    *,
    hook_address: str,
    hook_codehash: str,
    permission_bits: Sequence[str],
    reviewed_callbacks: Sequence[str],
    proxy_or_code_drift: bool = False,
) -> ContractResult:
    require_id(hook_address, "hook_address")
    require_id(hook_codehash, "hook_codehash")
    if proxy_or_code_drift:
        raise UltimateMegaError("PROXY_OR_CODE_DRIFT")
    permissions = tuple(sorted(set(permission_bits)))
    reviewed = tuple(sorted(set(reviewed_callbacks)))
    if set(permissions) - set(reviewed):
        raise UltimateMegaError("UNREVIEWED_HOOK")
    return record(
        "attest_v4_hook_behavior_scope",
        {"hook_address": hook_address, "hook_codehash": hook_codehash, "permissions": permissions, "reviewed_callbacks": reviewed},
    )


def bind_hook_quote_context(
    quote: Mapping[str, Any],
    *,
    caller: str,
    hook_data: bytes | str,
    unlock_order: Sequence[str],
    actual_caller: str,
    actual_hook_data: bytes | str,
    actual_unlock_order: Sequence[str],
) -> ContractResult:
    if caller != actual_caller or hook_data != actual_hook_data or tuple(unlock_order) != tuple(actual_unlock_order):
        raise UltimateMegaError("CONTEXT_MISMATCH")
    return record(
        "bind_hook_quote_context",
        {
            "quote_hash": stable_hash("v4-quote", quote),
            "caller": caller,
            "hook_data_hash": stable_hash("v4-hook-data", str(hook_data)),
            "unlock_order": tuple(unlock_order),
        },
    )


def interpret_hook_currency_deltas(
    deltas: Sequence[Mapping[str, Any]],
) -> ContractResult:
    totals: dict[str, int] = defaultdict(int)
    for row in deltas:
        currency = require_id(str(row.get("currency", "")), "currency")
        amount = require_int(int(row.get("amount", 0)), "amount")
        if row.get("internal_only", False):
            continue
        totals[currency] += amount
    return record("interpret_hook_currency_deltas", {"currency_deltas": dict(sorted(totals.items()))})


def construct_balanced_v4_plan(
    delta_ledger: Mapping[str, int],
    *,
    settlement_steps: Mapping[str, int],
) -> ContractResult:
    remaining = {str(k): require_int(v, f"delta_{k}") for k, v in delta_ledger.items()}
    for currency, amount in settlement_steps.items():
        remaining[str(currency)] = remaining.get(str(currency), 0) + require_int(amount, f"settle_{currency}")
    open_items = {k: v for k, v in remaining.items() if v != 0}
    if open_items:
        raise UltimateMegaError("OPEN_CURRENCY_OBLIGATION")
    return record(
        "construct_balanced_v4_plan",
        {"currencies": tuple(sorted(remaining)), "balanced": True, "unsigned": True},
    )


def replay_hook_adversarial_cases(
    *,
    baseline_codehash: str,
    observed_codehash: str,
    baseline_fee: int,
    adversarial_fee: int,
    callback_accepted: bool,
) -> ContractResult:
    if baseline_codehash != observed_codehash:
        raise UltimateMegaError("POST_QUOTE_HOOK_MUTATION")
    base = require_nonnegative(baseline_fee, "baseline_fee")
    adverse = require_nonnegative(adversarial_fee, "adversarial_fee")
    fail_closed = (not callback_accepted) or adverse != base
    return record(
        "replay_hook_adversarial_cases",
        {"codehash_stable": True, "baseline_fee": base, "adversarial_fee": adverse, "fail_closed_observed": fail_closed},
        status="OK" if fail_closed else "BLOCKED",
        blockers=() if fail_closed else ("ADVERSARIAL_CASE_NOT_REJECTED",),
    )

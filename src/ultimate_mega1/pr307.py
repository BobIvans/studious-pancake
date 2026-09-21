"""PR-307 / NF-916..920: epoch-bound stake-pool conversion qualification."""

from __future__ import annotations

from typing import Any, Mapping

from .core import ContractResult, UltimateMegaError, ppm_fee_ceil, record, require_nonnegative, require_positive, stable_hash


def detect_stake_pool_refresh_boundary(
    *,
    last_update_epoch: int,
    current_epoch: int,
    authority_supported: bool,
) -> ContractResult:
    last_epoch = require_nonnegative(last_update_epoch, "last_update_epoch")
    current = require_nonnegative(current_epoch, "current_epoch")
    if current < last_epoch:
        raise UltimateMegaError("UNTRUSTED_CLOCK")
    stale = last_epoch != current
    blockers = []
    if stale:
        blockers.append("POOL_EPOCH_STALE")
    if not authority_supported:
        blockers.append("AUTHORITY_UNSUPPORTED")
    return record(
        "detect_stake_pool_refresh_boundary",
        {
            "last_update_epoch": last_epoch,
            "current_epoch": current,
            "refresh_required": stale,
            "authority_supported": authority_supported,
        },
        status="BLOCKED" if blockers else "OK",
        blockers=tuple(blockers),
    )


def project_qualified_pool_refresh(
    *,
    total_lamports: int,
    pool_token_supply: int,
    validator_lamports: int | None,
    reserve_lamports: int,
    reward_lamports: int = 0,
) -> ContractResult:
    total = require_nonnegative(total_lamports, "total_lamports")
    supply = require_positive(pool_token_supply, "pool_token_supply")
    reserve = require_nonnegative(reserve_lamports, "reserve_lamports")
    reward = require_nonnegative(reward_lamports, "reward_lamports")
    if validator_lamports is None:
        raise UltimateMegaError("MISSING_VALIDATOR_STATE")
    validators = require_nonnegative(validator_lamports, "validator_lamports")
    refreshed = validators + reserve + reward
    if refreshed < total and reward > 0:
        raise UltimateMegaError("REFRESH_STATE_INCONSISTENT")
    return record(
        "project_qualified_pool_refresh",
        {
            "prior_total_lamports": total,
            "refreshed_total_lamports": refreshed,
            "pool_token_supply": supply,
            "validator_lamports": validators,
            "reserve_lamports": reserve,
            "reward_lamports": reward,
            "scenario_only": True,
        },
    )


def quote_epoch_bound_pool_exit(
    *,
    share_amount: int,
    total_lamports: int,
    pool_token_supply: int,
    reserve_lamports: int,
    withdrawal_fee_ppm: int = 0,
    immediate: bool = True,
) -> ContractResult:
    shares = require_nonnegative(share_amount, "share_amount")
    total = require_nonnegative(total_lamports, "total_lamports")
    supply = require_positive(pool_token_supply, "pool_token_supply")
    reserve = require_nonnegative(reserve_lamports, "reserve_lamports")
    gross = shares * total // supply
    fee = ppm_fee_ceil(gross, withdrawal_fee_ppm)
    net = max(0, gross - fee)
    if immediate and net > reserve:
        raise UltimateMegaError("INSTANT_CAPACITY_SHORTFALL")
    return record(
        "quote_epoch_bound_pool_exit",
        {
            "share_amount": shares,
            "gross_lamports": gross,
            "fee_lamports": fee,
            "net_lamports": net if immediate else 0,
            "delayed_stake_lamports": 0 if immediate else net,
            "immediate": immediate,
        },
    )


def compose_pool_refresh_exit_candidate(
    refresh: Mapping[str, Any],
    exit_quote: Mapping[str, Any],
    *,
    update_permissionless: bool,
    compute_units: int,
    max_compute_units: int,
) -> ContractResult:
    if not update_permissionless:
        raise UltimateMegaError("UPDATE_NOT_PERMISSIONLESS")
    cu = require_positive(compute_units, "compute_units")
    max_cu = require_positive(max_compute_units, "max_compute_units")
    if cu > max_cu:
        raise UltimateMegaError("MESSAGE_TOO_LARGE")
    immediate = bool(exit_quote.get("immediate", False))
    return record(
        "compose_pool_refresh_exit_candidate",
        {
            "refresh_hash": stable_hash("stake-refresh", refresh),
            "exit_hash": stable_hash("stake-exit", exit_quote),
            "compute_units": cu,
            "atomic": immediate,
        },
        status="OK" if immediate else "BLOCKED",
        blockers=() if immediate else ("DELAYED_EXIT_NON_ATOMIC",),
    )


def verify_pool_refresh_edge_survival(
    *,
    pre_refresh_net: int,
    post_refresh_net: int,
    total_cost: int,
) -> ContractResult:
    pre = require_nonnegative(pre_refresh_net, "pre_refresh_net")
    post = require_nonnegative(post_refresh_net, "post_refresh_net")
    cost = require_nonnegative(total_cost, "total_cost")
    residual = post - cost
    if residual <= 0:
        return record(
            "verify_pool_refresh_edge_survival",
            {"pre_refresh_net": pre, "post_refresh_net": post, "cost": cost, "residual": residual},
            status="BLOCKED",
            blockers=("EDGE_DISAPPEARED",),
        )
    return record(
        "verify_pool_refresh_edge_survival",
        {"pre_refresh_net": pre, "post_refresh_net": post, "cost": cost, "residual": residual},
    )

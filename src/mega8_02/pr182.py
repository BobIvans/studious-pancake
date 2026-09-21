"""PR-182 / LST-02: stake-pool deployment and exit capacity registry."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
from .core import (
    EvidenceBinding,
    Mega802Error,
    require_nonnegative_int,
    require_positive_int,
)


@dataclass(frozen=True, slots=True)
class StakePool:
    pool_id: str
    lst_asset: str
    exchange_numerator: int
    exchange_denominator: int
    instant_exit_capacity: int
    delayed_exit_capacity: int
    evidence: EvidenceBinding


def discover_stake_pool_deployments(
    pools: Sequence[StakePool], *, now: int
) -> tuple[StakePool, ...]:
    for pool in pools:
        pool.evidence.assert_usable(now=now)
    return tuple(sorted(pools, key=lambda item: item.pool_id))


def read_stake_pool_exchange_rate(pool: StakePool, *, now: int) -> tuple[int, int]:
    pool.evidence.assert_usable(now=now)
    require_positive_int(pool.exchange_numerator, "exchange_numerator")
    require_positive_int(pool.exchange_denominator, "exchange_denominator")
    return pool.exchange_numerator, pool.exchange_denominator


def model_exit_queue_capacity(pool: StakePool, *, immediate_required: bool) -> int:
    capacity = (
        pool.instant_exit_capacity
        if immediate_required
        else pool.instant_exit_capacity + pool.delayed_exit_capacity
    )
    return require_nonnegative_int(capacity, "capacity")


def rank_lender_independent_lst_edges(
    pools: Sequence[StakePool],
) -> tuple[str, ...]:
    eligible = [pool for pool in pools if pool.instant_exit_capacity > 0]
    return tuple(
        pool.pool_id
        for pool in sorted(
            eligible, key=lambda item: (-item.instant_exit_capacity, item.pool_id)
        )
    )

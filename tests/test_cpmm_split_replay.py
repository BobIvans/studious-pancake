from dataclasses import replace
import pytest

from tests.test_exact_cpmm_capacity import _three_hop_plan, NOW
from src.strategy.arbitrage_graph import VenueIdentity
from src.strategy.cpmm_split_replay import ExactCpmmSplitPath, shared_cpmm_state


def paths():
    first = _three_hop_plan()
    second = replace(
        first,
        pools=(
            first.pools[0],
            *(
                replace(
                    pool,
                    venue=VenueIdentity(
                        pool.venue.program_id, pool.venue.market_id + "-other"
                    ),
                )
                for pool in first.pools[1:]
            ),
        ),
    )
    return tuple(ExactCpmmSplitPath(plan, NOW, 100, 100) for plan in (first, second))


def test_shared_pool_is_repriced_after_first_branch_and_replay_is_immutable():
    a, b = paths()
    initial = shared_cpmm_state((a.plan, b.plan))
    first = a.evaluate(20, initial)
    second = b.evaluate(20, first.next_state)
    independent = b.evaluate(20, initial)
    assert second.output_units != independent.output_units
    assert initial == shared_cpmm_state((a.plan, b.plan))
    assert a.evaluate(20, initial) == first
    assert b.evaluate(20, first.next_state) == second
    reverse = a.evaluate(20, independent.next_state)
    assert reverse.next_state != second.next_state


def test_conflicting_alias_generation_and_stale_frames_fail_closed():
    a, b = paths()
    corrupted = replace(
        b.plan, pools=(replace(b.plan.pools[0], reserve_a=999), *b.plan.pools[1:])
    )
    with pytest.raises(ValueError, match="aliased"):
        shared_cpmm_state((a.plan, corrupted))
    initial = shared_cpmm_state((a.plan, b.plan))
    with pytest.raises(ValueError, match="generation"):
        a.evaluate(20, replace(initial, generation="other"))
    with pytest.raises(ValueError, match="stale"):
        replace(a, now=NOW + 10).evaluate(20, initial)


def test_joint_solver_matches_independent_integer_shared_reserve_oracle():
    from itertools import permutations, product
    from src.economics.split_flow import (
        solve_joint_split_flow,
        SplitLimits,
        SplitStopReason,
    )

    a, b = paths()
    initial = shared_cpmm_state((a.plan, b.plan))
    best = 0
    for allocations in product((0, 10, 20), repeat=2):
        if not 0 < sum(allocations) <= 20:
            continue
        for order in permutations(tuple(i for i, q in enumerate(allocations) if q)):
            reserves = {
                pool.venue: (pool.reserve_a, pool.reserve_b)
                for path in (a, b)
                for pool in path.plan.pools
            }
            output = 0
            valid = True
            for index in order:
                path = (a, b)[index]
                amount = allocations[index]
                asset = path.plan.settlement_asset
                for pool in path.plan.pools:
                    ra, rb = reserves[pool.venue]
                    rin, rout = (ra, rb) if asset == pool.asset_a else (rb, ra)
                    fee = (amount * pool.fee_bps + 9999) // 10000
                    swap = amount - fee
                    quoted = swap * rout // (rin + swap)
                    if quoted <= 0:
                        valid = False
                        break
                    if asset == pool.asset_a:
                        reserves[pool.venue] = (ra + amount, rb - quoted)
                        asset = pool.asset_b
                    else:
                        reserves[pool.venue] = (ra - quoted, rb + amount)
                        asset = pool.asset_a
                    amount = quoted
                output += amount
            if valid:
                best = max(best, output - sum(allocations))
    result = solve_joint_split_flow(
        (a, b),
        total_capital_units=20,
        allocation_step_units=10,
        initial_state=initial,
        limits=SplitLimits(1000, 1000, 1, 100, 2),
    )
    assert result.stop_reason is SplitStopReason.COMPLETE
    assert result.selected.conservative_net_units == best
    assert result.selected.selected_is_split

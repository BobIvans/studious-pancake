"""SX-12 — deterministic portfolio selection over shared strategy resources."""

from __future__ import annotations

import pytest

from src.research.pr356_allocation import (
    solve_opportunity_portfolio,
    verify_portfolio_feasibility,
)
from src.strategy.conflict_scheduler import WorkResourceSet
from src.strategy.portfolio_optimizer import (
    PortfolioCandidate,
    PortfolioCandidateError,
    SelectionMode,
    build_pr356_problem_from_candidates,
    optimize_portfolio,
)
from src.strategy.strategy_contract import ResourceManifest, SharedResourceCost


def _manifest(
    consumed: tuple[str, ...] = (),
    exclusive: tuple[str, ...] = (),
    read: tuple[str, ...] = (),
    shared_costs: tuple[SharedResourceCost, ...] = (),
) -> ResourceManifest:
    return ResourceManifest(
        read_resources=read,
        consumed_resources=consumed,
        exclusive_resources=exclusive,
        shared_costs=shared_costs,
    )


def _candidate(
    candidate_id: str,
    net: int,
    *,
    consumed: tuple[str, ...] = (),
    exclusive: tuple[str, ...] = (),
    read: tuple[str, ...] = (),
    shared_costs: tuple[SharedResourceCost, ...] = (),
    probability: float | None = None,
) -> PortfolioCandidate:
    return PortfolioCandidate(
        candidate_id=candidate_id,
        strategy_id=f"strategy-{candidate_id}",
        conservative_net_units=net,
        manifest=_manifest(consumed, exclusive, read, shared_costs),
        fill_probability=probability,
    )


def test_requires_a_resource_source() -> None:
    with pytest.raises(PortfolioCandidateError):
        PortfolioCandidate(
            candidate_id="c1", strategy_id="s1", conservative_net_units=10
        )


def test_probability_bounds_fail_closed() -> None:
    with pytest.raises(PortfolioCandidateError):
        _candidate("c1", 10, probability=0.0)
    with pytest.raises(PortfolioCandidateError):
        _candidate("c1", 10, probability=1.5)


def test_below_min_net_rejected_typed() -> None:
    selection = optimize_portfolio(
        [_candidate("c1", 5), _candidate("c2", -3)], min_net_units=0
    )
    outcome = {o.candidate_id: o for o in selection.outcomes}
    assert outcome["c1"].selected is True
    assert outcome["c2"].selected is False
    assert outcome["c2"].reason == "below_min_net"


def test_shared_pool_never_consumed_twice() -> None:
    selection = optimize_portfolio(
        [
            _candidate("c-high", 100, consumed=("pool-A",)),
            _candidate("c-low", 40, consumed=("pool-A",)),
        ]
    )
    # The selected set is always conflict-free; without shared-cost overlap
    # the joint label is rejected and the conflict-free set is returned.
    assert selection.mode is SelectionMode.INDEPENDENT_EXECUTION
    assert selection.selected_ids == ("c-high",)
    assert selection.total_conservative_net_units == 100
    outcome = {o.candidate_id: o for o in selection.outcomes}
    assert outcome["c-low"].selected is False
    assert outcome["c-low"].reason == "conflict_with:c-high"


def test_exclusive_resource_blocks_joint_selection() -> None:
    selection = optimize_portfolio(
        [
            _candidate("c1", 50, exclusive=("nonce-1",)),
            _candidate("c2", 30, exclusive=("nonce-1",)),
        ]
    )
    assert selection.selected_ids == ("c1",)
    outcome = {o.candidate_id: o for o in selection.outcomes}
    assert outcome["c2"].reason == "conflict_with:c1"


def test_read_only_resources_do_not_conflict() -> None:
    selection = optimize_portfolio(
        [
            _candidate("c1", 50, consumed=("pool-A",), read=("oracle-1",)),
            _candidate("c2", 30, consumed=("pool-B",), read=("oracle-1",)),
        ]
    )
    assert selection.selected_ids == ("c1", "c2")
    assert all(o.selected for o in selection.outcomes)


def test_work_resource_set_conflicts_use_agg05_semantics() -> None:
    left = PortfolioCandidate(
        candidate_id="l",
        strategy_id="s",
        conservative_net_units=60,
        work_resource_set=WorkResourceSet(pools=("pool-X",)),
    )
    right = PortfolioCandidate(
        candidate_id="r",
        strategy_id="s",
        conservative_net_units=70,
        work_resource_set=WorkResourceSet(readonly_accounts=("pool-X",)),
    )
    selection = optimize_portfolio([left, right])
    assert selection.selected_ids == ("r",)
    outcome = {o.candidate_id: o for o in selection.outcomes}
    assert outcome["l"].reason == "conflict_with:r"


def test_shared_fixed_cost_applied_once_in_joint_total() -> None:
    selection = optimize_portfolio(
        [
            _candidate(
                "c1",
                100,
                consumed=("pool-A",),
                shared_costs=(
                    SharedResourceCost(resource_id="rent", amount=50, unit="lamports"),
                ),
            ),
            _candidate(
                "c2",
                80,
                consumed=("pool-B",),
                shared_costs=(
                    SharedResourceCost(resource_id="rent", amount=50, unit="lamports"),
                ),
            ),
        ]
    )
    assert selection.mode is SelectionMode.JOINT_SELECTION
    assert selection.selected_ids == ("c1", "c2")
    assert selection.independent_baseline_net_units == 180
    assert selection.shared_cost_savings_units == 50
    assert selection.total_conservative_net_units == 130


def test_unknown_shared_cost_stays_none_and_flagged() -> None:
    selection = optimize_portfolio(
        [
            _candidate(
                "c1",
                100,
                consumed=("pool-A",),
                shared_costs=(SharedResourceCost(resource_id="rent"),),
            ),
            _candidate("c2", 80, consumed=("pool-B",)),
        ]
    )
    assert selection.unknown_shared_cost_resource_ids == ("rent",)
    assert selection.shared_cost_savings_units == 0
    assert selection.total_conservative_net_units == 180


def test_joint_not_better_rejected_with_independent_fallback() -> None:
    selection = optimize_portfolio(
        [
            _candidate("c1", 100, consumed=("pool-A",)),
            _candidate("c2", 80, consumed=("pool-B",)),
        ]
    )
    assert selection.mode is SelectionMode.INDEPENDENT_EXECUTION
    assert "joint_not_better_than_independent" in selection.typed_rejections
    assert selection.selected_ids == ("c1", "c2")
    assert selection.total_conservative_net_units == 180
    assert selection.shared_cost_savings_units == 0


def test_single_best_baseline_reported() -> None:
    selection = optimize_portfolio(
        [
            _candidate("c1", 40, consumed=("pool-A",)),
            _candidate("c2", 70, consumed=("pool-B",)),
            _candidate("c3", 55, consumed=("pool-C",)),
        ]
    )
    assert selection.single_best_net_units == 70
    assert selection.independent_baseline_net_units == 165


def test_expected_value_requires_calibrated_probabilities() -> None:
    uncalibrated = optimize_portfolio([_candidate("c1", 100, probability=None)])
    assert uncalibrated.total_expected_net_units is None
    assert "expected_value_uncalibrated_probability" in uncalibrated.typed_rejections

    calibrated = optimize_portfolio(
        [
            _candidate("c1", 100, consumed=("pool-A",), probability=0.5),
            _candidate("c2", 80, consumed=("pool-B",), probability=0.25),
        ]
    )
    assert calibrated.mode is SelectionMode.INDEPENDENT_EXECUTION
    assert calibrated.total_expected_net_units == pytest.approx(70.0)


def test_joint_beats_independent_via_shared_savings() -> None:
    shared = (SharedResourceCost(resource_id="blockspace", amount=30, unit="cu"),)
    selection = optimize_portfolio(
        [
            _candidate("c1", 100, consumed=("pool-A",), shared_costs=shared),
            _candidate("c2", 60, consumed=("pool-B",), shared_costs=shared),
        ]
    )
    assert selection.mode is SelectionMode.JOINT_SELECTION
    assert selection.total_conservative_net_units == 130
    assert selection.shared_cost_savings_units == 30


def test_budget_exhaustion_is_typed_not_silent() -> None:
    candidates = [
        _candidate(f"c{index:02d}", 10 + index, consumed=(f"pool-{index}",))
        for index in range(8)
    ]
    selection = optimize_portfolio(candidates, max_explored_nodes=5)
    assert "search_budget_exhausted" in selection.typed_rejections
    assert selection.budget_exhausted is True


def test_exhaustive_cross_check_beats_greedy() -> None:
    # Greedy takes c1 (net 100); the exhaustive cross-check finds the
    # compatible pair c2+c3 whose total exceeds c1 alone.
    selection = optimize_portfolio(
        [
            _candidate("c1", 100, consumed=("pool-A", "pool-B")),
            _candidate("c2", 70, consumed=("pool-A",)),
            _candidate("c3", 60, consumed=("pool-B",)),
        ]
    )
    assert selection.selected_ids == ("c2", "c3")
    assert selection.total_conservative_net_units == 130
    outcome = {o.candidate_id: o for o in selection.outcomes}
    assert outcome["c1"].reason == "not_selected_in_best_subset"


def test_worker_determinism_1_2_4_8() -> None:
    candidates = [
        _candidate(
            f"c{index:02d}",
            100 - 7 * index,
            consumed=(f"pool-{index}", f"shared-{index % 3}"),
            exclusive=(f"lock-{index % 2}",),
            read=(f"oracle-{index}",),
        )
        for index in range(8)
    ]
    hashes = set()
    for workers in (1, 2, 4, 8):
        selection = optimize_portfolio(candidates, workers=workers)
        hashes.add(selection.determinism_hash)
        # c02..c07 each conflict with c00/c01 on lock or shared pool id.
        assert selection.selected_ids == ("c00", "c01")
        assert selection.total_conservative_net_units == 193
    assert len(hashes) == 1


def test_input_order_cannot_change_selection() -> None:
    candidates = [
        _candidate("c1", 100, consumed=("pool-A",)),
        _candidate("c2", 80, consumed=("pool-B",)),
        _candidate("c3", 60, consumed=("pool-C",)),
    ]
    forward = optimize_portfolio(candidates)
    backward = optimize_portfolio(list(reversed(candidates)))
    assert forward.determinism_hash == backward.determinism_hash


def test_duplicate_candidate_id_rejected() -> None:
    with pytest.raises(PortfolioCandidateError):
        optimize_portfolio([_candidate("c1", 10), _candidate("c1", 12)])


def test_pr356_interop_reverifies_selection_through_existing_owner() -> None:
    candidates = [
        _candidate("c1", 100, consumed=("pool-A",)),
        _candidate("c2", 80, consumed=("pool-B",)),
        _candidate("c3", 60, consumed=("pool-A",)),
    ]
    problem = build_pr356_problem_from_candidates(
        candidates,
        budget={"capital_units": 1000},
        capital_usage={
            "c1": {"capital_units": 500},
            "c2": {"capital_units": 400},
            "c3": {"capital_units": 300},
        },
    )
    proposal = solve_opportunity_portfolio(problem)
    # PR-356 owns the capital dimension; c1+c2 dominate c3 (conflicts with c1).
    assert set(proposal.candidate_ids) == {"c1", "c2"}
    verification = verify_portfolio_feasibility(proposal, problem)
    assert verification["feasible"] is True
    sx_selection = optimize_portfolio(candidates)
    assert set(sx_selection.selected_ids) == {"c1", "c2"}


def test_pr356_interop_rejects_usage_missing_budget_dimension() -> None:
    with pytest.raises(PortfolioCandidateError):
        build_pr356_problem_from_candidates(
            [_candidate("c1", 10)],
            budget={"capital_units": 100},
            capital_usage={"c1": {"unknown_dimension": 5}},
        )

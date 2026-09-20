from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.economics.split_flow import (
    PathExecution,
    SharedExecutionState,
    SplitLimits,
    SplitStopReason,
    promote_split_candidate,
    solve_joint_split_flow,
)


@dataclass(frozen=True)
class CapacityPath:
    path_id: str
    resource: str
    profit_bps: int
    fixed_cost: int = 0
    debt: int = 0

    def evaluate(self, amount_units, state):
        if amount_units > state.capacity(self.resource):
            return None
        next_state = state.consume(self.resource, amount_units)
        output = amount_units + (amount_units * self.profit_bps) // 10_000
        return PathExecution(
            path_id=self.path_id,
            input_units=amount_units,
            output_units=output,
            next_state=next_state,
            compute_units=10,
            message_bytes=100,
            explicit_cost_units=self.fixed_cost,
            residual_debt_units=self.debt,
        )


def _limits(max_evaluations: int = 10_000) -> SplitLimits:
    return SplitLimits(
        max_compute_units=1_000,
        max_message_bytes=10_000,
        max_explicit_cost_units=1_000,
        max_evaluations=max_evaluations,
    )


def test_shared_pool_capacity_is_not_granted_to_two_paths_twice() -> None:
    state = SharedExecutionState("frame-1", (("pool", 100),))
    paths = (
        CapacityPath("a", "pool", 1_000),
        CapacityPath("b", "pool", 900),
    )
    result = solve_joint_split_flow(
        paths,
        total_capital_units=150,
        allocation_step_units=50,
        initial_state=state,
        limits=_limits(),
    )
    assert result.selected is not None
    assert result.selected.total_input_units <= 100
    assert result.selected.final_state.capacity("pool") >= 0


def test_split_can_beat_single_path_when_resources_are_independent() -> None:
    state = SharedExecutionState(
        "frame-1",
        (("pool-a", 50), ("pool-b", 50)),
    )
    paths = (
        CapacityPath("a", "pool-a", 1_000),
        CapacityPath("b", "pool-b", 900),
    )
    result = solve_joint_split_flow(
        paths,
        total_capital_units=100,
        allocation_step_units=50,
        initial_state=state,
        limits=_limits(),
    )
    selected = promote_split_candidate(result)
    assert selected.selected_is_split is True
    assert selected.total_input_units == 100
    assert selected.conservative_net_units > (result.best_single_path_net_units or 0)


def test_residual_debt_blocks_allocation() -> None:
    state = SharedExecutionState("frame-1", (("pool", 100),))
    result = solve_joint_split_flow(
        (CapacityPath("a", "pool", 1_000, debt=1),),
        total_capital_units=100,
        allocation_step_units=50,
        initial_state=state,
        limits=_limits(),
    )
    assert result.selected is None
    assert result.rejected_residual_debt > 0


def test_search_budget_exhaustion_never_claims_global_optimum() -> None:
    state = SharedExecutionState(
        "frame-1",
        (("a", 100), ("b", 100)),
    )
    result = solve_joint_split_flow(
        (
            CapacityPath("a", "a", 1_000),
            CapacityPath("b", "b", 1_000),
        ),
        total_capital_units=100,
        allocation_step_units=10,
        initial_state=state,
        limits=_limits(max_evaluations=2),
    )
    assert result.stop_reason is SplitStopReason.BUDGET_EXHAUSTED
    assert result.claims_global_optimum is False


def test_resource_limit_rejection_is_explicit() -> None:
    state = SharedExecutionState("frame-1", (("pool", 100),))
    limits = SplitLimits(
        max_compute_units=5,
        max_message_bytes=10_000,
        max_explicit_cost_units=1_000,
        max_evaluations=100,
    )
    result = solve_joint_split_flow(
        (CapacityPath("a", "pool", 1_000),),
        total_capital_units=100,
        allocation_step_units=50,
        initial_state=state,
        limits=limits,
    )
    assert result.selected is None
    assert result.rejected_resource_limits > 0


def test_promote_requires_real_split_and_nondominated_result() -> None:
    state = SharedExecutionState("frame-1", (("pool", 100),))
    result = solve_joint_split_flow(
        (CapacityPath("a", "pool", 1_000),),
        total_capital_units=100,
        allocation_step_units=50,
        initial_state=state,
        limits=_limits(),
    )
    with pytest.raises(ValueError):
        promote_split_candidate(result)


def test_promote_rejects_budget_exhausted_search() -> None:
    state = SharedExecutionState(
        "frame-1",
        (("a", 100), ("b", 100)),
    )
    result = solve_joint_split_flow(
        (
            CapacityPath("a", "a", 1_000),
            CapacityPath("b", "b", 1_000),
        ),
        total_capital_units=100,
        allocation_step_units=10,
        initial_state=state,
        limits=_limits(max_evaluations=2),
    )
    assert result.stop_reason is SplitStopReason.BUDGET_EXHAUSTED
    with pytest.raises(ValueError):
        promote_split_candidate(result)

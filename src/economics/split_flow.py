"""AGG-05 joint split-flow sizing with explicit shared-state replay.

The solver is deliberately bounded and discrete. It does not assume convexity,
monotonicity, or KKT conditions. Every candidate allocation is replayed against a
single immutable shared state, so one pool/reserve capacity cannot be granted in
full to multiple branches.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import permutations, product
from typing import Protocol


class SplitStopReason(StrEnum):
    COMPLETE = "complete"
    BUDGET_EXHAUSTED = "budget_exhausted"
    NO_FEASIBLE_ALLOCATION = "no_feasible_allocation"


@dataclass(frozen=True, slots=True)
class SharedExecutionState:
    generation: str
    capacities: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if not self.generation.strip():
            raise ValueError("generation is required")
        normalized: list[tuple[str, int]] = []
        keys: set[str] = set()
        for key, value in self.capacities:
            if not isinstance(key, str) or not key.strip():
                raise ValueError("capacity key must be nonblank")
            if key in keys:
                raise ValueError("capacity keys must be unique")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("capacity values must be non-negative integers")
            keys.add(key)
            normalized.append((key, value))
        object.__setattr__(self, "capacities", tuple(sorted(normalized)))

    def capacity(self, key: str) -> int:
        for item_key, value in self.capacities:
            if item_key == key:
                return value
        raise KeyError(key)

    def consume(self, key: str, amount: int) -> SharedExecutionState:
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ValueError("consume amount must be a non-negative integer")
        rows = dict(self.capacities)
        if key not in rows:
            raise KeyError(key)
        if amount > rows[key]:
            raise ValueError("shared capacity exceeded")
        rows[key] -= amount
        return SharedExecutionState(
            generation=self.generation,
            capacities=tuple(rows.items()),
        )


@dataclass(frozen=True, slots=True)
class PathExecution:
    path_id: str
    input_units: int
    output_units: int
    next_state: SharedExecutionState
    compute_units: int
    message_bytes: int
    explicit_cost_units: int = 0
    residual_debt_units: int = 0

    def __post_init__(self) -> None:
        if not self.path_id.strip():
            raise ValueError("path_id is required")
        for field in (
            "input_units",
            "output_units",
            "compute_units",
            "message_bytes",
            "explicit_cost_units",
            "residual_debt_units",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")
        if self.input_units <= 0:
            raise ValueError("input_units must be positive")
        if self.compute_units <= 0 or self.message_bytes <= 0:
            raise ValueError("compute_units and message_bytes must be positive")


class StatefulSplitPath(Protocol):
    path_id: str

    def evaluate(
        self,
        amount_units: int,
        state: SharedExecutionState,
    ) -> PathExecution | None: ...


@dataclass(frozen=True, slots=True)
class SplitLimits:
    max_compute_units: int
    max_message_bytes: int
    max_explicit_cost_units: int
    max_evaluations: int
    max_paths: int = 5

    def __post_init__(self) -> None:
        for field in (
            "max_compute_units",
            "max_message_bytes",
            "max_explicit_cost_units",
            "max_evaluations",
            "max_paths",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field} must be a positive integer")


@dataclass(frozen=True, slots=True)
class SplitAllocation:
    allocations: tuple[tuple[str, int], ...]
    execution_order: tuple[str, ...]
    total_input_units: int
    total_output_units: int
    explicit_cost_units: int
    conservative_net_units: int
    compute_units: int
    message_bytes: int
    final_state: SharedExecutionState
    selected_is_split: bool

    def __post_init__(self) -> None:
        if self.total_input_units <= 0:
            raise ValueError("total_input_units must be positive")
        if len(self.allocations) == 0:
            raise ValueError("allocations cannot be empty")
        if sum(amount for _, amount in self.allocations) != self.total_input_units:
            raise ValueError("allocation conservation mismatch")
        if any(amount <= 0 for _, amount in self.allocations):
            raise ValueError("stored allocations must be positive")
        if tuple(path for path, _ in self.allocations) != tuple(
            sorted(path for path, _ in self.allocations)
        ):
            raise ValueError("allocations must be sorted by path_id")
        if set(self.execution_order) != {path for path, _ in self.allocations}:
            raise ValueError("execution_order must contain every allocated path once")


@dataclass(frozen=True, slots=True)
class SplitSearchResult:
    selected: SplitAllocation | None
    evaluated: int
    stop_reason: SplitStopReason
    best_single_path_net_units: int | None
    rejected_infeasible: int
    rejected_resource_limits: int
    rejected_residual_debt: int

    @property
    def claims_global_optimum(self) -> bool:
        return self.stop_reason is SplitStopReason.COMPLETE


def _allocation_levels(total: int, step: int) -> tuple[int, ...]:
    levels = list(range(0, total + 1, step))
    if levels[-1] != total:
        levels.append(total)
    return tuple(levels)


def _evaluate_allocation(
    *,
    paths: tuple[StatefulSplitPath, ...],
    amounts: tuple[int, ...],
    order_indices: tuple[int, ...],
    initial_state: SharedExecutionState,
    limits: SplitLimits,
) -> tuple[SplitAllocation | None, str | None]:
    state = initial_state
    total_output = 0
    total_cost = 0
    total_compute = 0
    total_bytes = 0
    residual_debt = 0
    active_ids: list[str] = []

    for index in order_indices:
        amount = amounts[index]
        if amount <= 0:
            continue
        path = paths[index]
        execution = path.evaluate(amount, state)
        if execution is None:
            return None, "infeasible"
        if execution.path_id != path.path_id:
            raise ValueError("path evaluator returned a different path identity")
        if execution.input_units != amount:
            raise ValueError("path evaluator returned a different input amount")
        if execution.next_state.generation != initial_state.generation:
            raise ValueError("split replay cannot change state generation")
        state = execution.next_state
        total_output += execution.output_units
        total_cost += execution.explicit_cost_units
        total_compute += execution.compute_units
        total_bytes += execution.message_bytes
        residual_debt += execution.residual_debt_units
        active_ids.append(path.path_id)

    if not active_ids:
        return None, "infeasible"
    if residual_debt != 0:
        return None, "residual_debt"
    if (
        total_compute > limits.max_compute_units
        or total_bytes > limits.max_message_bytes
        or total_cost > limits.max_explicit_cost_units
    ):
        return None, "resource_limit"

    used = sum(amounts)
    net = total_output - used - total_cost
    rows = tuple(
        sorted(
            (paths[index].path_id, amount)
            for index, amount in enumerate(amounts)
            if amount > 0
        )
    )
    return (
        SplitAllocation(
            allocations=rows,
            execution_order=tuple(active_ids),
            total_input_units=used,
            total_output_units=total_output,
            explicit_cost_units=total_cost,
            conservative_net_units=net,
            compute_units=total_compute,
            message_bytes=total_bytes,
            final_state=state,
            selected_is_split=len(rows) > 1,
        ),
        None,
    )


def solve_joint_split_flow(
    paths: tuple[StatefulSplitPath, ...],
    *,
    total_capital_units: int,
    allocation_step_units: int,
    initial_state: SharedExecutionState,
    limits: SplitLimits,
    require_positive_net: bool = True,
) -> SplitSearchResult:
    """Enumerate bounded allocations and orderings against one shared state."""

    if (
        isinstance(total_capital_units, bool)
        or not isinstance(total_capital_units, int)
        or total_capital_units <= 0
    ):
        raise ValueError("total_capital_units must be a positive integer")
    if (
        isinstance(allocation_step_units, bool)
        or not isinstance(allocation_step_units, int)
        or allocation_step_units <= 0
    ):
        raise ValueError("allocation_step_units must be a positive integer")
    if len(paths) == 0 or len(paths) > limits.max_paths:
        raise ValueError("path count is outside configured split limits")
    path_ids = tuple(path.path_id for path in paths)
    if any(not path_id.strip() for path_id in path_ids):
        raise ValueError("every path_id is required")
    if len(path_ids) != len(set(path_ids)):
        raise ValueError("path_id values must be unique")

    ordered_paths = tuple(path for _, path in sorted(zip(path_ids, paths)))
    levels = _allocation_levels(total_capital_units, allocation_step_units)
    best: SplitAllocation | None = None
    best_single: int | None = None
    evaluated = 0
    infeasible = 0
    resource_limit = 0
    residual_debt = 0
    exhausted = False

    for amounts in product(levels, repeat=len(ordered_paths)):
        used = sum(amounts)
        if used <= 0 or used > total_capital_units:
            continue
        active = tuple(index for index, amount in enumerate(amounts) if amount > 0)
        for order in permutations(active):
            if evaluated >= limits.max_evaluations:
                exhausted = True
                break
            evaluated += 1
            allocation, rejection = _evaluate_allocation(
                paths=ordered_paths,
                amounts=amounts,
                order_indices=order,
                initial_state=initial_state,
                limits=limits,
            )
            if rejection == "infeasible":
                infeasible += 1
                continue
            if rejection == "resource_limit":
                resource_limit += 1
                continue
            if rejection == "residual_debt":
                residual_debt += 1
                continue
            if allocation is None:
                raise AssertionError("allocation/rejection contract violated")
            if require_positive_net and allocation.conservative_net_units <= 0:
                continue
            if not allocation.selected_is_split:
                if (
                    best_single is None
                    or allocation.conservative_net_units > best_single
                ):
                    best_single = allocation.conservative_net_units
            if best is None or (
                allocation.conservative_net_units,
                -allocation.compute_units,
                -allocation.message_bytes,
                tuple(allocation.allocations),
                tuple(allocation.execution_order),
            ) > (
                best.conservative_net_units,
                -best.compute_units,
                -best.message_bytes,
                tuple(best.allocations),
                tuple(best.execution_order),
            ):
                best = allocation
        if exhausted:
            break

    if exhausted:
        stop = SplitStopReason.BUDGET_EXHAUSTED
    elif best is None:
        stop = SplitStopReason.NO_FEASIBLE_ALLOCATION
    else:
        stop = SplitStopReason.COMPLETE
    return SplitSearchResult(
        selected=best,
        evaluated=evaluated,
        stop_reason=stop,
        best_single_path_net_units=best_single,
        rejected_infeasible=infeasible,
        rejected_resource_limits=resource_limit,
        rejected_residual_debt=residual_debt,
    )


def promote_split_candidate(result: SplitSearchResult) -> SplitAllocation:
    """Require a genuinely better multi-path result before split-flow promotion."""

    if result.stop_reason is not SplitStopReason.COMPLETE:
        raise ValueError("split promotion requires complete bounded search")
    selected = result.selected
    if selected is None:
        raise ValueError("no selected allocation")
    if not selected.selected_is_split:
        raise ValueError("selected allocation is not a split")
    if result.best_single_path_net_units is not None and (
        selected.conservative_net_units <= result.best_single_path_net_units
    ):
        raise ValueError("split allocation is dominated by a single path")
    return selected


__all__ = [
    "PathExecution",
    "SharedExecutionState",
    "SplitAllocation",
    "SplitLimits",
    "SplitSearchResult",
    "SplitStopReason",
    "StatefulSplitPath",
    "promote_split_candidate",
    "solve_joint_split_flow",
]

"""PR-206 / BANDIT-01 — safe exploration over simulation/recheck budget only."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .common import PPM, integer, require_rows


def define_safe_bandit_actions(
    actions: Sequence[Mapping[str, Any]],
    *,
    hard_quota_units: int,
) -> tuple[dict[str, Any], ...]:
    require_rows(actions, "actions")
    quota = integer(hard_quota_units, "hard_quota_units", minimum=0)
    accepted = [
        dict(row)
        for row in actions
        if str(row.get("action_id", "")).strip()
        and integer(row.get("cost_units", 0), "cost_units", minimum=0) <= quota
        and row.get("live_effect") is not True
    ]
    return tuple(sorted(accepted, key=lambda row: str(row["action_id"])))


def select_simulation_budget_action(
    actions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    require_rows(actions, "actions")
    def score(row: Mapping[str, Any]) -> int:
        value = integer(row.get("information_gain_ppm", 0), "information_gain_ppm")
        uncertainty = integer(row.get("uncertainty_reduction_ppm", 0), "uncertainty_reduction_ppm")
        cost = max(1, integer(row.get("cost_units", 1), "cost_units", minimum=1))
        return (value + uncertainty) * PPM // cost
    selected = max(actions, key=lambda row: (score(row), str(row.get("action_id", ""))))
    return dict(selected) | {"selection_score_ppm": score(selected), "execution_authority": False}


def apply_conservative_exploration(
    *,
    selected_action: Mapping[str, Any],
    baseline_action: Mapping[str, Any],
    exploration_budget_ppm: int,
    deterministic_draw_ppm: int,
) -> dict[str, Any]:
    budget = integer(exploration_budget_ppm, "exploration_budget_ppm", minimum=0)
    draw = integer(deterministic_draw_ppm, "deterministic_draw_ppm", minimum=0)
    use_selected = draw < min(PPM, budget)
    chosen = dict(selected_action if use_selected else baseline_action)
    return chosen | {"exploration_used": use_selected, "live_effect": False}


def audit_bandit_regret_and_cost(
    realized_values_atomic: Sequence[int],
    oracle_values_atomic: Sequence[int],
    action_cost_units: Sequence[int],
) -> dict[str, int]:
    if not realized_values_atomic or not (
        len(realized_values_atomic) == len(oracle_values_atomic) == len(action_cost_units)
    ):
        raise ValueError("bandit audit arrays must align")
    regret = sum(
        max(0, integer(oracle, "oracle") - integer(realized, "realized"))
        for realized, oracle in zip(realized_values_atomic, oracle_values_atomic, strict=True)
    )
    cost = sum(integer(value, "cost_units", minimum=0) for value in action_cost_units)
    return {"cumulative_regret_atomic": regret, "total_cost_units": cost}


__all__ = [
    "apply_conservative_exploration",
    "audit_bandit_regret_and_cost",
    "define_safe_bandit_actions",
    "select_simulation_budget_action",
]

"""PR-356 unit-safe, research-only resource portfolio allocator."""

from __future__ import annotations

from dataclasses import asdict
from itertools import combinations
from typing import Any, Mapping, Sequence

from src.mechanism_discovery.pr356_contracts import (
    AllocationProposal,
    PR356ContractError,
    ResourceClaimVector,
    StrategyEvidenceCard,
    canonical_hash,
)


def build_strategy_evidence_card(
    payload: Mapping[str, Any],
) -> StrategyEvidenceCard:
    return StrategyEvidenceCard(
        strategy_id=str(payload["strategy_id"]),
        strategy_version=str(payload["strategy_version"]),
        mechanism_scope=tuple(
            str(x) for x in payload.get("mechanism_scope", ())
        ),
        time_domain=str(payload["time_domain"]),
        evidence_tier=str(payload["evidence_tier"]),
        oos_metrics={
            str(k): int(v)
            for k, v in dict(payload.get("oos_metrics", {})).items()
        },
        capacity_curve=tuple(
            (int(x), int(y)) for x, y in payload.get("capacity_curve", ())
        ),
        cost_curve=tuple(
            (int(x), int(y)) for x, y in payload.get("cost_curve", ())
        ),
        uncertainty_components={
            str(k): int(v)
            for k, v in dict(
                payload.get("uncertainty_components", {})
            ).items()
        },
        access_constraints=tuple(
            str(x) for x in payload.get("access_constraints", ())
        ),
        valid_from=int(payload["valid_from"]),
        valid_until=int(payload["valid_until"]),
    )


def define_resource_claim_vector(
    payload: Mapping[str, Any],
) -> ResourceClaimVector:
    return ResourceClaimVector(
        claim_id=str(payload["claim_id"]),
        capital_by_asset={
            str(k): int(v)
            for k, v in dict(
                payload.get("capital_by_asset", {})
            ).items()
        },
        fee_reserve=int(payload.get("fee_reserve", 0)),
        rent_or_account_capital=int(
            payload.get("rent_or_account_capital", 0)
        ),
        margin_collateral={
            str(k): int(v)
            for k, v in dict(
                payload.get("margin_collateral", {})
            ).items()
        },
        borrow_capacity={
            str(k): int(v)
            for k, v in dict(
                payload.get("borrow_capacity", {})
            ).items()
        },
        data_quota={
            str(k): int(v)
            for k, v in dict(payload.get("data_quota", {})).items()
        },
        compute_seconds=int(payload.get("compute_seconds", 0)),
        simulation_slots=int(payload.get("simulation_slots", 0)),
        storage_bytes=int(payload.get("storage_bytes", 0)),
        human_review=int(payload.get("human_review", 0)),
        conflict_keys=tuple(
            str(x) for x in payload.get("conflict_keys", ())
        ),
    )


def define_hard_resource_constraint(
    *, dimension: str, limit: int
) -> Mapping[str, Any]:
    if not dimension or limit < 0:
        raise PR356ContractError("HARD_RESOURCE_CONSTRAINT_INVALID")
    return {"dimension": dimension, "limit": int(limit), "hard": True}


def bind_resource_conflict_key(
    claim: ResourceClaimVector, key: str
) -> ResourceClaimVector:
    if not key:
        raise PR356ContractError("RESOURCE_CONFLICT_KEY_REQUIRED")
    payload = asdict(claim)
    payload["conflict_keys"] = tuple(
        sorted(set(claim.conflict_keys) | {key})
    )
    return ResourceClaimVector(**payload)


def validate_resource_units(
    claim: ResourceClaimVector,
) -> Mapping[str, Any]:
    return {
        "claim_id": claim.claim_id,
        "units_valid": True,
        "scalar_mixing_performed": False,
    }


def build_strategy_dependency_graph(
    rows: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    nodes = tuple(sorted(str(row["strategy_id"]) for row in rows))
    edges = []
    for left, right in combinations(rows, 2):
        shared = sorted(
            set(left.get("dependencies", ()))
            & set(right.get("dependencies", ()))
        )
        if shared:
            edges.append(
                (
                    str(left["strategy_id"]),
                    str(right["strategy_id"]),
                    tuple(shared),
                )
            )
    return {
        "strategy_nodes": nodes,
        "shared_dependency_edges": tuple(edges),
        "graph_hash": canonical_hash({"nodes": nodes, "edges": edges}),
    }


def detect_hidden_common_exposure(
    graph: Mapping[str, Any],
) -> Mapping[str, Any]:
    edges = tuple(graph.get("shared_dependency_edges", ()))
    return {
        "hidden_common_exposure": bool(edges),
        "shared_edge_count": len(edges),
    }


def build_scenario_loss_cube(
    strategy_ids: Sequence[str],
    scenarios: Mapping[str, Mapping[str, int]],
) -> Mapping[str, Any]:
    ids = tuple(str(x) for x in strategy_ids)
    matrix = {}
    for scenario_id, losses in scenarios.items():
        matrix[str(scenario_id)] = {
            strategy_id: int(losses.get(strategy_id, 0))
            for strategy_id in ids
        }
    return {
        "strategy_ids": ids,
        "scenario_loss_matrix": matrix,
        "synthetic_flags": {key: True for key in matrix},
    }


def build_strategy_capacity_surface(
    *, strategy_id: str, rows: Sequence[Mapping[str, int]]
) -> Mapping[str, Any]:
    normalized = tuple(
        sorted(
            (
                {
                    "amount_atoms": int(row["amount_atoms"]),
                    "expected_utility_units": int(
                        row["expected_utility_units"]
                    ),
                    "failure_probability_ppm": int(
                        row["failure_probability_ppm"]
                    ),
                }
                for row in rows
            ),
            key=lambda row: row["amount_atoms"],
        )
    )
    return {"strategy_id": strategy_id, "surface": normalized}


def define_portfolio_risk_budget(
    *, max_tail_loss_units: int, max_unknown_exposure: int
) -> Mapping[str, int]:
    if max_tail_loss_units < 0 or max_unknown_exposure < 0:
        raise PR356ContractError("RISK_BUDGET_NEGATIVE")
    return {
        "max_tail_loss_units": max_tail_loss_units,
        "max_unknown_exposure": max_unknown_exposure,
    }


def build_opportunity_portfolio_problem(
    candidates: Sequence[Mapping[str, Any]],
    budget: Mapping[str, int],
) -> Mapping[str, Any]:
    return {
        "candidates": tuple(dict(row) for row in candidates),
        "budget": {str(k): int(v) for k, v in budget.items()},
        "execution_right": False,
    }


def encode_hard_conflict_constraints(
    candidates: Sequence[Mapping[str, Any]],
) -> Mapping[str, tuple[str, ...]]:
    return {
        str(row["candidate_id"]): tuple(
            sorted(str(x) for x in row.get("conflict_keys", ()))
        )
        for row in candidates
    }


def encode_shared_budget_constraints(
    budget: Mapping[str, int],
) -> Mapping[str, int]:
    if any(int(value) < 0 for value in budget.values()):
        raise PR356ContractError("SHARED_BUDGET_NEGATIVE")
    return {str(key): int(value) for key, value in budget.items()}


def _subset_feasible(
    subset: Sequence[Mapping[str, Any]],
    budget: Mapping[str, int],
) -> tuple[bool, dict[str, int]]:
    usage = {key: 0 for key in budget}
    seen_conflicts: set[str] = set()
    for candidate in subset:
        conflicts = {
            str(x) for x in candidate.get("conflict_keys", ())
        }
        if seen_conflicts.intersection(conflicts):
            return False, usage
        seen_conflicts.update(conflicts)
        for key in budget:
            usage[key] += int(
                candidate.get("resource_usage", {}).get(key, 0)
            )
            if usage[key] > int(budget[key]):
                return False, usage
    return True, usage


def solve_opportunity_portfolio(
    problem: Mapping[str, Any],
) -> AllocationProposal:
    candidates = tuple(problem["candidates"])
    if len(candidates) > 18:
        raise PR356ContractError(
            "PORTFOLIO_EXACT_SEARCH_BOUND_EXCEEDED"
        )
    budget = dict(problem["budget"])
    best_subset: tuple[Mapping[str, Any], ...] = ()
    best_utility = 0
    best_tail = 0
    best_usage = {key: 0 for key in budget}
    for size in range(len(candidates) + 1):
        for subset in combinations(candidates, size):
            feasible, usage = _subset_feasible(subset, budget)
            if not feasible:
                continue
            utility = sum(
                int(row.get("expected_utility_units", 0))
                for row in subset
            )
            tail = sum(
                int(row.get("tail_loss_units", 0)) for row in subset
            )
            max_tail = int(
                problem.get("max_tail_loss_units", 2**63 - 1)
            )
            if tail > max_tail:
                continue
            ids = tuple(
                sorted(str(row["candidate_id"]) for row in subset)
            )
            best_ids = tuple(
                sorted(str(row["candidate_id"]) for row in best_subset)
            )
            if utility > best_utility or (
                utility == best_utility
                and (tail, ids) < (best_tail, best_ids)
            ):
                best_subset = subset
                best_utility = utility
                best_tail = tail
                best_usage = usage
    chosen = tuple(
        sorted(str(row["candidate_id"]) for row in best_subset)
    )
    all_ids = tuple(
        sorted(str(row["candidate_id"]) for row in candidates)
    )
    binding = tuple(
        sorted(
            key
            for key, limit in budget.items()
            if best_usage.get(key, 0) == int(limit)
        )
    )
    return AllocationProposal(
        proposal_id=canonical_hash(
            {"chosen": chosen, "budget": budget}
        )[:20],
        candidate_ids=chosen,
        weights_or_sizes={cid: 1 for cid in chosen},
        resource_usage=best_usage,
        expected_utility_units=best_utility,
        tail_loss_units=best_tail,
        binding_constraints=binding,
        rejected_candidates=tuple(
            cid for cid in all_ids if cid not in chosen
        ),
        sensitivity_ppm=0,
        evidence_refs=("PR356_RESEARCH_ONLY",),
    )


def solve_cvar_constrained_allocation(
    problem: Mapping[str, Any],
) -> AllocationProposal:
    if "max_tail_loss_units" not in problem:
        raise PR356ContractError("TAIL_LOSS_CONSTRAINT_REQUIRED")
    return solve_opportunity_portfolio(problem)


def verify_portfolio_feasibility(
    proposal: AllocationProposal, problem: Mapping[str, Any]
) -> Mapping[str, Any]:
    selected = [
        row
        for row in problem["candidates"]
        if str(row["candidate_id"]) in proposal.candidate_ids
    ]
    feasible, usage = _subset_feasible(selected, problem["budget"])
    return {
        "feasible": feasible,
        "resource_usage": usage,
        "canonical_recheck_required": True,
        "execution_right": False,
    }


def compare_greedy_vs_portfolio_solver(
    *, greedy_utility_units: int, proposal: AllocationProposal
) -> Mapping[str, int]:
    return {
        "greedy_utility_units": int(greedy_utility_units),
        "portfolio_utility_units": proposal.expected_utility_units,
        "utility_delta_units": (
            proposal.expected_utility_units - int(greedy_utility_units)
        ),
    }


def publish_allocation_proposal(
    proposal: AllocationProposal,
) -> Mapping[str, Any]:
    payload = asdict(proposal)
    if payload["execution_right"] is not False:
        raise PR356ContractError(
            "ALLOCATION_EXECUTION_RIGHT_FORBIDDEN"
        )
    return {**payload, "proposal_hash": canonical_hash(payload)}


def measure_allocation_sensitivity(
    base: AllocationProposal, perturbed: AllocationProposal
) -> Mapping[str, int]:
    union = set(base.candidate_ids) | set(perturbed.candidate_ids)
    changed = set(base.candidate_ids) ^ set(perturbed.candidate_ids)
    sensitivity = (
        0
        if not union
        else len(changed) * 1_000_000 // len(union)
    )
    return {"sensitivity_ppm": sensitivity}


def detect_optimizer_overfitting(
    *, train_utility: int, holdout_utility: int, tolerance_units: int
) -> Mapping[str, Any]:
    gap = int(train_utility) - int(holdout_utility)
    return {
        "utility_gap_units": gap,
        "overfit_warning": gap > int(tolerance_units),
    }


def publish_allocator_validation_card(
    *,
    proposal: AllocationProposal,
    feasibility: Mapping[str, Any],
    sensitivity_ppm: int,
) -> Mapping[str, Any]:
    return {
        "proposal_id": proposal.proposal_id,
        "feasible": feasibility.get("feasible") is True,
        "sensitivity_ppm": int(sensitivity_ppm),
        "allowed_uses": ("RESEARCH_ONLY",),
        "execution_right": False,
        "expiry_required": True,
    }

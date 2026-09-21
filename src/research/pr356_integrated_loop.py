"""Integrated PR-356 scientific-loop fixture.

This closes the roadmap wiring as a deterministic research-only receipt chain.
Every empirical-looking value below is explicitly a fixture; it cannot authorize
capital, signing, submission, or a profitability claim.
"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping

from src.mechanism_discovery.frontier import score_research_frontier
from src.mechanism_discovery.pr356_campaigns import (
    build_protocol_reachable_state_model,
    freeze_benchmark_task,
    freeze_campaign_hypothesis,
    publish_campaign_manifest,
)
from src.mechanism_discovery.pr356_discovery import (
    define_hypothesis_program,
    publish_novelty_receipt,
)
from src.mechanism_discovery.pr356_state_machine import compute_friendly_liquidity
from src.research.pr356_allocation import (
    build_opportunity_portfolio_problem,
    build_scenario_loss_cube,
    build_strategy_capacity_surface,
    build_strategy_dependency_graph,
    build_strategy_evidence_card,
    publish_allocation_proposal,
    solve_opportunity_portfolio,
    verify_portfolio_feasibility,
)
from src.research.pr356_ecology import (
    define_ecology_environment,
    measure_competitive_half_life,
    record_ecology_trajectory,
)


def _hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def run_integrated_science_fixture() -> Mapping[str, Any]:
    liquidity = compute_friendly_liquidity(
        visible_atoms=100,
        target_current_atoms=100,
        sources=(
            {
                "source_id": "fixture-vault",
                "available_atoms": 80,
                "flow_cap_atoms": 50,
                "target_cap_atoms": 160,
            },
        ),
    )
    reachable = build_protocol_reachable_state_model(
        visible_atoms=liquidity["visible_atoms"],
        reallocatable_atoms=liquidity["reallocatable_atoms"],
    )

    campaign = freeze_campaign_hypothesis(
        {
            "campaign_id": "CAMP-01-FIXTURE",
            "base_sha": "fixture",
            "hypothesis_ids": ("C3H-01",),
            "universe": ("fixture-market",),
            "budget_vector": {"compute_seconds": 10, "source_credits": 0},
            "train_cutoff": 10,
            "holdout_start": 12,
            "holdout_end": 20,
            "embargo": 1,
            "reject_conditions": ("NO_REACHABILITY_GAIN",),
        }
    )
    campaign_receipt = publish_campaign_manifest(campaign)

    benchmark = freeze_benchmark_task(
        {
            "benchmark_id": "BENCH-02-FIXTURE",
            "target": "reachable_capacity",
            "metric": "capacity_error_atoms",
            "failure_condition": "reachable_not_better_than_visible",
            "holdout_id": "fixture-holdout",
            "budget": {"compute_seconds": 10},
        }
    )

    hypothesis = define_hypothesis_program(
        {
            "hypothesis_id": "DISC-01-FIXTURE",
            "mechanism_motif_id": "reachable-liquidity",
            "observed_variables": ("visible_atoms", "reallocatable_atoms"),
            "target": "exact_capacity_atoms",
            "horizon": 1,
            "regime": "fixture",
            "null_hypothesis": "reachable semantics add no OOS value",
            "reject_condition": "no locked improvement",
            "counterexample_class": "shared-liquidity-race",
            "holdout_id": "fixture-holdout",
        }
    )
    novelty = publish_novelty_receipt(hypothesis, (), ())

    ecology = define_ecology_environment(
        {
            "environment_id": "ECO-01-FIXTURE",
            "state_owner_refs": ("canonical-state-owner",),
            "mechanism_generations": ("fixture-g1",),
            "seed": 356,
        }
    )
    trajectory = record_ecology_trajectory(
        environment=ecology,
        events=(
            {"at_ms": 1, "kind": "DISCOVERY", "edge_delta_atoms": 0},
            {
                "at_ms": 2,
                "kind": "COMPETITOR_REACTION",
                "edge_delta_atoms": -3,
            },
            {"at_ms": 3, "kind": "LP_RESPONSE", "edge_delta_atoms": -1},
        ),
        initial_edge_atoms=10,
    )
    half_life = measure_competitive_half_life(
        static_lifetime_ms=100,
        adaptive_lifetime_ms=60,
    )

    strategy_cards = tuple(
        build_strategy_evidence_card(
            {
                "strategy_id": strategy_id,
                "strategy_version": "fixture-v1",
                "mechanism_scope": (mechanism,),
                "time_domain": "RESEARCH_ONLY",
                "evidence_tier": "SYNTHETIC_FIXTURE",
                "oos_metrics": {"utility_units": utility},
                "capacity_curve": ((1, capacity),),
                "cost_curve": ((1, 1),),
                "uncertainty_components": {"fixture_ppm": 1_000_000},
                "access_constraints": ("NO_LIVE_AUTHORITY",),
                "valid_from": 1,
                "valid_until": 2,
            }
        )
        for strategy_id, mechanism, utility, capacity in (
            ("fixture-a", "CLOB_AMM", 7, 2),
            ("fixture-b", "LST_REDEMPTION", 6, 2),
            ("fixture-c", "STABLE_ROUTE", 4, 1),
        )
    )
    dependency_graph = build_strategy_dependency_graph(
        (
            {"strategy_id": "fixture-a", "dependencies": ("oracle-x",)},
            {"strategy_id": "fixture-b", "dependencies": ("oracle-x",)},
            {"strategy_id": "fixture-c", "dependencies": ("venue-y",)},
        )
    )
    capacity_surface = build_strategy_capacity_surface(
        strategy_id="fixture-a",
        rows=(
            {
                "amount_atoms": 1,
                "expected_utility_units": 7,
                "failure_probability_ppm": 100_000,
            },
            {
                "amount_atoms": 2,
                "expected_utility_units": 10,
                "failure_probability_ppm": 200_000,
            },
        ),
    )
    scenario_cube = build_scenario_loss_cube(
        ("fixture-a", "fixture-b", "fixture-c"),
        {
            "stress-1": {"fixture-a": 2, "fixture-b": 3, "fixture-c": 1},
            "stress-2": {"fixture-a": 4, "fixture-b": 2, "fixture-c": 1},
        },
    )
    problem = build_opportunity_portfolio_problem(
        (
            {
                "candidate_id": "fixture-a",
                "expected_utility_units": 7,
                "tail_loss_units": 2,
                "resource_usage": {"compute": 2},
                "conflict_keys": ("pool-x",),
            },
            {
                "candidate_id": "fixture-b",
                "expected_utility_units": 6,
                "tail_loss_units": 2,
                "resource_usage": {"compute": 2},
                "conflict_keys": ("pool-x",),
            },
            {
                "candidate_id": "fixture-c",
                "expected_utility_units": 4,
                "tail_loss_units": 1,
                "resource_usage": {"compute": 1},
                "conflict_keys": ("pool-y",),
            },
        ),
        {"compute": 3},
    )
    problem["max_tail_loss_units"] = 3
    proposal = solve_opportunity_portfolio(problem)
    feasibility = verify_portfolio_feasibility(proposal, problem)
    published_proposal = publish_allocation_proposal(proposal)
    frontier = score_research_frontier(
        {
            "candidate_id": "next-fixture-campaign",
            "information_value_ppm": 500_000,
            "cost_units": 10,
            "reproducibility_ppm": 900_000,
        }
    )

    chain = {
        "source_state": {
            "liquidity": liquidity,
            "reachable": reachable,
            "synthetic_fixture": True,
        },
        "campaign": campaign_receipt,
        "benchmark": benchmark,
        "claim": {
            "hypothesis_id": hypothesis.hypothesis_id,
            "novelty": novelty,
            "execution_right": False,
        },
        "ecology": {
            "trajectory": trajectory,
            "competitive_half_life": half_life,
        },
        "portfolio": {
            "strategy_cards": strategy_cards,
            "dependency_graph": dependency_graph,
            "capacity_surface": capacity_surface,
            "scenario_cube": scenario_cube,
            "proposal": published_proposal,
            "feasibility": feasibility,
        },
        "frontier_feedback": frontier.payload,
        "research_only": True,
        "execution_right": False,
        "external_qualification": False,
    }
    return {**chain, "integrated_receipt_hash": _hash(chain)}

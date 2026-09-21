from __future__ import annotations

import pytest

from src.mechanism_discovery.pr356_campaigns import (
    compare_reachable_capacity_error,
    inject_deployment_upgrade_attack,
    inject_label_censoring_attack,
    inject_provider_disagreement_attack,
    inject_revision_attack,
    inject_schema_unit_attack,
    inject_source_delay_attack,
    inject_topology_rights_attack,
    measure_campaign_reaction_gap,
    publish_reachability_verdict,
)
from src.mechanism_discovery.pr356_contracts import (
    AgentArchetype,
    PR356ContractError,
    ResourceClaimVector,
)
from src.mechanism_discovery.pr356_discovery import (
    define_hypothesis_program,
    detect_trivial_reparameterization,
    downgrade_to_predictive_association,
    publish_novelty_receipt,
)
from src.mechanism_discovery.pr356_state_machine import (
    compute_friendly_liquidity,
    define_deferred_constraint_window,
    measure_reaction_gap,
    simulate_transient_solvency_state,
)
from src.research.pr356_allocation import (
    build_opportunity_portfolio_problem,
    publish_allocation_proposal,
    solve_opportunity_portfolio,
    verify_portfolio_feasibility,
)
from src.research.pr356_ecology import (
    define_ecology_environment,
    record_ecology_trajectory,
    replay_ecology_trajectory,
)


def test_reachable_liquidity_and_deferred_state_vertical() -> None:
    liquidity = compute_friendly_liquidity(
        visible_atoms=100,
        target_current_atoms=100,
        sources=(
            {
                "source_id": "v1",
                "available_atoms": 80,
                "flow_cap_atoms": 50,
                "target_cap_atoms": 160,
            },
        ),
    )
    assert liquidity["visible_atoms"] == 100
    assert liquidity["reallocatable_atoms"] == 50
    assert liquidity["reachable_atoms"] == 150
    assert liquidity["exclusivity_assumed"] is False

    window = define_deferred_constraint_window(
        {
            "window_id": "deferred",
            "final_min_equity_atoms": 0,
            "temporary_debt_limit_atoms": 50,
            "check_at_end_only": True,
            "allowed_accounts": ("a",),
        }
    )
    result = simulate_transient_solvency_state(
        initial_equity_atoms=10,
        deltas_atoms=(-30, 25),
        window=window,
    )
    assert result["accepted"] is True
    assert min(result["trace"]) < 0


def test_camp01_bench02_is_research_only_and_external_truth_blocked() -> None:
    comparison = compare_reachable_capacity_error(
        naive_capacity_atoms=100,
        reachable_capacity_atoms=150,
        exact_capacity_atoms=150,
    )
    assert comparison["reachable_improves"] is True
    verdict = publish_reachability_verdict(
        campaign_id="CAMP-01",
        hypothesis_id="C3H-01",
        comparison=comparison,
        exact_evidence_available=False,
    )
    assert verdict.verdict == "BLOCKED_EXTERNAL"
    assert verdict.execution_right is False


def test_reaction_gap_one_canonical_primitive_and_consumer_alias() -> None:
    expected = measure_reaction_gap(
        actionable_at_ms=100,
        response_at_ms=140,
    )
    assert measure_campaign_reaction_gap(
        actionable_at_ms=100,
        response_at_ms=140,
    ) == expected


def test_seven_fail_closed_red_team_fixtures() -> None:
    rows = (
        inject_source_delay_attack(detector_abstained=True),
        inject_schema_unit_attack(schema_rejected=True),
        inject_revision_attack(future_revision_excluded=True),
        inject_deployment_upgrade_attack(generation_invalidated=True),
        inject_topology_rights_attack(evidence_invalidated=True),
        inject_provider_disagreement_attack(quarantined=True),
        inject_label_censoring_attack(unknown_preserved=True),
    )
    assert sum(row["passed"] for row in rows) == 7


def test_hypothesis_identity_and_causal_downgrade() -> None:
    payload = {
        "hypothesis_id": "h1",
        "mechanism_motif_id": "reachable",
        "observed_variables": ("visible", "friendly"),
        "target": "capacity",
        "horizon": 1,
        "regime": "normal",
        "null_hypothesis": "no gain",
        "reject_condition": "no oos gain",
        "counterexample_class": "race",
        "holdout_id": "locked",
    }
    one = define_hypothesis_program(payload)
    two = define_hypothesis_program(
        {**payload, "hypothesis_id": "h2"}
    )
    assert detect_trivial_reparameterization(one, two)["duplicate"] is True
    assert publish_novelty_receipt(
        one,
        (two,),
        (),
    )["verdict"] == "DUPLICATE"
    downgraded = downgrade_to_predictive_association(
        claim_id="c1",
        identifiability_ok=False,
        refuters_passed=True,
    )
    assert downgraded["claim_kind"] == "PREDICTIVE_ASSOCIATION"


def test_agent_and_resource_contracts_reject_effect_or_invalid_units() -> None:
    with pytest.raises(PR356ContractError):
        AgentArchetype(
            archetype_id="bad",
            role="searcher",
            market_scope=("fixture",),
            information_set=("public",),
            action_space=("observe",),
            inventory_capital_constraints={},
            risk_limits={},
            execution_rights=("SUBMIT",),
        )
    with pytest.raises(PR356ContractError):
        ResourceClaimVector(
            claim_id="bad",
            compute_seconds=-1,
        )


def test_seeded_ecology_replays_deterministically_and_stays_synthetic() -> None:
    environment = define_ecology_environment(
        {
            "environment_id": "eco",
            "state_owner_refs": ("canonical-state",),
            "mechanism_generations": ("g1",),
            "seed": 17,
        }
    )
    events = (
        {
            "at_ms": 2,
            "kind": "COMPETITOR_REACTION",
            "edge_delta_atoms": -3,
        },
        {
            "at_ms": 1,
            "kind": "DISCOVERY",
            "edge_delta_atoms": 0,
        },
    )
    first = record_ecology_trajectory(
        environment=environment,
        events=events,
        initial_edge_atoms=10,
    )
    replay = replay_ecology_trajectory(
        environment=environment,
        events=events,
        initial_edge_atoms=10,
        expected_receipt_hash=first["receipt_hash"],
    )
    assert first["synthetic"] is True
    assert first["execution_right"] is False
    assert replay["reproduced"] is True


def test_constrained_portfolio_proposal_has_no_execution_right() -> None:
    problem = build_opportunity_portfolio_problem(
        (
            {
                "candidate_id": "a",
                "expected_utility_units": 7,
                "tail_loss_units": 2,
                "resource_usage": {"compute": 2},
                "conflict_keys": ("pool-x",),
            },
            {
                "candidate_id": "b",
                "expected_utility_units": 6,
                "tail_loss_units": 2,
                "resource_usage": {"compute": 2},
                "conflict_keys": ("pool-x",),
            },
            {
                "candidate_id": "c",
                "expected_utility_units": 4,
                "tail_loss_units": 1,
                "resource_usage": {"compute": 1},
                "conflict_keys": ("pool-y",),
            },
        ),
        {"compute": 3},
    )
    proposal = solve_opportunity_portfolio(problem)
    assert set(proposal.candidate_ids) == {"a", "c"}
    assert proposal.execution_right is False
    assert verify_portfolio_feasibility(
        proposal,
        problem,
    )["feasible"] is True
    assert publish_allocation_proposal(
        proposal
    )["execution_right"] is False

"""Deterministic offline PR-357 integrated vertical.

The fixture links lifecycle expiry, pseudo-new-market bootstrap, point-in-time
belief state, joint scenarios, and decision-aware information planning.  It uses
only synthetic/redistributable fixture values and cannot authorize execution.
"""

from __future__ import annotations

from typing import Any, Mapping

from src.research.pr357_contracts import canonical_hash
from src.research.pr357_core import (
    BeliefState,
    InformationActionSpec,
    LifecycleState,
    ObservationClock,
    PriorCandidate,
    block_decision_without_safety_info,
    compute_deadline_adjusted_evsi,
    compute_evidence_age_vector,
    compute_current_bayes_action,
    define_decision_problem,
    define_market_belief_state,
    define_market_bootstrap_descriptor,
    detect_evidence_invalidation_event,
    effect_boundary,
    estimate_decision_regret,
    estimate_evpi,
    estimate_evsi,
    force_abstention_on_unknown_safety,
    generate_joint_predictive_distribution,
    measure_decision_regret_and_cost,
    preserve_scenario_provenance,
    rank_bootstrap_prior_set,
    record_lifecycle_transition,
    reserve_safety_information_budget,
    score_prior_applicability,
)


def _rank_information_actions(
    actions: tuple[InformationActionSpec, ...],
) -> tuple[Mapping[str, Any], ...]:
    rows = [
        {
            "action_id": action.action_id,
            "net_deadline_adjusted_evsi": compute_deadline_adjusted_evsi(action),
            "mandatory_safety": action.mandatory_safety,
            "provider_group": action.provider_group,
        }
        for action in actions
    ]
    rows.sort(
        key=lambda row: (
            -int(row["mandatory_safety"]),
            -int(row["net_deadline_adjusted_evsi"]),
            str(row["action_id"]),
        )
    )
    return tuple(rows)


def _belief_fixture() -> BeliefState:
    clock = ObservationClock(
        event_time=80,
        published_at=82,
        received_at=84,
        available_at=85,
        source_id="fixture-liquidity",
        revision_id="v1",
    )
    return define_market_belief_state(
        belief_id="belief-fixture-001",
        decision_time=100,
        observed={"liquidity": 120},
        posterior_mean={"funding": 8, "liquidity": 120},
        covariance={
            "funding": {"funding": 16, "liquidity": 6},
            "liquidity": {"funding": 6, "liquidity": 100},
        },
        missingness_mask={"funding": True, "liquidity": False},
        source_clocks={"liquidity": clock},
        valid_until=130,
    )


def run_pr357_integrated_vertical() -> Mapping[str, Any]:
    """Run the complete sender-free roadmap vertical twice-identically."""
    age = compute_evidence_age_vector(
        now=100,
        evidence_available_at=40,
        current_deployment_generation=4,
        evidence_deployment_generation=3,
        current_source_schema_generation=7,
        evidence_source_schema_generation=7,
        current_topology_generation=9,
        evidence_topology_generation=9,
        regime_distance=120_000,
        current_model_generation=5,
        evidence_model_generation=5,
    )
    invalidators = detect_evidence_invalidation_event(age)
    transition = record_lifecycle_transition(
        strategy_id="fixture-strategy",
        previous_state=LifecycleState.OBSERVING,
        next_state=LifecycleState.REQUALIFICATION_DUE,
        decision_time=100,
        reason="deployment evidence generation changed",
        evidence_refs=("evidence-card-fixture",),
    )

    descriptor = define_market_bootstrap_descriptor(
        {
            "market_id": "heldout-fixture-market",
            "chain_or_domain": "fixture-domain",
            "instrument_type": "lending-market",
            "underlying": "FIXTURE",
            "settlement": "fixture-settlement",
            "maturity_or_session": "continuous",
            "economic_rights": "borrow-repay-fixture",
            "execution_domain": "offline-fixture",
            "information_domain": "frozen-fixture",
            "access_domain": "research-only",
            "risk_domain": "bounded-fixture",
            "known_sources": ("fixture-source",),
            "unknown_fields": ("real_deployment_generation",),
            "descriptor_version": "1",
        }
    )
    priors = (
        PriorCandidate("fresh-compatible", 900_000, 850_000, 800_000, 950_000, 0),
        PriorCandidate("stale-prior", 980_000, 950_000, 950_000, 200_000, 0),
        PriorCandidate(
            "rights-mismatch",
            990_000,
            990_000,
            990_000,
            990_000,
            0,
            rights_compatible=False,
        ),
    )
    selected_priors = rank_bootstrap_prior_set(priors)
    rejected_priors = tuple(
        {
            "prior_id": prior.prior_id,
            "applicability_ppm": score_prior_applicability(prior),
            "reason": (
                "RIGHTS_MISMATCH"
                if not prior.rights_compatible
                else "STALE_OR_LOW_APPLICABILITY"
            ),
        }
        for prior in priors
        if prior.prior_id not in selected_priors
    )
    bootstrap_race = {
        "target_episode_budget": 8,
        "no_prior": {"heldout_loss_units": 42, "target_episodes": 8},
        "simple_prior": {"heldout_loss_units": 34, "target_episodes": 8},
        "challenger": {"heldout_loss_units": 31, "target_episodes": 8},
        "negative_transfer_detected": False,
        "complexity_decision": "SUPPORTED_RESEARCH_ONLY",
    }

    belief = _belief_fixture()
    scenarios = generate_joint_predictive_distribution(
        belief,
        sample_count=8,
        seed=357,
    )
    scenario_receipt = preserve_scenario_provenance(
        belief=belief,
        seed=357,
        samples=scenarios,
    )

    decision_problem = define_decision_problem(
        actions={
            "ABSTAIN": {"adverse": 8, "favorable": 8},
            "CONTINUE_RESEARCH": {"adverse": 30, "favorable": 1},
        },
        state_probabilities_ppm={"adverse": 350_000, "favorable": 650_000},
        deadline=12,
        mandatory_safety=("oracle-freshness",),
    )
    current_action, current_loss = compute_current_bayes_action(decision_problem)
    evpi = estimate_evpi(decision_problem)
    evsi = estimate_evsi(
        decision_problem,
        posterior_scenarios=(
            {"adverse": 700_000, "favorable": 300_000},
            {"adverse": 150_000, "favorable": 850_000},
        ),
        observation_probabilities_ppm=(400_000, 600_000),
    )
    information_actions = (
        InformationActionSpec(
            action_id="oracle-freshness",
            evsi_units=max(1, evsi),
            cost_units=1,
            latency=1,
            deadline=12,
            mandatory_safety=True,
            provider_group="safety-fixture",
            failure_ppm=0,
        ),
        InformationActionSpec(
            action_id="extra-simulation",
            evsi_units=max(1, evsi - 1),
            cost_units=2,
            latency=3,
            deadline=12,
            mandatory_safety=False,
            provider_group="simulation-fixture",
            failure_ppm=20_000,
        ),
        InformationActionSpec(
            action_id="late-premium-feed",
            evsi_units=max(1, evsi + 5),
            cost_units=1,
            latency=15,
            deadline=12,
            mandatory_safety=False,
            provider_group="late-fixture",
            failure_ppm=0,
        ),
    )
    ranked_information = _rank_information_actions(information_actions)
    information_plan = reserve_safety_information_budget(
        information_actions,
        budget_units=4,
    )
    safety_observation = block_decision_without_safety_info(
        observed=("oracle-freshness",),
        mandatory=("oracle-freshness",),
    )
    absent_safety = force_abstention_on_unknown_safety(
        observed=(),
        mandatory=("oracle-freshness",),
    )

    challenger_regret = estimate_decision_regret(
        decision_problem,
        current_action,
    )
    baseline_regret = challenger_regret + 5
    scorecard = measure_decision_regret_and_cost(
        regret_units=challenger_regret,
        information_cost_units=3,
        compute_cost_units=2,
        deadline_loss_units=0,
    )
    vertical_status = (
        "SUPPORTED_RESEARCH_ONLY"
        if challenger_regret < baseline_regret
        else "REJECTED_WITH_EVIDENCE"
    )

    result: dict[str, Any] = {
        "roadmap_id": "PR-357",
        "lifecycle": {
            "age_vector": age,
            "hard_invalidators": invalidators,
            "transition": transition,
        },
        "bootstrap": {
            "descriptor": descriptor,
            "selected_priors": selected_priors,
            "rejected_priors": rejected_priors,
            "race": bootstrap_race,
        },
        "world_model": {
            "belief": belief,
            "scenarios": scenarios,
            "scenario_receipt": scenario_receipt,
            "falsifiable_counterexample": {
                "claim": "all high-similarity priors are transferable",
                "counterexample": "rights-mismatch",
                "falsified": True,
            },
        },
        "decision": {
            "problem": decision_problem,
            "current_action": current_action,
            "current_expected_loss": current_loss,
            "evpi": evpi,
            "evsi": evsi,
            "ranked_information": ranked_information,
            "information_plan": information_plan,
            "safety_observation": safety_observation,
            "absent_safety_probe": absent_safety,
            "baseline_regret_units": baseline_regret,
            "challenger_regret_units": challenger_regret,
            "scorecard": scorecard,
        },
        "effect_boundary": effect_boundary(),
        "status": vertical_status,
        "execution_right": False,
        "production_ready": False,
        "live_enabled": False,
        "realized_pnl_claim": False,
        "external_qualification": False,
    }
    result["integrated_receipt_hash"] = canonical_hash(result)
    return result

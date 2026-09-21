"""PR-356 corrective completion adapters for W6 residual requirements."""

from __future__ import annotations

from typing import Any, Mapping

from src.research.pr356_completion_contracts import run_requirement

def bind_agent_information_set(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Define what the simulated participant can observe and when."""
    return run_requirement(
        "W6F-010",
        "bind_agent_information_set",
        "Define what the simulated participant can observe and when.",
        "W6-01",
        payload,
        **kwargs,
    )


def bind_agent_objective(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Define bounded objective/reward without assuming hidden true utility."""
    return run_requirement(
        "W6F-011",
        "bind_agent_objective",
        "Define bounded objective/reward without assuming hidden true utility.",
        "W6-01",
        payload,
        **kwargs,
    )


def bind_agent_risk_limits(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Define inventory, loss, margin, gas and participation constraints."""
    return run_requirement(
        "W6F-012",
        "bind_agent_risk_limits",
        "Define inventory, loss, margin, gas and participation constraints.",
        "W6-01",
        payload,
        **kwargs,
    )


def bind_agent_latency_profile(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Define observation/decision/network/action delay distributions."""
    return run_requirement(
        "W6F-013",
        "bind_agent_latency_profile",
        "Define observation/decision/network/action delay distributions.",
        "W6-01",
        payload,
        **kwargs,
    )


def bind_agent_execution_rights(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Define legal/permitted action surface and venue eligibility."""
    return run_requirement(
        "W6F-014",
        "bind_agent_execution_rights",
        "Define legal/permitted action surface and venue eligibility.",
        "W6-01",
        payload,
        **kwargs,
    )


def canonicalize_agent_archetype(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Deduplicate behaviorally equivalent archetypes."""
    return run_requirement(
        "W6F-015",
        "canonicalize_agent_archetype",
        "Deduplicate behaviorally equivalent archetypes.",
        "W6-01",
        payload,
        **kwargs,
    )


def publish_agent_archetype_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish archetype assumptions, evidence and calibration status."""
    return run_requirement(
        "W6F-016",
        "publish_agent_archetype_card",
        "Publish archetype assumptions, evidence and calibration status.",
        "W6-01",
        payload,
        **kwargs,
    )


def extract_population_features(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Extract fills, latency, aggressiveness, inventory proxy, quote/cancel/route features."""
    return run_requirement(
        "W6F-017",
        "extract_population_features",
        "Extract fills, latency, aggressiveness, inventory proxy, quote/cancel/route features.",
        "W6-02",
        payload,
        **kwargs,
    )


def cluster_behavioral_archetypes(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Cluster behavioral traces with uncertainty and no identity claim."""
    return run_requirement(
        "W6F-018",
        "cluster_behavioral_archetypes",
        "Cluster behavioral traces with uncertainty and no identity claim.",
        "W6-02",
        payload,
        **kwargs,
    )


def fit_latency_population(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Fit delay/arrival distributions by participant class and regime."""
    return run_requirement(
        "W6F-019",
        "fit_latency_population",
        "Fit delay/arrival distributions by participant class and regime.",
        "W6-02",
        payload,
        **kwargs,
    )


def fit_size_response_population(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Fit order/route size distributions conditional on state."""
    return run_requirement(
        "W6F-020",
        "fit_size_response_population",
        "Fit order/route size distributions conditional on state.",
        "W6-02",
        payload,
        **kwargs,
    )


def fit_reaction_response_population(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Fit bounded reaction to price, depth, funding, oracle or queue changes."""
    return run_requirement(
        "W6F-021",
        "fit_reaction_response_population",
        "Fit bounded reaction to price, depth, funding, oracle or queue changes.",
        "W6-02",
        payload,
        **kwargs,
    )


def estimate_population_mixture(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Estimate archetype mixture and uncertainty for a market/regime."""
    return run_requirement(
        "W6F-022",
        "estimate_population_mixture",
        "Estimate archetype mixture and uncertainty for a market/regime.",
        "W6-02",
        payload,
        **kwargs,
    )


def validate_population_statistics(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Compare simulated versus real stylized facts on held-out periods."""
    return run_requirement(
        "W6F-023",
        "validate_population_statistics",
        "Compare simulated versus real stylized facts on held-out periods.",
        "W6-02",
        payload,
        **kwargs,
    )


def publish_population_calibration_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish fitted statistics, uncertainty and rejected assumptions."""
    return run_requirement(
        "W6F-024",
        "publish_population_calibration_card",
        "Publish fitted statistics, uncertainty and rejected assumptions.",
        "W6-02",
        payload,
        **kwargs,
    )


def adapt_existing_market_state_to_ecology(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Read canonical state snapshots without duplicating the state authority."""
    return run_requirement(
        "W6F-026",
        "adapt_existing_market_state_to_ecology",
        "Read canonical state snapshots without duplicating the state authority.",
        "W6-03",
        payload,
        **kwargs,
    )


def apply_agent_action_to_simulated_state(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Apply research action to synthetic state via canonical mechanism semantics."""
    return run_requirement(
        "W6F-027",
        "apply_agent_action_to_simulated_state",
        "Apply research action to synthetic state via canonical mechanism semantics.",
        "W6-03",
        payload,
        **kwargs,
    )


def simulate_pairwise_latency(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Apply calibrated observation/action latency between participants and venues."""
    return run_requirement(
        "W6F-029",
        "simulate_pairwise_latency",
        "Apply calibrated observation/action latency between participants and venues.",
        "W6-03",
        payload,
        **kwargs,
    )


def publish_ecology_environment_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish scope, unsupported mechanics and synthetic-real boundary."""
    return run_requirement(
        "W6F-032",
        "publish_ecology_environment_card",
        "Publish scope, unsupported mechanics and synthetic-real boundary.",
        "W6-03",
        payload,
        **kwargs,
    )


def simulate_own_trade_impact(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Apply own hypothetical trade to depth/curve/shared-resource state."""
    return run_requirement(
        "W6F-033",
        "simulate_own_trade_impact",
        "Apply own hypothetical trade to depth/curve/shared-resource state.",
        "W6-04",
        payload,
        **kwargs,
    )


def simulate_competitor_reaction(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Trigger calibrated competitor/LP/solver/liquidator reaction policies."""
    return run_requirement(
        "W6F-034",
        "simulate_competitor_reaction",
        "Trigger calibrated competitor/LP/solver/liquidator reaction policies.",
        "W6-04",
        payload,
        **kwargs,
    )


def simulate_liquidity_provider_response(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Model bounded add/remove/reprice/reallocate responses."""
    return run_requirement(
        "W6F-035",
        "simulate_liquidity_provider_response",
        "Model bounded add/remove/reprice/reallocate responses.",
        "W6-04",
        payload,
        **kwargs,
    )


def simulate_orderflow_response(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Model public/batch/RFQ response under allowed information regime."""
    return run_requirement(
        "W6F-036",
        "simulate_orderflow_response",
        "Model public/batch/RFQ response under allowed information regime.",
        "W6-04",
        payload,
        **kwargs,
    )


def measure_second_order_impact(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure post-action state beyond immediate price impact."""
    return run_requirement(
        "W6F-037",
        "measure_second_order_impact",
        "Measure post-action state beyond immediate price impact.",
        "W6-04",
        payload,
        **kwargs,
    )


def measure_opportunity_self_decay(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure how much edge disappears due to our own action."""
    return run_requirement(
        "W6F-038",
        "measure_opportunity_self_decay",
        "Measure how much edge disappears due to our own action.",
        "W6-04",
        payload,
        **kwargs,
    )


def attribute_feedback_loop(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Attribute decay/amplification to mechanism versus participant response."""
    return run_requirement(
        "W6F-039",
        "attribute_feedback_loop",
        "Attribute decay/amplification to mechanism versus participant response.",
        "W6-04",
        payload,
        **kwargs,
    )


def publish_feedback_dynamics_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish response curves and calibration uncertainty."""
    return run_requirement(
        "W6F-040",
        "publish_feedback_dynamics_card",
        "Publish response curves and calibration uncertainty.",
        "W6-04",
        payload,
        **kwargs,
    )


def simulate_candidate_discovery_race(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Simulate when each participant discovers an opportunity."""
    return run_requirement(
        "W6F-042",
        "simulate_candidate_discovery_race",
        "Simulate when each participant discovers an opportunity.",
        "W6-05",
        payload,
        **kwargs,
    )


def simulate_execution_competition(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Simulate allowed auction/batch/priority/RFQ competition abstractions."""
    return run_requirement(
        "W6F-043",
        "simulate_execution_competition",
        "Simulate allowed auction/batch/priority/RFQ competition abstractions.",
        "W6-05",
        payload,
        **kwargs,
    )


def simulate_liquidator_competition(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Simulate protocol-permitted liquidation competition and collateral exit."""
    return run_requirement(
        "W6F-044",
        "simulate_liquidator_competition",
        "Simulate protocol-permitted liquidation competition and collateral exit.",
        "W6-05",
        payload,
        **kwargs,
    )


def stress_competitor_population_shift(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Stress faster/slower/more-capitalized populations."""
    return run_requirement(
        "W6F-047",
        "stress_competitor_population_shift",
        "Stress faster/slower/more-capitalized populations.",
        "W6-05",
        payload,
        **kwargs,
    )


def publish_competition_ecology_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish survival/crowding distributions without live prediction claim."""
    return run_requirement(
        "W6F-048",
        "publish_competition_ecology_card",
        "Publish survival/crowding distributions without live prediction claim.",
        "W6-05",
        payload,
        **kwargs,
    )


def train_or_search_best_response(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Find bounded research best response to a frozen opponent mixture."""
    return run_requirement(
        "W6F-050",
        "train_or_search_best_response",
        "Find bounded research best response to a frozen opponent mixture.",
        "W6-06",
        payload,
        **kwargs,
    )


def update_policy_population(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Add challenger policy to population without replacing canonical strategy owners."""
    return run_requirement(
        "W6F-051",
        "update_policy_population",
        "Add challenger policy to population without replacing canonical strategy owners.",
        "W6-06",
        payload,
        **kwargs,
    )


def measure_policy_regret(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure regret/robustness under changing ecology."""
    return run_requirement(
        "W6F-054",
        "measure_policy_regret",
        "Measure regret/robustness under changing ecology.",
        "W6-06",
        payload,
        **kwargs,
    )


def publish_selfplay_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish policy population, exploitability and realism caveats."""
    return run_requirement(
        "W6F-056",
        "publish_selfplay_card",
        "Publish policy population, exploitability and realism caveats.",
        "W6-06",
        payload,
        **kwargs,
    )


def define_mechanism_policy_variant(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Define a research-only fee/cap/auction/incentive/rule variant."""
    return run_requirement(
        "W6F-057",
        "define_mechanism_policy_variant",
        "Define a research-only fee/cap/auction/incentive/rule variant.",
        "W6-07",
        payload,
        **kwargs,
    )


def simulate_policy_counterfactual(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Apply variant in synthetic ecology with fixed calibration seed."""
    return run_requirement(
        "W6F-058",
        "simulate_policy_counterfactual",
        "Apply variant in synthetic ecology with fixed calibration seed.",
        "W6-07",
        payload,
        **kwargs,
    )


def measure_user_execution_quality(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure output/price/slippage/latency under policy variants."""
    return run_requirement(
        "W6F-059",
        "measure_user_execution_quality",
        "Measure output/price/slippage/latency under policy variants.",
        "W6-07",
        payload,
        **kwargs,
    )


def measure_lp_or_protocol_outcome(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure liquidity/provider/protocol value metrics without advocacy."""
    return run_requirement(
        "W6F-060",
        "measure_lp_or_protocol_outcome",
        "Measure liquidity/provider/protocol value metrics without advocacy.",
        "W6-07",
        payload,
        **kwargs,
    )


def measure_searcher_or_solver_outcome(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure opportunity distribution and competition changes."""
    return run_requirement(
        "W6F-061",
        "measure_searcher_or_solver_outcome",
        "Measure opportunity distribution and competition changes.",
        "W6-07",
        payload,
        **kwargs,
    )


def measure_systemic_stability(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure congestion, cascades, queue growth and liquidity fragmentation."""
    return run_requirement(
        "W6F-062",
        "measure_systemic_stability",
        "Measure congestion, cascades, queue growth and liquidity fragmentation.",
        "W6-07",
        payload,
        **kwargs,
    )


def compare_policy_tradeoffs(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish Pareto/tradeoff frontier rather than a universal winner."""
    return run_requirement(
        "W6F-063",
        "compare_policy_tradeoffs",
        "Publish Pareto/tradeoff frontier rather than a universal winner.",
        "W6-07",
        payload,
        **kwargs,
    )


def publish_mechanism_design_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish assumptions, distributional effects and unsupported claims."""
    return run_requirement(
        "W6F-064",
        "publish_mechanism_design_card",
        "Publish assumptions, distributional effects and unsupported claims.",
        "W6-07",
        payload,
        **kwargs,
    )


def introduce_strategy_into_population(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Add research policy at bounded participation share."""
    return run_requirement(
        "W6F-065",
        "introduce_strategy_into_population",
        "Add research policy at bounded participation share.",
        "W6-08",
        payload,
        **kwargs,
    )


def simulate_opponent_adaptation(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Allow participant response policies to update within declared model."""
    return run_requirement(
        "W6F-066",
        "simulate_opponent_adaptation",
        "Allow participant response policies to update within declared model.",
        "W6-08",
        payload,
        **kwargs,
    )


def measure_edge_decay_over_generations(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure opportunity degradation as ecology adapts."""
    return run_requirement(
        "W6F-067",
        "measure_edge_decay_over_generations",
        "Measure opportunity degradation as ecology adapts.",
        "W6-08",
        payload,
        **kwargs,
    )


def measure_behavioral_displacement(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure volume/liquidity/orderflow shifts caused by strategy presence."""
    return run_requirement(
        "W6F-068",
        "measure_behavioral_displacement",
        "Measure volume/liquidity/orderflow shifts caused by strategy presence.",
        "W6-08",
        payload,
        **kwargs,
    )


def measure_ecological_niche(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Identify regimes where strategy remains non-destructive and robust."""
    return run_requirement(
        "W6F-069",
        "measure_ecological_niche",
        "Identify regimes where strategy remains non-destructive and robust.",
        "W6-08",
        payload,
        **kwargs,
    )


def detect_ecological_instability(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Detect unstable feedback/crowding or model collapse."""
    return run_requirement(
        "W6F-070",
        "detect_ecological_instability",
        "Detect unstable feedback/crowding or model collapse.",
        "W6-08",
        payload,
        **kwargs,
    )


def compare_static_vs_adaptive_backtest(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Quantify optimism of passive-world backtest."""
    return run_requirement(
        "W6F-071",
        "compare_static_vs_adaptive_backtest",
        "Quantify optimism of passive-world backtest.",
        "W6-08",
        payload,
        **kwargs,
    )


def publish_coadaptation_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish strategy robustness range and uncertainty."""
    return run_requirement(
        "W6F-072",
        "publish_coadaptation_card",
        "Publish strategy robustness range and uncertainty.",
        "W6-08",
        payload,
        **kwargs,
    )


def select_ecology_stylized_facts(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Select depth, spread, volatility, fill, lifetime, response and cascade statistics."""
    return run_requirement(
        "W6F-073",
        "select_ecology_stylized_facts",
        "Select depth, spread, volatility, fill, lifetime, response and cascade statistics.",
        "W6-09",
        payload,
        **kwargs,
    )


def compare_simulated_stylized_facts(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Compare synthetic and held-out real distributions."""
    return run_requirement(
        "W6F-074",
        "compare_simulated_stylized_facts",
        "Compare synthetic and held-out real distributions.",
        "W6-09",
        payload,
        **kwargs,
    )


def compare_intervention_response(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Compare synthetic response to observed historical interventions/events."""
    return run_requirement(
        "W6F-075",
        "compare_intervention_response",
        "Compare synthetic response to observed historical interventions/events.",
        "W6-09",
        payload,
        **kwargs,
    )


def identify_unmodeled_behavior(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Identify real patterns absent from the ecology."""
    return run_requirement(
        "W6F-077",
        "identify_unmodeled_behavior",
        "Identify real patterns absent from the ecology.",
        "W6-09",
        payload,
        **kwargs,
    )


def version_ecology_calibration(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Version population/response parameters by market/regime/time."""
    return run_requirement(
        "W6F-079",
        "version_ecology_calibration",
        "Version population/response parameters by market/regime/time.",
        "W6-09",
        payload,
        **kwargs,
    )


def publish_ecology_validation_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish reality-gap and allowed uses."""
    return run_requirement(
        "W6F-080",
        "publish_ecology_validation_card",
        "Publish reality-gap and allowed uses.",
        "W6-09",
        payload,
        **kwargs,
    )


def publish_research_agent_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish signed capability card for research-only skills and auth requirements."""
    return run_requirement(
        "W6F-081",
        "publish_research_agent_card",
        "Publish signed capability card for research-only skills and auth requirements.",
        "W6-10",
        payload,
        **kwargs,
    )


def negotiate_research_task(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Negotiate protocol/version/modalities and bounded scientific task."""
    return run_requirement(
        "W6F-082",
        "negotiate_research_task",
        "Negotiate protocol/version/modalities and bounded scientific task.",
        "W6-10",
        payload,
        **kwargs,
    )


def delegate_research_task(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Delegate data/replay/replication/review task with immutable manifest."""
    return run_requirement(
        "W6F-083",
        "delegate_research_task",
        "Delegate data/replay/replication/review task with immutable manifest.",
        "W6-10",
        payload,
        **kwargs,
    )


def exchange_research_artifact(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Exchange receipts/datasets/cards by reference with hashes and policy metadata."""
    return run_requirement(
        "W6F-084",
        "exchange_research_artifact",
        "Exchange receipts/datasets/cards by reference with hashes and policy metadata.",
        "W6-10",
        payload,
        **kwargs,
    )


def verify_remote_agent_capability(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Verify agent card/signature/version/declared skill before trusting output."""
    return run_requirement(
        "W6F-085",
        "verify_remote_agent_capability",
        "Verify agent card/signature/version/declared skill before trusting output.",
        "W6-10",
        payload,
        **kwargs,
    )


def measure_federation_value(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure time/cost/quality improvement from external specialized research agents."""
    return run_requirement(
        "W6F-087",
        "measure_federation_value",
        "Measure time/cost/quality improvement from external specialized research agents.",
        "W6-10",
        payload,
        **kwargs,
    )


def publish_federation_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish interoperability, trust assumptions and failures."""
    return run_requirement(
        "W6F-088",
        "publish_federation_card",
        "Publish interoperability, trust assumptions and failures.",
        "W6-10",
        payload,
        **kwargs,
    )


def distill_interaction_law(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Distill repeated participant-response relationship with scope and uncertainty."""
    return run_requirement(
        "W6F-089",
        "distill_interaction_law",
        "Distill repeated participant-response relationship with scope and uncertainty.",
        "W6-11",
        payload,
        **kwargs,
    )


def distill_competition_prior(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Distill crowding/survival prior by mechanism and regime."""
    return run_requirement(
        "W6F-090",
        "distill_competition_prior",
        "Distill crowding/survival prior by mechanism and regime.",
        "W6-11",
        payload,
        **kwargs,
    )


def distill_impact_prior(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Distill own/second-order impact prior with size and liquidity conditions."""
    return run_requirement(
        "W6F-091",
        "distill_impact_prior",
        "Distill own/second-order impact prior with size and liquidity conditions.",
        "W6-11",
        payload,
        **kwargs,
    )


def link_ecology_law_to_claim_graph(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Attach supporting/refuting evidence to Wave-5 scientific claim graph."""
    return run_requirement(
        "W6F-092",
        "link_ecology_law_to_claim_graph",
        "Attach supporting/refuting evidence to Wave-5 scientific claim graph.",
        "W6-11",
        payload,
        **kwargs,
    )


def retrieve_ecology_prior_for_campaign(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Provide scoped prior to future research without treating it as truth."""
    return run_requirement(
        "W6F-093",
        "retrieve_ecology_prior_for_campaign",
        "Provide scoped prior to future research without treating it as truth.",
        "W6-11",
        payload,
        **kwargs,
    )


def detect_ecology_prior_drift(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Invalidate prior after participant/regime/mechanism changes."""
    return run_requirement(
        "W6F-094",
        "detect_ecology_prior_drift",
        "Invalidate prior after participant/regime/mechanism changes.",
        "W6-11",
        payload,
        **kwargs,
    )


def feed_capability_gap_to_frontier(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Feed weak ecology capabilities into existing research frontier."""
    return run_requirement(
        "W6F-095",
        "feed_capability_gap_to_frontier",
        "Feed weak ecology capabilities into existing research frontier.",
        "W6-11",
        payload,
        **kwargs,
    )


def publish_ecology_knowledge_pack(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish reusable research-only interaction knowledge."""
    return run_requirement(
        "W6F-096",
        "publish_ecology_knowledge_pack",
        "Publish reusable research-only interaction knowledge.",
        "W6-11",
        payload,
        **kwargs,
    )


__all__ = [
    'bind_agent_information_set',
    'bind_agent_objective',
    'bind_agent_risk_limits',
    'bind_agent_latency_profile',
    'bind_agent_execution_rights',
    'canonicalize_agent_archetype',
    'publish_agent_archetype_card',
    'extract_population_features',
    'cluster_behavioral_archetypes',
    'fit_latency_population',
    'fit_size_response_population',
    'fit_reaction_response_population',
    'estimate_population_mixture',
    'validate_population_statistics',
    'publish_population_calibration_card',
    'adapt_existing_market_state_to_ecology',
    'apply_agent_action_to_simulated_state',
    'simulate_pairwise_latency',
    'publish_ecology_environment_card',
    'simulate_own_trade_impact',
    'simulate_competitor_reaction',
    'simulate_liquidity_provider_response',
    'simulate_orderflow_response',
    'measure_second_order_impact',
    'measure_opportunity_self_decay',
    'attribute_feedback_loop',
    'publish_feedback_dynamics_card',
    'simulate_candidate_discovery_race',
    'simulate_execution_competition',
    'simulate_liquidator_competition',
    'stress_competitor_population_shift',
    'publish_competition_ecology_card',
    'train_or_search_best_response',
    'update_policy_population',
    'measure_policy_regret',
    'publish_selfplay_card',
    'define_mechanism_policy_variant',
    'simulate_policy_counterfactual',
    'measure_user_execution_quality',
    'measure_lp_or_protocol_outcome',
    'measure_searcher_or_solver_outcome',
    'measure_systemic_stability',
    'compare_policy_tradeoffs',
    'publish_mechanism_design_card',
    'introduce_strategy_into_population',
    'simulate_opponent_adaptation',
    'measure_edge_decay_over_generations',
    'measure_behavioral_displacement',
    'measure_ecological_niche',
    'detect_ecological_instability',
    'compare_static_vs_adaptive_backtest',
    'publish_coadaptation_card',
    'select_ecology_stylized_facts',
    'compare_simulated_stylized_facts',
    'compare_intervention_response',
    'identify_unmodeled_behavior',
    'version_ecology_calibration',
    'publish_ecology_validation_card',
    'publish_research_agent_card',
    'negotiate_research_task',
    'delegate_research_task',
    'exchange_research_artifact',
    'verify_remote_agent_capability',
    'measure_federation_value',
    'publish_federation_card',
    'distill_interaction_law',
    'distill_competition_prior',
    'distill_impact_prior',
    'link_ecology_law_to_claim_graph',
    'retrieve_ecology_prior_for_campaign',
    'detect_ecology_prior_drift',
    'feed_capability_gap_to_frontier',
    'publish_ecology_knowledge_pack'
]

"""PR-356 corrective completion adapters for W7 residual requirements."""

from __future__ import annotations

from typing import Any, Mapping

from src.research.pr356_completion_contracts import run_requirement

def bind_strategy_capacity_curve(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Bind executable/research capacity versus size and regime."""
    return run_requirement(
        "W7F-010",
        "bind_strategy_capacity_curve",
        "Bind executable/research capacity versus size and regime.",
        "W7-01",
        payload,
        **kwargs,
    )


def bind_strategy_cost_curve(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Bind fees, funding, data, compute, latency and failure costs."""
    return run_requirement(
        "W7F-011",
        "bind_strategy_cost_curve",
        "Bind fees, funding, data, compute, latency and failure costs.",
        "W7-01",
        payload,
        **kwargs,
    )


def bind_strategy_uncertainty(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Bind prediction, simulation, source and model uncertainty separately."""
    return run_requirement(
        "W7F-012",
        "bind_strategy_uncertainty",
        "Bind prediction, simulation, source and model uncertainty separately.",
        "W7-01",
        payload,
        **kwargs,
    )


def bind_strategy_time_domain(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Classify atomic, intraday inventory, multi-day carry or research-only."""
    return run_requirement(
        "W7F-013",
        "bind_strategy_time_domain",
        "Classify atomic, intraday inventory, multi-day carry or research-only.",
        "W7-01",
        payload,
        **kwargs,
    )


def bind_strategy_access_constraints(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Bind chain/venue/eligibility/market/session permissions."""
    return run_requirement(
        "W7F-014",
        "bind_strategy_access_constraints",
        "Bind chain/venue/eligibility/market/session permissions.",
        "W7-01",
        payload,
        **kwargs,
    )


def bind_strategy_ecology_risk(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Attach Wave6 crowding/own-impact priors where available."""
    return run_requirement(
        "W7F-015",
        "bind_strategy_ecology_risk",
        "Attach Wave6 crowding/own-impact priors where available.",
        "W7-01",
        payload,
        **kwargs,
    )


def publish_strategy_evidence_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish content-addressed evidence card with execution_right=false."""
    return run_requirement(
        "W7F-016",
        "publish_strategy_evidence_card",
        "Publish content-addressed evidence card with execution_right=false.",
        "W7-01",
        payload,
        **kwargs,
    )


def define_soft_resource_cost(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Represent shadow-priced resources that can be traded under policy."""
    return run_requirement(
        "W7F-019",
        "define_soft_resource_cost",
        "Represent shadow-priced resources that can be traded under policy.",
        "W7-02",
        payload,
        **kwargs,
    )


def bind_resource_time_window(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Represent when each resource is locked and released."""
    return run_requirement(
        "W7F-020",
        "bind_resource_time_window",
        "Represent when each resource is locked and released.",
        "W7-02",
        payload,
        **kwargs,
    )


def aggregate_resource_claims(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Aggregate portfolio claims without double counting shared resources."""
    return run_requirement(
        "W7F-022",
        "aggregate_resource_claims",
        "Aggregate portfolio claims without double counting shared resources.",
        "W7-02",
        payload,
        **kwargs,
    )


def publish_resource_claim_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish vector and hard/soft constraints for research optimization."""
    return run_requirement(
        "W7F-024",
        "publish_resource_claim_card",
        "Publish vector and hard/soft constraints for research optimization.",
        "W7-02",
        payload,
        **kwargs,
    )


def estimate_return_or_utility_dependence(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Estimate dependence only from mature/OOS evidence."""
    return run_requirement(
        "W7F-026",
        "estimate_return_or_utility_dependence",
        "Estimate dependence only from mature/OOS evidence.",
        "W7-03",
        payload,
        **kwargs,
    )


def estimate_tail_dependence(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Estimate joint stress behavior and co-failure."""
    return run_requirement(
        "W7F-027",
        "estimate_tail_dependence",
        "Estimate joint stress behavior and co-failure.",
        "W7-03",
        payload,
        **kwargs,
    )


def measure_diversification_breakdown(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure regime-specific correlation/tail breakdown."""
    return run_requirement(
        "W7F-030",
        "measure_diversification_breakdown",
        "Measure regime-specific correlation/tail breakdown.",
        "W7-03",
        payload,
        **kwargs,
    )


def version_dependency_graph(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Version dependencies by topology/regime/source generation."""
    return run_requirement(
        "W7F-031",
        "version_dependency_graph",
        "Version dependencies by topology/regime/source generation.",
        "W7-03",
        payload,
        **kwargs,
    )


def publish_dependency_risk_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish dependency/tail uncertainty and blind spots."""
    return run_requirement(
        "W7F-032",
        "publish_dependency_risk_card",
        "Publish dependency/tail uncertainty and blind spots.",
        "W7-03",
        payload,
        **kwargs,
    )


def estimate_marginal_strategy_value(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Estimate marginal expected utility/net evidence value per next unit."""
    return run_requirement(
        "W7F-034",
        "estimate_marginal_strategy_value",
        "Estimate marginal expected utility/net evidence value per next unit.",
        "W7-04",
        payload,
        **kwargs,
    )


def estimate_crowding_decay(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Apply ecology-derived decay versus own/competitor participation."""
    return run_requirement(
        "W7F-035",
        "estimate_crowding_decay",
        "Apply ecology-derived decay versus own/competitor participation.",
        "W7-04",
        payload,
        **kwargs,
    )


def estimate_shared_capacity_bottleneck(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Respect common lender/vault/venue resource."""
    return run_requirement(
        "W7F-036",
        "estimate_shared_capacity_bottleneck",
        "Respect common lender/vault/venue resource.",
        "W7-04",
        payload,
        **kwargs,
    )


def solve_continuous_capacity_allocation(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Solve divisible allocation under convex/concave-safe assumptions."""
    return run_requirement(
        "W7F-037",
        "solve_continuous_capacity_allocation",
        "Solve divisible allocation under convex/concave-safe assumptions.",
        "W7-04",
        payload,
        **kwargs,
    )


def solve_discrete_capacity_allocation(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Solve indivisible/boolean/lot-size decisions under constraints."""
    return run_requirement(
        "W7F-038",
        "solve_discrete_capacity_allocation",
        "Solve indivisible/boolean/lot-size decisions under constraints.",
        "W7-04",
        payload,
        **kwargs,
    )


def stress_capacity_allocation(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Stress liquidity loss, crowding and source disagreement."""
    return run_requirement(
        "W7F-039",
        "stress_capacity_allocation",
        "Stress liquidity loss, crowding and source disagreement.",
        "W7-04",
        payload,
        **kwargs,
    )


def publish_capacity_allocation_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish allocations, dual/shadow values and assumption scope."""
    return run_requirement(
        "W7F-040",
        "publish_capacity_allocation_card",
        "Publish allocations, dual/shadow values and assumption scope.",
        "W7-04",
        payload,
        **kwargs,
    )


def compute_strategy_risk_contribution(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Compute marginal and component risk contributions."""
    return run_requirement(
        "W7F-042",
        "compute_strategy_risk_contribution",
        "Compute marginal and component risk contributions.",
        "W7-05",
        payload,
        **kwargs,
    )


def solve_risk_budget_allocation(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Solve risk-parity/risk-budget candidate allocation."""
    return run_requirement(
        "W7F-043",
        "solve_risk_budget_allocation",
        "Solve risk-parity/risk-budget candidate allocation.",
        "W7-05",
        payload,
        **kwargs,
    )


def stress_risk_budget(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Apply regime/cascade/provider/liquidity stress scenarios."""
    return run_requirement(
        "W7F-045",
        "stress_risk_budget",
        "Apply regime/cascade/provider/liquidity stress scenarios.",
        "W7-05",
        payload,
        **kwargs,
    )


def detect_risk_concentration(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Detect one factor/venue/stablecoin/oracle dominating loss."""
    return run_requirement(
        "W7F-046",
        "detect_risk_concentration",
        "Detect one factor/venue/stablecoin/oracle dominating loss.",
        "W7-05",
        payload,
        **kwargs,
    )


def measure_risk_budget_stability(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure turnover/sensitivity to estimation error."""
    return run_requirement(
        "W7F-047",
        "measure_risk_budget_stability",
        "Measure turnover/sensitivity to estimation error.",
        "W7-05",
        payload,
        **kwargs,
    )


def publish_risk_budget_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish tail limits, contributions, uncertainty and rejected portfolios."""
    return run_requirement(
        "W7F-048",
        "publish_risk_budget_card",
        "Publish tail limits, contributions, uncertainty and rejected portfolios.",
        "W7-05",
        payload,
        **kwargs,
    )


def partition_capital_by_time_domain(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Partition hypothetical budgets by lock duration and authority domain."""
    return run_requirement(
        "W7F-049",
        "partition_capital_by_time_domain",
        "Partition hypothetical budgets by lock duration and authority domain.",
        "W7-06",
        payload,
        **kwargs,
    )


def estimate_capital_duration_cost(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Estimate opportunity cost of locked capital by duration/regime."""
    return run_requirement(
        "W7F-050",
        "estimate_capital_duration_cost",
        "Estimate opportunity cost of locked capital by duration/regime.",
        "W7-06",
        payload,
        **kwargs,
    )


def model_fee_reserve_floor(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Preserve fee/rent/recovery reserve independent of opportunity allocation."""
    return run_requirement(
        "W7F-051",
        "model_fee_reserve_floor",
        "Preserve fee/rent/recovery reserve independent of opportunity allocation.",
        "W7-06",
        payload,
        **kwargs,
    )


def model_inventory_margin_buffer(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Model margin/liquidation buffer for non-atomic research strategies."""
    return run_requirement(
        "W7F-052",
        "model_inventory_margin_buffer",
        "Model margin/liquidation buffer for non-atomic research strategies.",
        "W7-06",
        payload,
        **kwargs,
    )


def model_settlement_and_redemption_lock(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Model capital locked in queues/redemption/bridges/claims."""
    return run_requirement(
        "W7F-053",
        "model_settlement_and_redemption_lock",
        "Model capital locked in queues/redemption/bridges/claims.",
        "W7-06",
        payload,
        **kwargs,
    )


def compare_atomic_vs_inventory_use(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Compare opportunity utility under distinct capital-duration regimes."""
    return run_requirement(
        "W7F-054",
        "compare_atomic_vs_inventory_use",
        "Compare opportunity utility under distinct capital-duration regimes.",
        "W7-06",
        payload,
        **kwargs,
    )


def stress_capital_lock_extension(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Stress delayed settlement/withdrawal/finality."""
    return run_requirement(
        "W7F-055",
        "stress_capital_lock_extension",
        "Stress delayed settlement/withdrawal/finality.",
        "W7-06",
        payload,
        **kwargs,
    )


def publish_time_domain_allocation_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish separated budgets and no-cross-subsidy constraints."""
    return run_requirement(
        "W7F-056",
        "publish_time_domain_allocation_card",
        "Publish separated budgets and no-cross-subsidy constraints.",
        "W7-06",
        payload,
        **kwargs,
    )


def estimate_capital_shadow_price(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Estimate marginal value of one additional unit of qualified capital."""
    return run_requirement(
        "W7F-057",
        "estimate_capital_shadow_price",
        "Estimate marginal value of one additional unit of qualified capital.",
        "W7-07",
        payload,
        **kwargs,
    )


def estimate_fee_budget_shadow_price(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Estimate marginal value of one additional fee/tip/rent unit."""
    return run_requirement(
        "W7F-058",
        "estimate_fee_budget_shadow_price",
        "Estimate marginal value of one additional fee/tip/rent unit.",
        "W7-07",
        payload,
        **kwargs,
    )


def estimate_margin_shadow_price(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Estimate value of extra collateral/margin capacity."""
    return run_requirement(
        "W7F-059",
        "estimate_margin_shadow_price",
        "Estimate value of extra collateral/margin capacity.",
        "W7-07",
        payload,
        **kwargs,
    )


def estimate_data_shadow_price(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Estimate value of next source quota/paid-data unit."""
    return run_requirement(
        "W7F-060",
        "estimate_data_shadow_price",
        "Estimate value of next source quota/paid-data unit.",
        "W7-07",
        payload,
        **kwargs,
    )


def estimate_compute_shadow_price(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Estimate value of next simulation/CPU/GPU unit."""
    return run_requirement(
        "W7F-061",
        "estimate_compute_shadow_price",
        "Estimate value of next simulation/CPU/GPU unit.",
        "W7-07",
        payload,
        **kwargs,
    )


def estimate_liquidity_shadow_price(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Estimate marginal value of lender/venue capacity."""
    return run_requirement(
        "W7F-062",
        "estimate_liquidity_shadow_price",
        "Estimate marginal value of lender/venue capacity.",
        "W7-07",
        payload,
        **kwargs,
    )


def compare_shadow_prices_across_regimes(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Track scarcity changes through market regimes."""
    return run_requirement(
        "W7F-063",
        "compare_shadow_prices_across_regimes",
        "Track scarcity changes through market regimes.",
        "W7-07",
        payload,
        **kwargs,
    )


def publish_shadow_price_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish marginal values with units and uncertainty."""
    return run_requirement(
        "W7F-064",
        "publish_shadow_price_card",
        "Publish marginal values with units and uncertainty.",
        "W7-07",
        payload,
        **kwargs,
    )


def build_research_resource_portfolio(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Build candidate set of data queries, captures, simulations, replications and reviews."""
    return run_requirement(
        "W7F-065",
        "build_research_resource_portfolio",
        "Build candidate set of data queries, captures, simulations, replications and reviews.",
        "W7-08",
        payload,
        **kwargs,
    )


def estimate_research_action_value(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Estimate information/qualification value from existing frontier evidence."""
    return run_requirement(
        "W7F-066",
        "estimate_research_action_value",
        "Estimate information/qualification value from existing frontier evidence.",
        "W7-08",
        payload,
        **kwargs,
    )


def estimate_research_action_cost(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Estimate credits/USD/compute/storage/human/time vector."""
    return run_requirement(
        "W7F-067",
        "estimate_research_action_cost",
        "Estimate credits/USD/compute/storage/human/time vector.",
        "W7-08",
        payload,
        **kwargs,
    )


def solve_research_budget_portfolio(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Choose bounded set under quota/compute/storage/time constraints."""
    return run_requirement(
        "W7F-068",
        "solve_research_budget_portfolio",
        "Choose bounded set under quota/compute/storage/time constraints.",
        "W7-08",
        payload,
        **kwargs,
    )


def reserve_control_sample_budget(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Protect random/reference sampling budget from adaptive starvation."""
    return run_requirement(
        "W7F-069",
        "reserve_control_sample_budget",
        "Protect random/reference sampling budget from adaptive starvation.",
        "W7-08",
        payload,
        **kwargs,
    )


def reserve_replication_budget(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Protect independent replication budget."""
    return run_requirement(
        "W7F-070",
        "reserve_replication_budget",
        "Protect independent replication budget.",
        "W7-08",
        payload,
        **kwargs,
    )


def measure_research_portfolio_yield(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure closed hypotheses/evidence gain per budget."""
    return run_requirement(
        "W7F-071",
        "measure_research_portfolio_yield",
        "Measure closed hypotheses/evidence gain per budget.",
        "W7-08",
        payload,
        **kwargs,
    )


def publish_research_budget_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish chosen/deferred actions and shadow resource prices."""
    return run_requirement(
        "W7F-072",
        "publish_research_budget_card",
        "Publish chosen/deferred actions and shadow resource prices.",
        "W7-08",
        payload,
        **kwargs,
    )


def build_strategy_policy_set(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Build qualified research strategy set with scope/evidence cards."""
    return run_requirement(
        "W7F-073",
        "build_strategy_policy_set",
        "Build qualified research strategy set with scope/evidence cards.",
        "W7-09",
        payload,
        **kwargs,
    )


def estimate_strategy_mixture_utility(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Estimate scenario-weighted portfolio utility."""
    return run_requirement(
        "W7F-074",
        "estimate_strategy_mixture_utility",
        "Estimate scenario-weighted portfolio utility.",
        "W7-09",
        payload,
        **kwargs,
    )


def solve_robust_strategy_mixture(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Solve robust mixture under uncertainty/tail/capacity constraints."""
    return run_requirement(
        "W7F-075",
        "solve_robust_strategy_mixture",
        "Solve robust mixture under uncertainty/tail/capacity constraints.",
        "W7-09",
        payload,
        **kwargs,
    )


def compare_champion_vs_mixture(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Compare single best historical strategy to diversified mixture."""
    return run_requirement(
        "W7F-076",
        "compare_champion_vs_mixture",
        "Compare single best historical strategy to diversified mixture.",
        "W7-09",
        payload,
        **kwargs,
    )


def measure_strategy_turnover_cost(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure cost/instability from frequent reallocation."""
    return run_requirement(
        "W7F-077",
        "measure_strategy_turnover_cost",
        "Measure cost/instability from frequent reallocation.",
        "W7-09",
        payload,
        **kwargs,
    )


def measure_regime_specialist_value(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure specialist strategies versus universal mixture."""
    return run_requirement(
        "W7F-078",
        "measure_regime_specialist_value",
        "Measure specialist strategies versus universal mixture.",
        "W7-09",
        payload,
        **kwargs,
    )


def detect_ensemble_false_diversification(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Detect correlated models sharing same data/mechanism failure."""
    return run_requirement(
        "W7F-079",
        "detect_ensemble_false_diversification",
        "Detect correlated models sharing same data/mechanism failure.",
        "W7-09",
        payload,
        **kwargs,
    )


def publish_strategy_mixture_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish mixture weights as research output only."""
    return run_requirement(
        "W7F-080",
        "publish_strategy_mixture_card",
        "Publish mixture weights as research output only.",
        "W7-09",
        payload,
        **kwargs,
    )


def encode_capacity_constraints(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Encode lender/venue/shared-liquidity capacity."""
    return run_requirement(
        "W7F-084",
        "encode_capacity_constraints",
        "Encode lender/venue/shared-liquidity capacity.",
        "W7-10",
        payload,
        **kwargs,
    )


def backtest_allocator_on_frozen_evidence(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Run allocator on sealed OOS evidence without future labels."""
    return run_requirement(
        "W7F-089",
        "backtest_allocator_on_frozen_evidence",
        "Run allocator on sealed OOS evidence without future labels.",
        "W7-11",
        payload,
        **kwargs,
    )


def measure_allocation_reality_gap(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Compare proposed versus actually available/realized evidence when available."""
    return run_requirement(
        "W7F-090",
        "measure_allocation_reality_gap",
        "Compare proposed versus actually available/realized evidence when available.",
        "W7-11",
        payload,
        **kwargs,
    )


def measure_allocator_regret(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Compare proposal against ex-post oracle only as clearly labeled counterfactual."""
    return run_requirement(
        "W7F-092",
        "measure_allocator_regret",
        "Compare proposal against ex-post oracle only as clearly labeled counterfactual.",
        "W7-11",
        payload,
        **kwargs,
    )


def measure_allocator_turnover(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure unnecessary reallocation and resource churn."""
    return run_requirement(
        "W7F-093",
        "measure_allocator_turnover",
        "Measure unnecessary reallocation and resource churn.",
        "W7-11",
        payload,
        **kwargs,
    )


def feed_allocator_gap_to_frontier(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Feed missing data/model/constraint capability to existing frontier."""
    return run_requirement(
        "W7F-095",
        "feed_allocator_gap_to_frontier",
        "Feed missing data/model/constraint capability to existing frontier.",
        "W7-11",
        payload,
        **kwargs,
    )


__all__ = [
    'bind_strategy_capacity_curve',
    'bind_strategy_cost_curve',
    'bind_strategy_uncertainty',
    'bind_strategy_time_domain',
    'bind_strategy_access_constraints',
    'bind_strategy_ecology_risk',
    'publish_strategy_evidence_card',
    'define_soft_resource_cost',
    'bind_resource_time_window',
    'aggregate_resource_claims',
    'publish_resource_claim_card',
    'estimate_return_or_utility_dependence',
    'estimate_tail_dependence',
    'measure_diversification_breakdown',
    'version_dependency_graph',
    'publish_dependency_risk_card',
    'estimate_marginal_strategy_value',
    'estimate_crowding_decay',
    'estimate_shared_capacity_bottleneck',
    'solve_continuous_capacity_allocation',
    'solve_discrete_capacity_allocation',
    'stress_capacity_allocation',
    'publish_capacity_allocation_card',
    'compute_strategy_risk_contribution',
    'solve_risk_budget_allocation',
    'stress_risk_budget',
    'detect_risk_concentration',
    'measure_risk_budget_stability',
    'publish_risk_budget_card',
    'partition_capital_by_time_domain',
    'estimate_capital_duration_cost',
    'model_fee_reserve_floor',
    'model_inventory_margin_buffer',
    'model_settlement_and_redemption_lock',
    'compare_atomic_vs_inventory_use',
    'stress_capital_lock_extension',
    'publish_time_domain_allocation_card',
    'estimate_capital_shadow_price',
    'estimate_fee_budget_shadow_price',
    'estimate_margin_shadow_price',
    'estimate_data_shadow_price',
    'estimate_compute_shadow_price',
    'estimate_liquidity_shadow_price',
    'compare_shadow_prices_across_regimes',
    'publish_shadow_price_card',
    'build_research_resource_portfolio',
    'estimate_research_action_value',
    'estimate_research_action_cost',
    'solve_research_budget_portfolio',
    'reserve_control_sample_budget',
    'reserve_replication_budget',
    'measure_research_portfolio_yield',
    'publish_research_budget_card',
    'build_strategy_policy_set',
    'estimate_strategy_mixture_utility',
    'solve_robust_strategy_mixture',
    'compare_champion_vs_mixture',
    'measure_strategy_turnover_cost',
    'measure_regime_specialist_value',
    'detect_ensemble_false_diversification',
    'publish_strategy_mixture_card',
    'encode_capacity_constraints',
    'backtest_allocator_on_frozen_evidence',
    'measure_allocation_reality_gap',
    'measure_allocator_regret',
    'measure_allocator_turnover',
    'feed_allocator_gap_to_frontier'
]

"""PR-356 corrective completion adapters for W4 residual requirements."""

from __future__ import annotations

from typing import Any, Mapping

from src.research.pr356_completion_contracts import run_requirement

def compare_source_to_state(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure discrepancies between provider/indexed data and independently reconstructed state."""
    return run_requirement(
        "W4F-010",
        "compare_source_to_state",
        "Measure discrepancies between provider/indexed data and independently reconstructed state.",
        "W4-01",
        payload,
        **kwargs,
    )


def compare_state_to_local_math(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure decoder/math/rounding/units disagreement."""
    return run_requirement(
        "W4F-011",
        "compare_state_to_local_math",
        "Measure decoder/math/rounding/units disagreement.",
        "W4-01",
        payload,
        **kwargs,
    )


def compare_math_to_simulation(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure message/account/program/runtime divergence."""
    return run_requirement(
        "W4F-012",
        "compare_math_to_simulation",
        "Measure message/account/program/runtime divergence.",
        "W4-01",
        payload,
        **kwargs,
    )


def compare_simulation_to_paper_outcome(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure latency/survival/cost assumptions without claiming actual landing."""
    return run_requirement(
        "W4F-013",
        "compare_simulation_to_paper_outcome",
        "Measure latency/survival/cost assumptions without claiming actual landing.",
        "W4-01",
        payload,
        **kwargs,
    )


def compare_simulation_to_finalized(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """When actual authorized outcomes exist, compare exact finalized deltas to simulation."""
    return run_requirement(
        "W4F-014",
        "compare_simulation_to_finalized",
        "When actual authorized outcomes exist, compare exact finalized deltas to simulation.",
        "W4-01",
        payload,
        **kwargs,
    )


def publish_reality_gap_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish per-mechanism calibration and abstention thresholds."""
    return run_requirement(
        "W4F-016",
        "publish_reality_gap_card",
        "Publish per-mechanism calibration and abstention thresholds.",
        "W4-01",
        payload,
        **kwargs,
    )


def select_benchmark_universe(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Select bounded markets/mechanisms with declared inclusion rules."""
    return run_requirement(
        "W4F-017",
        "select_benchmark_universe",
        "Select bounded markets/mechanisms with declared inclusion rules.",
        "W4-02",
        payload,
        **kwargs,
    )


def sample_anomaly_windows(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Sample candidate/event windows without leaking future labels."""
    return run_requirement(
        "W4F-018",
        "sample_anomaly_windows",
        "Sample candidate/event windows without leaking future labels.",
        "W4-02",
        payload,
        **kwargs,
    )


def sample_normal_control_windows(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Sample ordinary periods independently of detector output."""
    return run_requirement(
        "W4F-019",
        "sample_normal_control_windows",
        "Sample ordinary periods independently of detector output.",
        "W4-02",
        payload,
        **kwargs,
    )


def sample_blind_spot_windows(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Sample areas with known missingness or semantic uncertainty."""
    return run_requirement(
        "W4F-020",
        "sample_blind_spot_windows",
        "Sample areas with known missingness or semantic uncertainty.",
        "W4-02",
        payload,
        **kwargs,
    )


def materialize_revision_scenarios(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Preserve first-published and later-revised versions separately."""
    return run_requirement(
        "W4F-021",
        "materialize_revision_scenarios",
        "Preserve first-published and later-revised versions separately.",
        "W4-02",
        payload,
        **kwargs,
    )


def materialize_latency_scenarios(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Replay realistic source/decision/simulation delays."""
    return run_requirement(
        "W4F-022",
        "materialize_latency_scenarios",
        "Replay realistic source/decision/simulation delays.",
        "W4-02",
        payload,
        **kwargs,
    )


def verify_corpus_replay(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Reproduce benchmark state from sealed inputs only."""
    return run_requirement(
        "W4F-024",
        "verify_corpus_replay",
        "Reproduce benchmark state from sealed inputs only.",
        "W4-02",
        payload,
        **kwargs,
    )


def define_reference_search_budget(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Define exact universe, routes, sizes, mechanisms and compute budget."""
    return run_requirement(
        "W4F-025",
        "define_reference_search_budget",
        "Define exact universe, routes, sizes, mechanisms and compute budget.",
        "W4-03",
        payload,
        **kwargs,
    )


def run_reference_route_search(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Run stronger exhaustive/near-exhaustive search within declared bounds."""
    return run_requirement(
        "W4F-026",
        "run_reference_route_search",
        "Run stronger exhaustive/near-exhaustive search within declared bounds.",
        "W4-03",
        payload,
        **kwargs,
    )


def run_candidate_system_search(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Run normal production-like cheap search on same frozen state."""
    return run_requirement(
        "W4F-027",
        "run_candidate_system_search",
        "Run normal production-like cheap search on same frozen state.",
        "W4-03",
        payload,
        **kwargs,
    )


def match_reference_and_detected_opportunities(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Match variants by identity, amount band and mechanism."""
    return run_requirement(
        "W4F-028",
        "match_reference_and_detected_opportunities",
        "Match variants by identity, amount band and mechanism.",
        "W4-03",
        payload,
        **kwargs,
    )


def attribute_search_miss(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Attribute miss to graph coverage, amount grid, stale state, heuristic pruning or semantics."""
    return run_requirement(
        "W4F-031",
        "attribute_search_miss",
        "Attribute miss to graph coverage, amount grid, stale state, heuristic pruning or semantics.",
        "W4-03",
        payload,
        **kwargs,
    )


def publish_search_completeness_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish recall with explicit reference-search limitations."""
    return run_requirement(
        "W4F-032",
        "publish_search_completeness_card",
        "Publish recall with explicit reference-search limitations.",
        "W4-03",
        payload,
        **kwargs,
    )


def build_leave_one_market_out_split(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Hold out an entire target market."""
    return run_requirement(
        "W4F-033",
        "build_leave_one_market_out_split",
        "Hold out an entire target market.",
        "W4-04",
        payload,
        **kwargs,
    )


def build_leave_one_regime_out_split(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Hold out stress/liquidity/funding/config regime."""
    return run_requirement(
        "W4F-034",
        "build_leave_one_regime_out_split",
        "Hold out stress/liquidity/funding/config regime.",
        "W4-04",
        payload,
        **kwargs,
    )


def build_leave_one_mechanism_out_split(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Hold out a financial mechanism family."""
    return run_requirement(
        "W4F-035",
        "build_leave_one_mechanism_out_split",
        "Hold out a financial mechanism family.",
        "W4-04",
        payload,
        **kwargs,
    )


def evaluate_target_only_baseline(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Train only on target historical training slice where allowed."""
    return run_requirement(
        "W4F-036",
        "evaluate_target_only_baseline",
        "Train only on target historical training slice where allowed.",
        "W4-04",
        payload,
        **kwargs,
    )


def evaluate_pooled_baseline(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Evaluate simple pooled-market training."""
    return run_requirement(
        "W4F-037",
        "evaluate_pooled_baseline",
        "Evaluate simple pooled-market training.",
        "W4-04",
        payload,
        **kwargs,
    )


def evaluate_transfer_challenger(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Evaluate shared mechanism/topology representation with local adapter."""
    return run_requirement(
        "W4F-038",
        "evaluate_transfer_challenger",
        "Evaluate shared mechanism/topology representation with local adapter.",
        "W4-04",
        payload,
        **kwargs,
    )


def measure_generalization_gap(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure target/regime/mechanism generalization and negative transfer."""
    return run_requirement(
        "W4F-039",
        "measure_generalization_gap",
        "Measure target/regime/mechanism generalization and negative transfer.",
        "W4-04",
        payload,
        **kwargs,
    )


def publish_generalization_leaderboard(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish per-task results without one universal model winner claim."""
    return run_requirement(
        "W4F-040",
        "publish_generalization_leaderboard",
        "Publish per-task results without one universal model winner claim.",
        "W4-04",
        payload,
        **kwargs,
    )


def evaluate_interval_calibration(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure empirical coverage and interval width."""
    return run_requirement(
        "W4F-042",
        "evaluate_interval_calibration",
        "Measure empirical coverage and interval width.",
        "W4-05",
        payload,
        **kwargs,
    )


def evaluate_selective_risk_curve(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure error/utility as model abstains on uncertain cases."""
    return run_requirement(
        "W4F-043",
        "evaluate_selective_risk_curve",
        "Measure error/utility as model abstains on uncertain cases.",
        "W4-05",
        payload,
        **kwargs,
    )


def evaluate_conformal_challenger(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Evaluate allowed conformal/interval challenger under drift."""
    return run_requirement(
        "W4F-044",
        "evaluate_conformal_challenger",
        "Evaluate allowed conformal/interval challenger under drift.",
        "W4-05",
        payload,
        **kwargs,
    )


def measure_abstention_utility(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure economic/research value at fixed accepted coverage."""
    return run_requirement(
        "W4F-045",
        "measure_abstention_utility",
        "Measure economic/research value at fixed accepted coverage.",
        "W4-05",
        payload,
        **kwargs,
    )


def stress_calibration_by_regime(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Break calibration down by volatility/liquidity/topology regimes."""
    return run_requirement(
        "W4F-046",
        "stress_calibration_by_regime",
        "Break calibration down by volatility/liquidity/topology regimes.",
        "W4-05",
        payload,
        **kwargs,
    )


def detect_overconfident_failure_cluster(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Find clusters of high-confidence wrong predictions."""
    return run_requirement(
        "W4F-047",
        "detect_overconfident_failure_cluster",
        "Find clusters of high-confidence wrong predictions.",
        "W4-05",
        payload,
        **kwargs,
    )


def publish_calibration_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish calibration, coverage, abstention and regime failures."""
    return run_requirement(
        "W4F-048",
        "publish_calibration_card",
        "Publish calibration, coverage, abstention and regime failures.",
        "W4-05",
        payload,
        **kwargs,
    )


def detect_label_overlap_leakage(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Detect overlapping horizons and train/test contamination."""
    return run_requirement(
        "W4F-051",
        "detect_label_overlap_leakage",
        "Detect overlapping horizons and train/test contamination.",
        "W4-06",
        payload,
        **kwargs,
    )


def detect_revision_and_availability_leakage(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Detect future revisions or first-seen violations."""
    return run_requirement(
        "W4F-052",
        "detect_revision_and_availability_leakage",
        "Detect future revisions or first-seen violations.",
        "W4-06",
        payload,
        **kwargs,
    )


def run_outcome_blind_agent_test(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Evaluate research agent on post-freeze/new outcomes it cannot know from pretraining."""
    return run_requirement(
        "W4F-053",
        "run_outcome_blind_agent_test",
        "Evaluate research agent on post-freeze/new outcomes it cannot know from pretraining.",
        "W4-06",
        payload,
        **kwargs,
    )


def estimate_multiple_try_penalty(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Quantify uncertainty inflation from many attempted hypotheses/configurations."""
    return run_requirement(
        "W4F-054",
        "estimate_multiple_try_penalty",
        "Quantify uncertainty inflation from many attempted hypotheses/configurations.",
        "W4-06",
        payload,
        **kwargs,
    )


def downgrade_overfit_claim(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Downgrade supported claim when research process violates frozen protocol."""
    return run_requirement(
        "W4F-055",
        "downgrade_overfit_claim",
        "Downgrade supported claim when research process violates frozen protocol.",
        "W4-06",
        payload,
        **kwargs,
    )


def publish_research_integrity_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish trial count, leakage checks, holdout history and integrity verdict."""
    return run_requirement(
        "W4F-056",
        "publish_research_integrity_card",
        "Publish trial count, leakage checks, holdout history and integrity verdict.",
        "W4-06",
        payload,
        **kwargs,
    )


def publish_red_team_resilience_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish detection, abstention and failure-mode coverage."""
    return run_requirement(
        "W4F-064",
        "publish_red_team_resilience_card",
        "Publish detection, abstention and failure-mode coverage.",
        "W4-07",
        payload,
        **kwargs,
    )


def extract_empirical_stress_seed(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Extract stress seed from real incident/outage/market episode."""
    return run_requirement(
        "W4F-065",
        "extract_empirical_stress_seed",
        "Extract stress seed from real incident/outage/market episode.",
        "W4-08",
        payload,
        **kwargs,
    )


def fit_stress_parameter_bounds(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Fit conservative bounds from observed distributions."""
    return run_requirement(
        "W4F-066",
        "fit_stress_parameter_bounds",
        "Fit conservative bounds from observed distributions.",
        "W4-08",
        payload,
        **kwargs,
    )


def generate_counterfactual_stress_family(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Generate bounded variations with explicit synthetic label."""
    return run_requirement(
        "W4F-067",
        "generate_counterfactual_stress_family",
        "Generate bounded variations with explicit synthetic label.",
        "W4-08",
        payload,
        **kwargs,
    )


def preserve_real_synthetic_boundary(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Ensure generated stress never enters actual-outcome labels."""
    return run_requirement(
        "W4F-068",
        "preserve_real_synthetic_boundary",
        "Ensure generated stress never enters actual-outcome labels.",
        "W4-08",
        payload,
        **kwargs,
    )


def evaluate_model_under_stress(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Evaluate calibration, abstention and state semantics under stress."""
    return run_requirement(
        "W4F-069",
        "evaluate_model_under_stress",
        "Evaluate calibration, abstention and state semantics under stress.",
        "W4-08",
        payload,
        **kwargs,
    )


def evaluate_strategy_under_stress(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Evaluate exact route/capacity/debt closure where applicable."""
    return run_requirement(
        "W4F-070",
        "evaluate_strategy_under_stress",
        "Evaluate exact route/capacity/debt closure where applicable.",
        "W4-08",
        payload,
        **kwargs,
    )


def measure_stress_generalization(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Compare unseen real stress to synthetic curriculum."""
    return run_requirement(
        "W4F-071",
        "measure_stress_generalization",
        "Compare unseen real stress to synthetic curriculum.",
        "W4-08",
        payload,
        **kwargs,
    )


def publish_stress_curriculum_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish seeds, bounds, synthetic status and observed transfer value."""
    return run_requirement(
        "W4F-072",
        "publish_stress_curriculum_card",
        "Publish seeds, bounds, synthetic status and observed transfer value.",
        "W4-08",
        payload,
        **kwargs,
    )


def run_independent_data_replay(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Rebuild normalized data/state in isolated process/environment."""
    return run_requirement(
        "W4F-074",
        "run_independent_data_replay",
        "Rebuild normalized data/state in isolated process/environment.",
        "W4-09",
        payload,
        **kwargs,
    )


def run_independent_model_replay(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Reproduce frozen training/evaluation where allowed."""
    return run_requirement(
        "W4F-075",
        "run_independent_model_replay",
        "Reproduce frozen training/evaluation where allowed.",
        "W4-09",
        payload,
        **kwargs,
    )


def run_independent_verdict_check(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Recompute key metrics and verdict thresholds."""
    return run_requirement(
        "W4F-076",
        "run_independent_verdict_check",
        "Recompute key metrics and verdict thresholds.",
        "W4-09",
        payload,
        **kwargs,
    )


def measure_replication_cost(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure compute/time/manual intervention."""
    return run_requirement(
        "W4F-078",
        "measure_replication_cost",
        "Measure compute/time/manual intervention.",
        "W4-09",
        payload,
        **kwargs,
    )


def publish_replication_certificate(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish research-only reproducibility certificate bound to receipt."""
    return run_requirement(
        "W4F-080",
        "publish_replication_certificate",
        "Publish research-only reproducibility certificate bound to receipt.",
        "W4-09",
        payload,
        **kwargs,
    )


def aggregate_capability_metrics(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Aggregate reachability, recall, calibration, transfer, source value, drift and replication metrics."""
    return run_requirement(
        "W4F-081",
        "aggregate_capability_metrics",
        "Aggregate reachability, recall, calibration, transfer, source value, drift and replication metrics.",
        "W4-10",
        payload,
        **kwargs,
    )


def score_capability_gap(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure gap versus preregistered capability threshold."""
    return run_requirement(
        "W4F-082",
        "score_capability_gap",
        "Measure gap versus preregistered capability threshold.",
        "W4-10",
        payload,
        **kwargs,
    )


def rank_benchmark_priority(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Rank next benchmark by uncertainty, impact, cost and dependency readiness."""
    return run_requirement(
        "W4F-083",
        "rank_benchmark_priority",
        "Rank next benchmark by uncertainty, impact, cost and dependency readiness.",
        "W4-10",
        payload,
        **kwargs,
    )


def select_curriculum_task(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Select next research task without changing live authority."""
    return run_requirement(
        "W4F-084",
        "select_curriculum_task",
        "Select next research task without changing live authority.",
        "W4-10",
        payload,
        **kwargs,
    )


def detect_benchmark_overfitting(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Detect repeated optimization to one benchmark/corpus."""
    return run_requirement(
        "W4F-085",
        "detect_benchmark_overfitting",
        "Detect repeated optimization to one benchmark/corpus.",
        "W4-10",
        payload,
        **kwargs,
    )


def rotate_hidden_challenge(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Rotate sealed future/market/mechanism challenge set."""
    return run_requirement(
        "W4F-086",
        "rotate_hidden_challenge",
        "Rotate sealed future/market/mechanism challenge set.",
        "W4-10",
        payload,
        **kwargs,
    )


def measure_learning_progress(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure whether capability improves across waves without forgetting."""
    return run_requirement(
        "W4F-087",
        "measure_learning_progress",
        "Measure whether capability improves across waves without forgetting.",
        "W4-10",
        payload,
        **kwargs,
    )


def publish_scientific_leaderboard(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish capability cards and unresolved weaknesses; no political-style ranking issue here."""
    return run_requirement(
        "W4F-088",
        "publish_scientific_leaderboard",
        "Publish capability cards and unresolved weaknesses; no political-style ranking issue here.",
        "W4-10",
        payload,
        **kwargs,
    )


__all__ = [
    'compare_source_to_state',
    'compare_state_to_local_math',
    'compare_math_to_simulation',
    'compare_simulation_to_paper_outcome',
    'compare_simulation_to_finalized',
    'publish_reality_gap_card',
    'select_benchmark_universe',
    'sample_anomaly_windows',
    'sample_normal_control_windows',
    'sample_blind_spot_windows',
    'materialize_revision_scenarios',
    'materialize_latency_scenarios',
    'verify_corpus_replay',
    'define_reference_search_budget',
    'run_reference_route_search',
    'run_candidate_system_search',
    'match_reference_and_detected_opportunities',
    'attribute_search_miss',
    'publish_search_completeness_card',
    'build_leave_one_market_out_split',
    'build_leave_one_regime_out_split',
    'build_leave_one_mechanism_out_split',
    'evaluate_target_only_baseline',
    'evaluate_pooled_baseline',
    'evaluate_transfer_challenger',
    'measure_generalization_gap',
    'publish_generalization_leaderboard',
    'evaluate_interval_calibration',
    'evaluate_selective_risk_curve',
    'evaluate_conformal_challenger',
    'measure_abstention_utility',
    'stress_calibration_by_regime',
    'detect_overconfident_failure_cluster',
    'publish_calibration_card',
    'detect_label_overlap_leakage',
    'detect_revision_and_availability_leakage',
    'run_outcome_blind_agent_test',
    'estimate_multiple_try_penalty',
    'downgrade_overfit_claim',
    'publish_research_integrity_card',
    'publish_red_team_resilience_card',
    'extract_empirical_stress_seed',
    'fit_stress_parameter_bounds',
    'generate_counterfactual_stress_family',
    'preserve_real_synthetic_boundary',
    'evaluate_model_under_stress',
    'evaluate_strategy_under_stress',
    'measure_stress_generalization',
    'publish_stress_curriculum_card',
    'run_independent_data_replay',
    'run_independent_model_replay',
    'run_independent_verdict_check',
    'measure_replication_cost',
    'publish_replication_certificate',
    'aggregate_capability_metrics',
    'score_capability_gap',
    'rank_benchmark_priority',
    'select_curriculum_task',
    'detect_benchmark_overfitting',
    'rotate_hidden_challenge',
    'measure_learning_progress',
    'publish_scientific_leaderboard'
]

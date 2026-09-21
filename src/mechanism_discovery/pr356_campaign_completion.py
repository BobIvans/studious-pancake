"""PR-356 corrective completion adapters for W3 residual requirements."""

from __future__ import annotations

from typing import Any, Mapping

from src.research.pr356_completion_contracts import run_requirement

def build_campaign_source_manifest(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Bind source schema/version/terms/cost/finality/availability assumptions."""
    return run_requirement(
        "W3F-009",
        "build_campaign_source_manifest",
        "Bind source schema/version/terms/cost/finality/availability assumptions.",
        "W3-01",
        payload,
        **kwargs,
    )


def capture_campaign_raw_events(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Capture bounded raw payload hashes/cursors with gap and retry evidence."""
    return run_requirement(
        "W3F-010",
        "capture_campaign_raw_events",
        "Capture bounded raw payload hashes/cursors with gap and retry evidence.",
        "W3-01",
        payload,
        **kwargs,
    )


def materialize_campaign_state_frames(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Build coherent point-in-time state frames from allowed observations only."""
    return run_requirement(
        "W3F-011",
        "materialize_campaign_state_frames",
        "Build coherent point-in-time state frames from allowed observations only.",
        "W3-01",
        payload,
        **kwargs,
    )


def sample_random_control_windows(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Sample ordinary periods independently of anomaly detection."""
    return run_requirement(
        "W3F-012",
        "sample_random_control_windows",
        "Sample ordinary periods independently of anomaly detection.",
        "W3-01",
        payload,
        **kwargs,
    )


def sample_reference_search_windows(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Sample declared-universe windows for missed-opportunity measurement."""
    return run_requirement(
        "W3F-013",
        "sample_reference_search_windows",
        "Sample declared-universe windows for missed-opportunity measurement.",
        "W3-01",
        payload,
        **kwargs,
    )


def freeze_campaign_dataset(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Hash raw/state/control/reference manifests and exact cutoffs."""
    return run_requirement(
        "W3F-014",
        "freeze_campaign_dataset",
        "Hash raw/state/control/reference manifests and exact cutoffs.",
        "W3-01",
        payload,
        **kwargs,
    )


def replay_campaign_dataset(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Reproduce normalized state without hidden latest-state reads."""
    return run_requirement(
        "W3F-015",
        "replay_campaign_dataset",
        "Reproduce normalized state without hidden latest-state reads.",
        "W3-01",
        payload,
        **kwargs,
    )


def score_campaign_data_quality(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Report completeness/freshness/gaps/revisions/coverage separately from alpha."""
    return run_requirement(
        "W3F-016",
        "score_campaign_data_quality",
        "Report completeness/freshness/gaps/revisions/coverage separately from alpha.",
        "W3-01",
        payload,
        **kwargs,
    )


def assign_episode_trigger(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Record first eligible trigger and available-at time."""
    return run_requirement(
        "W3F-018",
        "assign_episode_trigger",
        "Record first eligible trigger and available-at time.",
        "W3-02",
        payload,
        **kwargs,
    )


def define_episode_horizon(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Define survival/economic/forecast horizon before outcome."""
    return run_requirement(
        "W3F-019",
        "define_episode_horizon",
        "Define survival/economic/forecast horizon before outcome.",
        "W3-02",
        payload,
        **kwargs,
    )


def audit_episode_independence(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Estimate dependence/interference among episodes and cluster splits accordingly."""
    return run_requirement(
        "W3F-023",
        "audit_episode_independence",
        "Estimate dependence/interference among episodes and cluster splits accordingly.",
        "W3-02",
        payload,
        **kwargs,
    )


def publish_episode_ledger_view(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish read-only research view linked to existing evidence, not a second economic ledger."""
    return run_requirement(
        "W3F-024",
        "publish_episode_ledger_view",
        "Publish read-only research view linked to existing evidence, not a second economic ledger.",
        "W3-02",
        payload,
        **kwargs,
    )


def stress_state_reachability(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Stress caps, race, stale state, intermediate obligations and failure rollback."""
    return run_requirement(
        "W3F-030",
        "stress_state_reachability",
        "Stress caps, race, stale state, intermediate obligations and failure rollback.",
        "W3-03",
        payload,
        **kwargs,
    )


def attribute_reachability_gain(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Attribute gain to specific protocol semantics rather than model complexity."""
    return run_requirement(
        "W3F-031",
        "attribute_reachability_gain",
        "Attribute gain to specific protocol semantics rather than model complexity.",
        "W3-03",
        payload,
        **kwargs,
    )


def build_topology_snapshot_sequence(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Version graph structure and economic rights through time."""
    return run_requirement(
        "W3F-033",
        "build_topology_snapshot_sequence",
        "Version graph structure and economic rights through time.",
        "W3-04",
        payload,
        **kwargs,
    )


def derive_mechanism_motif_signature(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Create mechanism fingerprint independent of ticker/protocol name."""
    return run_requirement(
        "W3F-034",
        "derive_mechanism_motif_signature",
        "Create mechanism fingerprint independent of ticker/protocol name.",
        "W3-04",
        payload,
        **kwargs,
    )


def train_target_only_mechanism_baseline(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Train target-market-only model as mandatory comparator."""
    return run_requirement(
        "W3F-035",
        "train_target_only_mechanism_baseline",
        "Train target-market-only model as mandatory comparator.",
        "W3-04",
        payload,
        **kwargs,
    )


def train_pooled_market_baseline(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Train pooled cross-market model."""
    return run_requirement(
        "W3F-036",
        "train_pooled_market_baseline",
        "Train pooled cross-market model.",
        "W3-04",
        payload,
        **kwargs,
    )


def train_motif_transfer_challenger(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Transfer shared mechanism representation plus local adapter."""
    return run_requirement(
        "W3F-037",
        "train_motif_transfer_challenger",
        "Transfer shared mechanism representation plus local adapter.",
        "W3-04",
        payload,
        **kwargs,
    )


def measure_sample_efficiency_gain(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure episodes/time needed to reach declared calibration/utility threshold."""
    return run_requirement(
        "W3F-038",
        "measure_sample_efficiency_gain",
        "Measure episodes/time needed to reach declared calibration/utility threshold.",
        "W3-04",
        payload,
        **kwargs,
    )


def measure_topology_negative_transfer(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure failure under changed topology/rights/regimes."""
    return run_requirement(
        "W3F-039",
        "measure_topology_negative_transfer",
        "Measure failure under changed topology/rights/regimes.",
        "W3-04",
        payload,
        **kwargs,
    )


def publish_graph_transfer_verdict(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Promote transfer only if target-only is beaten on locked future data."""
    return run_requirement(
        "W3F-040",
        "publish_graph_transfer_verdict",
        "Promote transfer only if target-only is beaten on locked future data.",
        "W3-04",
        payload,
        **kwargs,
    )


def classify_information_regime(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Classify visibility/access/order/update commitment regime."""
    return run_requirement(
        "W3F-041",
        "classify_information_regime",
        "Classify visibility/access/order/update commitment regime.",
        "W3-05",
        payload,
        **kwargs,
    )


def align_information_reveal_timeline(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Align observe/commit/reveal/update/inclusion times."""
    return run_requirement(
        "W3F-042",
        "align_information_reveal_timeline",
        "Align observe/commit/reveal/update/inclusion times.",
        "W3-05",
        payload,
        **kwargs,
    )


def measure_private_public_execution_gap(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Compare public versus permitted private/RFQ execution quality."""
    return run_requirement(
        "W3F-044",
        "measure_private_public_execution_gap",
        "Compare public versus permitted private/RFQ execution quality.",
        "W3-05",
        payload,
        **kwargs,
    )


def measure_update_right_value(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure OEV/update-right outcome under allowed protocols."""
    return run_requirement(
        "W3F-045",
        "measure_update_right_value",
        "Measure OEV/update-right outcome under allowed protocols.",
        "W3-05",
        payload,
        **kwargs,
    )


def measure_preconfirmation_value(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure inclusion/reliability improvement versus cost."""
    return run_requirement(
        "W3F-046",
        "measure_preconfirmation_value",
        "Measure inclusion/reliability improvement versus cost.",
        "W3-05",
        payload,
        **kwargs,
    )


def stress_information_regime_change(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Test model degradation when visibility regime changes."""
    return run_requirement(
        "W3F-047",
        "stress_information_regime_change",
        "Test model degradation when visibility regime changes.",
        "W3-05",
        payload,
        **kwargs,
    )


def publish_information_regime_verdict(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish predictive/operational value without harmful execution authority."""
    return run_requirement(
        "W3F-048",
        "publish_information_regime_verdict",
        "Publish predictive/operational value without harmful execution authority.",
        "W3-05",
        payload,
        **kwargs,
    )


def define_equal_budget_source_trials(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Create baseline, +A, +B, +A+B trials with equal compute/data budget."""
    return run_requirement(
        "W3F-049",
        "define_equal_budget_source_trials",
        "Create baseline, +A, +B, +A+B trials with equal compute/data budget.",
        "W3-06",
        payload,
        **kwargs,
    )


def measure_incremental_forecast_value(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure OOS loss/calibration improvement."""
    return run_requirement(
        "W3F-050",
        "measure_incremental_forecast_value",
        "Measure OOS loss/calibration improvement.",
        "W3-06",
        payload,
        **kwargs,
    )


def measure_incremental_candidate_value(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure qualified candidates and false-positive reduction."""
    return run_requirement(
        "W3F-051",
        "measure_incremental_candidate_value",
        "Measure qualified candidates and false-positive reduction.",
        "W3-06",
        payload,
        **kwargs,
    )


def measure_source_latency_cost(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure data delay, gaps, request cost and storage cost."""
    return run_requirement(
        "W3F-052",
        "measure_source_latency_cost",
        "Measure data delay, gaps, request cost and storage cost.",
        "W3-06",
        payload,
        **kwargs,
    )


def measure_source_redundancy(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Estimate overlap with existing sources and provider concentration."""
    return run_requirement(
        "W3F-053",
        "measure_source_redundancy",
        "Estimate overlap with existing sources and provider concentration.",
        "W3-06",
        payload,
        **kwargs,
    )


def audit_adaptive_source_selection_bias(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Check whether source allocator hides missed events."""
    return run_requirement(
        "W3F-054",
        "audit_adaptive_source_selection_bias",
        "Check whether source allocator hides missed events.",
        "W3-06",
        payload,
        **kwargs,
    )


def retire_low_value_source(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Recommend disable/downgrade when value is not robust."""
    return run_requirement(
        "W3F-055",
        "retire_low_value_source",
        "Recommend disable/downgrade when value is not robust.",
        "W3-06",
        payload,
        **kwargs,
    )


def publish_source_value_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish source value, cost, regimes, blind spots and recheck date."""
    return run_requirement(
        "W3F-056",
        "publish_source_value_card",
        "Publish source value, cost, regimes, blind spots and recheck date.",
        "W3-06",
        payload,
        **kwargs,
    )


def time_to_first_dossier(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure time from discovery to first machine/human-readable dossier."""
    return run_requirement(
        "W3F-057",
        "time_to_first_dossier",
        "Measure time from discovery to first machine/human-readable dossier.",
        "W3-07",
        payload,
        **kwargs,
    )


def score_semantic_dossier_accuracy(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Compare inferred inputs/outputs/rights/timing/capacity against verified semantics."""
    return run_requirement(
        "W3F-058",
        "score_semantic_dossier_accuracy",
        "Compare inferred inputs/outputs/rights/timing/capacity against verified semantics.",
        "W3-07",
        payload,
        **kwargs,
    )


def count_human_semantic_corrections(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Count substantive corrections required before replay."""
    return run_requirement(
        "W3F-059",
        "count_human_semantic_corrections",
        "Count substantive corrections required before replay.",
        "W3-07",
        payload,
        **kwargs,
    )


def measure_minimum_data_plan_quality(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure whether requested data was sufficient and not wasteful."""
    return run_requirement(
        "W3F-060",
        "measure_minimum_data_plan_quality",
        "Measure whether requested data was sufficient and not wasteful.",
        "W3-07",
        payload,
        **kwargs,
    )


def time_to_first_falsifiable_hypothesis(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure time from discovery to preregistered test."""
    return run_requirement(
        "W3F-061",
        "time_to_first_falsifiable_hypothesis",
        "Measure time from discovery to preregistered test.",
        "W3-07",
        payload,
        **kwargs,
    )


def measure_quarantine_precision(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure true unsafe/unknown deployments versus false quarantines."""
    return run_requirement(
        "W3F-062",
        "measure_quarantine_precision",
        "Measure true unsafe/unknown deployments versus false quarantines.",
        "W3-07",
        payload,
        **kwargs,
    )


def measure_deprecation_detection_delay(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure time to detect upgrade/deprecation/right changes."""
    return run_requirement(
        "W3F-063",
        "measure_deprecation_detection_delay",
        "Measure time to detect upgrade/deprecation/right changes.",
        "W3-07",
        payload,
        **kwargs,
    )


def publish_mechanism_discovery_scorecard(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish onboarding efficiency and error categories."""
    return run_requirement(
        "W3F-064",
        "publish_mechanism_discovery_scorecard",
        "Publish onboarding efficiency and error categories.",
        "W3-07",
        payload,
        **kwargs,
    )


def propose_research_from_coverage_gap(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Generate hypothesis candidate from explicit unknown/blind-spot cell."""
    return run_requirement(
        "W3F-065",
        "propose_research_from_coverage_gap",
        "Generate hypothesis candidate from explicit unknown/blind-spot cell.",
        "W3-08",
        payload,
        **kwargs,
    )


def deduplicate_research_proposal(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Reject semantic duplicates against prior hypotheses and owners."""
    return run_requirement(
        "W3F-066",
        "deduplicate_research_proposal",
        "Reject semantic duplicates against prior hypotheses and owners.",
        "W3-08",
        payload,
        **kwargs,
    )


def request_bounded_data_capture(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Ask existing provider governance for bounded capture only."""
    return run_requirement(
        "W3F-068",
        "request_bounded_data_capture",
        "Ask existing provider governance for bounded capture only.",
        "W3-08",
        payload,
        **kwargs,
    )


def dispatch_reproducible_experiment(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Run sandboxed deterministic research task."""
    return run_requirement(
        "W3F-069",
        "dispatch_reproducible_experiment",
        "Run sandboxed deterministic research task.",
        "W3-08",
        payload,
        **kwargs,
    )


def feed_verdict_to_memory_and_frontier(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Update coverage/motif/source utility without auto-enabling execution."""
    return run_requirement(
        "W3F-072",
        "feed_verdict_to_memory_and_frontier",
        "Update coverage/motif/source utility without auto-enabling execution.",
        "W3-08",
        payload,
        **kwargs,
    )


def record_qualification_cost_vector(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Record wall time, source credits/USD, bytes, compute, human corrections and trials separately."""
    return run_requirement(
        "W3F-073",
        "record_qualification_cost_vector",
        "Record wall time, source credits/USD, bytes, compute, human corrections and trials separately.",
        "W3-09",
        payload,
        **kwargs,
    )


def record_qualification_evidence_vector(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Record independent episodes, regimes, null tests, replay/fork coverage and external blockers."""
    return run_requirement(
        "W3F-074",
        "record_qualification_evidence_vector",
        "Record independent episodes, regimes, null tests, replay/fork coverage and external blockers.",
        "W3-09",
        payload,
        **kwargs,
    )


def compute_policy_normalized_qualification_score(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Optionally normalize dimensions using explicit policy weights; raw vector remains canonical."""
    return run_requirement(
        "W3F-075",
        "compute_policy_normalized_qualification_score",
        "Optionally normalize dimensions using explicit policy weights; raw vector remains canonical.",
        "W3-09",
        payload,
        **kwargs,
    )


def measure_time_to_research_closure(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure discovery→dossier→dataset→hypothesis→verdict elapsed time."""
    return run_requirement(
        "W3F-076",
        "measure_time_to_research_closure",
        "Measure discovery→dossier→dataset→hypothesis→verdict elapsed time.",
        "W3-09",
        payload,
        **kwargs,
    )


def measure_research_yield(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure reproducible supported/rejected hypotheses per budget."""
    return run_requirement(
        "W3F-077",
        "measure_research_yield",
        "Measure reproducible supported/rejected hypotheses per budget.",
        "W3-09",
        payload,
        **kwargs,
    )


def measure_mechanism_reuse_gain(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure how much prior IR/motif/adapter work reduces new-market cost."""
    return run_requirement(
        "W3F-078",
        "measure_mechanism_reuse_gain",
        "Measure how much prior IR/motif/adapter work reduces new-market cost.",
        "W3-09",
        payload,
        **kwargs,
    )


def rank_next_research_campaign(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Use existing frontier owner with qualification-cost feedback."""
    return run_requirement(
        "W3F-079",
        "rank_next_research_campaign",
        "Use existing frontier owner with qualification-cost feedback.",
        "W3-09",
        payload,
        **kwargs,
    )


def publish_qualification_economics_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish cost/evidence vectors and next recheck trigger."""
    return run_requirement(
        "W3F-080",
        "publish_qualification_economics_card",
        "Publish cost/evidence vectors and next recheck trigger.",
        "W3-09",
        payload,
        **kwargs,
    )


__all__ = [
    'build_campaign_source_manifest',
    'capture_campaign_raw_events',
    'materialize_campaign_state_frames',
    'sample_random_control_windows',
    'sample_reference_search_windows',
    'freeze_campaign_dataset',
    'replay_campaign_dataset',
    'score_campaign_data_quality',
    'assign_episode_trigger',
    'define_episode_horizon',
    'audit_episode_independence',
    'publish_episode_ledger_view',
    'stress_state_reachability',
    'attribute_reachability_gain',
    'build_topology_snapshot_sequence',
    'derive_mechanism_motif_signature',
    'train_target_only_mechanism_baseline',
    'train_pooled_market_baseline',
    'train_motif_transfer_challenger',
    'measure_sample_efficiency_gain',
    'measure_topology_negative_transfer',
    'publish_graph_transfer_verdict',
    'classify_information_regime',
    'align_information_reveal_timeline',
    'measure_private_public_execution_gap',
    'measure_update_right_value',
    'measure_preconfirmation_value',
    'stress_information_regime_change',
    'publish_information_regime_verdict',
    'define_equal_budget_source_trials',
    'measure_incremental_forecast_value',
    'measure_incremental_candidate_value',
    'measure_source_latency_cost',
    'measure_source_redundancy',
    'audit_adaptive_source_selection_bias',
    'retire_low_value_source',
    'publish_source_value_card',
    'time_to_first_dossier',
    'score_semantic_dossier_accuracy',
    'count_human_semantic_corrections',
    'measure_minimum_data_plan_quality',
    'time_to_first_falsifiable_hypothesis',
    'measure_quarantine_precision',
    'measure_deprecation_detection_delay',
    'publish_mechanism_discovery_scorecard',
    'propose_research_from_coverage_gap',
    'deduplicate_research_proposal',
    'request_bounded_data_capture',
    'dispatch_reproducible_experiment',
    'feed_verdict_to_memory_and_frontier',
    'record_qualification_cost_vector',
    'record_qualification_evidence_vector',
    'compute_policy_normalized_qualification_score',
    'measure_time_to_research_closure',
    'measure_research_yield',
    'measure_mechanism_reuse_gain',
    'rank_next_research_campaign',
    'publish_qualification_economics_card'
]

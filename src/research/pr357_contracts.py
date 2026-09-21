"""PR-357 typed research-only contracts.

The 40 normative contract names/fields come from the PR-357 roadmap.  Contracts
are immutable, keyword-only dataclasses with deterministic serialization and a
shared fail-closed effect boundary.  They intentionally expose no sender,
signer, wallet, release, capital-mutation, or remote-mutation capability.
"""

from __future__ import annotations

from dataclasses import asdict, field, make_dataclass
from hashlib import sha256
import json
from typing import Any, Final, Mapping

ROADMAP_ID: Final = "PR-357"
ALLOWED_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "SUPPORTED_RESEARCH_ONLY",
        "REJECTED_WITH_EVIDENCE",
        "INCONCLUSIVE",
        "BLOCKED_EXTERNAL",
        "SATISFIED_BY_EXISTING",
        "CONTRACT_IMPLEMENTED",
    }
)
EFFECT_BOUNDARY: Final[dict[str, bool]] = {
    "production_ready": False,
    "live_enabled": False,
    "execution_right": False,
    "signer_access": False,
    "submission_access": False,
    "wallet_access": False,
    "remote_mutation": False,
    "automatic_promotion": False,
    "automatic_capital_increase": False,
}


class PR357ContractError(ValueError):
    """Fail-closed PR-357 contract violation."""


def canonical_hash(payload: Any) -> str:
    """Return a stable SHA-256 over JSON-safe research evidence."""
    if hasattr(payload, "__dataclass_fields__"):
        payload = asdict(payload)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def _validate_effect_boundary(values: Mapping[str, Any]) -> None:
    for key in EFFECT_BOUNDARY:
        value = values.get(key)
        if value not in (None, False, 0, "false", "FALSE"):
            raise PR357ContractError(f"PR357_EFFECT_AUTHORITY_FORBIDDEN:{key}")


def _validate_common(self: Any) -> None:
    values = asdict(self)
    _validate_effect_boundary(values)

    for key, value in values.items():
        if value is None:
            raise PR357ContractError(f"PR357_REQUIRED_FIELD_MISSING:{key}")
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value < 0
            and any(
                token in key
                for token in (
                    "age",
                    "budget",
                    "cost",
                    "count",
                    "deadline",
                    "latency",
                    "storage",
                    "time",
                )
            )
        ):
            raise PR357ContractError(f"PR357_NEGATIVE_VALUE:{key}")

    if "decision_time" in values and "valid_until" in values:
        decision_time = values["decision_time"]
        valid_until = values["valid_until"]
        if (
            isinstance(decision_time, int)
            and isinstance(valid_until, int)
            and valid_until < decision_time
        ):
            raise PR357ContractError("PR357_VALIDITY_PRECEDES_DECISION")


CONTRACT_SCHEMAS: Final[dict[str, tuple[str, ...]]] = {
    "BootstrapDataPlan": (
        "target_market",
        "current_milestone",
        "next_milestone",
        "candidate_actions",
        "information_gain_estimate",
        "cost_vectors",
        "control_reserve",
        "validation_reserve",
        "selected_actions",
        "stop_rule",
        "blockers",
    ),
    "BootstrapEfficiencyVector": (
        "time_to_semantics",
        "time_to_replay",
        "time_to_baseline",
        "time_to_calibration",
        "time_to_research_closure",
        "target_episodes_used",
        "source_credits",
        "source_usd",
        "compute_seconds",
        "storage_bytes",
        "human_semantic_corrections",
        "failed_trials",
        "negative_transfer_events",
    ),
    "ColdStartTrial": (
        "trial_id",
        "target_market",
        "policy_type",
        "target_episode_budget",
        "target_label_budget",
        "source_prior_markets",
        "train_cutoff",
        "heldout_period",
        "metrics",
        "calibration",
        "negative_transfer",
    ),
    "ComputationValueCard": (
        "computation_id",
        "fidelity",
        "compute_cost",
        "latency",
        "error_model",
        "expected_decision_improvement",
        "decision_stability",
        "next_fidelity_or_stop",
    ),
    "CounterfactualScenarioCard": (
        "intervention",
        "causal_claim_refs",
        "identification_status",
        "support_overlap",
        "alternative_graphs",
        "rollout_distribution",
        "sensitivity",
        "speculative_flag",
        "execution_right",
    ),
    "DecisionAction": (
        "action_id",
        "action_type",
        "downstream_owner",
        "expected_utility_distribution",
        "hard_constraints",
        "terminal_or_nonterminal",
        "execution_right",
    ),
    "DecisionIntelligenceScorecard": (
        "benchmark_id",
        "baseline_policies",
        "decision_regret",
        "information_cost",
        "compute_cost",
        "deadline_loss",
        "safety_coverage",
        "abstention",
        "replication_status",
        "allowed_uses",
    ),
    "DecisionProblemCard": (
        "decision_id",
        "decision_time",
        "actions",
        "utility_or_loss_definition",
        "belief_state_ref",
        "deadline",
        "mandatory_safety",
        "resource_budget",
        "scope",
        "execution_right",
    ),
    "DecisionValueCard": (
        "decision_id",
        "current_action",
        "current_expected_loss",
        "evpi",
        "evsi",
        "expected_regret_reduction",
        "information_cost",
        "deadline_adjustment",
        "net_decision_value",
        "uncertainty",
    ),
    "DegradationAttributionCard": (
        "strategy_id",
        "period",
        "source_component",
        "crowding_component",
        "cost_component",
        "model_component",
        "semantic_component",
        "regime_component",
        "unknown_component",
        "counterfactual_checks",
        "uncertainty",
    ),
    "EvidenceFreshnessCard": (
        "evidence_id",
        "wall_age",
        "deployment_generation_age",
        "source_schema_age",
        "topology_age",
        "regime_distance",
        "model_generation_age",
        "hard_invalidators",
        "decay_estimate",
        "next_requalification",
    ),
    "FoundationModelTrial": (
        "model_name",
        "repo_version",
        "weights_id",
        "code_license",
        "weight_license",
        "task",
        "input_cutoff",
        "compute_budget",
        "baseline_results",
        "trial_results",
        "negative_transfer",
        "allowed_use",
    ),
    "InformationAction": (
        "information_action_id",
        "kind",
        "source_or_simulator",
        "cost_vector",
        "latency_distribution",
        "observation_schema",
        "failure_modes",
        "mandatory_safety",
        "access_constraints",
    ),
    "InformationDependencyCard": (
        "nodes",
        "conditional_edges",
        "redundancy_estimates",
        "common_failure_groups",
        "marginal_values",
        "generation",
        "uncertainty",
    ),
    "LatentRegimeCard": (
        "regime_model_id",
        "latent_dimensions",
        "training_cutoff",
        "posterior_regime_probabilities",
        "market_alignment",
        "market_specific_residuals",
        "stability",
        "uncertainty",
    ),
    "LifecyclePolicyCard": (
        "policy_id",
        "transition_rules",
        "freshness_rules",
        "hazard_rules",
        "change_point_rules",
        "stopping_rules",
        "hysteresis",
        "benchmarks",
        "churn",
        "regret",
        "allowed_uses",
    ),
    "MarketBeliefState": (
        "belief_id",
        "decision_time",
        "pit_snapshot_refs",
        "observed_variables",
        "latent_variables",
        "posterior_summaries",
        "dependence",
        "missingness_mask",
        "model_versions",
        "assumption_refs",
        "valid_until",
        "execution_right",
    ),
    "MarketBootstrapDescriptor": (
        "market_id",
        "chain_or_domain",
        "instrument_type",
        "underlying",
        "settlement",
        "maturity_or_session",
        "economic_rights",
        "execution_domain",
        "information_domain",
        "access_domain",
        "risk_domain",
        "known_sources",
        "unknown_fields",
        "descriptor_version",
    ),
    "MarketPackBootstrapPlan": (
        "marketpack_id",
        "descriptor_ref",
        "existing_owner_refs",
        "missing_specializations",
        "source_plan",
        "replay_plan",
        "baseline_plan",
        "hypotheses",
        "acceptance_gates",
        "blockers",
        "execution_right",
    ),
    "MetareasoningPolicyCard": (
        "policy_id",
        "belief_state_space",
        "meta_actions",
        "observation_model",
        "transition_model",
        "loss_or_reward",
        "horizon",
        "baseline_comparison",
        "execution_right",
    ),
    "MissingDataBeliefCard": (
        "variable",
        "missingness_type",
        "last_observed_at",
        "posterior_if_inferred",
        "uncertainty_widening",
        "abstention_status",
        "future_backfill_prohibited",
    ),
    "NewMarketBootstrapScorecard": (
        "target_market",
        "knowledge_cutoff",
        "from_scratch_vector",
        "prior_assisted_vector",
        "meta_learning_vector",
        "semantic_correctness",
        "data_integrity",
        "calibration",
        "heldout_utility",
        "negative_transfer",
        "final_verdict",
        "next_capability_gap",
    ),
    "ObservationLikelihoodCard": (
        "information_action_id",
        "possible_observation",
        "likelihood_model",
        "conditioning_state",
        "model_version",
        "fit_cutoff",
        "calibration",
        "unknown_support",
    ),
    "OnboardingEpisode": (
        "episode_id",
        "target_market",
        "knowledge_cutoff",
        "initial_descriptor",
        "prior_set",
        "actions_taken",
        "data_acquired",
        "semantic_corrections",
        "milestones",
        "cost_vector",
        "elapsed_time",
        "final_research_verdict",
        "negative_transfer",
        "receipt_refs",
    ),
    "OptimalStoppingCard": (
        "decision_state",
        "act_value",
        "wait_value",
        "abandon_value",
        "expiry",
        "resource_state",
        "policy",
        "uncertainty",
        "stress_results",
        "execution_right",
    ),
    "PriorRetrievalCard": (
        "target_market",
        "candidate_priors",
        "semantic_similarity",
        "topology_similarity",
        "source_similarity",
        "freshness_status",
        "negative_transfer_history",
        "selected_priors",
        "rejected_priors",
        "uncertainty",
    ),
    "PropagationEdgeCard": (
        "source_event_or_state",
        "target_state",
        "lag_distribution",
        "conditional_response",
        "regime_scope",
        "predictive_or_causal",
        "common_cause_controls",
        "uncertainty",
    ),
    "RegimeTransitionCard": (
        "market_scope",
        "feature_panel",
        "detector_versions",
        "candidate_breaks",
        "confirmed_break",
        "data_break_checks",
        "false_alarm_estimate",
        "lifecycle_actions",
        "evidence_refs",
    ),
    "ScenarioEnsemble": (
        "ensemble_id",
        "belief_state_ref",
        "horizons",
        "variables",
        "samples_or_quantiles",
        "dependence_model",
        "conditions",
        "synthetic_flags",
        "calibration_metrics",
    ),
    "SequentialInformationPlan": (
        "plan_id",
        "decision_id",
        "root_belief",
        "query_tree",
        "branch_observations",
        "branch_actions",
        "stop_rules",
        "budget",
        "deadline",
        "receipt_hash",
    ),
    "ShadowExplorationLog": (
        "context",
        "available_actions",
        "logging_policy",
        "propensity",
        "chosen_action",
        "shadow_outcome",
        "outcome_available_at",
        "censored",
        "offpolicy_estimators",
        "cost_vector",
        "execution_right",
    ),
    "ShadowTreasuryCard": (
        "hypothetical_assets",
        "free",
        "reserved",
        "locked",
        "reserve_floors",
        "lock_durations",
        "idle_option_value",
        "stress_scenarios",
        "ruin_proxy",
        "proposal_only",
    ),
    "SourceSchemaBootstrapCard": (
        "source_id",
        "schema_version",
        "field_mapping",
        "unit_mapping",
        "timestamp_semantics",
        "revision_semantics",
        "unknown_fields",
        "conformance_vectors",
        "mapping_coverage",
        "quarantine_status",
    ),
    "StrategyLifecycleRecord": (
        "strategy_id",
        "strategy_version",
        "lifecycle_state",
        "state_since",
        "transition_history",
        "evidence_refs",
        "freshness_card",
        "regime_scope",
        "valid_until",
        "retest_trigger",
        "execution_right",
    ),
    "StrategyLineageCard": (
        "strategy_id",
        "parent_ids",
        "successor_ids",
        "semantic_delta",
        "evidence_inheritance",
        "invalidated_evidence",
        "inherited_counterexamples",
        "stress_suite_refs",
        "regression_checks",
    ),
    "StrategySurvivalRecord": (
        "strategy_id",
        "start_time",
        "stop_or_censor_time",
        "event_type",
        "censored",
        "time_varying_covariates",
        "regime",
        "topology_generation",
        "source_generation",
        "survival_model_version",
    ),
    "StructuralUncertaintyCard": (
        "model_id",
        "priors",
        "likelihood",
        "latent_state",
        "posterior",
        "identifiability",
        "prior_sensitivity",
        "posterior_predictive_checks",
        "heldout_metrics",
    ),
    "SyntheticBootstrapManifest": (
        "generator_id",
        "mechanism_generation",
        "ecology_generation",
        "synthetic_episode_ids",
        "real_train_ids",
        "real_holdout_ids",
        "mixture_policy",
        "bias_checks",
        "synthetic_flag",
    ),
    "TimescaleLayer": (
        "layer_id",
        "timescale",
        "market_scope",
        "variables",
        "event_clock",
        "available_at_policy",
        "aggregation_policy",
        "latency_distribution",
        "revision_policy",
    ),
    "WorldModelScorecard": (
        "world_model_id",
        "benchmark_id",
        "joint_forecast_metrics",
        "propagation_metrics",
        "missingness_metrics",
        "counterfactual_sensitivity",
        "compression_metrics",
        "compute_cost",
        "reality_gap",
        "replication_status",
        "allowed_uses",
    ),
}


def _build_contract_type(name: str, fields: tuple[str, ...]) -> type[Any]:
    rows: list[tuple[Any, ...]] = []
    for field_name in fields:
        if field_name == "execution_right":
            rows.append((field_name, bool, field(default=False)))
        else:
            rows.append((field_name, object))
    contract_type = make_dataclass(
        name,
        rows,
        namespace={"__post_init__": _validate_common},
        frozen=True,
        slots=True,
        kw_only=True,
    )
    contract_type.__module__ = __name__
    return contract_type


for _contract_name, _contract_fields in CONTRACT_SCHEMAS.items():
    globals()[_contract_name] = _build_contract_type(
        _contract_name,
        _contract_fields,
    )


def contract_type(name: str) -> type[Any]:
    """Resolve one normative contract type by exact roadmap name."""
    value = globals().get(name)
    if name not in CONTRACT_SCHEMAS or not isinstance(value, type):
        raise PR357ContractError(f"PR357_UNKNOWN_CONTRACT:{name}")
    return value


__all__ = [
    "ALLOWED_STATUSES",
    "CONTRACT_SCHEMAS",
    "EFFECT_BOUNDARY",
    "PR357ContractError",
    "ROADMAP_ID",
    "canonical_hash",
    "contract_type",
    *sorted(CONTRACT_SCHEMAS),
]

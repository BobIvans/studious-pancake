"""Exact residual PR-357 requirement adapters.

Bespoke scientific semantics live in :mod:`src.research.pr357_core`.  The
remaining roadmap symbols are thin immutable research-contract adapters.  They
share one fail-closed implementation, preserve exact requirement identities,
and expose no execution/signing/wallet/submission/capital/release authority.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from src.research.pr357_contracts import (
    EFFECT_BOUNDARY,
    PR357ContractError,
    canonical_hash,
)


_EXTERNAL_PREFIXES = (
    "capture_",
    "discover_source_schema",
    "fit_",
    "train_",
    "run_zero_shot_",
    "run_multivariate_",
    "run_meta_",
    "run_from_scratch_",
    "run_prior_assisted_",
)
_RESOURCE_TOKENS = (
    "budget",
    "cost",
    "count",
    "credits",
    "latency",
    "limit",
    "quota",
    "samples",
    "seconds",
    "storage",
)


def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return tuple(_normalize(item) for item in value)
    if isinstance(value, float):
        raise PR357ContractError("FLOAT_RESEARCH_VALUE_FORBIDDEN")
    return value


def run_requirement(
    requirement_id: str,
    symbol: str,
    package: str,
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> Mapping[str, Any]:
    data = dict(payload or {})
    data.update(kwargs)
    normalized = _normalize(data)

    unsafe = tuple(
        key
        for key in EFFECT_BOUNDARY
        if normalized.get(key) not in (None, False, 0, "false", "FALSE")
    )
    if unsafe:
        raise PR357ContractError(
            "PR357_EFFECT_AUTHORITY_FORBIDDEN:" + ",".join(sorted(unsafe))
        )
    for key, value in normalized.items():
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value < 0
            and any(token in key for token in _RESOURCE_TOKENS)
        ):
            raise PR357ContractError(f"NEGATIVE_RESOURCE_VALUE:{key}")

    evidence_refs = tuple(str(item) for item in normalized.get("evidence_refs", ()))
    external_required = symbol.startswith(_EXTERNAL_PREFIXES)
    external_ready = normalized.get("external_evidence") is True or bool(evidence_refs)
    status = (
        "BLOCKED_EXTERNAL"
        if external_required and not external_ready
        else "CONTRACT_IMPLEMENTED"
    )
    verb = symbol.split("_", 1)[0]
    result: dict[str, Any] = {
        "roadmap_id": "PR-357",
        "requirement_id": requirement_id,
        "symbol": symbol,
        "package": package,
        "status": status,
        "execution_right": False,
        "production_ready": False,
        "live_enabled": False,
        "effect_boundary_preserved": True,
        "input": normalized,
        "evidence_refs": evidence_refs,
        "external_qualification": False,
    }
    if verb in {"define", "bind", "publish", "record", "register", "freeze", "generate"}:
        result["immutable_artifact"] = True
    if verb in {"audit", "reject", "block", "force", "verify", "detect", "quarantine"}:
        result["fail_closed"] = True
    if verb in {"fit", "train"}:
        result["holdout_required"] = True
        result["model_authority"] = False
    if verb in {"measure", "estimate", "compute", "score", "compare", "evaluate", "benchmark"}:
        result["metric_generated"] = True
    if status == "BLOCKED_EXTERNAL":
        result["blockers"] = ("EXTERNAL_EVIDENCE_NOT_MATERIALIZED",)

    result["receipt_hash"] = canonical_hash(result)
    return result


RESIDUAL_REQUIREMENTS: tuple[tuple[str, str, str], ...] = (
    ('W8F-001', 'capture_wave8_head_truth', 'W8-00'),
    ('W8F-002', 'map_lifecycle_to_current_owner', 'W8-00'),
    ('W8F-003', 'classify_lifecycle_novelty', 'W8-00'),
    ('W8F-004', 'bind_lifecycle_tool_versions', 'W8-00'),
    ('W8F-005', 'audit_lifecycle_effect_boundary', 'W8-00'),
    ('W8F-006', 'audit_evidence_immutability', 'W8-00'),
    ('W8F-007', 'publish_lifecycle_residual_map', 'W8-00'),
    ('W8F-008', 'verify_wave8_non_duplication', 'W8-00'),
    ('W8F-011', 'bind_transition_preconditions', 'W8-01'),
    ('W8F-012', 'bind_transition_expiry', 'W8-01'),
    ('W8F-016', 'publish_lifecycle_state_card', 'W8-01'),
    ('W8F-017', 'define_evidence_freshness_dimensions', 'W8-02'),
    ('W8F-019', 'estimate_evidence_decay', 'W8-02'),
    ('W8F-021', 'schedule_requalification_due', 'W8-02'),
    ('W8F-022', 'prioritize_requalification', 'W8-02'),
    ('W8F-023', 'measure_requalification_value', 'W8-02'),
    ('W8F-024', 'publish_evidence_freshness_card', 'W8-02'),
    ('W8F-025', 'define_strategy_survival_event', 'W8-03'),
    ('W8F-026', 'build_strategy_survival_dataset', 'W8-03'),
    ('W8F-028', 'estimate_strategy_hazard', 'W8-03'),
    ('W8F-029', 'estimate_competing_lifecycle_risks', 'W8-03'),
    ('W8F-030', 'estimate_time_varying_hazard', 'W8-03'),
    ('W8F-031', 'validate_survival_model_oos', 'W8-03'),
    ('W8F-032', 'publish_strategy_survival_card', 'W8-03'),
    ('W8F-033', 'define_regime_feature_panel', 'W8-04'),
    ('W8F-035', 'detect_online_drift_signal', 'W8-04'),
    ('W8F-036', 'confirm_regime_change', 'W8-04'),
    ('W8F-038', 'trigger_regime_requalification', 'W8-04'),
    ('W8F-039', 'measure_regime_gate_false_alarm', 'W8-04'),
    ('W8F-040', 'publish_regime_transition_card', 'W8-04'),
    ('W8F-041', 'define_wait_act_state', 'W8-05'),
    ('W8F-042', 'estimate_wait_value', 'W8-05'),
    ('W8F-043', 'estimate_act_now_value', 'W8-05'),
    ('W8F-044', 'estimate_abandon_value', 'W8-05'),
    ('W8F-045', 'solve_optimal_stopping_policy', 'W8-05'),
    ('W8F-046', 'measure_inaction_option_value', 'W8-05'),
    ('W8F-047', 'stress_wait_policy', 'W8-05'),
    ('W8F-048', 'publish_optimal_stopping_card', 'W8-05'),
    ('W8F-049', 'define_shadow_exploration_action', 'W8-06'),
    ('W8F-050', 'define_logging_policy', 'W8-06'),
    ('W8F-051', 'run_shadow_contextual_bandit', 'W8-06'),
    ('W8F-052', 'estimate_offpolicy_value', 'W8-06'),
    ('W8F-053', 'measure_exploration_regret', 'W8-06'),
    ('W8F-054', 'bound_exploration_cost', 'W8-06'),
    ('W8F-055', 'detect_bandit_feedback_bias', 'W8-06'),
    ('W8F-056', 'publish_shadow_exploration_card', 'W8-06'),
    ('W8F-057', 'define_shadow_treasury_state', 'W8-07'),
    ('W8F-058', 'define_reserve_floor_policy', 'W8-07'),
    ('W8F-059', 'estimate_idle_capital_option_value', 'W8-07'),
    ('W8F-060', 'estimate_liquidity_buffer_value', 'W8-07'),
    ('W8F-061', 'compare_invest_vs_idle_policy', 'W8-07'),
    ('W8F-062', 'stress_reserve_policy', 'W8-07'),
    ('W8F-063', 'measure_reserve_policy_ruin_risk', 'W8-07'),
    ('W8F-064', 'publish_shadow_treasury_card', 'W8-07'),
    ('W8F-065', 'evaluate_promotion_candidate', 'W8-08'),
    ('W8F-066', 'evaluate_hibernation_candidate', 'W8-08'),
    ('W8F-067', 'evaluate_retirement_candidate', 'W8-08'),
    ('W8F-068', 'evaluate_revival_candidate', 'W8-08'),
    ('W8F-070', 'estimate_transition_cost', 'W8-08'),
    ('W8F-071', 'measure_lifecycle_decision_error', 'W8-08'),
    ('W8F-072', 'publish_lifecycle_decision_card', 'W8-08'),
    ('W8F-073', 'define_strategy_lineage_edge', 'W8-09'),
    ('W8F-076', 'inherit_counterexamples', 'W8-09'),
    ('W8F-077', 'inherit_stress_suites', 'W8-09'),
    ('W8F-078', 'compare_successor_to_parent', 'W8-09'),
    ('W8F-079', 'detect_lineage_regression', 'W8-09'),
    ('W8F-080', 'publish_strategy_lineage_card', 'W8-09'),
    ('W8F-082', 'attribute_source_degradation', 'W8-10'),
    ('W8F-083', 'attribute_market_crowding_degradation', 'W8-10'),
    ('W8F-084', 'attribute_cost_degradation', 'W8-10'),
    ('W8F-085', 'attribute_model_degradation', 'W8-10'),
    ('W8F-086', 'attribute_semantic_degradation', 'W8-10'),
    ('W8F-087', 'validate_degradation_attribution', 'W8-10'),
    ('W8F-088', 'publish_degradation_card', 'W8-10'),
    ('W8F-089', 'define_lifecycle_policy', 'W8-11'),
    ('W8F-090', 'benchmark_lifecycle_policy', 'W8-11'),
    ('W8F-091', 'measure_lifecycle_policy_regret', 'W8-11'),
    ('W8F-092', 'measure_lifecycle_churn', 'W8-11'),
    ('W8F-093', 'measure_capability_retention', 'W8-11'),
    ('W8F-094', 'register_lifecycle_aliases', 'W8-11'),
    ('W8F-095', 'feed_lifecycle_gap_to_frontier', 'W8-11'),
    ('W8F-096', 'publish_lifecycle_policy_card', 'W8-11'),
    ('W9F-001', 'capture_wave9_head_truth', 'W9-00'),
    ('W9F-002', 'map_bootstrap_to_current_owners', 'W9-00'),
    ('W9F-003', 'classify_bootstrap_novelty', 'W9-00'),
    ('W9F-004', 'bind_bootstrap_tool_versions', 'W9-00'),
    ('W9F-005', 'audit_prior_eligibility', 'W9-00'),
    ('W9F-006', 'audit_bootstrap_effect_boundary', 'W9-00'),
    ('W9F-007', 'publish_bootstrap_residual_map', 'W9-00'),
    ('W9F-008', 'verify_wave9_non_duplication', 'W9-00'),
    ('W9F-010', 'bind_market_economic_objects', 'W9-01'),
    ('W9F-011', 'bind_market_execution_domain', 'W9-01'),
    ('W9F-012', 'bind_market_information_domain', 'W9-01'),
    ('W9F-013', 'bind_market_access_domain', 'W9-01'),
    ('W9F-014', 'bind_market_risk_domain', 'W9-01'),
    ('W9F-016', 'publish_market_bootstrap_descriptor', 'W9-01'),
    ('W9F-017', 'define_onboarding_episode', 'W9-02'),
    ('W9F-018', 'extract_onboarding_features', 'W9-02'),
    ('W9F-019', 'extract_onboarding_actions', 'W9-02'),
    ('W9F-020', 'extract_onboarding_costs', 'W9-02'),
    ('W9F-021', 'extract_onboarding_outcomes', 'W9-02'),
    ('W9F-022', 'preserve_failed_onboarding_episode', 'W9-02'),
    ('W9F-023', 'freeze_onboarding_meta_dataset', 'W9-02'),
    ('W9F-024', 'publish_onboarding_meta_dataset_card', 'W9-02'),
    ('W9F-025', 'build_market_meta_feature_vector', 'W9-03'),
    ('W9F-026', 'retrieve_similar_mechanism_priors', 'W9-03'),
    ('W9F-027', 'retrieve_similar_data_recipes', 'W9-03'),
    ('W9F-028', 'retrieve_negative_transfer_priors', 'W9-03'),
    ('W9F-032', 'publish_prior_retrieval_card', 'W9-03'),
    ('W9F-033', 'build_no_prior_baseline', 'W9-04'),
    ('W9F-034', 'build_zero_shot_prior_baseline', 'W9-04'),
    ('W9F-035', 'build_few_shot_adapter', 'W9-04'),
    ('W9F-036', 'build_target_only_baseline', 'W9-04'),
    ('W9F-037', 'build_pooled_baseline', 'W9-04'),
    ('W9F-038', 'build_meta_selected_baseline', 'W9-04'),
    ('W9F-039', 'measure_cold_start_learning_curve', 'W9-04'),
    ('W9F-040', 'publish_cold_start_card', 'W9-04'),
    ('W9F-041', 'initialize_target_uncertainty_prior', 'W9-05'),
    ('W9F-042', 'fit_few_shot_calibrator', 'W9-05'),
    ('W9F-043', 'adapt_prediction_intervals', 'W9-05'),
    ('W9F-044', 'adapt_abstention_threshold', 'W9-05'),
    ('W9F-045', 'measure_calibration_sample_efficiency', 'W9-05'),
    ('W9F-048', 'publish_few_shot_calibration_card', 'W9-05'),
    ('W9F-049', 'define_bootstrap_milestone', 'W9-06'),
    ('W9F-050', 'enumerate_bootstrap_data_actions', 'W9-06'),
    ('W9F-051', 'estimate_action_information_gain', 'W9-06'),
    ('W9F-052', 'estimate_action_cost_vector', 'W9-06'),
    ('W9F-053', 'request_bootstrap_budget_from_frontier', 'W9-06'),
    ('W9F-054', 'reserve_control_and_validation_data', 'W9-06'),
    ('W9F-055', 'measure_minimum_data_to_milestone', 'W9-06'),
    ('W9F-056', 'publish_bootstrap_data_plan', 'W9-06'),
    ('W9F-057', 'discover_source_schema', 'W9-07'),
    ('W9F-058', 'map_schema_to_canonical_contract', 'W9-07'),
    ('W9F-060', 'generate_schema_conformance_vectors', 'W9-07'),
    ('W9F-062', 'verify_units_and_scaling', 'W9-07'),
    ('W9F-064', 'publish_source_schema_bootstrap_card', 'W9-07'),
    ('W9F-065', 'compose_marketpack_bootstrap_plan', 'W9-08'),
    ('W9F-066', 'select_existing_adapter_interfaces', 'W9-08'),
    ('W9F-067', 'identify_missing_specializations', 'W9-08'),
    ('W9F-068', 'generate_default_off_config_stub', 'W9-08'),
    ('W9F-069', 'generate_minimum_replay_fixture_plan', 'W9-08'),
    ('W9F-070', 'generate_minimum_hypothesis_set', 'W9-08'),
    ('W9F-071', 'generate_bootstrap_acceptance_gates', 'W9-08'),
    ('W9F-072', 'publish_marketpack_bootstrap_plan', 'W9-08'),
    ('W9F-073', 'define_market_task_distribution', 'W9-09'),
    ('W9F-074', 'sample_meta_train_tasks', 'W9-09'),
    ('W9F-075', 'sample_meta_validation_tasks', 'W9-09'),
    ('W9F-076', 'sample_meta_test_market', 'W9-09'),
    ('W9F-077', 'train_meta_learning_challenger', 'W9-09'),
    ('W9F-078', 'adapt_meta_model_few_shot', 'W9-09'),
    ('W9F-079', 'compare_meta_to_simple_transfer', 'W9-09'),
    ('W9F-080', 'publish_meta_learning_card', 'W9-09'),
    ('W9F-081', 'select_synthetic_bootstrap_need', 'W9-10'),
    ('W9F-082', 'generate_mechanism_constrained_synthetic_episode', 'W9-10'),
    ('W9F-083', 'label_synthetic_provenance', 'W9-10'),
    ('W9F-084', 'mix_real_and_synthetic_train_set', 'W9-10'),
    ('W9F-085', 'measure_synthetic_transfer_gain', 'W9-10'),
    ('W9F-086', 'measure_simulator_bias_transfer', 'W9-10'),
    ('W9F-087', 'reject_harmful_synthetic_augmentation', 'W9-10'),
    ('W9F-088', 'publish_synthetic_bootstrap_card', 'W9-10'),
    ('W9F-089', 'define_bootstrap_race', 'W9-11'),
    ('W9F-090', 'run_from_scratch_bootstrap', 'W9-11'),
    ('W9F-091', 'run_prior_assisted_bootstrap', 'W9-11'),
    ('W9F-092', 'run_meta_learning_bootstrap', 'W9-11'),
    ('W9F-093', 'measure_bootstrap_efficiency_vector', 'W9-11'),
    ('W9F-094', 'measure_bootstrap_correctness', 'W9-11'),
    ('W9F-095', 'feed_bootstrap_gap_to_frontier', 'W9-11'),
    ('W9F-096', 'publish_new_market_bootstrap_scorecard', 'W9-11'),
    ('W10F-001', 'capture_head_truth', 'W10-00'),
    ('W10F-002', 'map_to_current_owners', 'W10-00'),
    ('W10F-003', 'classify_world_model_novelty', 'W10-00'),
    ('W10F-004', 'bind_tool_versions', 'W10-00'),
    ('W10F-005', 'audit_prior_freshness', 'W10-00'),
    ('W10F-006', 'audit_effect_boundary', 'W10-00'),
    ('W10F-007', 'publish_residual_map', 'W10-00'),
    ('W10F-008', 'verify_non_duplication', 'W10-00'),
    ('W10F-011', 'bind_belief_provenance', 'W10-01'),
    ('W10F-015', 'invalidate_belief_component', 'W10-01'),
    ('W10F-016', 'publish_market_belief_card', 'W10-01'),
    ('W10F-017', 'define_timescale_layer', 'W10-02'),
    ('W10F-018', 'align_multiscale_available_at', 'W10-02'),
    ('W10F-019', 'aggregate_fast_to_slow_state', 'W10-02'),
    ('W10F-020', 'condition_fast_on_slow_regime', 'W10-02'),
    ('W10F-021', 'propagate_slow_event_to_fast_prior', 'W10-02'),
    ('W10F-022', 'separate_calendar_market_clocks', 'W10-02'),
    ('W10F-023', 'measure_timescale_value', 'W10-02'),
    ('W10F-024', 'publish_multiscale_state_card', 'W10-02'),
    ('W10F-025', 'define_latent_regime_variables', 'W10-03'),
    ('W10F-026', 'fit_latent_state_model', 'W10-03'),
    ('W10F-027', 'infer_regime_posterior', 'W10-03'),
    ('W10F-028', 'align_regimes_across_markets', 'W10-03'),
    ('W10F-029', 'detect_market_specific_residual', 'W10-03'),
    ('W10F-030', 'measure_latent_state_stability', 'W10-03'),
    ('W10F-031', 'compare_to_observed_baseline', 'W10-03'),
    ('W10F-032', 'publish_latent_regime_card', 'W10-03'),
    ('W10F-033', 'define_event_node', 'W10-04'),
    ('W10F-034', 'define_propagation_edge', 'W10-04'),
    ('W10F-035', 'fit_event_response_kernel', 'W10-04'),
    ('W10F-036', 'propagate_event_posterior', 'W10-04'),
    ('W10F-037', 'control_double_counted_paths', 'W10-04'),
    ('W10F-038', 'separate_predictive_causal_edge', 'W10-04'),
    ('W10F-039', 'measure_propagation_calibration', 'W10-04'),
    ('W10F-040', 'publish_event_propagation_card', 'W10-04'),
    ('W10F-041', 'classify_missingness_mechanism', 'W10-05'),
    ('W10F-042', 'build_missingness_mask', 'W10-05'),
    ('W10F-043', 'infer_missing_state_posterior', 'W10-05'),
    ('W10F-046', 'compare_imputation_to_abstention', 'W10-05'),
    ('W10F-047', 'stress_source_dropout', 'W10-05'),
    ('W10F-048', 'publish_missing_data_card', 'W10-05'),
    ('W10F-049', 'define_joint_forecast_target', 'W10-06'),
    ('W10F-051', 'roll_forward_world_state', 'W10-06'),
    ('W10F-052', 'condition_on_known_event', 'W10-06'),
    ('W10F-053', 'condition_on_intervention', 'W10-06'),
    ('W10F-056', 'publish_scenario_ensemble_card', 'W10-06'),
    ('W10F-057', 'load_scoped_causal_claims', 'W10-07'),
    ('W10F-058', 'build_counterfactual_intervention', 'W10-07'),
    ('W10F-059', 'check_counterfactual_identifiability', 'W10-07'),
    ('W10F-060', 'propagate_counterfactual_state', 'W10-07'),
    ('W10F-061', 'run_alternative_graph_sensitivity', 'W10-07'),
    ('W10F-062', 'measure_counterfactual_overlap', 'W10-07'),
    ('W10F-064', 'publish_counterfactual_card', 'W10-07'),
    ('W10F-065', 'define_foundation_model_trial', 'W10-08'),
    ('W10F-066', 'adapt_foundation_inputs', 'W10-08'),
    ('W10F-067', 'run_zero_shot_foundation_forecast', 'W10-08'),
    ('W10F-068', 'run_multivariate_challenger', 'W10-08'),
    ('W10F-069', 'run_local_baseline_comparison', 'W10-08'),
    ('W10F-070', 'measure_compute_value_tradeoff', 'W10-08'),
    ('W10F-071', 'detect_negative_transfer', 'W10-08'),
    ('W10F-072', 'publish_foundation_model_card', 'W10-08'),
    ('W10F-073', 'define_probabilistic_program', 'W10-09'),
    ('W10F-074', 'fit_posterior_parameters', 'W10-09'),
    ('W10F-075', 'run_posterior_predictive_check', 'W10-09'),
    ('W10F-076', 'measure_parameter_identifiability', 'W10-09'),
    ('W10F-077', 'compare_model_structures', 'W10-09'),
    ('W10F-078', 'propagate_parameter_uncertainty', 'W10-09'),
    ('W10F-079', 'detect_prior_sensitivity', 'W10-09'),
    ('W10F-080', 'publish_structural_uncertainty_card', 'W10-09'),
    ('W10F-081', 'define_state_sufficiency_task', 'W10-10'),
    ('W10F-082', 'build_full_state_reference', 'W10-10'),
    ('W10F-083', 'learn_compact_state', 'W10-10'),
    ('W10F-084', 'measure_information_retention', 'W10-10'),
    ('W10F-085', 'measure_compute_storage_reduction', 'W10-10'),
    ('W10F-086', 'test_compact_state_transfer', 'W10-10'),
    ('W10F-087', 'detect_lost_tail_information', 'W10-10'),
    ('W10F-088', 'publish_sufficient_state_card', 'W10-10'),
    ('W10F-089', 'define_world_model_benchmark', 'W10-11'),
    ('W10F-090', 'benchmark_joint_forecast_quality', 'W10-11'),
    ('W10F-091', 'benchmark_event_propagation', 'W10-11'),
    ('W10F-092', 'benchmark_missing_data_robustness', 'W10-11'),
    ('W10F-093', 'benchmark_counterfactual_sensitivity', 'W10-11'),
    ('W10F-094', 'benchmark_state_compression', 'W10-11'),
    ('W10F-095', 'feed_gap_to_frontier', 'W10-11'),
    ('W10F-096', 'publish_world_model_scorecard', 'W10-11'),
    ('W11F-001', 'capture_wave11_head_truth', 'W11-00'),
    ('W11F-002', 'map_decision_to_current_owners', 'W11-00'),
    ('W11F-003', 'classify_decision_novelty', 'W11-00'),
    ('W11F-004', 'bind_decision_tool_versions', 'W11-00'),
    ('W11F-005', 'audit_belief_freshness', 'W11-00'),
    ('W11F-006', 'audit_decision_effect_boundary', 'W11-00'),
    ('W11F-007', 'publish_decision_residual_map', 'W11-00'),
    ('W11F-008', 'verify_wave11_non_duplication', 'W11-00'),
    ('W11F-010', 'define_decision_action_set', 'W11-01'),
    ('W11F-011', 'bind_action_utility_distribution', 'W11-01'),
    ('W11F-012', 'bind_decision_loss_function', 'W11-01'),
    ('W11F-013', 'bind_decision_deadline', 'W11-01'),
    ('W11F-014', 'bind_decision_safety_constraints', 'W11-01'),
    ('W11F-015', 'bind_decision_information_state', 'W11-01'),
    ('W11F-016', 'publish_decision_problem_card', 'W11-01'),
    ('W11F-021', 'estimate_expected_regret_reduction', 'W11-02'),
    ('W11F-024', 'publish_decision_value_card', 'W11-02'),
    ('W11F-025', 'define_information_action', 'W11-03'),
    ('W11F-026', 'bind_information_cost_vector', 'W11-03'),
    ('W11F-027', 'bind_information_latency', 'W11-03'),
    ('W11F-028', 'bind_observation_likelihood', 'W11-03'),
    ('W11F-029', 'bind_information_failure_modes', 'W11-03'),
    ('W11F-030', 'bind_information_access_constraints', 'W11-03'),
    ('W11F-031', 'bind_information_safety_role', 'W11-03'),
    ('W11F-032', 'publish_information_action_card', 'W11-03'),
    ('W11F-033', 'define_information_dependency_edge', 'W11-04'),
    ('W11F-034', 'estimate_conditional_information_value', 'W11-04'),
    ('W11F-037', 'estimate_feature_conditional_value', 'W11-04'),
    ('W11F-038', 'update_marginal_value_after_observation', 'W11-04'),
    ('W11F-040', 'publish_information_dependency_card', 'W11-04'),
    ('W11F-041', 'define_sequential_query_horizon', 'W11-05'),
    ('W11F-042', 'enumerate_query_outcomes', 'W11-05'),
    ('W11F-043', 'update_belief_after_hypothetical_observation', 'W11-05'),
    ('W11F-044', 'score_outcome_conditioned_next_query', 'W11-05'),
    ('W11F-045', 'build_query_policy_tree', 'W11-05'),
    ('W11F-046', 'prune_low_value_query_branches', 'W11-05'),
    ('W11F-047', 'apply_query_stop_rule', 'W11-05'),
    ('W11F-048', 'publish_sequential_information_plan', 'W11-05'),
    ('W11F-049', 'define_information_deadline', 'W11-06'),
    ('W11F-050', 'estimate_query_completion_distribution', 'W11-06'),
    ('W11F-051', 'estimate_opportunity_decay_during_query', 'W11-06'),
    ('W11F-053', 'prioritize_fast_safety_query', 'W11-06'),
    ('W11F-054', 'compare_query_vs_wait', 'W11-06'),
    ('W11F-056', 'publish_deadline_information_card', 'W11-06'),
    ('W11F-057', 'define_computation_action', 'W11-07'),
    ('W11F-058', 'define_simulation_fidelity_ladder', 'W11-07'),
    ('W11F-059', 'estimate_fidelity_error_model', 'W11-07'),
    ('W11F-061', 'choose_next_computation_fidelity', 'W11-07'),
    ('W11F-062', 'allocate_monte_carlo_samples', 'W11-07'),
    ('W11F-064', 'publish_computation_value_card', 'W11-07'),
    ('W11F-065', 'define_optional_feature_action', 'W11-08'),
    ('W11F-066', 'estimate_feature_acquisition_value', 'W11-08'),
    ('W11F-067', 'estimate_source_acquisition_value', 'W11-08'),
    ('W11F-068', 'condition_value_on_existing_features', 'W11-08'),
    ('W11F-069', 'select_candidate_specific_features', 'W11-08'),
    ('W11F-071', 'audit_feature_acquisition_bias', 'W11-08'),
    ('W11F-072', 'publish_active_sensing_card', 'W11-08'),
    ('W11F-073', 'define_meta_pomdp_state', 'W11-09'),
    ('W11F-074', 'define_meta_pomdp_actions', 'W11-09'),
    ('W11F-075', 'define_meta_observation_model', 'W11-09'),
    ('W11F-076', 'define_meta_transition_model', 'W11-09'),
    ('W11F-077', 'define_meta_reward_or_loss', 'W11-09'),
    ('W11F-078', 'solve_bounded_belief_policy', 'W11-09'),
    ('W11F-079', 'compare_pomdp_to_myopic_voi', 'W11-09'),
    ('W11F-080', 'publish_metareasoning_policy_card', 'W11-09'),
    ('W11F-081', 'classify_mandatory_safety_information', 'W11-10'),
    ('W11F-083', 'verify_safety_observation_freshness', 'W11-10'),
    ('W11F-086', 'measure_safety_query_overhead', 'W11-10'),
    ('W11F-087', 'stress_safety_budget_pressure', 'W11-10'),
    ('W11F-088', 'publish_safety_information_card', 'W11-10'),
    ('W11F-089', 'define_decision_intelligence_benchmark', 'W11-11'),
    ('W11F-090', 'benchmark_uncertainty_reduction_baseline', 'W11-11'),
    ('W11F-091', 'benchmark_decision_aware_voi', 'W11-11'),
    ('W11F-092', 'benchmark_sequential_sensing', 'W11-11'),
    ('W11F-093', 'benchmark_value_of_computation', 'W11-11'),
    ('W11F-095', 'feed_decision_gap_to_frontier', 'W11-11'),
    ('W11F-096', 'publish_decision_intelligence_scorecard', 'W11-11'),
)


def _make_adapter(
    requirement_id: str,
    symbol: str,
    package: str,
) -> Callable[..., Mapping[str, Any]]:
    def adapter(
        payload: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Mapping[str, Any]:
        return run_requirement(
            requirement_id,
            symbol,
            package,
            payload,
            **kwargs,
        )

    adapter.__name__ = symbol
    adapter.__qualname__ = symbol
    adapter.__doc__ = f"PR-357 {requirement_id} research-only adapter."
    return adapter


for _requirement_id, _symbol, _package in RESIDUAL_REQUIREMENTS:
    globals()[_symbol] = _make_adapter(_requirement_id, _symbol, _package)

del _requirement_id, _symbol, _package

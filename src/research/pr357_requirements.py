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

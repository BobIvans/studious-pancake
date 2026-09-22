"""Exact residual PR-358 requirement adapters.

Bespoke deterministic semantics live in :mod:`src.research.pr358_core`.  The
remaining roadmap symbols are thin research-contract adapters.  They preserve
exact requirement identities while keeping external/paid/live work blocked.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from src.research.pr358_contracts import (
    EFFECT_BOUNDARY,
    PR358ContractError,
    canonical_hash,
)

_EXTERNAL_PREFIXES = (
    "capture_",
    "fit_",
    "run_lpcmci",
    "run_causal_graph",
    "search_symbolic_",
    "simulate_private_orderflow_",
    "bind_service_protocol_versions",
)
_RESOURCE_TOKENS = (
    "budget",
    "cost",
    "count",
    "latency",
    "limit",
    "price",
    "quota",
    "reserve",
    "spend",
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
        raise PR358ContractError("PR358_FLOAT_RESEARCH_VALUE_FORBIDDEN")
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
        raise PR358ContractError(
            "PR358_EFFECT_AUTHORITY_FORBIDDEN:" + ",".join(sorted(unsafe))
        )
    for key, value in normalized.items():
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value < 0
            and any(token in key for token in _RESOURCE_TOKENS)
        ):
            raise PR358ContractError(f"PR358_NEGATIVE_RESOURCE_VALUE:{key}")

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
        "roadmap_id": "PR-358",
        "requirement_id": requirement_id,
        "symbol": symbol,
        "package": package,
        "status": status,
        "execution_right": False,
        "production_ready": False,
        "live_enabled": False,
        "remote_mutation": False,
        "customer_billing": False,
        "external_service_activation": False,
        "effect_boundary_preserved": True,
        "input": normalized,
        "evidence_refs": evidence_refs,
        "external_qualification": False,
    }
    if verb in {
        "define",
        "bind",
        "publish",
        "record",
        "register",
        "materialize",
        "assemble",
    }:
        result["immutable_artifact"] = True
    if verb in {
        "audit",
        "reject",
        "block",
        "verify",
        "detect",
        "retract",
        "validate",
    }:
        result["fail_closed"] = True
    if verb in {"fit", "run", "search"}:
        result["holdout_or_control_required"] = True
        result["automatic_promotion"] = False
    if verb in {
        "measure",
        "estimate",
        "compute",
        "compare",
        "benchmark",
        "classify",
    }:
        result["metric_generated"] = True
    if status == "BLOCKED_EXTERNAL":
        result["blockers"] = ("EXTERNAL_EVIDENCE_NOT_MATERIALIZED",)

    result["receipt_hash"] = canonical_hash(result)
    return result


RESIDUAL_REQUIREMENTS: tuple[tuple[str, str, str], ...] = (
    ("W12F-001", "capture_wave12_head_truth", "W12-00"),
    ("W12F-002", "map_fabric_to_current_owners", "W12-00"),
    ("W12F-003", "classify_fabric_novelty", "W12-00"),
    ("W12F-004", "bind_fabric_tool_versions", "W12-00"),
    ("W12F-005", "audit_research_only_effect_boundary", "W12-00"),
    ("W12F-006", "audit_market_truth_boundary", "W12-00"),
    ("W12F-007", "publish_fabric_residual_map", "W12-00"),
    ("W12F-008", "verify_wave12_non_duplication", "W12-00"),
    ("W12F-012", "bind_node_inputs", "W12-01"),
    ("W12F-013", "bind_node_outputs", "W12-01"),
    ("W12F-014", "bind_node_determinism_class", "W12-01"),
    ("W12F-016", "publish_experiment_dag_manifest", "W12-01"),
    ("W12F-017", "lookup_node_cache", "W12-02"),
    ("W12F-018", "store_node_cache_entry", "W12-02"),
    ("W12F-022", "recompute_impacted_partitions", "W12-02"),
    ("W12F-023", "measure_cache_hit_value", "W12-02"),
    ("W12F-024", "publish_cache_reuse_card", "W12-02"),
    ("W12F-026", "bind_node_resource_request", "W12-03"),
    ("W12F-028", "bind_node_checkpoint_policy", "W12-03"),
    ("W12F-030", "reschedule_preempted_node", "W12-03"),
    ("W12F-031", "measure_scheduler_efficiency", "W12-03"),
    ("W12F-032", "publish_compute_schedule_card", "W12-03"),
    ("W12F-034", "expand_trial_grid", "W12-04"),
    ("W12F-037", "apply_early_stop_policy", "W12-04"),
    ("W12F-038", "apply_successive_fidelity_policy", "W12-04"),
    ("W12F-040", "publish_experiment_matrix_card", "W12-04"),
    ("W12F-046", "bind_synthetic_flag", "W12-05"),
    ("W12F-047", "sample_control_correlation_windows", "W12-05"),
    ("W12F-048", "publish_correlation_pool_card", "W12-05"),
    ("W12F-049", "register_data_bucket", "W12-06"),
    ("W12F-050", "register_bucket_partition", "W12-06"),
    ("W12F-051", "register_bucket_semantics", "W12-06"),
    ("W12F-056", "publish_bucket_registry_card", "W12-06"),
    ("W12F-058", "bind_view_watermark", "W12-07"),
    ("W12F-059", "bind_view_revision_policy", "W12-07"),
    ("W12F-064", "publish_incremental_view_card", "W12-07"),
    ("W12F-065", "emit_run_lineage_event", "W12-08"),
    ("W12F-066", "emit_dataset_lineage_event", "W12-08"),
    ("W12F-067", "bind_code_data_environment", "W12-08"),
    ("W12F-069", "attach_failed_node_evidence", "W12-08"),
    ("W12F-072", "publish_evidence_bundle", "W12-08"),
    ("W12F-075", "map_technology_to_data_buckets", "W12-09"),
    ("W12F-076", "define_technology_baseline", "W12-09"),
    ("W12F-077", "define_technology_experiment", "W12-09"),
    ("W12F-078", "record_technology_cost_profile", "W12-09"),
    ("W12F-079", "record_technology_result", "W12-09"),
    ("W12F-080", "publish_technology_observatory_card", "W12-09"),
    ("W12F-082", "bind_vertical_bucket_inputs", "W12-10"),
    ("W12F-083", "bind_vertical_compute_profile", "W12-10"),
    ("W12F-084", "bind_vertical_baselines", "W12-10"),
    ("W12F-085", "bind_vertical_metrics", "W12-10"),
    ("W12F-086", "bind_vertical_holdout", "W12-10"),
    ("W12F-088", "publish_vertical_experiment_card", "W12-10"),
    ("W12F-089", "measure_experiment_throughput", "W12-11"),
    ("W12F-091", "measure_incremental_recompute_savings", "W12-11"),
    ("W12F-093", "measure_evidence_assembly_latency", "W12-11"),
    ("W12F-094", "measure_bucket_reuse_value", "W12-11"),
    ("W12F-095", "feed_compute_gap_to_frontier", "W12-11"),
    ("W12F-096", "publish_research_fleet_scorecard", "W12-11"),
    ("W13F-001", "capture_wave13_head_truth", "W13-00"),
    ("W13F-002", "map_relation_to_current_owners", "W13-00"),
    ("W13F-003", "classify_relation_novelty", "W13-00"),
    ("W13F-004", "bind_relation_tool_versions", "W13-00"),
    ("W13F-005", "audit_relation_effect_boundary", "W13-00"),
    ("W13F-006", "audit_relation_graph_boundary", "W13-00"),
    ("W13F-007", "publish_relation_residual_map", "W13-00"),
    ("W13F-008", "verify_wave13_non_duplication", "W13-00"),
    ("W13F-010", "bind_relation_variables", "W13-01"),
    ("W13F-011", "bind_relation_lag_distribution", "W13-01"),
    ("W13F-012", "bind_relation_scope", "W13-01"),
    ("W13F-013", "bind_relation_method", "W13-01"),
    ("W13F-014", "bind_relation_uncertainty", "W13-01"),
    ("W13F-015", "bind_relation_status", "W13-01"),
    ("W13F-016", "publish_relation_candidate_card", "W13-01"),
    ("W13F-017", "build_relation_episode", "W13-02"),
    ("W13F-019", "cluster_interfering_events", "W13-02"),
    ("W13F-022", "bind_episode_market_state", "W13-02"),
    ("W13F-023", "bind_episode_outcome_maturity", "W13-02"),
    ("W13F-024", "publish_relation_episode_corpus", "W13-02"),
    ("W13F-030", "run_conditional_dependence_challenger", "W13-03"),
    ("W13F-032", "publish_relation_method_card", "W13-03"),
    ("W13F-033", "define_relation_conditioning_set", "W13-04"),
    ("W13F-036", "run_conditional_independence_test", "W13-04"),
    ("W13F-037", "run_lpcmci_or_pcmci_challenger", "W13-04"),
    ("W13F-038", "run_causal_graph_refuter", "W13-04"),
    ("W13F-040", "publish_conditional_relation_card", "W13-04"),
    ("W13F-041", "define_event_sequence_family", "W13-05"),
    ("W13F-042", "fit_multivariate_excitation_card", "W13-05"),
    ("W13F-043", "mine_precursor_sequence", "W13-05"),
    ("W13F-046", "stress_sequence_under_regime_change", "W13-05"),
    ("W13F-047", "link_sequence_to_counterexamples", "W13-05"),
    ("W13F-048", "publish_early_warning_sequence", "W13-05"),
    ("W13F-050", "fit_vine_copula_challenger", "W13-06"),
    ("W13F-051", "estimate_conditional_tail_risk", "W13-06"),
    ("W13F-053", "measure_tail_relation_stability", "W13-06"),
    ("W13F-054", "compare_tail_to_linear_relation", "W13-06"),
    ("W13F-055", "detect_tail_only_relation", "W13-06"),
    ("W13F-056", "publish_tail_relation_card", "W13-06"),
    ("W13F-057", "define_invariant_search_space", "W13-07"),
    ("W13F-059", "search_symbolic_relation_family", "W13-07"),
    ("W13F-062", "test_cross_market_symbolic_model", "W13-07"),
    ("W13F-064", "publish_invariant_law_candidate", "W13-07"),
    ("W13F-065", "define_relation_stability_window", "W13-08"),
    ("W13F-067", "measure_regime_specific_relation", "W13-08"),
    ("W13F-070", "estimate_relation_decay", "W13-08"),
    ("W13F-071", "schedule_relation_requalification", "W13-08"),
    ("W13F-072", "publish_relation_stability_card", "W13-08"),
    ("W13F-073", "define_relation_motif", "W13-09"),
    ("W13F-074", "retrieve_prior_relation_motifs", "W13-09"),
    ("W13F-075", "map_motif_to_target_market", "W13-09"),
    ("W13F-076", "fit_target_local_relation", "W13-09"),
    ("W13F-077", "fit_motif_transfer_relation", "W13-09"),
    ("W13F-078", "measure_relation_transfer_gain", "W13-09"),
    ("W13F-080", "publish_relation_transfer_card", "W13-09"),
    ("W13F-081", "define_relation_hypothesis_family", "W13-10"),
    ("W13F-084", "search_counterexample_windows", "W13-10"),
    ("W13F-085", "canonicalize_relation_counterexample", "W13-10"),
    ("W13F-087", "retain_negative_relation_memory", "W13-10"),
    ("W13F-088", "publish_relation_falsification_card", "W13-10"),
    ("W13F-094", "materialize_early_warning_feed", "W13-11"),
    ("W13F-095", "benchmark_relation_atlas", "W13-11"),
    ("W13F-096", "publish_relation_atlas_scorecard", "W13-11"),
    ("W14F-001", "capture_wave14_head_truth", "W14-00"),
    ("W14F-002", "map_service_to_current_owners", "W14-00"),
    ("W14F-003", "classify_service_novelty", "W14-00"),
    ("W14F-004", "bind_service_protocol_versions", "W14-00"),
    ("W14F-005", "audit_service_effect_boundary", "W14-00"),
    ("W14F-006", "audit_product_ledger_boundary", "W14-00"),
    ("W14F-007", "publish_service_residual_map", "W14-00"),
    ("W14F-008", "verify_wave14_non_duplication", "W14-00"),
    ("W14F-010", "bind_service_input_contract", "W14-01"),
    ("W14F-011", "bind_service_output_contract", "W14-01"),
    ("W14F-012", "bind_service_evidence_requirements", "W14-01"),
    ("W14F-013", "bind_service_freshness_policy", "W14-01"),
    ("W14F-014", "bind_service_sla", "W14-01"),
    ("W14F-015", "bind_service_price_model", "W14-01"),
    ("W14F-016", "publish_service_offer_card", "W14-01"),
    ("W14F-017", "register_evidence_product", "W14-02"),
    ("W14F-019", "bind_product_version", "W14-02"),
    ("W14F-023", "materialize_product_catalog", "W14-02"),
    ("W14F-024", "publish_product_catalog_card", "W14-02"),
    ("W14F-025", "define_service_demand_experiment", "W14-03"),
    ("W14F-027", "estimate_customer_value_proxy", "W14-03"),
    ("W14F-029", "compare_pay_per_result_pricing", "W14-03"),
    ("W14F-030", "measure_demand_elasticity", "W14-03"),
    ("W14F-031", "detect_subsidy_dependency", "W14-03"),
    ("W14F-032", "publish_service_economics_card", "W14-03"),
    ("W14F-035", "enumerate_solver_strategy_classes", "W14-04"),
    ("W14F-037", "measure_user_surplus", "W14-04"),
    ("W14F-038", "measure_solver_margin", "W14-04"),
    ("W14F-039", "measure_fade_or_failure_risk", "W14-04"),
    ("W14F-040", "publish_solver_market_card", "W14-04"),
    ("W14F-042", "define_keeper_job_request", "W14-05"),
    ("W14F-043", "bind_keeper_authorization_ref", "W14-05"),
    ("W14F-045", "measure_keeper_completion_quality", "W14-05"),
    ("W14F-046", "measure_keeper_failure_cost", "W14-05"),
    ("W14F-047", "estimate_keeper_fee_schedule", "W14-05"),
    ("W14F-048", "publish_keeper_market_card", "W14-05"),
    ("W14F-050", "normalize_sponsor_capability", "W14-06"),
    ("W14F-051", "estimate_sponsor_cost_distribution", "W14-06"),
    ("W14F-052", "estimate_token_fee_conversion_risk", "W14-06"),
    ("W14F-053", "simulate_sponsor_abuse_case", "W14-06"),
    ("W14F-055", "compare_paymaster_models", "W14-06"),
    ("W14F-056", "publish_sponsor_economics_card", "W14-06"),
    ("W14F-057", "define_machine_service_request", "W14-07"),
    ("W14F-059", "bind_payment_network_asset", "W14-07"),
    ("W14F-062", "measure_payment_overhead", "W14-07"),
    ("W14F-063", "measure_micropayment_break_even", "W14-07"),
    ("W14F-064", "publish_machine_payment_card", "W14-07"),
    ("W14F-065", "define_agent_service_identity", "W14-08"),
    ("W14F-066", "bind_agent_capability_claims", "W14-08"),
    ("W14F-067", "bind_agent_validation_evidence", "W14-08"),
    ("W14F-068", "record_service_feedback", "W14-08"),
    ("W14F-071", "compare_validation_models", "W14-08"),
    ("W14F-072", "publish_agent_trust_card", "W14-08"),
    ("W14F-074", "bind_state_root_and_candidate_hash", "W14-09"),
    ("W14F-075", "bind_simulation_artifact", "W14-09"),
    ("W14F-076", "bind_proof_or_replay_method", "W14-09"),
    ("W14F-077", "measure_verification_cost", "W14-09"),
    ("W14F-078", "measure_information_leakage_risk", "W14-09"),
    ("W14F-079", "simulate_validator_market", "W14-09"),
    ("W14F-080", "publish_verifiable_simulation_card", "W14-09"),
    ("W14F-082", "define_information_reveal_policy", "W14-10"),
    ("W14F-083", "simulate_private_orderflow_market", "W14-10"),
    ("W14F-085", "measure_user_execution_quality", "W14-10"),
    ("W14F-087", "classify_cross_domain_atomicity", "W14-10"),
    ("W14F-088", "publish_confidential_market_card", "W14-10"),
    ("W14F-089", "define_market_science_exchange_benchmark", "W14-11"),
    ("W14F-090", "benchmark_evidence_api_product", "W14-11"),
    ("W14F-091", "benchmark_solver_keeper_products", "W14-11"),
    ("W14F-092", "benchmark_payment_trust_stack", "W14-11"),
    ("W14F-095", "feed_product_gap_to_frontier", "W14-11"),
    ("W14F-096", "publish_market_science_exchange_scorecard", "W14-11"),
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
    adapter.__doc__ = f"PR-358 {requirement_id} research-only adapter."
    return adapter


for _requirement_id, _symbol, _package in RESIDUAL_REQUIREMENTS:
    globals()[_symbol] = _make_adapter(_requirement_id, _symbol, _package)

del _requirement_id, _symbol, _package

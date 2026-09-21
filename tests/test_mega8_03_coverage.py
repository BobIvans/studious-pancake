from __future__ import annotations

import importlib
import json
from pathlib import Path

from src.mega8_03.common import (
    EvidenceEnvelope,
    OfflineDecision,
    AdvisoryModel,
)


EXPECTED = {
    "pr186_keeper": (
        "discover_rebalance_jobs",
        "price_keeper_reward_and_cost",
        "build_authorized_keeper_plan",
        "qualify_keeper_operation",
    ),
    "pr187_clmm": (
        "measure_clmm_range_pressure",
        "detect_rebalance_residual",
        "estimate_fee_growth_dislocation",
        "emit_clmm_position_candidate",
    ),
    "pr188_rfq": (
        "ingest_solana_intent_quotes",
        "price_rfq_fill_path",
        "build_limit_order_fill_plan",
        "qualify_opt_in_intent_fill",
    ),
    "pr189_orderflow": (
        "index_trigger_and_dca_orders",
        "estimate_scheduled_flow_impact",
        "detect_post_execution_residual",
        "enforce_orderflow_permissions",
    ),
    "pr190_perp_research": (
        "collect_perp_mark_index_funding",
        "normalize_perp_contract_specs",
        "detect_spot_perp_basis",
        "rank_inventory_required_basis",
    ),
    "pr191_spot_perp_sandbox": (
        "build_spot_perp_hedge_plan",
        "reserve_margin_and_inventory",
        "simulate_partial_fill_risk",
        "reconcile_hedged_position",
    ),
    "pr192_liquidation_competition": (
        "estimate_liquidation_competition",
        "cluster_liquidation_queue",
        "simulate_liquidation_cascade",
        "rank_tail_liquidations",
    ),
    "pr193_market_activation": (
        "detect_new_market_activation",
        "compare_router_direct_coverage",
        "verify_liquid_exit_path",
        "qualify_new_market_worker",
    ),
    "pr194_recoveries": (
        "attribute_positive_slippage",
        "attribute_transaction_rebate",
        "attribute_affiliate_or_fee_refund",
        "reconcile_recovery_components",
    ),
    "pr195_survival": (
        "fit_kaplan_meier_survival",
        "fit_parametric_edge_duration",
        "handle_censored_opportunities",
        "calibrate_duration_predictions",
    ),
    "pr196_conformal": (
        "fit_conformal_net_interval",
        "fit_conformal_latency_interval",
        "compute_prediction_set",
        "gate_on_uncertainty_budget",
    ),
    "pr197_causal": (
        "build_causal_event_graph",
        "estimate_transfer_entropy",
        "test_event_precedence_hypothesis",
        "promote_causal_feature",
    ),
    "pr198_hawkes": (
        "fit_hawkes_event_model",
        "estimate_cross_venue_excitation",
        "forecast_event_intensity",
        "validate_intensity_gain",
    ),
    "pr199_gnn": (
        "encode_dynamic_market_graph",
        "train_graph_anomaly_model",
        "score_graph_state_transition",
        "compare_graph_baseline",
    ),
    "pr200_temporal": (
        "build_temporal_sequence_dataset",
        "train_temporal_anomaly_model",
        "score_sequence_survival",
        "benchmark_inference_latency",
    ),
    "pr201_active_learning": (
        "select_uncertain_samples",
        "request_targeted_labels",
        "update_active_learning_pool",
        "measure_label_efficiency",
    ),
    "pr202_meta": (
        "learn_cross_market_representation",
        "adapt_model_to_new_venue",
        "measure_transfer_gain",
        "prevent_negative_transfer",
    ),
    "pr203_model_robustness": (
        "generate_adversarial_features",
        "test_model_data_poisoning",
        "detect_distribution_attack",
        "quarantine_unsafe_model",
    ),
    "pr204_explanations": (
        "compute_local_feature_attribution",
        "emit_human_reason_code",
        "trace_model_to_evidence",
        "audit_explanation_stability",
    ),
    "pr205_ope": (
        "estimate_offline_policy_value",
        "compute_importance_weights",
        "run_doubly_robust_estimator",
        "reject_unsupported_policy_shift",
    ),
    "pr206_bandit": (
        "define_safe_bandit_actions",
        "select_simulation_budget_action",
        "apply_conservative_exploration",
        "audit_bandit_regret_and_cost",
    ),
    "pr207_digital_twin": (
        "generate_synthetic_market_scenario",
        "calibrate_digital_twin",
        "validate_sim_to_real_gap",
        "label_synthetic_vs_observed",
    ),
    "pr208_competition": (
        "cluster_competitor_archetypes",
        "estimate_crowding_regime",
        "model_alpha_capacity_decay",
        "adjust_candidate_for_competition",
    ),
}


def test_exact_meg8_03_function_surface_is_92_unique_callables() -> None:
    observed: list[str] = []
    for module_name, expected_names in EXPECTED.items():
        module = importlib.import_module(f"src.mega8_03.{module_name}")
        assert set(module.__all__) == set(expected_names)
        for name in expected_names:
            assert callable(getattr(module, name))
            observed.append(name)

    assert len(observed) == 92
    assert len(set(observed)) == 92


def test_coverage_manifest_maps_exact_contiguous_nf_range_and_children() -> None:
    payload = json.loads(Path("config/mega8_03_coverage.json").read_text())
    assert payload["mega_id"] == "MEGA8-03"
    assert payload["nf_range"] == ["NF-493", "NF-584"]
    assert payload["nf_count"] == 92
    assert len(payload["children"]) == 23
    nf = [nf_id for child in payload["children"] for nf_id in child["nf"]]
    assert nf == [f"NF-{index:03d}" for index in range(493, 585)]
    assert [child["child"] for child in payload["children"]] == [
        f"PR-{index:03d}" for index in range(186, 209)
    ]


def test_coverage_manifest_cannot_claim_live_release_or_capital_promotion() -> None:
    payload = json.loads(Path("config/mega8_03_coverage.json").read_text())
    assert payload["implementation_status"] == "IMPLEMENTED_OFFLINE"
    assert payload["operational_status"] == "BLOCKED_EXTERNAL_AND_UNQUALIFIED"
    assert payload["source_copy_mode"] == "NO_SOURCE_COPY; INTERNAL_OR_REFERENCE_ONLY"
    for field in (
        "signing_enabled",
        "submission_enabled",
        "live_enabled",
        "automatic_capital_increase_allowed",
        "release_claim_allowed",
        "production_ready",
    ):
        assert payload[field] is False
    assert payload["residual_blockers"]


def test_common_contract_types_default_to_no_execution_authority() -> None:
    envelope = EvidenceEnvelope(
        evidence_id="coverage-fixture",
        evidence_sha256="a" * 64,
        state_generation="state-1",
        deployment_generation="deploy-1",
        policy_generation="policy-1",
        observed_at_ns=1,
        available_at_ns=2,
    )
    assert envelope.signer_allowed is False
    assert envelope.submission_allowed is False
    assert envelope.live_enabled is False

    decision_fields = OfflineDecision.__dataclass_fields__
    for field in (
        "execution_authority",
        "signing_allowed",
        "submission_allowed",
        "live_enabled",
        "automatic_capital_increase_allowed",
    ):
        assert decision_fields[field].default is False

    assert AdvisoryModel.__dataclass_fields__["execution_authority"].default is False

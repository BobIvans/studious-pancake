"""Exact PR-354 ownership manifest for NF-1089..1184."""

from __future__ import annotations

PACKAGES = {
    "RND-00": {
        "module": "operationalize",
        "start": 1089,
        "names": [
            "bind_concrete_source_to_evo",
            "capture_evo_point_in_time_corpus",
            "join_real_bot_operations",
            "build_evo_replay_fixture",
            "run_evo_source_ablation",
            "run_evo_walk_forward",
            "measure_evo_coverage",
            "publish_evo_qualification_verdict"
        ]
    },
    "RND-01": {
        "module": "hook_native",
        "start": 1097,
        "names": [
            "ingest_v4_hook_registry",
            "attest_hook_runtime_identity",
            "decode_hook_state_machine",
            "simulate_hook_fee_surface",
            "simulate_wrapper_hook_parity",
            "simulate_dualpool_jit_liquidity",
            "detect_hook_cross_venue_residual",
            "qualify_hook_family"
        ]
    },
    "RND-02": {
        "module": "reclamm",
        "start": 1105,
        "names": [
            "ingest_reclamm_state",
            "project_reclamm_virtual_balances",
            "project_reclamm_price_range",
            "quote_reclamm_time_surface",
            "detect_reclamm_transition_basis",
            "attribute_reclamm_residual",
            "stress_reclamm_parameter_change",
            "qualify_reclamm_strategy"
        ]
    },
    "RND-03": {
        "module": "midnight",
        "start": 1113,
        "names": [
            "ingest_midnight_market",
            "reconstruct_credit_debt_book",
            "price_midnight_zero_coupon_curve",
            "model_settlement_liquidity",
            "detect_cross_maturity_kink",
            "detect_fixed_float_basis",
            "model_post_maturity_and_liquidation",
            "qualify_midnight_family"
        ]
    },
    "RND-04": {
        "module": "intent_graph",
        "start": 1121,
        "names": [
            "attest_intent_resolver",
            "resolve_order_requirements",
            "compile_intent_dependency_graph",
            "normalize_intent_deadlines_and_finality",
            "compare_solver_quotes_same_intent",
            "estimate_solver_inventory_shadow_cost",
            "detect_intent_settlement_basis",
            "qualify_intent_dialect"
        ]
    },
    "RND-05": {
        "module": "fluid",
        "start": 1129,
        "names": [
            "ingest_fluid_liquidity_layer",
            "ingest_fluid_dex_state",
            "model_smart_collateral_debt_coupling",
            "quote_fluid_liquidation_swap",
            "model_fluid_steth_redemption",
            "detect_fluid_utilization_transition",
            "detect_fluid_cross_protocol_residual",
            "qualify_fluid_family"
        ]
    },
    "RND-06": {
        "module": "umbrella",
        "start": 1137,
        "names": [
            "ingest_umbrella_reserve_state",
            "project_umbrella_slash_exchange_rate",
            "price_umbrella_reward_slash_basis",
            "detect_umbrella_deficit_transition",
            "model_umbrella_cooldown_liquidity",
            "attribute_umbrella_market_residual",
            "stress_umbrella_multi_reserve_event",
            "qualify_umbrella_specialization"
        ]
    },
    "RND-07": {
        "module": "stvault",
        "start": 1145,
        "names": [
            "ingest_stvault_identity_and_roles",
            "ingest_stvault_metrics_and_quarantine",
            "model_stvault_steth_liquidity",
            "model_validator_operator_basis",
            "detect_quarantine_liquidity_basis",
            "detect_stvault_fee_term_basis",
            "stress_stvault_withdrawal_shortfall",
            "qualify_stvault_specialization"
        ]
    },
    "RND-08": {
        "module": "hip3",
        "start": 1153,
        "names": [
            "ingest_hip3_dex_config",
            "track_hip3_config_transition",
            "normalize_hip3_oracle_basis",
            "model_hip3_funding_oi_constraint",
            "detect_hip3_halt_resume_residual",
            "detect_hip3_cross_dex_basis",
            "attribute_hip3_deployer_regime",
            "qualify_hip3_specialization"
        ]
    },
    "RND-09": {
        "module": "contagion",
        "start": 1161,
        "names": [
            "build_collateral_dependency_graph",
            "estimate_protocol_exposure_surface",
            "detect_forced_flow_trigger",
            "simulate_contagion_sequence",
            "estimate_forced_flow_liquidity_depletion",
            "detect_post_contagion_residual",
            "attribute_contagion_episode",
            "qualify_contagion_model"
        ]
    },
    "RND-10": {
        "module": "mechanism_compiler",
        "start": 1169,
        "names": [
            "discover_mechanism_surface",
            "extract_mechanism_state_schema",
            "infer_rights_obligations_timing",
            "compile_candidate_financial_primitives",
            "generate_decoder_adapter_skeleton",
            "generate_mechanism_test_vectors",
            "validate_primitives_against_traces",
            "publish_mechanism_dossier"
        ]
    },
    "RND-11": {
        "module": "deployment_watcher",
        "start": 1177,
        "names": [
            "watch_protocol_registry_delta",
            "watch_onchain_deployment_delta",
            "classify_semantic_delta",
            "score_research_priority",
            "quarantine_new_mechanism",
            "schedule_minimum_data_capture",
            "retire_obsolete_mechanism",
            "feed_watcher_into_evo09"
        ]
    }
}

NF_TO_SYMBOL = {
    spec["start"] + offset: (package, spec["module"], symbol)
    for package, spec in PACKAGES.items()
    for offset, symbol in enumerate(spec["names"])
}
NF_IDS = tuple(sorted(NF_TO_SYMBOL))
ALL_FUNCTIONS = tuple(NF_TO_SYMBOL[nf][2] for nf in NF_IDS)
FUNCTION_COUNT = len(ALL_FUNCTIONS)

if NF_IDS != tuple(range(1089, 1185)):
    raise RuntimeError("PR354_NF_RANGE_MISMATCH")
if FUNCTION_COUNT != 96 or len(set(ALL_FUNCTIONS)) != 96:
    raise RuntimeError("PR354_FUNCTION_OWNERSHIP_MISMATCH")

__all__ = [
    "ALL_FUNCTIONS",
    "FUNCTION_COUNT",
    "NF_IDS",
    "NF_TO_SYMBOL",
    "PACKAGES",
]

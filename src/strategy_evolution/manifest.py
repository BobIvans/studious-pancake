"""Exact PR-353 ownership manifest for NF-1017..1088."""

from __future__ import annotations

PACKAGES = {
    "EVO-01": {"module": "governance_transition", "start": 1017, "names": ["normalize_governance_event","decode_parameter_delta","simulate_post_change_state","price_transition_window","detect_pre_post_activation_basis","bound_governance_execution_uncertainty","build_governance_transition_candidate","qualify_governance_transition"]},
    "EVO-02": {"module": "incentive_epoch", "start": 1025, "names": ["ingest_epoch_emission_schedule","compute_gauge_reward_surface","estimate_incentive_vote_break_even","forecast_fee_distributor_claim","compute_buyback_pressure_band","detect_epoch_roll_dislocation","build_incentive_rotation_candidate","qualify_incentive_rotation"]},
    "EVO-03": {"module": "stake_queue", "start": 1033, "names": ["ingest_validator_queue_state","estimate_validator_activation_exit_eta","price_withdrawal_request_fee","normalize_restaking_withdrawal_state","model_slashing_loss_distribution","compute_stake_liquidity_basis","build_stake_queue_candidate","qualify_stake_queue"]},
    "EVO-04": {"module": "primary_market", "start": 1041, "names": ["normalize_primary_market_terms","track_async_vault_request","estimate_next_nav_oracle_window","price_mint_redeem_latency","detect_primary_secondary_basis","size_settlement_inventory","build_primary_market_candidate","qualify_primary_market"]},
    "EVO-05": {"module": "solvency_event", "start": 1049, "names": ["normalize_solvency_state","estimate_insurance_fund_runway","model_auto_deleveraging_priority","detect_bad_debt_recapitalization_event","price_backstop_auction","price_cover_claim_right","build_solvency_event_candidate","qualify_solvency_event"]},
    "EVO-06": {"module": "intent_rescue", "start": 1057, "names": ["normalize_intent_auction","reconstruct_solver_score","estimate_batch_clearing_price","detect_solver_surplus_residual","detect_keeper_liveness_gap","price_rescue_bounty","build_intent_rescue_candidate","qualify_intent_rescue"]},
    "EVO-07": {"module": "blockspace_option", "start": 1065, "names": ["ingest_inclusion_market_quote","estimate_inclusion_probability_curve","price_preconfirmation_option","estimate_blob_calldata_cost_surface","detect_da_mode_switch","allocate_inclusion_budget","build_blockspace_candidate","qualify_blockspace_candidate"]},
    "EVO-08": {"module": "rights_lifecycle", "start": 1073, "names": ["normalize_rights_lifecycle_event","estimate_expiry_exercise_flow","price_settlement_basis","forecast_unlock_stream_supply","detect_claim_window_mispricing","estimate_transferability_haircut","build_lifecycle_candidate","qualify_lifecycle_candidate"]},
    "EVO-09": {"module": "residual_discovery", "start": 1081, "names": ["build_market_event_feature_frame","build_bot_operation_feature_frame","align_cross_domain_event_time","discover_residual_anomaly_clusters","estimate_anomaly_lead_lag_graph","attribute_opportunity_to_anomaly","score_anomaly_arbitrageability","update_anomaly_coverage_registry"]},
}

NF_TO_SYMBOL = {
    spec["start"] + offset: (package, spec["module"], symbol)
    for package, spec in PACKAGES.items()
    for offset, symbol in enumerate(spec["names"])
}
NF_IDS = tuple(sorted(NF_TO_SYMBOL))
ALL_FUNCTIONS = tuple(NF_TO_SYMBOL[nf][2] for nf in NF_IDS)
FUNCTION_COUNT = len(ALL_FUNCTIONS)

if NF_IDS != tuple(range(1017, 1089)):
    raise RuntimeError("PR353_NF_RANGE_MISMATCH")
if FUNCTION_COUNT != 72 or len(set(ALL_FUNCTIONS)) != 72:
    raise RuntimeError("PR353_FUNCTION_OWNERSHIP_MISMATCH")

__all__ = [
    "ALL_FUNCTIONS",
    "FUNCTION_COUNT",
    "NF_IDS",
    "NF_TO_SYMBOL",
    "PACKAGES",
]

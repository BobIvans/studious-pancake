"""MEGA8-02 ownership manifest for PR-163..185 / NF-401..492."""
from __future__ import annotations

CHILDREN = {
    163: (
        "GRAPH-02",
        (
            (401, "define_financial_primitive_type"),
            (402, "validate_asset_units_and_rights"),
            (403, "resolve_wrapper_underlying_chain"),
            (404, "reject_invalid_primitive_composition"),
        ),
    ),
    164: (
        "GRAPH-03",
        (
            (405, "compile_operation_hyperedge"),
            (406, "bind_multi_input_obligations"),
            (407, "value_multi_output_residuals"),
            (408, "simulate_hyperedge_state_transition"),
        ),
    ),
    165: (
        "ROUTE-01",
        (
            (409, "canonicalize_route"),
            (410, "hash_economic_equivalence_class"),
            (411, "deduplicate_route_variants"),
            (412, "preserve_distinct_resource_profiles"),
        ),
    ),
    166: (
        "GRAPH-04",
        (
            (413, "update_incremental_graph_index"),
            (414, "maintain_scc_cycle_cache"),
            (415, "identify_affected_routes"),
            (416, "invalidate_stale_route_proofs"),
        ),
    ),
    167: (
        "SIM-03",
        (
            (417, "apply_route_leg_to_state"),
            (418, "trace_shared_resource_mutations"),
            (419, "rollback_failed_route_branch"),
            (420, "emit_state_transition_proof"),
        ),
    ),
    168: (
        "PREDICT-01",
        (
            (421, "predict_compute_units"),
            (422, "predict_account_metas"),
            (423, "predict_message_bytes"),
            (424, "calibrate_resource_predictor"),
        ),
    ),
    169: (
        "PREDICT-02",
        (
            (425, "estimate_writable_lock_contention"),
            (426, "build_account_conflict_features"),
            (427, "predict_local_auction_competition"),
            (428, "gate_high_contention_candidate"),
        ),
    ),
    170: (
        "FEE-01",
        (
            (429, "ingest_priority_fee_market"),
            (430, "ingest_tip_floor_market"),
            (431, "estimate_inclusion_cost_curve"),
            (432, "select_economic_fee_bid"),
        ),
    ),
    171: (
        "SOLVER-03",
        (
            (433, "score_route_objectives"),
            (434, "build_pareto_frontier"),
            (435, "select_policy_constrained_route"),
            (436, "explain_tradeoff_selection"),
        ),
    ),
    172: (
        "SOLVER-04",
        (
            (437, "formulate_mixed_route_problem"),
            (438, "solve_discrete_route_choice"),
            (439, "solve_continuous_flow_allocation"),
            (440, "verify_solver_optimality_gap"),
        ),
    ),
    173: (
        "SOLVER-05",
        (
            (441, "estimate_quote_uncertainty"),
            (442, "build_capacity_confidence_envelope"),
            (443, "optimize_worst_case_net"),
            (444, "reject_fragile_opportunity"),
        ),
    ),
    174: (
        "CAPITAL-03",
        (
            (445, "enumerate_lender_variants"),
            (446, "model_shared_lender_liquidity"),
            (447, "allocate_borrow_across_lenders"),
            (448, "select_atomic_financing_variant"),
        ),
    ),
    175: (
        "TXVAR-01",
        (
            (449, "generate_transaction_variants"),
            (450, "bind_variant_resources"),
            (451, "prune_dominated_variants"),
            (452, "schedule_variant_simulations"),
        ),
    ),
    176: (
        "PROOF-01",
        (
            (453, "build_solver_certificate"),
            (454, "trace_constraint_bindings"),
            (455, "explain_candidate_rejection"),
            (456, "verify_certificate_replay"),
        ),
    ),
    177: (
        "SOLANA-CONFIG-01",
        (
            (457, "collect_program_upgrade_events"),
            (458, "collect_protocol_config_changes"),
            (459, "classify_upgrade_impact"),
            (460, "trigger_protocol_requalification"),
        ),
    ),
    178: (
        "ORACLE-02",
        (
            (461, "model_oracle_publish_schedule"),
            (462, "score_confidence_band_dislocation"),
            (463, "detect_oracle_update_lag"),
            (464, "route_oracle_signal_to_workers"),
        ),
    ),
    179: (
        "STABLE-01",
        (
            (465, "register_stablecoin_redemption_right"),
            (466, "read_mint_redeem_capacity"),
            (467, "quote_stablecoin_conversion"),
            (468, "detect_stablecoin_parity_cycle"),
        ),
    ),
    180: (
        "VAULT-01",
        (
            (469, "register_vault_share_semantics"),
            (470, "read_vault_nav_and_capacity"),
            (471, "quote_share_mint_burn"),
            (472, "detect_vault_share_parity"),
        ),
    ),
    181: (
        "YIELD-01",
        (
            (473, "register_yield_exchange_rate"),
            (474, "normalize_accrual_index"),
            (475, "quote_immediate_yield_conversion"),
            (476, "detect_exchange_rate_dislocation"),
        ),
    ),
    182: (
        "LST-02",
        (
            (477, "discover_stake_pool_deployments"),
            (478, "read_stake_pool_exchange_rate"),
            (479, "model_exit_queue_capacity"),
            (480, "rank_lender_independent_lst_edges"),
        ),
    ),
    183: (
        "LST-03",
        (
            (481, "quote_stake_account_exchange"),
            (482, "build_stake_account_route"),
            (483, "verify_instant_exit_capacity"),
            (484, "simulate_stake_account_cycle"),
        ),
    ),
    184: (
        "LP-01",
        (
            (485, "decode_lp_share_supply"),
            (486, "compute_lp_token_nav"),
            (487, "quote_lp_mint_burn"),
            (488, "detect_lp_nav_cycle"),
        ),
    ),
    185: (
        "POL-01",
        (
            (489, "collect_protocol_owned_liquidity"),
            (490, "collect_fee_sweep_events"),
            (491, "estimate_inventory_release_impact"),
            (492, "emit_protocol_inventory_candidate"),
        ),
    ),
}

FUNCTION_COUNT = sum(len(rows) for _, rows in CHILDREN.values())
NF_IDS = tuple(nf for _, (_, rows) in sorted(CHILDREN.items()) for nf, _ in rows)
ALL_FUNCTIONS = tuple(
    name for _, (_, rows) in sorted(CHILDREN.items()) for _, name in rows
)

__all__ = ["CHILDREN", "FUNCTION_COUNT", "NF_IDS", "ALL_FUNCTIONS"]

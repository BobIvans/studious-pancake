"""Exact ULTIMATE-MEGA1 new-owner manifest: PR-303..326 / NF-897..1016."""

from __future__ import annotations

CHILDREN = {
    303: (
        (897, "seed_replay_witness_from_message"),
        (898, "expand_witness_dependency_closure"),
        (899, "minimize_replay_witness"),
        (900, "replay_witness_without_network"),
        (901, "export_witness_reproduction_bundle"),
    ),
    304: (
        (902, "define_replay_intervention_matrix"),
        (903, "run_paired_failure_replays"),
        (904, "reduce_failure_trigger_set"),
        (905, "export_candidate_repair_hypothesis"),
    ),
    305: (
        (906, "encode_financing_composition_constraints"),
        (907, "encode_prefix_balance_and_lifetimes"),
        (908, "solve_financing_order_variant"),
        (909, "verify_solved_financing_variant"),
        (910, "record_financing_unsat_core"),
    ),
    306: (
        (911, "capture_token_amount_basis"),
        (912, "normalize_quote_amount_basis"),
        (913, "segment_epoch_fee_boundaries"),
        (914, "reject_cosmetic_price_anomaly"),
        (915, "reconcile_display_adjusted_fills"),
    ),
    307: (
        (916, "detect_stake_pool_refresh_boundary"),
        (917, "project_qualified_pool_refresh"),
        (918, "quote_epoch_bound_pool_exit"),
        (919, "compose_pool_refresh_exit_candidate"),
        (920, "verify_pool_refresh_edge_survival"),
    ),
    308: (
        (921, "classify_orderbook_observability"),
        (922, "propagate_queue_position_bounds"),
        (923, "replay_partial_fill_envelopes"),
        (924, "separate_replay_and_impact_models"),
        (925, "compare_fill_envelope_to_settlement"),
    ),
    309: (
        (926, "decode_jit_auction_envelope"),
        (927, "evaluate_jit_price_at_slot"),
        (928, "plan_jit_fill_and_hedge"),
        (929, "build_unsigned_jit_variant"),
        (930, "score_jit_counterfactual_quality"),
    ),
    310: (
        (931, "normalize_async_vault_claim"),
        (932, "advance_async_claim_state"),
        (933, "price_claim_liquidity_discount"),
        (934, "plan_claim_acquisition_and_settlement"),
        (935, "reconcile_async_claim_cashflows"),
    ),
    311: (
        (936, "classify_term_redemption_phase"),
        (937, "bind_matured_principal_index"),
        (938, "quote_matured_pt_cash_exit"),
        (939, "build_matured_pt_route"),
        (940, "evaluate_maturity_boundary_episode"),
    ),
    312: (
        (941, "attest_v4_hook_behavior_scope"),
        (942, "bind_hook_quote_context"),
        (943, "interpret_hook_currency_deltas"),
        (944, "construct_balanced_v4_plan"),
        (945, "replay_hook_adversarial_cases"),
    ),
    313: (
        (946, "load_virtual_order_checkpoint"),
        (947, "advance_virtual_orders_to_block"),
        (948, "quote_post_virtual_order_swap"),
        (949, "assemble_twamm_residual_cycle"),
        (950, "test_lazy_execution_equivalence"),
    ),
    314: (
        (951, "read_clipper_sale_envelope"),
        (952, "classify_clipper_take_or_reset"),
        (953, "size_clipper_collateral_bid"),
        (954, "compose_clipper_callback_settlement"),
        (955, "reconcile_clipper_sale_attempt"),
    ),
    315: (
        (956, "resolve_borrower_preliquidation_rights"),
        (957, "evaluate_preliquidation_band"),
        (958, "size_authorized_preliquidation"),
        (959, "bind_preliquidation_callback"),
        (960, "publish_preliquidation_class_evidence"),
    ),
    316: (
        (961, "attest_liquidatable_wrapper_family"),
        (962, "expand_seized_collateral_outputs"),
        (963, "solve_basket_to_debt_unwind"),
        (964, "compile_liquidation_basket_obligations"),
        (965, "verify_basket_liquidation_conservation"),
    ),
    317: (
        (966, "normalize_outcome_partition_contract"),
        (967, "verify_disjoint_complete_partition"),
        (968, "derive_negative_risk_payoff_map"),
        (969, "price_executable_outcome_package"),
        (970, "emit_outcome_package_witness"),
    ),
    318: (
        (971, "normalize_option_settlement_family"),
        (972, "construct_executable_payoff_matrix"),
        (973, "solve_integer_option_package"),
        (974, "recheck_option_payoff_certificate"),
        (975, "simulate_option_leg_fill_failures"),
    ),
    319: (
        (976, "normalize_perp_funding_cashflow"),
        (977, "align_hedge_funding_calendars"),
        (978, "solve_inverse_linear_hedge_units"),
        (979, "stress_funding_basis_path"),
        (980, "reconcile_funding_ledger_receipts"),
    ),
    320: (
        (981, "capture_short_borrow_entitlement"),
        (982, "bind_short_leg_to_borrow_window"),
        (983, "simulate_borrow_recall_path"),
        (984, "invalidate_short_admission_on_recall"),
        (985, "reconcile_borrow_term_costs"),
    ),
    321: (
        (986, "normalize_transfer_rail_identity"),
        (987, "record_transfer_rail_capability"),
        (988, "estimate_transfer_latency_envelope"),
        (989, "validate_prefunded_crossvenue_plan"),
        (990, "reconcile_transfer_identity_chain"),
    ),
    322: (
        (991, "read_l2_sequencer_health_witness"),
        (992, "enforce_sequencer_recovery_window"),
        (993, "estimate_l2_full_fee_components"),
        (994, "bind_l2_finality_observation"),
        (995, "verify_l2_fee_and_recovery_cases"),
    ),
    323: (
        (996, "build_typed_cashflow_lattice"),
        (997, "derive_cashflow_equivalence_classes"),
        (998, "search_executable_payoff_packages"),
        (999, "certify_package_obligation_balance"),
        (1000, "compile_verified_package_to_existing_dialect"),
        (1001, "benchmark_package_search_against_cycles"),
    ),
    324: (
        (1002, "define_sentinel_sampling_frame"),
        (1003, "draw_independent_sentinel_cells"),
        (1004, "run_reference_search_on_sentinel"),
        (1005, "estimate_observable_miss_rate"),
        (1006, "allocate_detector_improvement_from_misses"),
    ),
    325: (
        (1007, "construct_experiment_interference_graph"),
        (1008, "assign_resource_cluster_experiment"),
        (1009, "detect_cross_arm_contamination"),
        (1010, "estimate_cluster_aware_effects"),
        (1011, "publish_interference_sensitivity"),
    ),
    326: (
        (1012, "register_sequential_metric_contract"),
        (1013, "update_anytime_evidence_state"),
        (1014, "validate_optional_stopping_rule"),
        (1015, "stress_sequential_error_control"),
        (1016, "export_sequential_qualification_evidence"),
    ),
}

NF_IDS = tuple(nf for pr in sorted(CHILDREN) for nf, _ in CHILDREN[pr])
ALL_FUNCTIONS = tuple(name for pr in sorted(CHILDREN) for _, name in CHILDREN[pr])
FUNCTION_COUNT = len(ALL_FUNCTIONS)

__all__ = ["ALL_FUNCTIONS", "CHILDREN", "FUNCTION_COUNT", "NF_IDS"]

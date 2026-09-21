"""MEGA8-06 ownership manifest for PR-255..270 / NF-705..768."""

CHILDREN = {
    255: ("MICRO-01", ((705, "estimate_adverse_selection"), (706, "predict_fill_quality"), (707, "compute_markout_curve"), (708, "gate_toxic_fill"))),
    256: ("IMPACT-01", ((709, "fit_market_impact_curve"), (710, "estimate_capacity_frontier"), (711, "simulate_self_impact"), (712, "cap_route_size_by_impact"))),
    257: ("TCA-01", ((713, "decompose_transaction_costs"), (714, "benchmark_execution_shortfall"), (715, "compare_submission_channels"), (716, "publish_tca_report"))),
    258: ("PORTFOLIO-02", ((717, "build_opportunity_portfolio"), (718, "estimate_cross_strategy_dependencies"), (719, "solve_portfolio_admission"), (720, "reconcile_portfolio_outcomes"))),
    259: ("RUIN-01", ((721, "estimate_bankroll_survival"), (722, "compute_risk_of_ruin"), (723, "allocate_microcapital_budget"), (724, "trigger_survival_stop"))),
    260: ("TAIL-01", ((725, "build_correlated_stress_scenarios"), (726, "compute_tail_loss_distribution"), (727, "estimate_cvar_budget"), (728, "gate_tail_exposure"))),
    261: ("COUNTERPARTY-01", ((729, "register_counterparty_exposure"), (730, "propagate_dependency_failure"), (731, "score_bridge_custody_risk"), (732, "enforce_counterparty_limits"))),
    262: ("ECON-02", ((733, "estimate_alpha_capacity"), (734, "model_self_crowding_decay"), (735, "detect_strategy_saturation"), (736, "throttle_capacity_usage"))),
    263: ("NETWORK-01", ((737, "probe_rpc_region_quality"), (738, "score_stream_path"), (739, "route_read_request"), (740, "quarantine_degraded_region"))),
    264: ("NETWORK-02", ((741, "ingest_leader_schedule"), (742, "estimate_slot_send_window"), (743, "select_slot_aware_transport"), (744, "audit_slot_submission"))),
    265: ("NETWORK-03", ((745, "build_tpu_quic_payload"), (746, "probe_tpu_endpoint"), (747, "simulate_direct_send_policy"), (748, "qualify_direct_send_adapter"))),
    266: ("SUBMIT-03", ((749, "register_submission_transport"), (750, "score_transport_inclusion"), (751, "route_submission_variant"), (752, "reconcile_transport_receipts"))),
    267: ("MEV-02", ((753, "simulate_adversarial_ordering"), (754, "inject_competing_transactions"), (755, "estimate_mev_loss_envelope"), (756, "gate_ordering_fragility"))),
    268: ("ORDERFLOW-02", ((757, "register_opt_in_orderflow_policy"), (758, "compute_user_surplus_floor"), (759, "build_protective_backrun_plan"), (760, "verify_orderflow_consent"))),
    269: ("RL-EXEC-01", ((761, "build_execution_trajectory_dataset"), (762, "train_offline_execution_policy"), (763, "evaluate_execution_policy_offline"), (764, "gate_policy_deployment"))),
    270: ("RL-BID-01", ((765, "build_fee_bid_dataset"), (766, "train_safe_bid_policy"), (767, "calibrate_bid_risk"), (768, "select_guarded_fee_bid"))),
}

FUNCTION_COUNT = sum(len(rows) for _, rows in CHILDREN.values())
NF_IDS = tuple(nf for _, (_, rows) in sorted(CHILDREN.items()) for nf, _ in rows)
ALL_FUNCTIONS = tuple(
    name for _, (_, rows) in sorted(CHILDREN.items()) for _, name in rows
)

__all__ = ["CHILDREN", "FUNCTION_COUNT", "NF_IDS", "ALL_FUNCTIONS"]

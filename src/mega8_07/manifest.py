"""Exact MEGA8-07 ownership manifest: PR-271..286 / NF-769..832."""

from __future__ import annotations

CHILDREN = {
    271: (
        "PERF-01",
        (
            (769, "define_rust_sidecar_protocol"),
            (770, "batch_quote_in_rust"),
            (771, "search_routes_in_rust"),
            (772, "verify_sidecar_parity"),
        ),
    ),
    272: (
        "PERF-02",
        (
            (773, "vectorize_quote_surface"),
            (774, "batch_route_state_transitions"),
            (775, "benchmark_vectorized_solver"),
            (776, "fall_back_to_scalar_reference"),
        ),
    ),
    273: (
        "GPU-01",
        (
            (777, "build_gpu_feature_batch"),
            (778, "run_gpu_simulation_batch"),
            (779, "benchmark_gpu_economics"),
            (780, "reject_unjustified_gpu_path"),
        ),
    ),
    274: (
        "CACHE-02",
        (
            (781, "publish_immutable_state_slice"),
            (782, "subscribe_edge_cache"),
            (783, "validate_cache_generation"),
            (784, "revoke_stale_cache"),
        ),
    ),
    275: (
        "DIST-01",
        (
            (785, "shard_research_workload"),
            (786, "schedule_deterministic_job"),
            (787, "merge_distributed_results"),
            (788, "verify_distributed_replay"),
        ),
    ),
    276: (
        "STREAM-02",
        (
            (789, "join_event_time_streams"),
            (790, "manage_watermark_lateness"),
            (791, "materialize_stream_state"),
            (792, "replay_stream_join"),
        ),
    ),
    277: (
        "ARCHIVE-02",
        (
            (793, "archive_cold_partition"),
            (794, "verify_archive_manifest"),
            (795, "restore_archived_dataset"),
            (796, "test_archive_disaster_recovery"),
        ),
    ),
    278: (
        "CATALOG-01",
        (
            (797, "catalog_dataset_lineage"),
            (798, "catalog_feature_lineage"),
            (799, "search_evidence_graph"),
            (800, "export_lineage_manifest"),
        ),
    ),
    279: (
        "CAPITAL-04",
        (
            (801, "compute_reinvestment_budget"),
            (802, "apply_growth_policy"),
            (803, "cap_profit_redeployment"),
            (804, "reconcile_growth_cycle"),
        ),
    ),
    280: (
        "WALLET-02",
        (
            (805, "allocate_wallet_roles"),
            (806, "isolate_canary_treasury"),
            (807, "rotate_wallet_generation"),
            (808, "audit_wallet_segregation"),
        ),
    ),
    281: (
        "CAPITAL-05",
        (
            (809, "forecast_flash_liquidity"),
            (810, "reserve_lender_capacity"),
            (811, "detect_capacity_shortfall"),
            (812, "release_capacity_reservation"),
        ),
    ),
    282: (
        "MARGIN-01",
        (
            (813, "normalize_margin_requirements"),
            (814, "optimize_collateral_allocation"),
            (815, "simulate_margin_liquidation"),
            (816, "gate_non_atomic_leverage"),
        ),
    ),
    283: (
        "CREDIT-01",
        (
            (817, "collect_lending_rate_curves"),
            (818, "detect_borrow_supply_spread"),
            (819, "build_rate_arbitrage_plan"),
            (820, "qualify_rate_strategy"),
        ),
    ),
    284: (
        "STABLE-02",
        (
            (821, "register_stablecoin_reserve_model"),
            (822, "ingest_redemption_capacity"),
            (823, "stress_stablecoin_run"),
            (824, "emit_depeg_risk_signal"),
        ),
    ),
    285: (
        "TERM-01",
        (
            (825, "build_term_structure_curve"),
            (826, "normalize_fixed_rate_instruments"),
            (827, "detect_term_basis"),
            (828, "qualify_term_structure_trade"),
        ),
    ),
    286: (
        "LIQ-04",
        (
            (829, "index_cross_protocol_liquidations"),
            (830, "value_protocol_owned_collateral"),
            (831, "allocate_liquidation_capital"),
            (832, "reconcile_liquidation_portfolio"),
        ),
    ),
}

NF_IDS = tuple(nf for _, (_, rows) in sorted(CHILDREN.items()) for nf, _ in rows)
ALL_FUNCTIONS = tuple(
    name for _, (_, rows) in sorted(CHILDREN.items()) for _, name in rows
)
FUNCTION_COUNT = len(ALL_FUNCTIONS)

__all__ = ["ALL_FUNCTIONS", "CHILDREN", "FUNCTION_COUNT", "NF_IDS"]

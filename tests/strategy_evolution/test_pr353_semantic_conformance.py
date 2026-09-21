from __future__ import annotations

import pytest

from src.strategy_evolution.blockspace_option import (
    allocate_inclusion_budget,
    build_blockspace_candidate,
    estimate_blob_calldata_cost_surface,
    estimate_inclusion_probability_curve,
)
from src.strategy_evolution.core import (
    CorrelationHypothesis,
    CoverageCell,
    EvolutionError,
)
from src.strategy_evolution.governance_transition import (
    decode_parameter_delta,
    normalize_governance_event,
    price_transition_window,
    simulate_post_change_state,
)
from src.strategy_evolution.incentive_epoch import (
    build_incentive_rotation_candidate,
    compute_gauge_reward_surface,
    detect_epoch_roll_dislocation,
    ingest_epoch_emission_schedule,
    qualify_incentive_rotation,
)
from src.strategy_evolution.intent_rescue import (
    build_intent_rescue_candidate,
    detect_solver_surplus_residual,
    estimate_batch_clearing_price,
    price_rescue_bounty,
    qualify_intent_rescue,
)
from src.strategy_evolution.primary_market import (
    build_primary_market_candidate,
    detect_primary_secondary_basis,
    price_mint_redeem_latency,
    qualify_primary_market,
    size_settlement_inventory,
    track_async_vault_request,
)
from src.strategy_evolution.residual_discovery import (
    align_cross_domain_event_time,
    attribute_opportunity_to_anomaly,
    build_bot_operation_feature_frame,
    estimate_anomaly_lead_lag_graph,
    update_anomaly_coverage_registry,
)
from src.strategy_evolution.rights_lifecycle import (
    build_lifecycle_candidate,
    forecast_unlock_stream_supply,
    qualify_lifecycle_candidate,
)
from src.strategy_evolution.solvency_event import (
    build_solvency_event_candidate,
    estimate_insurance_fund_runway,
    model_auto_deleveraging_priority,
    normalize_solvency_state,
    qualify_solvency_event,
)
from src.strategy_evolution.stake_queue import (
    build_stake_queue_candidate,
    estimate_validator_activation_exit_eta,
    ingest_validator_queue_state,
    price_withdrawal_request_fee,
    qualify_stake_queue,
)


def _raises(code: str, fn, *args, **kwargs) -> None:
    with pytest.raises(EvolutionError, match=code):
        fn(*args, **kwargs)


def test_evo01_semantic_failures() -> None:
    _raises("AMBIGUOUS_CLOCK", normalize_governance_event, {"clock_ambiguous": True})
    _raises("STATE_UNAVAILABLE", decode_parameter_delta, {"state_available": False})
    _raises(
        "NONDETERMINISTIC_ADAPTER",
        simulate_post_change_state,
        {"adapter_deterministic": False},
    )
    _raises(
        "NO_EXECUTABLE_QUOTE",
        price_transition_window,
        {"executable_quote_available": False},
    )
    _raises(
        "COST_UNKNOWN",
        price_transition_window,
        {"value_low_atoms": 1, "cost_high_atoms": None},
    )


def test_evo02_semantic_failures() -> None:
    _raises(
        "TOKEN_METADATA_UNKNOWN",
        ingest_epoch_emission_schedule,
        {"token_metadata_verified": False},
    )
    _raises("OVERFLOW", compute_gauge_reward_surface, {"tvl_atoms": 2**255})
    _raises(
        "INSIDE_BAND",
        detect_epoch_roll_dislocation,
        {"capacity_atoms": 1, "value_low_atoms": 1, "cost_high_atoms": 1},
    )
    _raises(
        "REWARD_RISK_UNBOUNDED",
        build_incentive_rotation_candidate,
        {"reward_risk_unbounded": True},
    )
    _raises(
        "ATTRIBUTION_LEAK",
        qualify_incentive_rotation,
        object(),
        epoch_count=3,
        policy_passed=True,
        attribution_clean=False,
    )


def test_evo03_eip7002_and_semantic_failures() -> None:
    _raises(
        "UNFINALIZED_HEAD",
        ingest_validator_queue_state,
        {"finality": "PROCESSED", "churn_limit": 1},
    )
    _raises(
        "CHURN_UNKNOWN",
        ingest_validator_queue_state,
        {"finality": "FINALIZED", "churn_limit": 0},
    )
    _raises(
        "FORK_MISMATCH",
        estimate_validator_activation_exit_eta,
        {"fork_mismatch": True},
    )
    fee = price_withdrawal_request_fee(
        {
            "active": True,
            "base_fee_atoms": 1,
            "excess_requests": 17,
            "fee_update_fraction": 17,
        }
    )
    assert fee.payload["request_fee_atoms"] == 2
    _raises(
        "ARITHMETIC_MISMATCH",
        price_withdrawal_request_fee,
        {
            "active": True,
            "base_fee_atoms": 1,
            "excess_requests": 17,
            "fee_update_fraction": 17,
            "expected_fee_atoms": 3,
        },
    )
    _raises(
        "DURATION_LIMIT",
        build_stake_queue_candidate,
        {"duration_seconds": 11, "max_duration_seconds": 10},
    )
    _raises(
        "SAMPLE_TOO_SMALL",
        qualify_stake_queue,
        object(),
        replay_count=2,
        policy_passed=True,
        stress_passed=True,
    )


def test_evo04_semantic_failures() -> None:
    _raises("EVENT_GAP", track_async_vault_request, {"event_gap": True})
    _raises("CLAIM_UNCERTAIN", price_mint_redeem_latency, {"claim_uncertain": True})
    _raises(
        "NEGATIVE_WORST_CASE",
        detect_primary_secondary_basis,
        {"value_low_atoms": 2, "cost_high_atoms": 2},
    )
    _raises(
        "CAP_EXCEEDED",
        size_settlement_inventory,
        {
            "requested_atoms": 11,
            "capacity_atoms": 10,
            "duration_seconds": 1,
            "max_duration_seconds": 2,
        },
    )
    _raises(
        "LINEAGE_GAP",
        build_primary_market_candidate,
        {"primary_leg_proven": True, "hedge_present": True},
    )
    _raises(
        "SETTLEMENT_SAMPLE_SMALL",
        qualify_primary_market,
        object(),
        replay_count=2,
        policy_passed=True,
        reconciliation_passed=True,
    )


def test_evo05_semantic_failures() -> None:
    _raises("VERSION_UNKNOWN", normalize_solvency_state, {"version_verified": False})
    _raises(
        "INFLOW_UNVERIFIED",
        estimate_insurance_fund_runway,
        {"inflow_verified": False},
    )
    _raises(
        "RANK_MISMATCH",
        model_auto_deleveraging_priority,
        {
            "rules_verified": True,
            "exposure_scores": {"a": 2, "b": 1},
            "reported_priority": (("b", 1), ("a", 2)),
        },
    )
    _raises(
        "NEGATIVE_EDGE",
        build_solvency_event_candidate,
        {"value_low_atoms": 1, "cost_high_atoms": 1},
    )
    _raises(
        "WATERFALL_REPLAY_FAIL",
        qualify_solvency_event,
        object(),
        replay_count=3,
        policy_passed=True,
        tail_risk_bounded=True,
        waterfall_replay_passed=False,
    )


def test_evo06_semantic_failures() -> None:
    _raises(
        "NUMERIC_OVERFLOW",
        estimate_batch_clearing_price,
        {"feasible_prices_atoms": (2**255,)},
    )
    _raises(
        "ATTRIBUTION_GAP",
        detect_solver_surplus_residual,
        {"attribution_complete": False},
    )
    _raises("COST_UNBOUNDED", price_rescue_bounty, {"reward_funded": True})
    _raises(
        "LINEAGE_GAP",
        build_intent_rescue_candidate,
        {
            "candidate_type": "KEEPER_RESCUE",
            "value_low_atoms": 2,
            "cost_high_atoms": 1,
        },
    )
    _raises(
        "NET_EDGE_NONPOSITIVE",
        build_intent_rescue_candidate,
        {
            "candidate_type": "KEEPER_RESCUE",
            "evidence_refs": ("x",),
            "value_low_atoms": 1,
            "cost_high_atoms": 1,
        },
    )
    _raises(
        "REPLAY_DIVERGENCE",
        qualify_intent_rescue,
        object(),
        replay_count=3,
        policy_passed=True,
        concurrency_passed=True,
        replay_diverged=True,
    )


def test_evo07_semantic_failures() -> None:
    _raises(
        "REGIME_UNKNOWN",
        estimate_inclusion_probability_curve,
        {"regime_unknown": True},
    )
    _raises(
        "MODE_UNAVAILABLE",
        estimate_blob_calldata_cost_surface,
        {"mode_available": False},
    )
    _raises(
        "BUDGET_EXCEEDED",
        allocate_inclusion_budget,
        {"budget_atoms": 1, "options": ((2, 10),)},
    )
    _raises(
        "CURVE_NONMONOTONE",
        allocate_inclusion_budget,
        {"budget_atoms": 10, "curve_nonmonotone": True, "options": ((1, 2),)},
    )
    _raises("SECRET_PRESENT", build_blockspace_candidate, {"private_key": "nope"})
    _raises(
        "LINEAGE_GAP",
        build_blockspace_candidate,
        {"candidate_type": "BLOCKSPACE_OPTION"},
    )


def test_evo08_semantic_failures() -> None:
    _raises(
        "ENTITY_MAP_WEAK",
        forecast_unlock_stream_supply,
        {"entity_map_weak": True},
    )
    _raises(
        "LINEAGE_GAP",
        build_lifecycle_candidate,
        {"candidate_type": "EXPIRY", "terminal_state_known": True},
    )
    _raises(
        "REPLAY_DIVERGENCE",
        qualify_lifecycle_candidate,
        object(),
        replay_count=3,
        policy_passed=True,
        entity_concentration_ok=True,
        replay_diverged=True,
    )


def test_evo09_semantic_failures() -> None:
    _raises(
        "SCHEMA_DRIFT",
        build_bot_operation_feature_frame,
        ({"schema_drift": True},),
    )
    _raises(
        "CLOCK_UNTRUSTED",
        align_cross_domain_event_time,
        {"clock_trusted": False},
        {"rows": ()},
        decision_at=1,
    )
    _raises(
        "CROSS_DOMAIN_AMBIGUITY",
        align_cross_domain_event_time,
        {"cross_domain_ambiguous": True},
        {"rows": ()},
        decision_at=1,
    )
    _raises(
        "GRAPH_TOO_SPARSE",
        estimate_anomaly_lead_lag_graph,
        experiment_id="sparse",
        trigger=(1, 0),
        target=(0, 1),
        max_lag=1,
        latency_corrected=True,
    )
    _raises(
        "ATTRIBUTION_UNSTABLE",
        attribute_opportunity_to_anomaly,
        {"attribution_unstable": True},
    )
    hypothesis = CorrelationHypothesis("h", ("s",), 0, 1, True, ("e",))
    _raises(
        "TAXONOMY_UNKNOWN",
        update_anomaly_coverage_registry,
        cells=(
            CoverageCell(
                "made-up-domain",
                "lead-lag",
                "seconds",
                "hypothesis",
                "informational",
                "finalized",
                "OBSERVED",
            ),
        ),
        hypothesis=hypothesis,
        existing_hypothesis_ids=(),
        evidence_complete=True,
    )

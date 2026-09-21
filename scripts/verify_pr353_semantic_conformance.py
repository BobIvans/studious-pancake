#!/usr/bin/env python3
"""Strict semantic-contract verifier for the PR-353 hardening delta."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

from src.strategy_evolution.stake_queue import price_withdrawal_request_fee

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_LOCAL_FAILURE_CODES = {
    "normalize_governance_event": ("AMBIGUOUS_CLOCK",),
    "decode_parameter_delta": ("STATE_UNAVAILABLE",),
    "simulate_post_change_state": ("NONDETERMINISTIC_ADAPTER",),
    "price_transition_window": ("NO_EXECUTABLE_QUOTE", "COST_UNKNOWN"),
    "ingest_epoch_emission_schedule": ("TOKEN_METADATA_UNKNOWN",),
    "compute_gauge_reward_surface": ("OVERFLOW",),
    "detect_epoch_roll_dislocation": ("INSIDE_BAND",),
    "build_incentive_rotation_candidate": ("REWARD_RISK_UNBOUNDED",),
    "qualify_incentive_rotation": ("ATTRIBUTION_LEAK",),
    "ingest_validator_queue_state": ("UNFINALIZED_HEAD", "CHURN_UNKNOWN"),
    "estimate_validator_activation_exit_eta": ("FORK_MISMATCH",),
    "price_withdrawal_request_fee": ("ARITHMETIC_MISMATCH",),
    "build_stake_queue_candidate": ("DURATION_LIMIT",),
    "qualify_stake_queue": ("SAMPLE_TOO_SMALL",),
    "track_async_vault_request": ("EVENT_GAP",),
    "price_mint_redeem_latency": ("CLAIM_UNCERTAIN",),
    "detect_primary_secondary_basis": ("NEGATIVE_WORST_CASE",),
    "size_settlement_inventory": ("CAP_EXCEEDED",),
    "build_primary_market_candidate": ("LINEAGE_GAP",),
    "qualify_primary_market": ("SETTLEMENT_SAMPLE_SMALL",),
    "normalize_solvency_state": ("VERSION_UNKNOWN",),
    "estimate_insurance_fund_runway": ("INFLOW_UNVERIFIED",),
    "model_auto_deleveraging_priority": ("RANK_MISMATCH",),
    "build_solvency_event_candidate": ("NEGATIVE_EDGE",),
    "qualify_solvency_event": ("WATERFALL_REPLAY_FAIL",),
    "estimate_batch_clearing_price": ("NUMERIC_OVERFLOW",),
    "detect_solver_surplus_residual": ("ATTRIBUTION_GAP",),
    "price_rescue_bounty": ("COST_UNBOUNDED",),
    "build_intent_rescue_candidate": ("NET_EDGE_NONPOSITIVE", "LINEAGE_GAP"),
    "qualify_intent_rescue": ("REPLAY_DIVERGENCE",),
    "estimate_inclusion_probability_curve": ("REGIME_UNKNOWN",),
    "estimate_blob_calldata_cost_surface": ("MODE_UNAVAILABLE",),
    "allocate_inclusion_budget": ("BUDGET_EXCEEDED", "CURVE_NONMONOTONE"),
    "build_blockspace_candidate": ("SECRET_PRESENT", "LINEAGE_GAP"),
    "forecast_unlock_stream_supply": ("ENTITY_MAP_WEAK",),
    "build_lifecycle_candidate": ("LINEAGE_GAP",),
    "qualify_lifecycle_candidate": ("REPLAY_DIVERGENCE",),
    "build_bot_operation_feature_frame": ("SCHEMA_DRIFT",),
    "align_cross_domain_event_time": ("CLOCK_UNTRUSTED", "CROSS_DOMAIN_AMBIGUITY"),
    "estimate_anomaly_lead_lag_graph": ("GRAPH_TOO_SPARSE",),
    "attribute_opportunity_to_anomaly": ("ATTRIBUTION_UNSTABLE",),
    "update_anomaly_coverage_registry": ("TAXONOMY_UNKNOWN",),
}

MODULES = (
    "governance_transition.py",
    "incentive_epoch.py",
    "stake_queue.py",
    "primary_market.py",
    "solvency_event.py",
    "intent_rescue.py",
    "blockspace_option.py",
    "rights_lifecycle.py",
    "residual_discovery.py",
)


def _function_strings(path: Path) -> dict[str, set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        strings = {
            item.value
            for item in ast.walk(node)
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        }
        values[node.name] = strings
    return values


def verify() -> dict[str, object]:
    function_strings: dict[str, set[str]] = {}
    for module in MODULES:
        function_strings.update(
            _function_strings(ROOT / "src" / "strategy_evolution" / module)
        )

    errors: list[str] = []
    for symbol, codes in sorted(REQUIRED_LOCAL_FAILURE_CODES.items()):
        strings = function_strings.get(symbol)
        if strings is None:
            errors.append(f"MISSING_FUNCTION:{symbol}")
            continue
        for code in codes:
            if code not in strings:
                errors.append(f"MISSING_FAILURE_CODE:{symbol}:{code}")

    fee = price_withdrawal_request_fee(
        {
            "active": True,
            "base_fee_atoms": 1,
            "excess_requests": 17,
            "fee_update_fraction": 17,
        }
    )
    if fee.payload["request_fee_atoms"] != 2:
        errors.append("EIP7002_FAKE_EXPONENTIAL_VECTOR_MISMATCH")

    return {
        "accepted": not errors,
        "audited_function_count": len(REQUIRED_LOCAL_FAILURE_CODES),
        "audited_failure_code_count": sum(
            len(codes) for codes in REQUIRED_LOCAL_FAILURE_CODES.values()
        ),
        "errors": errors,
        "live_enabled": False,
        "signing_enabled": False,
        "submission_enabled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = verify()
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(payload)
    return 0 if payload["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

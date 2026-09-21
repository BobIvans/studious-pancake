"""PR-355 MP-N01 Boros cashflow vertical using deterministic fixtures only."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .claims import compile_fixed_floating_payoff, define_cashflow_stream
from .core import stable_hash
from .evidence_native_core import EvidenceNativeError, ResearchReceipt, record, require_int
from .research_quality import (
    benjamini_hochberg_ppm,
    compare_four_model_variants,
    evaluate_probability_calibration,
    form_independent_episodes,
    purged_walk_forward_split,
    source_value_report,
)


def build_boros_fixture_rows() -> tuple[Mapping[str, int | str], ...]:
    return (
        {
            "month": 1,
            "fixed_rate_ppm": 120_000,
            "floating_rate_ppm": 140_000,
            "bid_atoms": 98,
            "ask_atoms": 102,
            "settlement_liquidity_atoms": 2_000,
            "settlement_value_atoms": 20,
            "available_at": 100,
            "revision": 1,
        },
        {
            "month": 2,
            "fixed_rate_ppm": 125_000,
            "floating_rate_ppm": 155_000,
            "bid_atoms": 97,
            "ask_atoms": 103,
            "settlement_liquidity_atoms": 1_800,
            "settlement_value_atoms": 30,
            "available_at": 200,
            "revision": 2,
        },
        {
            "month": 3,
            "fixed_rate_ppm": 130_000,
            "floating_rate_ppm": 135_000,
            "bid_atoms": 99,
            "ask_atoms": 101,
            "settlement_liquidity_atoms": 1_600,
            "settlement_value_atoms": 10,
            "available_at": 300,
            "revision": 3,
        },
        {
            "month": 4,
            "fixed_rate_ppm": 128_000,
            "floating_rate_ppm": 168_000,
            "bid_atoms": 96,
            "ask_atoms": 104,
            "settlement_liquidity_atoms": 1_200,
            "settlement_value_atoms": 40,
            "available_at": 400,
            "revision": 4,
        },
        {
            "month": 5,
            "fixed_rate_ppm": 132_000,
            "floating_rate_ppm": 157_000,
            "bid_atoms": 98,
            "ask_atoms": 103,
            "settlement_liquidity_atoms": 1_000,
            "settlement_value_atoms": 25,
            "available_at": 500,
            "revision": 5,
        },
    )


def ingest_boros_fixture_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    max_rows: int,
) -> tuple[Mapping[str, Any], ...]:
    limit = require_int(max_rows, "max_rows", minimum=1)
    if len(rows) > limit:
        raise EvidenceNativeError("BOROS_INGEST_BOUND_EXCEEDED")
    seen_months: set[int] = set()
    records: list[Mapping[str, Any]] = []
    for row in rows:
        month = require_int(row.get("month"), "month", minimum=1)
        if month in seen_months:
            raise EvidenceNativeError("BOROS_DUPLICATE_MONTH")
        seen_months.add(month)
        normalized = {
            "month": month,
            "fixed_rate_ppm": require_int(
                row.get("fixed_rate_ppm"), "fixed_rate_ppm", minimum=0
            ),
            "floating_rate_ppm": require_int(
                row.get("floating_rate_ppm"), "floating_rate_ppm", minimum=0
            ),
            "bid_atoms": require_int(row.get("bid_atoms"), "bid_atoms", minimum=0),
            "ask_atoms": require_int(row.get("ask_atoms"), "ask_atoms", minimum=0),
            "settlement_liquidity_atoms": require_int(
                row.get("settlement_liquidity_atoms"),
                "settlement_liquidity_atoms",
                minimum=0,
            ),
            "settlement_value_atoms": require_int(
                row.get("settlement_value_atoms"), "settlement_value_atoms"
            ),
            "available_at": require_int(
                row.get("available_at"), "available_at", minimum=0
            ),
            "revision": require_int(row.get("revision"), "revision", minimum=0),
        }
        normalized["raw_hash"] = stable_hash("pr355:boros-raw", normalized)
        records.append(normalized)
    return tuple(records)


def materialize_boros_fixture_state(
    records: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    states: list[Mapping[str, Any]] = []
    previous_available = -1
    previous_revision = -1
    for record_row in records:
        available_at = require_int(
            record_row.get("available_at"), "available_at", minimum=0
        )
        revision = require_int(record_row.get("revision"), "revision", minimum=0)
        if available_at <= previous_available:
            raise EvidenceNativeError("BOROS_AVAILABLE_AT_NOT_MONOTONIC")
        if revision <= previous_revision:
            raise EvidenceNativeError("BOROS_REVISION_NOT_MONOTONIC")
        bid = require_int(record_row.get("bid_atoms"), "bid_atoms", minimum=0)
        ask = require_int(record_row.get("ask_atoms"), "ask_atoms", minimum=0)
        if ask < bid:
            raise EvidenceNativeError("BOROS_ORDERBOOK_INVERTED")
        states.append(
            {
                "state_id": stable_hash(
                    "pr355:boros-state",
                    {
                        "raw_hash": str(record_row["raw_hash"]),
                        "available_at": available_at,
                        "revision": revision,
                    },
                ),
                "month": int(record_row["month"]),
                "fixed_rate_ppm": int(record_row["fixed_rate_ppm"]),
                "floating_rate_ppm": int(record_row["floating_rate_ppm"]),
                "bid_atoms": bid,
                "ask_atoms": ask,
                "spread_atoms": ask - bid,
                "settlement_liquidity_atoms": int(
                    record_row["settlement_liquidity_atoms"]
                ),
                "settlement_value_atoms": int(record_row["settlement_value_atoms"]),
                "available_at": available_at,
                "revision": revision,
                "raw_hash": str(record_row["raw_hash"]),
            }
        )
        previous_available = available_at
        previous_revision = revision
    return tuple(states)


def _boros_episode_rows(
    states: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, int | str], ...]:
    rows: list[Mapping[str, int | str]] = []
    for current, following in zip(states, states[1:]):
        rows.append(
            {
                "episode_id": f"boros-{current['month']}-to-{following['month']}",
                "feature_available_at": int(current["available_at"]),
                "label_available_at": int(following["available_at"]),
                "feature_atoms": (
                    int(current["floating_rate_ppm"])
                    - int(current["fixed_rate_ppm"])
                ),
                "label_atoms": int(following["settlement_value_atoms"]),
            }
        )
    return tuple(rows)


def run_boros_fixture_vertical(
    rows: Sequence[Mapping[str, Any]] | None = None,
    *,
    source_pin_attested: bool = False,
):
    observations = tuple(rows or build_boros_fixture_rows())
    if len(observations) < 5:
        raise EvidenceNativeError("BOROS_FIXTURE_REQUIRES_FIVE_PERIODS")

    raw_records = ingest_boros_fixture_rows(observations, max_rows=12)
    states = materialize_boros_fixture_state(raw_records)
    first = states[0]
    mature = states[-1]

    cashflow = define_cashflow_stream(
        {
            "cashflow_id": "boros-fixture-fixed-float",
            "instrument_id": "BOROS_FIXTURE_IRS",
            "payer_role": "FIXED_PAYER",
            "receiver_role": "FLOATING_PAYER",
            "payment_asset": "USD_ATOMS",
            "payment_unit": "atoms",
            "fixed_or_floating": "FLOATING",
            "index_id": "BOROS_FIXTURE_FUNDING_INDEX",
            "observation_schedule": tuple(range(1, len(states) + 1)),
            "settlement_schedule": (len(states),),
            "maturity": len(states),
            "margin_atoms": 5,
            "collateral_asset": "USD_ATOMS",
            "eligibility": ("RESEARCH_FIXTURE",),
            "transferable": False,
            "event_time": 1,
            "published_at": 1,
            "received_at": 1,
            "available_at": int(first["available_at"]),
            "revision": 1,
            "provenance": "LOCAL_DETERMINISTIC_FIXTURE",
        }
    )

    forecast_written_at = int(first["available_at"])
    mature_available_at = int(mature["available_at"])
    if mature_available_at <= forecast_written_at:
        raise EvidenceNativeError("BOROS_OUTCOME_NOT_MATURE_AFTER_FORECAST")

    forecast = compile_fixed_floating_payoff(
        {
            "notional_atoms": 1_000,
            "fixed_rate_ppm": int(first["fixed_rate_ppm"]),
            "floating_rate_ppm": int(first["floating_rate_ppm"]),
            "day_count_num": 1,
            "day_count_den": 1,
        }
    )
    prediction = int(forecast["payoff_atoms"])
    outcome = int(mature["settlement_value_atoms"])

    episodes = form_independent_episodes(
        _boros_episode_rows(states),
        minimum_gap=100,
    )
    split = purged_walk_forward_split(
        episodes,
        train_end=300,
        embargo=50,
    )
    train_labels = tuple(item.label_atoms for item in split["train"])
    holdout_labels = tuple(item.label_atoms for item in split["holdout"])
    model_comparison = compare_four_model_variants(
        train_labels=train_labels,
        pooled_labels=(15, 35, 20),
        holdout_labels=holdout_labels,
        mechanism_prediction_atoms=prediction,
    )
    fdr = benjamini_hochberg_ppm(
        (10_000, 80_000, 300_000),
        fdr_ppm=50_000,
    )
    calibration = evaluate_probability_calibration(
        (
            {
                "probability_ppm": 700_000,
                "outcome": 1,
                "interval_low_ppm": 500_000,
                "interval_high_ppm": 1_000_000,
            },
            {
                "probability_ppm": 300_000,
                "outcome": 0,
                "interval_low_ppm": 0,
                "interval_high_ppm": 500_000,
            },
        )
    )

    fees_atoms = 3
    margin_cost_atoms = 5
    liquidity_shortfall_atoms = max(
        0,
        1_000 - int(first["settlement_liquidity_atoms"]),
    )
    net_after_stress_atoms = (
        prediction - fees_atoms - margin_cost_atoms - liquidity_shortfall_atoms
    )
    source_value = source_value_report(
        qualified_candidates=0,
        engineering_cost_units=10,
        data_cost_units=0,
        license_cost_units=0,
        source_failures=1,
    )

    output_payload = {
        "prediction_atoms": prediction,
        "outcome_atoms": outcome,
        "cashflow_id": cashflow.cashflow_id,
        "model_comparison_hash": str(model_comparison["evidence_hash"]),
        "fdr_hash": str(fdr["evidence_hash"]),
        "calibration_hash": str(calibration["evidence_hash"]),
        "net_after_stress_atoms": net_after_stress_atoms,
    }
    output_hash = stable_hash("pr355:boros-output", output_payload)
    receipt = ResearchReceipt(
        source_snapshot_ids=tuple(
            f"BOROS_FIXTURE_M{state['month']}" for state in states
        ),
        raw_hashes=tuple(str(record_row["raw_hash"]) for record_row in raw_records),
        code_commit="2a5f6b8d699981ff967208db7b9b0a12fbf27031",
        tree_hash=stable_hash("pr355:boros-tree", {"fixture": 2}),
        config_hash=stable_hash(
            "pr355:boros-config",
            {"mode": "read_only_replay", "max_rows": 12},
        ),
        model_hash=stable_hash(
            "pr355:boros-model",
            {
                "comparators": (
                    "simple",
                    "local_only",
                    "pooled_markets",
                    "mechanism_transfer",
                )
            },
        ),
        environment_lock_hash=stable_hash("pr355:boros-env", {"python": "3.13"}),
        deterministic_seed=355,
        command="run_boros_fixture_vertical",
        output_hashes=(output_hash,),
        verdict="BLOCKED_EXTERNAL",
        redaction_policy="NO_SECRETS_NO_ROUTE_DISCLOSURE",
    )

    return record(
        "run_boros_fixture_vertical",
        {
            "marketpack_id": "MP-N01",
            "hypothesis_id": "NXE-01",
            "bounded_ingest": True,
            "raw_record_count": len(raw_records),
            "raw_hashes": tuple(str(row["raw_hash"]) for row in raw_records),
            "pit_state_ids": tuple(str(state["state_id"]) for state in states),
            "forecast_written_at": forecast_written_at,
            "mature_label_available_at": mature_available_at,
            "prediction_atoms": prediction,
            "mature_outcome_atoms": outcome,
            "absolute_error_atoms": abs(prediction - outcome),
            "model_comparison": dict(model_comparison),
            "purged_walk_forward": {
                "train_count": len(split["train"]),
                "holdout_count": len(split["holdout"]),
                "embargo": int(split["embargo"]),
            },
            "fdr": dict(fdr),
            "calibration": dict(calibration),
            "fees_atoms": fees_atoms,
            "margin_cost_atoms": margin_cost_atoms,
            "liquidity_shortfall_atoms": liquidity_shortfall_atoms,
            "net_after_stress_atoms": net_after_stress_atoms,
            "source_value": dict(source_value),
            "receipt_hash": receipt.receipt_hash,
            "fixture_tested": True,
            "source_pin_attested": source_pin_attested,
            "verdict": "BLOCKED_EXTERNAL",
            "blockers": (
                "BOROS_PRIMARY_HISTORICAL_SOURCE_PIN_ENTITLEMENT_NOT_MATERIALIZED",
            ),
            "blind_spots": (
                "NO_PRIMARY_HISTORICAL_DATASET",
                "NO_REAL_MARGIN_ENGINE",
                "NO_REAL_ORDERBOOK_REPLAY",
            ),
            "synthetic_pass": False,
        },
    )


__all__ = [
    "build_boros_fixture_rows",
    "ingest_boros_fixture_rows",
    "materialize_boros_fixture_state",
    "run_boros_fixture_vertical",
]

"""PR-355 MP-N01 Boros cashflow vertical using deterministic fixtures only."""

from __future__ import annotations

from typing import Mapping, Sequence, Any

from .claims import compile_fixed_floating_payoff, define_cashflow_stream
from .core import stable_hash
from .evidence_native_core import ResearchReceipt, record, require_int


def build_boros_fixture_rows() -> tuple[Mapping[str, int | str], ...]:
    return (
        {
            "month": 1,
            "fixed_rate_ppm": 120_000,
            "floating_rate_ppm": 140_000,
            "settlement_value_atoms": 20,
            "available_at": 100,
        },
        {
            "month": 2,
            "fixed_rate_ppm": 125_000,
            "floating_rate_ppm": 155_000,
            "settlement_value_atoms": 30,
            "available_at": 200,
        },
    )


def run_boros_fixture_vertical(
    rows: Sequence[Mapping[str, Any]] | None = None,
    *,
    source_pin_attested: bool = False,
):
    observations = tuple(rows or build_boros_fixture_rows())
    if len(observations) < 2:
        raise ValueError("BOROS_FIXTURE_REQUIRES_TWO_PERIODS")
    first, mature = observations[0], observations[-1]
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
            "observation_schedule": (1, 2),
            "settlement_schedule": (2,),
            "maturity": 2,
            "margin_atoms": 5,
            "collateral_asset": "USD_ATOMS",
            "eligibility": ("RESEARCH_FIXTURE",),
            "transferable": False,
            "event_time": 1,
            "published_at": 1,
            "received_at": 1,
            "available_at": require_int(first.get("available_at"), "available_at", minimum=0),
            "revision": 1,
            "provenance": "LOCAL_DETERMINISTIC_FIXTURE",
        }
    )
    forecast_written_at = require_int(first.get("available_at"), "forecast_written_at", minimum=0)
    mature_available_at = require_int(mature.get("available_at"), "mature_available_at", minimum=0)
    if mature_available_at <= forecast_written_at:
        raise ValueError("BOROS_OUTCOME_NOT_MATURE_AFTER_FORECAST")
    forecast = compile_fixed_floating_payoff(
        {
            "notional_atoms": 1_000,
            "fixed_rate_ppm": require_int(first.get("fixed_rate_ppm"), "fixed_rate_ppm", minimum=0),
            "floating_rate_ppm": require_int(first.get("floating_rate_ppm"), "floating_rate_ppm", minimum=0),
            "day_count_num": 1,
            "day_count_den": 1,
        }
    )
    outcome = require_int(mature.get("settlement_value_atoms"), "settlement_value_atoms")
    prediction = int(forecast["payoff_atoms"])
    raw_hashes = tuple(stable_hash("pr355:boros-raw", dict(row)) for row in observations)
    output_hash = stable_hash(
        "pr355:boros-output",
        {"prediction_atoms": prediction, "outcome_atoms": outcome, "cashflow_id": cashflow.cashflow_id},
    )
    receipt = ResearchReceipt(
        source_snapshot_ids=("BOROS_FIXTURE_M1", "BOROS_FIXTURE_M2"),
        raw_hashes=raw_hashes,
        code_commit="d8d6d9079689efdddf77ce373120675255a99327",
        tree_hash=stable_hash("pr355:boros-tree", {"fixture": 1}),
        config_hash=stable_hash("pr355:boros-config", {"mode": "read_only_replay"}),
        model_hash=stable_hash("pr355:boros-model", {"baseline": "fixed-floating-delta"}),
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
            "forecast_written_at": forecast_written_at,
            "mature_label_available_at": mature_available_at,
            "prediction_atoms": prediction,
            "mature_outcome_atoms": outcome,
            "absolute_error_atoms": abs(prediction - outcome),
            "receipt_hash": receipt.receipt_hash,
            "fixture_tested": True,
            "source_pin_attested": source_pin_attested,
            "verdict": "BLOCKED_EXTERNAL",
            "blockers": ("BOROS_PRIMARY_HISTORICAL_SOURCE_PIN_ENTITLEMENT_NOT_MATERIALIZED",),
            "synthetic_pass": False,
        },
    )

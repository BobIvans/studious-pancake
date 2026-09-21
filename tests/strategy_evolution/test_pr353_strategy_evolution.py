from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from scripts.verify_pr353_strategy_evolution import verify
from src.strategy_evolution.core import (
    CorrelationHypothesis,
    CoverageCell,
    EvolutionError,
    EvolutionState,
    build_candidate,
    evidence_ref,
    shadow_opportunity_adapter,
)
from src.strategy_evolution.governance_transition import (
    bound_governance_execution_uncertainty,
    price_transition_window,
)
from src.strategy_evolution.manifest import (
    FUNCTION_COUNT,
    NF_IDS,
    NF_TO_SYMBOL,
    PACKAGES,
)
from src.strategy_evolution.primary_market import track_async_vault_request
from src.strategy_evolution.residual_discovery import (
    align_cross_domain_event_time,
    build_bot_operation_feature_frame,
    build_market_event_feature_frame,
    estimate_anomaly_lead_lag_graph,
    update_anomaly_coverage_registry,
)
from src.strategy_evolution.rights_lifecycle import (
    estimate_transferability_haircut,
)

ROOT = Path(__file__).resolve().parents[2]


def _candidate_payload() -> dict[str, object]:
    ref = evidence_ref(
        "fixture",
        {"x": 1},
        observed_at=11,
        finality="FINALIZED",
    )
    return {
        "chain_domain": "solana:mainnet",
        "detected_at": 12,
        "event_time": 10,
        "finality": "FINALIZED",
        "expires_at": 20,
        "input_atoms": 100,
        "output_atoms": 120,
        "cost_low_atoms": 1,
        "cost_high_atoms": 2,
        "value_low_atoms": 10,
        "value_high_atoms": 12,
        "capacity_low_atoms": 1,
        "capacity_high_atoms": 100,
        "unit": "lamports",
        "scenario_ids": ("base",),
        "evidence_refs": (ref,),
        "config_digest": "1" * 64,
        "code_sha": "2" * 40,
    }


def test_exact_nf_surface_and_symbols_import() -> None:
    assert tuple(PACKAGES) == tuple(f"EVO-{index:02d}" for index in range(1, 10))
    assert FUNCTION_COUNT == 72
    assert NF_IDS == tuple(range(1017, 1089))
    assert len(set(row[2] for row in NF_TO_SYMBOL.values())) == 72
    for _nf, (_package, module_name, symbol) in NF_TO_SYMBOL.items():
        module = importlib.import_module(f"src.strategy_evolution.{module_name}")
        assert callable(getattr(module, symbol))


def test_all_packages_checked_in_disabled_and_no_live_effects() -> None:
    payload = json.loads(
        (ROOT / "config/strategy_evolution.json").read_text(encoding="utf-8")
    )
    assert all(row["state"] == "DISABLED" for row in payload["packages"].values())
    assert all(row["live"] is False for row in payload["packages"].values())
    assert not any(payload["effect_boundary"].values())


def test_candidate_id_is_deterministic_and_not_queueable_before_qualification() -> None:
    left = build_candidate("EVO-01", "GOVERNANCE_TRANSITION", _candidate_payload())
    reversed_payload = dict(reversed(list(_candidate_payload().items())))
    right = build_candidate("EVO-01", "GOVERNANCE_TRANSITION", reversed_payload)
    assert left.candidate_id == right.candidate_id
    assert left.state is EvolutionState.SHADOW_CANDIDATE
    with pytest.raises(EvolutionError, match="CANDIDATE_NOT_VERIFIED_SHADOW"):
        shadow_opportunity_adapter(
            left,
            detection_slot=1,
            input_mint="a",
            output_mint="b",
        )


def test_extra_cost_cannot_improve_worst_case_net() -> None:
    base = price_transition_window(
        {
            "value_low_atoms": 20,
            "value_high_atoms": 30,
            "cost_low_atoms": 1,
            "cost_high_atoms": 2,
            "capacity_atoms": 100,
        }
    )
    costly = price_transition_window(
        {
            "value_low_atoms": 20,
            "value_high_atoms": 30,
            "cost_low_atoms": 1,
            "cost_high_atoms": 9,
            "capacity_atoms": 100,
        }
    )
    assert costly.payload["worst_case_net_atoms"] < base.payload["worst_case_net_atoms"]


def test_illegal_async_lifecycle_transition_fails_closed() -> None:
    with pytest.raises(EvolutionError, match="ILLEGAL_TRANSITION"):
        track_async_vault_request(
            {
                "current_state": "REQUESTED",
                "target_state": "CLAIMED",
                "controller": "c",
                "expected_controller": "c",
            }
        )


def test_unbounded_governance_clock_fails_closed() -> None:
    with pytest.raises(EvolutionError, match="WINDOW_UNBOUNDED"):
        bound_governance_execution_uncertainty(
            {
                "clock_mode": "BLOCK",
                "executor_known": True,
                "earliest_execution": 10,
                "latest_execution": 9,
            }
        )


def test_nontransferable_right_has_full_secondary_haircut() -> None:
    report = estimate_transferability_haircut(
        {"transferable": False, "restrictions_ambiguous": False}
    )
    assert report.payload["haircut_ppm"] == 1_000_000


def test_evo09_point_in_time_alignment_drops_future_and_keeps_rejects() -> None:
    market = build_market_event_feature_frame(
        (
            {
                "event_id": "e1",
                "domain": "price",
                "event_time": 1,
                "observed_at": 2,
                "finality": "FINALIZED",
                "value_atoms": 10,
                "source_id": "s",
                "source_licensed": True,
            },
            {
                "event_id": "future",
                "domain": "price",
                "event_time": 2,
                "observed_at": 20,
                "finality": "FINALIZED",
                "value_atoms": 11,
                "source_id": "s",
                "source_licensed": True,
            },
        )
    )
    bot = build_bot_operation_feature_frame(
        (
            {
                "operation_id": "o1",
                "decision_at": 5,
                "disposition": "REJECTED",
                "predicted_net_atoms": 1,
            },
        )
    )
    aligned = align_cross_domain_event_time(
        market.payload,
        bot.payload,
        decision_at=5,
    )
    assert [row["event_id"] for row in aligned.payload["market_rows"]] == ["e1"]
    assert aligned.payload["dropped_future_rows"] == 1
    assert bot.payload["negative_or_rejected_rows"] == 1


def test_evo09_reuses_canonical_lead_lag_engine() -> None:
    report = estimate_anomaly_lead_lag_graph(
        experiment_id="lag",
        trigger=(0, 1, 0, 1, 0, 1),
        target=(0, 0, 1, 0, 1, 0),
        max_lag=1,
        latency_corrected=True,
    )
    assert report.payload["canonical_engine"] == "src.decision.agg10.lead_lag_research"
    assert (
        report.payload["challenger_metric_ppm"] > report.payload["baseline_metric_ppm"]
    )


def test_evo09_coverage_preserves_blind_spots_without_promotion() -> None:
    cells = (
        CoverageCell(
            "price",
            "lead-lag",
            "seconds",
            "hypothesis",
            "informational",
            "finalized",
            "OBSERVED",
        ),
        CoverageCell(
            "queue",
            "regime shift",
            "minutes",
            "unknown",
            "inventory-bound",
            "missing",
            "BLIND_SPOT",
        ),
    )
    hypothesis = CorrelationHypothesis(
        "h1",
        ("s1", "s2"),
        1,
        2,
        True,
        ("e1",),
    )
    report = update_anomaly_coverage_registry(
        cells=cells,
        hypothesis=hypothesis,
        existing_hypothesis_ids=(),
        evidence_complete=True,
    )
    assert report.payload["unknown_or_blind_spots"] == 1
    assert report.payload["auto_promotion"] is False


def test_secret_material_is_rejected_from_bot_telemetry() -> None:
    with pytest.raises(EvolutionError, match="SECRET_DETECTED"):
        build_bot_operation_feature_frame(
            ({"operation_id": "o", "decision_at": 1, "secret_key": "x"},)
        )


def test_structural_verifier_accepts_repository_tree() -> None:
    payload = verify()
    assert payload["accepted"] is True, payload["errors"]
    assert payload["live_enabled"] is False

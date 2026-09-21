from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from scripts.verify_pr355 import verify
from src.mechanism_discovery.boros import run_boros_fixture_vertical
from src.mechanism_discovery.causal_twin import reject_unsupported_causal_claim
from src.mechanism_discovery.claims import (
    define_cashflow_stream,
    qualify_cashflow_identity,
)
from src.mechanism_discovery.evidence_native_core import (
    EvidenceNativeError,
    ResearchReceipt,
)
from src.mechanism_discovery.incident_admission import (
    quarantine_vulnerable_deployment,
)
from src.mechanism_discovery.mechanism_transfer import (
    measure_negative_transfer,
    promote_or_reject_transfer,
)
from src.mechanism_discovery.pr355_manifest import (
    FUNCTION_COUNT,
    NXF_IDS,
    NXF_TO_SYMBOL,
)
from src.mechanism_discovery.research_receipt import (
    generate_optional_computation_proof,
    replay_receipt_computation,
    verify_computation_proof,
)
from src.mechanism_discovery.research_resources import (
    authorize_bounded_resource_purchase,
)
from src.mechanism_discovery.shared_credit import (
    simulate_cross_spoke_utilization,
)
from src.strategy_evolution.core import EvolutionError
from src.strategy_evolution.residual_discovery import (
    build_bot_operation_feature_frame,
    discover_residual_anomaly_clusters,
    score_anomaly_arbitrageability,
)

ROOT = Path(__file__).resolve().parents[2]


def test_exact_nxf_surface_without_new_nf_allocation() -> None:
    assert FUNCTION_COUNT == 72
    assert NXF_IDS == tuple(f"NXF-{index:03d}" for index in range(1, 73))
    for _nxf, (_group, module_name, symbol) in NXF_TO_SYMBOL.items():
        module = importlib.import_module(f"src.mechanism_discovery.{module_name}")
        assert callable(getattr(module, symbol))
    owner_map = json.loads(
        (ROOT / "config/pr355_owner_map.json").read_text(encoding="utf-8")
    )
    assert owner_map["counts"] == {
        "ig": 57,
        "nxf": 72,
        "marketpacks": 9,
        "total": 138,
    }
    assert owner_map["permanent_nf_allocated"] is False
    assert owner_map["duplicate_authorities"] == []


def test_all_marketpacks_disabled_and_effect_boundary_false() -> None:
    payload = json.loads(
        (ROOT / "config/pr355_marketpacks.json").read_text(encoding="utf-8")
    )
    assert len(payload["packages"]) == 9
    assert all(row["state"] == "DISABLED" for row in payload["packages"].values())
    assert all(row["live"] is False for row in payload["packages"].values())
    assert not any(payload["effect_boundary"].values())
    assert payload["marginfi"] == "PAUSED"
    assert payload["slumlord_low_capital_requirement"] == "REQUIRED"


def test_cashflow_clock_and_identity_fail_closed() -> None:
    with pytest.raises(EvidenceNativeError, match="AVAILABILITY_CLOCK_ORDER_INVALID"):
        define_cashflow_stream(
            {
                "cashflow_id": "c",
                "instrument_id": "i",
                "payer_role": "p",
                "receiver_role": "r",
                "payment_asset": "usd",
                "payment_unit": "atoms",
                "fixed_or_floating": "FIXED",
                "index_id": "idx",
                "observation_schedule": (1,),
                "settlement_schedule": (2,),
                "maturity": 2,
                "margin_atoms": 0,
                "collateral_asset": "usd",
                "eligibility": ("research",),
                "transferable": False,
                "event_time": 1,
                "published_at": 3,
                "received_at": 2,
                "available_at": 4,
                "revision": 1,
                "provenance": "fixture",
            }
        )
    report = qualify_cashflow_identity(
        {
            "left_maturity": 1,
            "right_maturity": 2,
            "left_settlement_asset": "usd",
            "right_settlement_asset": "usd",
            "left_index_id": "a",
            "right_index_id": "a",
            "left_collateral_asset": "usd",
            "right_collateral_asset": "usd",
            "left_eligibility_id": "x",
            "right_eligibility_id": "x",
        }
    )
    assert report["compatible"] is False
    assert "maturity" in report["mismatches"]


def test_boros_vertical_is_temporal_reproducible_and_blocked_external() -> None:
    left = run_boros_fixture_vertical()
    right = run_boros_fixture_vertical()
    assert left["forecast_written_at"] < left["mature_label_available_at"]
    assert left["receipt_hash"] == right["receipt_hash"]
    assert left["fixture_tested"] is True
    assert left["synthetic_pass"] is False
    assert left["verdict"] == "BLOCKED_EXTERNAL"


def test_shared_credit_sequential_capacity_prevents_double_counting() -> None:
    ok = simulate_cross_spoke_utilization(
        100,
        (
            {"kind": "DRAW", "amount_atoms": 60},
            {"kind": "ADD", "amount_atoms": 10},
            {"kind": "DRAW", "amount_atoms": 50},
        ),
    )
    assert ok["final_hub_atoms"] == 0
    with pytest.raises(EvidenceNativeError, match="SEQUENTIAL_SHARED_CAPACITY_EXHAUSTED"):
        simulate_cross_spoke_utilization(
            100,
            (
                {"kind": "DRAW", "amount_atoms": 70},
                {"kind": "DRAW", "amount_atoms": 40},
            ),
        )


def test_negative_transfer_is_preserved_and_rejected() -> None:
    measurement = measure_negative_transfer(
        {
            "local_holdout_mae_atoms": 10,
            "transfer_holdout_mae_atoms": 12,
            "old_regime_mae_before_atoms": 8,
            "old_regime_mae_after_atoms": 9,
        }
    )
    assert measurement["negative_transfer"] is True
    decision = promote_or_reject_transfer(
        {
            "local_holdout_mae_atoms": 10,
            "transfer_holdout_mae_atoms": 12,
            "old_regime_degradation_atoms": 1,
            "max_old_regime_degradation_atoms": 0,
        }
    )
    assert decision["accepted"] is False
    assert decision["live_promotion"] is False


def _receipt() -> ResearchReceipt:
    return ResearchReceipt(
        source_snapshot_ids=("s1",),
        raw_hashes=("1" * 64,),
        code_commit="2" * 40,
        tree_hash="3" * 64,
        config_hash="4" * 64,
        model_hash="5" * 64,
        environment_lock_hash="6" * 64,
        deterministic_seed=355,
        command="fixture",
        output_hashes=("7" * 64,),
        verdict="BLOCKED_EXTERNAL",
        redaction_policy="redacted",
    )


def test_receipt_replay_and_mock_proof_never_grant_live() -> None:
    receipt = _receipt()
    replay = replay_receipt_computation(
        receipt,
        observed_output_hashes=receipt.output_hashes,
    )
    assert replay["replay_match"] is True
    with pytest.raises(EvidenceNativeError, match="HIDDEN_LATEST_STATE_READ"):
        replay_receipt_computation(
            receipt,
            observed_output_hashes=receipt.output_hashes,
            latest_state_read=True,
        )
    proof = generate_optional_computation_proof(
        {
            "backend": "MOCK_SP1",
            "receipt_hash": receipt.receipt_hash,
            "version": "fixture-v1",
        }
    )
    verified = verify_computation_proof(
        {
            "backend": "MOCK_SP1",
            "receipt_hash": receipt.receipt_hash,
            "proof_hash": proof["proof_hash"],
            "version": "fixture-v1",
        }
    )
    assert verified["verified"] is True
    assert verified["live_authority"] is False
    assert verified["profitability_claim"] is False


def test_real_resource_payment_is_forbidden() -> None:
    with pytest.raises(EvidenceNativeError, match="PRODUCTION_RESOURCE_PAYMENT_FORBIDDEN"):
        authorize_bounded_resource_purchase(
            {
                "payment_scheme": "X402_PRODUCTION",
                "quoted_atoms": 1,
                "cap_atoms": 1,
            }
        )


def test_incident_and_causal_layers_fail_closed() -> None:
    quarantine = quarantine_vulnerable_deployment(
        {
            "deployment_id": "bunni-reference",
            "known_vulnerable": True,
            "fix_attested": False,
        }
    )
    assert quarantine["quarantined"] is True
    assert quarantine["production_adapter_allowed"] is False
    causal = reject_unsupported_causal_claim(
        {"assumptions_supported": False, "sensitivity_bounded": False}
    )
    assert causal["conclusion"] == "ASSOCIATION_ONLY"
    assert causal["execution_right"] is False


def test_evo09_missing_outcome_and_financial_units_repaired() -> None:
    frame = build_bot_operation_feature_frame(
        (
            {
                "operation_id": "unsent",
                "decision_at": 10,
                "disposition": "NO_TRADE",
                "predicted_net_atoms": 5,
            },
        )
    )
    row = frame.payload["rows"][0]
    assert row["realized_net_atoms"] is None
    assert row["actual_landed"] is None
    assert row["outcome_missing"] is True

    score = score_anomaly_arbitrageability(
        {
            "net_edge_atoms": 100,
            "capacity_atoms": 1_000,
            "lead_time_ms": 500,
            "reproducibility_ppm": 900_000,
            "data_cost_atoms": 10,
            "tail_risk_atoms": 5,
        }
    )
    assert score.payload["financial_score_atoms"] == 85
    assert score.payload["score_atoms"] == 85
    assert score.payload["mixed_units_combined"] is False


def test_evo09_cluster_requires_real_stability_evidence() -> None:
    aligned = {
        "market_rows": (
            {"event_id": "1", "domain": "x", "missing": False},
            {"event_id": "2", "domain": "x", "missing": False},
        )
    }
    with pytest.raises(EvolutionError, match="STABILITY_EVIDENCE_REQUIRED"):
        discover_residual_anomaly_clusters(
            aligned,
            explained_event_ids=(),
            multiple_testing_passed=True,
        )
    report = discover_residual_anomaly_clusters(
        aligned,
        explained_event_ids=(),
        multiple_testing_passed=True,
        stability_evidence_ref="stability:1",
        fdr_evidence_ref="fdr:1",
        persistence_evidence_ref="persistence:1",
    )
    assert report.payload["clusters"]["x"] == ["1", "2"]


def test_structural_verifier_accepts_pr355_tree() -> None:
    payload = verify()
    assert payload["accepted"] is True, payload["errors"]
    assert payload["nxf_count"] == 72
    assert payload["ig_count"] == 57
    assert payload["marketpack_count"] == 9
    assert payload["experiment_count"] == 26
    assert payload["boros_verdict"] == "BLOCKED_EXTERNAL"
    assert payload["live_enabled"] is False

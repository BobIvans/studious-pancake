from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from scripts.verify_pr355 import verify
from src.mechanism_discovery.boros import run_boros_fixture_vertical
from src.mechanism_discovery.evidence_native_core import (
    EvidenceNativeError,
    ResearchReceipt,
)
from src.mechanism_discovery.incident_admission import (
    derive_incident_invariant_tests,
    detect_semantic_security_drift,
)
from src.mechanism_discovery.liquidity_shape import compare_hybrid_execution_paths
from src.mechanism_discovery.marketpack_adapters import (
    all_marketpack_bindings,
)
from src.mechanism_discovery.research_quality import (
    benjamini_hochberg_ppm,
    compare_four_model_variants,
    evaluate_detection_coverage,
    evaluate_null_control,
    evaluate_probability_calibration,
    form_independent_episodes,
    purged_walk_forward_split,
    run_equal_budget_ablation,
)
from src.mechanism_discovery.research_receipt import (
    redact_receipt_for_sharing,
    verify_receipt_components,
)
from src.mechanism_discovery.research_resources import reconcile_resource_payment
from src.mechanism_discovery.rwa import qualify_rwa_access_path
from src.strategy_evolution.core import EvolutionError
from src.strategy_evolution.residual_discovery import (
    build_bot_operation_feature_frame,
    score_anomaly_arbitrageability,
    select_training_labels_as_of,
)

ROOT = Path(__file__).resolve().parents[2]


def _module_from_path(path: str):
    return importlib.import_module(path[:-3].replace("/", "."))


def test_every_owner_map_row_has_importable_exact_owner_and_evidence() -> None:
    payload = json.loads(
        (ROOT / "config/pr355_owner_map.json").read_text(encoding="utf-8")
    )
    rows = (
        payload["ig_obligations"]
        + payload["nxf_requirements"]
        + payload["marketpacks"]
    )
    assert len(rows) == 138
    for row in rows:
        assert row["owner_path"].startswith("src/")
        symbol = row.get("owner_symbol") or row.get("symbol")
        assert symbol
        module = _module_from_path(row["owner_path"])
        assert callable(getattr(module, symbol))
        assert row["tests"]
        assert row["evidence_refs"]


def test_predecessor_scope_map_and_planning_aliases_are_explicit() -> None:
    payload = json.loads(
        (ROOT / "config/pr355_owner_map.json").read_text(encoding="utf-8")
    )
    refs = payload["predecessor_scope_refs"]
    assert refs["NF-001..NF-1016"]["exact_range"] == [1, 1016]
    assert refs["EVO-01..EVO-09 / NF-1017..NF-1088"]["exact_range"] == [
        1017,
        1088,
    ]
    assert refs["RND-00..RND-11 / NF-1089..NF-1184"]["exact_range"] == [
        1089,
        1184,
    ]
    assert (
        refs["NF-001..NF-1016"]["canonical_owner_source"]
        == "src/release_gate/ultimate_mega1_closure.py::NF_TO_CLOSURE"
    )
    for alias in ("L0-L8", "B00-B08"):
        row = payload["planning_alias_refs"][alias]
        assert row["literal_aliases_present_in_current_repo"] is False
        assert row["no_new_owner_created"] is True
        assert row["disposition"] == "SATISFIED_BY_EXISTING"


def test_unified_research_protocol_covers_entire_statistical_contract() -> None:
    protocol = json.loads(
        (ROOT / "config/pr355_research_protocol.json").read_text(
            encoding="utf-8"
        )
    )
    assert protocol["sampling"] == {
        "universe_required": True,
        "inclusion_probability_required": True,
        "control_windows_required": True,
        "adaptive_selection_bias_audit_required": True,
    }
    assert protocol["comparators"] == [
        "SIMPLE_BASELINE",
        "TARGET_MARKET_LOCAL_ONLY",
        "POOLED_MARKETS",
        "MECHANISM_TRANSFER_WITH_LOCAL_ADAPTER",
    ]
    assert all(protocol["evaluation"].values())
    assert protocol["arbitrageability_prerequisites"] == [
        "EXACT_RIGHTS",
        "COMPLETE_COSTS",
        "EXACT_ROUTE",
        "EXECUTABLE_CAPACITY",
        "TIMING",
    ]
    assert protocol["live_promotion"] is False
    assert protocol["universal_anomaly_claim"] is False
    assert protocol["measured_coverage_required"] is True
    assert protocol["unknown_zones_required"] is True


def test_all_nine_marketpack_bindings_are_concrete_default_off_and_blocked() -> None:
    bindings = all_marketpack_bindings()
    assert len(bindings) == 9
    assert {binding.pack_id for binding in bindings} == {
        f"MP-N{index:02d}" for index in range(1, 10)
    }
    for binding in bindings:
        assert binding.state == "DISABLED"
        assert binding.live_enabled is False
        assert binding.signer_access is False
        assert binding.submission_access is False
        assert binding.remote_mutation is False
        assert binding.blockers
        for owner in (
            binding.instrument_owner,
            binding.data_owner,
            binding.rights_owner,
            binding.target_owner,
            binding.evidence_owner,
        ):
            module_name, symbol = owner.split(":", 1)
            assert callable(getattr(importlib.import_module(module_name), symbol))


def test_nxe_registry_has_concrete_frozen_target_horizon_control_and_metric() -> None:
    payload = json.loads(
        (ROOT / "config/pr355_experiments.json").read_text(encoding="utf-8")
    )
    assert payload["preregistered"] is True
    assert payload["frozen_before_external_evaluation"] is True
    assert len(payload["rows"]) == 26
    for row in payload["rows"]:
        assert not row["target"].startswith("DECLARED_")
        assert not row["horizon"].startswith("DECLARED_")
        assert row["control"]
        assert row["primary_metric"]
        assert isinstance(row["costs"], dict)
        assert row["missing_and_censored"] == (
            "PRESERVE_SEPARATELY_AND_EXCLUDE_FUTURE_LABELS"
        )
        assert row["execution_right"] is False


def test_evo09_training_cutoff_preserves_missing_censored_and_future() -> None:
    telemetry = build_bot_operation_feature_frame(
        (
            {
                "operation_id": "matured",
                "decision_at": 1,
                "disposition": "PAPER_OBSERVED",
                "predicted_net_atoms": 1,
                "realized_net_atoms": 2,
                "label_available_at": 5,
            },
            {
                "operation_id": "future",
                "decision_at": 1,
                "disposition": "PAPER_OBSERVED",
                "predicted_net_atoms": 1,
                "realized_net_atoms": 3,
                "label_available_at": 20,
            },
            {
                "operation_id": "censored",
                "decision_at": 1,
                "disposition": "FAILED",
                "predicted_net_atoms": 1,
                "realized_net_atoms": 4,
                "label_available_at": 4,
                "censored": True,
            },
            {
                "operation_id": "missing",
                "decision_at": 1,
                "disposition": "NO_TRADE",
                "predicted_net_atoms": 1,
            },
        )
    )
    selected = select_training_labels_as_of(
        telemetry.payload["rows"],
        training_cutoff=10,
    )
    assert selected.payload["selected_count"] == 1
    assert selected.payload["future_labels_excluded"] == 1
    assert selected.payload["censored_preserved"] == 1
    assert selected.payload["missing_preserved"] == 1
    assert selected.payload["label_leakage"] is False


def test_boros_full_fixture_protocol_covers_all_four_comparators_and_blind_spots() -> None:
    result = run_boros_fixture_vertical()
    assert result["bounded_ingest"] is True
    assert result["raw_record_count"] == 5
    assert len(result["raw_hashes"]) == 5
    assert len(result["pit_state_ids"]) == 5
    assert result["forecast_written_at"] < result["mature_label_available_at"]
    comparison = result["model_comparison"]
    for key in (
        "simple_baseline_mae_atoms",
        "local_only_mae_atoms",
        "pooled_markets_mae_atoms",
        "mechanism_transfer_mae_atoms",
    ):
        assert key in comparison
    assert result["purged_walk_forward"]["train_count"] >= 1
    assert result["purged_walk_forward"]["holdout_count"] >= 1
    assert "fdr" in result
    assert "calibration" in result
    assert "equal_budget_ablation" in result
    assert "null_control" in result
    assert "detection_coverage" in result
    assert "source_value" in result
    assert result["blind_spots"]
    assert result["verdict"] == "BLOCKED_EXTERNAL"
    assert result["synthetic_pass"] is False


def test_research_quality_protocol_has_purge_fdr_calibration_and_negative_transfer() -> None:
    episodes = form_independent_episodes(
        (
            {
                "episode_id": "e1",
                "feature_available_at": 1,
                "label_available_at": 2,
                "feature_atoms": 10,
                "label_atoms": 20,
            },
            {
                "episode_id": "e2",
                "feature_available_at": 3,
                "label_available_at": 4,
                "feature_atoms": 11,
                "label_atoms": 30,
            },
            {
                "episode_id": "e3",
                "feature_available_at": 10,
                "label_available_at": 11,
                "feature_atoms": 12,
                "label_atoms": 25,
            },
        ),
        minimum_gap=1,
    )
    split = purged_walk_forward_split(episodes, train_end=4, embargo=2)
    assert len(split["train"]) == 2
    assert len(split["holdout"]) == 1

    comparison = compare_four_model_variants(
        train_labels=(20, 30),
        pooled_labels=(100, 100),
        holdout_labels=(25,),
        mechanism_prediction_atoms=40,
    )
    assert comparison["negative_transfer"] is True

    fdr = benjamini_hochberg_ppm((5_000, 20_000, 400_000), fdr_ppm=50_000)
    assert fdr["test_count"] == 3

    calibration = evaluate_probability_calibration(
        (
            {
                "probability_ppm": 800_000,
                "outcome": 1,
                "interval_low_ppm": 500_000,
                "interval_high_ppm": 1_000_000,
            },
        )
    )
    assert calibration["interval_coverage_ppm"] == 1_000_000



def test_equal_budget_null_and_detection_coverage_protocol() -> None:
    ablation = run_equal_budget_ablation(
        baseline_utility_units=10,
        challenger_utility_units=12,
        baseline_cost_units=5,
        challenger_cost_units=5,
        budget_units=5,
    )
    assert ablation["utility_delta_units"] == 2

    null = evaluate_null_control(
        observed_metric_atoms=10,
        null_metric_atoms=2,
        minimum_effect_atoms=5,
    )
    assert null["null_rejected"] is True

    coverage = evaluate_detection_coverage(
        false_discoveries=1,
        discoveries=10,
        false_negatives=2,
        positives=10,
        observable_cells=20,
        covered_cells=15,
    )
    assert coverage["fdr_ppm"] == 100_000
    assert coverage["fnr_ppm"] == 200_000
    assert coverage["observable_miss_ppm"] == 250_000


def test_arbitrageability_requires_rights_cost_route_capacity_and_timing() -> None:
    with pytest.raises(EvolutionError, match="ARBITRAGEABILITY_PROOF_INCOMPLETE"):
        score_anomaly_arbitrageability(
            {
                "net_edge_atoms": 10,
                "capacity_atoms": 100,
                "correlation_only": False,
            }
        )
    report = score_anomaly_arbitrageability(
        {
            "net_edge_atoms": 10,
            "capacity_atoms": 100,
            "correlation_only": False,
            "rights_verified": True,
            "costs_complete": True,
            "route_verified": True,
            "capacity_verified": True,
            "timing_verified": True,
        }
    )
    assert report.payload["score_atoms"] == 10
    assert report.payload["mixed_units_combined"] is False


def test_rwa_unknown_access_hybrid_mismatch_and_resource_error_fail_closed() -> None:
    access = qualify_rwa_access_path(
        {
            "jurisdiction_known": False,
            "allowlist_known": True,
            "session_known": True,
            "custody_known": True,
        }
    )
    assert access["qualified"] is False
    assert "jurisdiction_known" in access["unknown_fields"]

    with pytest.raises(EvidenceNativeError, match="HYBRID_CONSTRAINT_MISMATCH"):
        compare_hybrid_execution_paths(
            (
                {
                    "constraint_id": "a",
                    "path_id": "rfq",
                    "kind": "RFQ",
                    "net_output_atoms": 10,
                    "latency_ms": 1,
                    "capacity_atoms": 10,
                },
                {
                    "constraint_id": "b",
                    "path_id": "amm",
                    "kind": "AMM",
                    "net_output_atoms": 11,
                    "latency_ms": 1,
                    "capacity_atoms": 10,
                },
            )
        )

    with pytest.raises(EvidenceNativeError, match="ERROR_OR_CANCEL_CHARGED"):
        reconcile_resource_payment(
            {
                "payment_scheme": "MOCK",
                "status": "ERROR",
                "charged_atoms": 1,
                "response": {},
                "latency_ms": 1,
            }
        )


def test_incident_invariants_security_drift_and_receipt_redaction() -> None:
    invariants = derive_incident_invariant_tests(
        {"mechanics": ("shared-vault-accounting", "withdrawal-ordering")}
    )
    assert invariants["test_count"] == 2

    drift = detect_semantic_security_drift(
        {
            "previous_semantic_hash": "old",
            "current_semantic_hash": "new",
            "previous_config_hash": "config-a",
            "current_config_hash": "config-b",
        }
    )
    assert drift["drift"] is True
    assert drift["invalidate_prior_safety_evidence"] is True

    redacted = redact_receipt_for_sharing(
        {
            "receipt_hash": "public",
            "authorization": "secret",
            "signed_transaction": "signed",
            "sensitive_route": "route",
        }
    )
    assert set(redacted["removed_fields"]) == {
        "authorization",
        "sensitive_route",
        "signed_transaction",
    }


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


def test_receipt_component_identity_rejects_code_config_model_and_output_tampering() -> None:
    receipt = _receipt()
    verified = verify_receipt_components(
        receipt,
        raw_hashes=receipt.raw_hashes,
        code_commit=receipt.code_commit,
        tree_hash=receipt.tree_hash,
        config_hash=receipt.config_hash,
        model_hash=receipt.model_hash,
        environment_lock_hash=receipt.environment_lock_hash,
        output_hashes=receipt.output_hashes,
    )
    assert verified["verified"] is True
    assert verified["live_authority"] is False

    with pytest.raises(EvidenceNativeError, match="RECEIPT_COMPONENT_MISMATCH"):
        verify_receipt_components(
            receipt,
            raw_hashes=receipt.raw_hashes,
            code_commit=receipt.code_commit,
            tree_hash=receipt.tree_hash,
            config_hash="8" * 64,
            model_hash=receipt.model_hash,
            environment_lock_hash=receipt.environment_lock_hash,
            output_hashes=receipt.output_hashes,
        )


def test_incident_corpus_and_rollback_are_quarantined_and_append_only() -> None:
    incident = json.loads(
        (ROOT / "docs/mechanism_discovery/pr355_incident_corpus.json").read_text(
            encoding="utf-8"
        )
    )
    assert incident["rows"]
    assert all(row["source_status"] == "REFERENCE_ONLY" for row in incident["rows"])
    assert all(
        row["production_adapter_allowed"] is False for row in incident["rows"]
    )
    assert all(row["quarantine_required"] is True for row in incident["rows"])

    rollback = json.loads(
        (ROOT / "config/pr355_rollback.json").read_text(encoding="utf-8")
    )
    assert rollback["config_first"] is True
    assert len(rollback["steps"]) == 5
    assert all(step["preserve_evidence"] is True for step in rollback["steps"])
    assert rollback["signing_required"] is False
    assert rollback["fund_recovery_required"] is False


def test_completion_audit_covers_sections_zero_through_eighteen() -> None:
    payload = json.loads(
        (ROOT / "release_artifacts/pr355/completion_audit.json").read_text(
            encoding="utf-8"
        )
    )
    assert [row["section"] for row in payload["sections"]] == [
        str(index) for index in range(19)
    ]
    assert not any(payload["external_nonclaims"].values())


def test_complete_pr355_verifier_accepts_tree() -> None:
    payload = verify()
    assert payload["accepted"] is True, payload["errors"]
    assert payload["owner_total"] == 138
    assert payload["marketpack_binding_count"] == 9
    assert payload["experiment_count"] == 26
    assert payload["completion_section_count"] == 19
    assert payload["boros_verdict"] == "BLOCKED_EXTERNAL"
    assert payload["live_enabled"] is False

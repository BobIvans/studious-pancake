from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_pr358 import verify
from src.research.pr358_contracts import CONTRACT_SCHEMAS, PR358ContractError, contract_type
from src.research.pr358_core import (
    CacheEntry,
    CorrelationObservation,
    ExperimentNode,
    apply_relation_multiple_testing_control,
    bind_distribution_entitlement,
    bind_product_query_budget,
    bind_product_staleness,
    classify_cache_reuse,
    compute_incremental_invalidation,
    compute_node_content_key,
    define_experiment_dag,
    define_machine_payment_quote,
    define_market_science_service,
    define_semantic_join,
    detect_relation_negative_transfer,
    measure_relation_half_life,
    measure_stream_batch_equivalence,
    retract_reorg_revision,
    simulate_solver_competition,
    simulate_x402_single_payment,
    test_accounting_invariant as check_accounting_invariant,
)
from src.research.pr358_integrated import run_pr358_integrated_vertical

ROOT = Path(__file__).resolve().parents[2]


def _node(node_id: str, dependencies: tuple[str, ...] = ()) -> ExperimentNode:
    return ExperimentNode(
        node_id=node_id,
        node_kind="STAT_TEST",
        symbol_version="v1",
        params_hash="a" * 64,
        upstream_artifact_hashes=("b" * 64,),
        data_snapshot_ids=("c" * 64,),
        tool_versions=("stdlib",),
        environment_lock_hash="d" * 64,
        seed=358,
        time_cutoff=100,
        license_generation="l1",
        entitlement_generation="e1",
        semantic_version="s1",
        dependencies=dependencies,
    )


def _obs(bucket: str, frame: str, available_at: int = 10) -> CorrelationObservation:
    return CorrelationObservation(
        frame_id=frame,
        entity_id="market",
        instrument_id="FIX/USDC",
        bucket_id=bucket,
        feature_name=f"feature-{bucket}",
        value=1,
        unit="unit",
        event_at=available_at - 3,
        published_at=available_at - 2,
        received_at=available_at - 1,
        available_at=available_at,
        revision="v1",
        source_id="fixture",
        source_generation="1",
        synthetic=True,
        privacy_class="PUBLIC_SYNTHETIC",
        distribution_allowed=True,
        entitlement_scope="research",
        provenance_hash="e" * 64,
    )


def test_owner_map_covers_all_288_requirements() -> None:
    payload = json.loads((ROOT / "config/pr358_owner_map.json").read_text(encoding="utf-8"))
    rows = payload["requirements"]
    assert len(rows) == 288
    assert len({row["id"] for row in rows}) == 288
    assert len({row["symbol"] for row in rows}) == 288
    assert payload["counts"]["not_run"] == 0
    assert payload["duplicate_authorities"] == []
    assert not any(payload["effect_boundary"].values())


def test_24_normative_contracts_are_immutable_and_fail_closed() -> None:
    assert len(CONTRACT_SCHEMAS) == 24
    relation = contract_type("RelationCandidate")
    kwargs = {field.split("=", 1)[0].replace("/", "_"): "fixture" for field in CONTRACT_SCHEMAS["RelationCandidate"]}
    kwargs["causal_claim"] = True
    kwargs["execution_right"] = False
    with pytest.raises(PR358ContractError):
        relation(**kwargs)


def test_dag_key_acyclicity_cache_and_precise_invalidation() -> None:
    a = _node("a")
    b = _node("b", ("a",))
    c = _node("c", ("b",))
    assert compute_node_content_key(a) == compute_node_content_key(a)
    assert define_experiment_dag((a, b, c))["execution_right"] is False
    assert compute_incremental_invalidation((a, b, c), ("b",)) == ("b", "c")
    entry = CacheEntry(compute_node_content_key(a), "f" * 64, 100, "l1", "e1", "r1", "d1", "s1")
    exact = classify_cache_reuse(entry, expected_content_key=entry.content_key, time_cutoff=100, license_generation="l1", entitlement_generation="e1", source_revision="r1", deployment_generation="d1", semantic_version="s1")
    changed = classify_cache_reuse(entry, expected_content_key=entry.content_key, time_cutoff=100, license_generation="l1", entitlement_generation="e1", source_revision="r2", deployment_generation="d1", semantic_version="s1")
    assert exact == "REUSE_EXACT"
    assert changed == "INVALIDATE"
    with pytest.raises(PR358ContractError):
        define_experiment_dag((_node("x", ("y",)), _node("y", ("x",))))


def test_pit_identity_and_bucket_join_fail_closed() -> None:
    left = _obs("DB-01", "left", 10)
    right = _obs("DB-03", "right", 11)
    joined = define_semantic_join((left, right), decision_time=11)
    assert len(joined["rows"]) == 2
    with pytest.raises(PR358ContractError):
        define_semantic_join((left, _obs("DB-05", "future", 12)), decision_time=11)


def test_stream_batch_equivalence_and_retraction() -> None:
    left = _obs("DB-01", "a", 10)
    right = _obs("DB-03", "b", 10)
    assert measure_stream_batch_equivalence((left, right), (right, left)) is True
    view = {"rows": (left, right), "watermark": 10, "retractions": (), "view_hash": "x"}
    retracted = retract_reorg_revision(view, frame_id="a", revision="v1")
    assert tuple(row.frame_id for row in retracted["rows"]) == ("b",)
    assert retracted["retractions"] == (("a", "v1"),)


def test_fdr_stability_invariants_and_negative_transfer() -> None:
    assert apply_relation_multiple_testing_control({"signal": 10_000, "null": 900_000}, alpha_ppm=50_000) == ("signal",)
    assert measure_relation_half_life((1_000_000, 600_000, 400_000)) == 2
    assert check_accounting_invariant((10, 5), (8, 7), tolerance=0)["holds"] is True
    assert detect_relation_negative_transfer(target_local_loss=10, transferred_loss=12) is True


def test_entitlement_query_budget_and_staleness_fail_closed() -> None:
    service = define_market_science_service(
        service_id="svc",
        service_family="evidence",
        input_schema="in-v1",
        output_schema="out-v1",
        evidence_tier="fixture",
        max_age=5,
        access_scope="research",
        distribution_rights=True,
        privacy_class="PUBLIC_SYNTHETIC",
        query_budget=2,
        redaction_policy="public-only",
        price_model="simulated",
        prohibited_use=("live",),
    )
    assert bind_distribution_entitlement(service, requested_scope="research") is True
    assert bind_product_query_budget(service, used_queries=1) == 1
    assert bind_product_staleness(service, artifact_age=5) is False
    with pytest.raises(PR358ContractError):
        bind_product_query_budget(service, used_queries=2)
    with pytest.raises(PR358ContractError):
        bind_product_staleness(service, artifact_age=6)


def test_solver_and_x402_are_simulation_only() -> None:
    solver = simulate_solver_competition({"a": 100, "b": 95}, {"a": 5, "b": 1})
    assert solver["simulation_only"] is True
    assert solver["execution_right"] is False
    quote = define_machine_payment_quote(service_id="svc", price_units=5, settlement_overhead=1)
    payment = simulate_x402_single_payment(quote)
    assert payment["payment_state"] == "SIMULATED_ONLY"
    assert payment["payment_sent"] is False


def test_integrated_vertical_is_replayable_and_effect_free() -> None:
    first = run_pr358_integrated_vertical()
    second = run_pr358_integrated_vertical()
    assert first["integrated_receipt_hash"] == second["integrated_receipt_hash"]
    assert first["status"] == "SUPPORTED_RESEARCH_ONLY"
    assert first["joined_bucket_count"] >= 3
    assert first["cache"]["exact"] == "REUSE_EXACT"
    assert first["cache"]["revision_change"] == "INVALIDATE"
    assert first["service"]["canonical_product_response"]["actual_pnl_claimed"] is False
    assert first["service"]["economics"]["customer_billing"] is False
    assert not any(first["effect_boundary"].values())


def test_full_pr358_verifier() -> None:
    result = verify()
    assert result["accepted"], result["errors"]
    assert result["requirements"] == 288
    assert result["packages"] == 36
    assert result["typed_contracts"] == 24
    assert result["hypotheses"] == 72
    assert result["challenges"] == 28
    assert result["data_buckets"] == 12
    assert result["technology_buckets"] == 14
    assert result["vertical_templates"] == 16
    assert result["execution_right"] is False

"""Deterministic offline PR-358 integrated relation-science vertical.

The fixture proves composition over the canonical AGG-02 raw journal/source
owner, PR-358 experiment/relation primitives, PR-357 proposal interfaces, and
AGG-14 data-evidence product policy.  It performs no network, payment, signing,
submission, wallet, release, or external-service action.
"""

from __future__ import annotations

import hashlib
from importlib import resources
import json
from typing import Any, Mapping

from src.agg02.contracts import RawEventEnvelope
from src.agg02.source_budget import SourceAccess, SourceRegistryEntry
from src.agg02.storage import DurableRawJournal
from src.research.product import DataEvidenceApi, DataEvidenceArtifact, DataEvidenceKind
from src.research.pr358_core import (
    CacheEntry,
    CorrelationObservation,
    ExperimentNode,
    apply_relation_multiple_testing_control,
    assemble_experiment_evidence,
    bind_distribution_entitlement,
    bind_product_query_budget,
    bind_product_redaction_policy,
    bind_product_staleness,
    classify_cache_reuse,
    compile_relation_to_bootstrap_prior,
    compile_relation_to_hypothesis_ir,
    compile_relation_to_voi_question,
    compile_relation_to_world_model_prior,
    compute_incremental_invalidation,
    compute_node_content_key,
    define_experiment_dag,
    define_market_science_service,
    define_relation_candidate,
    deterministic_receipt,
    effect_boundary,
    estimate_service_cost_floor,
    materialize_joined_research_view,
    materialize_relation_atlas_snapshot,
    measure_precursor_lead_time,
    measure_sequence_precision_recall,
    measure_service_unit_economics,
    run_granger_predictive_baseline,
    run_rank_correlation_baseline,
    run_transfer_entropy_challenger,
    sample_negative_control_episode,
    sample_normal_control_episode,
)

def _load_fixture() -> Mapping[str, Any]:
    payload = json.loads(
        resources.files("src.resources")
        .joinpath("pr358_relation_vertical.json")
        .read_text(encoding="utf-8")
    )
    expected = payload["fixture_sha256"]
    body = dict(payload)
    body.pop("fixture_sha256", None)
    actual = hashlib.sha256(
        json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    if actual != expected:
        raise ValueError("PR358_FIXTURE_HASH_MISMATCH")
    return payload


def _journal_fixture(fixture: Mapping[str, Any]) -> Mapping[str, Any]:
    source = SourceRegistryEntry(
        source_id="pr358-fixture",
        role="frozen-public-research-fixture",
        metering_unit="record",
        credential_scope="none",
        storage_allowed=True,
        access=SourceAccess.ACTIVE,
        correlation_group="synthetic-pr358",
    )
    source.assert_usable(now_ms=2_000)
    journal = DurableRawJournal(":memory:")
    receipts = []
    for offset, record in enumerate(fixture["records"], 1):
        payload = json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        envelope = RawEventEnvelope(
            event_id=str(record["record_id"]),
            source_id=source.source_id,
            chain_id="fixture-domain",
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            received_at_ms=int(record["received_at"]),
            available_at_ms=int(record["available_at"]),
            decoder_version="pr358-fixture-v1",
            cursor_source=source.source_id,
            cursor_partition="frozen-v1",
            cursor_offset=offset,
            reconnect_epoch=0,
            source_event_time_ms=int(record["event_at"]),
        )
        receipts.append(journal.append(envelope, payload))
    return {
        "source_id": source.source_id,
        "journal_receipt_hashes": tuple(row.receipt_hash for row in receipts),
        "journal_event_count": len(receipts),
    }


def _observations(fixture: Mapping[str, Any]) -> tuple[CorrelationObservation, ...]:
    rows = []
    for record in fixture["records"]:
        rows.append(
            CorrelationObservation(
                frame_id=str(record["record_id"]),
                entity_id=str(record["entity_id"]),
                instrument_id=str(record["instrument_id"]),
                bucket_id=str(record["bucket_id"]),
                feature_name=str(record["feature_name"]),
                value=int(record["value"]),
                unit=str(record["unit"]),
                event_at=int(record["event_at"]),
                published_at=int(record["published_at"]),
                received_at=int(record["received_at"]),
                available_at=int(record["available_at"]),
                revision=str(record["revision"]),
                source_id=str(record["source_id"]),
                source_generation=str(record["source_generation"]),
                synthetic=bool(record["synthetic"]),
                privacy_class=str(record["privacy_class"]),
                distribution_allowed=bool(record["distribution_allowed"]),
                entitlement_scope=str(record["entitlement_scope"]),
                provenance_hash=hashlib.sha256(
                    json.dumps(
                        record,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
            )
        )
    return tuple(rows)


def _series(
    observations: tuple[CorrelationObservation, ...], feature: str
) -> tuple[int, ...]:
    selected = sorted(
        (row for row in observations if row.feature_name == feature),
        key=lambda row: row.event_at,
    )
    return tuple(row.value for row in selected)


def _experiment_nodes(fixture_hash: str) -> tuple[ExperimentNode, ...]:
    common: dict[str, Any] = {
        "params_hash": hashlib.sha256(b"pr358-params-v1").hexdigest(),
        "data_snapshot_ids": (fixture_hash,),
        "tool_versions": ("stdlib", "repo-canonical-owners"),
        "environment_lock_hash": hashlib.sha256(b"requirements.lock").hexdigest(),
        "seed": 358,
        "time_cutoff": 1_070,
        "license_generation": "public-synthetic-v1",
        "entitlement_generation": "research-v1",
        "semantic_version": "pr358-v1",
    }
    specifications = (
        ("source", "SOURCE_SNAPSHOT", "fixture-v1", (), ()),
        ("join", "PIT_JOIN", "semantic-join-v1", ("source",), (fixture_hash,)),
        ("baseline", "STAT_TEST", "rank-v1", ("join",), (fixture_hash,)),
        ("challenger", "STAT_TEST", "directional-v1", ("join",), (fixture_hash,)),
        ("fdr", "EVALUATION", "bh-fdr-v1", ("baseline", "challenger"), (fixture_hash,)),
        ("evidence", "EVIDENCE_ASSEMBLY", "evidence-v1", ("fdr",), (fixture_hash,)),
        ("service", "EVALUATION", "service-v1", ("evidence",), (fixture_hash,)),
    )
    return tuple(
        ExperimentNode(
            node_id=node_id,
            node_kind=node_kind,
            symbol_version=symbol_version,
            upstream_artifact_hashes=upstream,
            dependencies=dependencies,
            **common,
        )
        for node_id, node_kind, symbol_version, dependencies, upstream in specifications
    )


def run_pr358_integrated_vertical() -> Mapping[str, Any]:
    """Run one deterministic, fully offline relation-to-service research vertical."""
    fixture = _load_fixture()
    journal = _journal_fixture(fixture)
    observations = _observations(fixture)
    joined = materialize_joined_research_view(observations, decision_time=1_070)
    bucket_ids = tuple(sorted({row.bucket_id for row in joined["rows"]}))

    nodes = _experiment_nodes(str(fixture["fixture_sha256"]))
    dag = define_experiment_dag(nodes)
    baseline_node = next(node for node in nodes if node.node_id == "baseline")
    baseline_key = compute_node_content_key(baseline_node)
    exact_cache = CacheEntry(
        content_key=baseline_key,
        output_hash=hashlib.sha256(b"baseline-output").hexdigest(),
        time_cutoff=baseline_node.time_cutoff,
        license_generation=baseline_node.license_generation,
        entitlement_generation=baseline_node.entitlement_generation,
        source_revision="v1",
        deployment_generation="fixture-1",
        semantic_version=baseline_node.semantic_version,
    )
    cache_hit = classify_cache_reuse(
        exact_cache,
        expected_content_key=baseline_key,
        time_cutoff=baseline_node.time_cutoff,
        license_generation=baseline_node.license_generation,
        entitlement_generation=baseline_node.entitlement_generation,
        source_revision="v1",
        deployment_generation="fixture-1",
        semantic_version=baseline_node.semantic_version,
    )
    revised_cache = classify_cache_reuse(
        exact_cache,
        expected_content_key=baseline_key,
        time_cutoff=baseline_node.time_cutoff,
        license_generation=baseline_node.license_generation,
        entitlement_generation=baseline_node.entitlement_generation,
        source_revision="v2",
        deployment_generation="fixture-1",
        semantic_version=baseline_node.semantic_version,
    )
    invalidated = compute_incremental_invalidation(nodes, ("source",))

    oracle = _series(observations, "oracle_deviation_bps")
    dex = _series(observations, "dex_price_impact_bps")
    keeper = _series(observations, "keeper_reaction_ms")
    normal_control = sample_normal_control_episode(oracle)
    negative_control = sample_negative_control_episode(oracle)
    baseline = run_rank_correlation_baseline(oracle, dex)
    lagged = run_granger_predictive_baseline(oracle, dex, lag=1)
    challenger = run_transfer_entropy_challenger(oracle, dex)
    accepted_relations = apply_relation_multiple_testing_control(
        {
            "oracle_to_dex": 10_000,
            "negative_control": 900_000,
            "keeper_spurious": 800_000,
        },
        alpha_ppm=50_000,
    )
    precursor = measure_precursor_lead_time((1_030, 1_040), (1_040, 1_050))
    sequence_quality = measure_sequence_precision_recall(
        (1_040, 1_050), (1_040, 1_050), tolerance=1
    )

    relation_status = (
        "REPLICATED_PREDICTIVE"
        if "oracle_to_dex" in accepted_relations
        and baseline["abs_effect_ppm"] >= 500_000
        else "REJECTED_WITH_EVIDENCE"
    )
    relation = define_relation_candidate(
        relation_id="REL-PR358-FIXTURE-001",
        source_variables=("oracle_deviation_bps",),
        target_variables=("dex_price_impact_bps",),
        relation_family="oracle-dex-reaction-gap",
        lag=1,
        market_scope="fixture-market",
        regime_scope="frozen-synthetic-v1",
        method_id="rank+lagged+directional",
        discovery_cutoff=1_070,
        status=relation_status,
    )

    node_receipts = tuple(
        deterministic_receipt(
            {
                "node_id": node.node_id,
                "content_key": compute_node_content_key(node),
                "status": "COMPLETED",
            }
        )
        for node in nodes
    )
    evidence = assemble_experiment_evidence(
        experiment_id="pr358-oracle-dex-keeper-v1",
        dag_hash=str(dag["dag_hash"]),
        node_receipts=node_receipts,
        failed_nodes=(),
        licenses=("PUBLIC_SYNTHETIC_REDIStributable",),
    )
    evidence_hash = str(evidence["evidence_hash"])
    pr357_inputs = {
        "hypothesis": compile_relation_to_hypothesis_ir(
            relation, evidence_hash=evidence_hash
        ),
        "world_model": compile_relation_to_world_model_prior(
            relation, evidence_hash=evidence_hash
        ),
        "bootstrap": compile_relation_to_bootstrap_prior(
            relation, evidence_hash=evidence_hash
        ),
        "voi": compile_relation_to_voi_question(relation, evidence_hash=evidence_hash),
    }
    atlas = materialize_relation_atlas_snapshot((relation,), knowledge_cutoff=1_070)

    service = define_market_science_service(
        service_id="svc-pr358-relation-evidence",
        service_family="relation-evidence-api",
        input_schema="relation-id.v1",
        output_schema="relation-evidence-card.v1",
        evidence_tier="REPLAYABLE_SYNTHETIC_FIXTURE",
        max_age=100,
        access_scope="research",
        distribution_rights=True,
        privacy_class="PUBLIC_SYNTHETIC",
        query_budget=3,
        redaction_policy="PUBLIC_SYNTHETIC_ONLY",
        price_model="SIMULATED_USAGE_ONLY",
        prohibited_use=("live-trading-authorization", "causal-truth-claim"),
    )
    bind_distribution_entitlement(service, requested_scope="research")
    remaining_queries = bind_product_query_budget(service, used_queries=1)
    redaction = bind_product_redaction_policy(service, privacy_class="PUBLIC_SYNTHETIC")
    stale = bind_product_staleness(service, artifact_age=1)

    artifact_hash = hashlib.sha256(
        json.dumps(atlas, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    artifact = DataEvidenceArtifact(
        artifact_id="pr358-atlas-fixture",
        version="v1",
        artifact_sha256=artifact_hash,
        provenance_sha256=evidence_hash,
        evidence_kind=DataEvidenceKind.SIMULATED,
        distribution_allowed=True,
        access_scopes=("research",),
        max_queries_per_lease=3,
    )
    api = DataEvidenceApi((artifact,))
    api_response = api.read(
        artifact_id=artifact.artifact_id,
        lease_id="fixture-lease",
        access_scope="research",
    )

    cost_floor = estimate_service_cost_floor(
        compute_cost=2,
        source_cost=0,
        verification_cost=1,
        support_cost=1,
    )
    economics = measure_service_unit_economics(
        simulated_revenue=6,
        total_cost=cost_floor,
    )
    fulfillment = deterministic_receipt(
        {
            "request_id": "req-pr358-fixture",
            "service_id": service.service_id,
            "provider_id": "internal-research-fixture",
            "artifact_hash": artifact_hash,
            "evidence_refs": (evidence_hash,),
            "started_at": 1_071,
            "completed_at": 1_072,
            "sla_status": "SIMULATED_PASS",
            "cost_vector": {"total": cost_floor},
            "payment_state": "SIMULATED_ONLY",
            "consumer_feedback_ref": None,
            "actual_market_outcome_claimed": False,
            "customer_billing": False,
        }
    )

    status = (
        "SUPPORTED_RESEARCH_ONLY"
        if relation.status == "REPLICATED_PREDICTIVE"
        and cache_hit == "REUSE_EXACT"
        and revised_cache == "INVALIDATE"
        else "REJECTED_WITH_EVIDENCE"
    )
    result: dict[str, Any] = {
        "roadmap_id": "PR-358",
        "status": status,
        "dependency": {
            "pr357_merge_sha": "dd40b9c8f3e95cedb94a630a0a0c83e02a73a146",
            "available": True,
        },
        "canonical_journal": journal,
        "joined_bucket_ids": bucket_ids,
        "joined_bucket_count": len(bucket_ids),
        "dag": dag,
        "cache": {
            "exact": cache_hit,
            "revision_change": revised_cache,
            "invalidated_nodes": invalidated,
        },
        "controls": {
            "normal": normal_control,
            "negative": negative_control,
            "fdr_accepted": accepted_relations,
        },
        "relation": {
            "candidate": relation,
            "baseline": baseline,
            "lagged": lagged,
            "challenger": challenger,
            "keeper_series": keeper,
            "lead_time": precursor,
            "sequence_quality": sequence_quality,
            "causal_claim": False,
            "execution_right": False,
        },
        "evidence": evidence,
        "pr357_inputs": pr357_inputs,
        "atlas": atlas,
        "service": {
            "offer": service,
            "remaining_queries": remaining_queries,
            "redaction": redaction,
            "stale": stale,
            "canonical_product_response": {
                "artifact_id": api_response.artifact_id,
                "remaining_queries": api_response.remaining_queries,
                "actual_pnl_claimed": api_response.actual_pnl_claimed,
            },
            "fulfillment": fulfillment,
            "economics": economics,
        },
        "effect_boundary": effect_boundary(),
        "production_ready": False,
        "live_enabled": False,
        "execution_right": False,
        "customer_billing": False,
        "external_service_activation": False,
        "realized_pnl_claim": False,
        "causal_truth_claim": False,
    }
    result["integrated_receipt_hash"] = deterministic_receipt(result)["receipt_hash"]
    return result

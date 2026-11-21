from __future__ import annotations

import copy
import json

import pytest

from src.contracts.registry import get_schema_registry
from src.intelligence.openlineage import (
    FACET_SCHEMA_BASE_URL,
    OPENLINEAGE_CORE_SCHEMA_URL,
    OPENLINEAGE_RUN_EVENT_SCHEMA_ID,
    BlockContext,
    DataQualityContext,
    DatasetRef,
    ExplicitLineageEdge,
    OpenLineageEventType,
    OpenLineageProjectionError,
    StrategyContext,
    project_event,
    serialize_run_event,
    validate_openlineage_run_event,
)
from src.observability.events import Environment, EventType, Outcome, make_event

REPO_SHA = "a" * 40


def _event(*, generation: int = 2):
    return make_event(
        event_type=EventType.opportunity_detected,
        logical_opportunity_id="opportunity-001",
        plan_hash="b" * 64,
        sequence_no=7,
        environment=Environment.paper,
        aggregate_id="candidate-001",
        trace_id="trace-001",
        attempt_generation=generation,
        stage="DISCOVERY",
        outcome=Outcome.observed,
        attributes={
            "private_marker": "credential_DO_NOT_EXPORT_123",
            "nested_debug": {"private_key": "never-copy-this"},
        },
        runtime_id="paper-runtime-001",
        attempt_id=f"attempt-{generation}",
        event_id=f"event-{generation}",
        provider_id="provider-a",
        venue_id="venue-a",
        producer_code_version="git:abc123",
        config_checksum="c" * 64,
        contract_fixture_version="market-contract-v2",
    )


def _projection(envelope=None):
    source_a = DatasetRef("studious://market", "raw-observations")
    source_b = DatasetRef("studious://market", "provider-health")
    target_a = DatasetRef("studious://market", "normalized-observations")
    target_b = DatasetRef("studious://runtime", "operation-episode")
    return project_event(
        envelope or _event(),
        event_type=OpenLineageEventType.RUNNING,
        job_namespace="studious://studious-pancake",
        job_name="paper-market-observation",
        repo_sha=REPO_SHA,
        inputs=(source_a, source_b),
        outputs=(target_a, target_b),
        lineage_edges=(
            ExplicitLineageEdge(
                source_a,
                target_a,
                provenance="AGG02_NORMALIZATION_RECEIPT",
                evidence_refs=("agg02:event:123", "normalization:receipt:456"),
            ),
        ),
        strategy=StrategyContext(
            strategy_id="strategy-cross-venue-01",
            strategy_version="2.1",
            strategy_family="cross-venue-arbitrage",
        ),
        block=BlockContext(
            chain_id="solana:mainnet",
            network="mainnet-beta",
            block_number=250,
            block_hash="block-hash-250",
            transaction_hash="transaction-hash-250",
            transaction_index=1,
            log_index=3,
            canonicality="CANONICAL",
            finality="FINALIZED",
            contract_address="pool-address",
            deployment_version="deployment-v3",
        ),
        dataset_quality={
            source_a: DataQualityContext(
                source_mode="POLL_ONLY",
                provider_id="provider-a",
                adapter_id="adapter-a",
                adapter_version="1.2.0",
                schema_id="market.observation.v2",
                schema_version="2",
                cursor="slot:250",
                watermark="slot:250",
                event_time="2026-11-21T19:10:00Z",
                ingest_time="2026-11-21T19:10:00.250Z",
                freshness_ms=250,
                coverage_ratio_ppm=980000,
                gap_refs=("gap:source-a:249-250",),
                correction_kind="original",
                normalization_version="normalizer-v4",
                raw_payload_ref="agg02://payload/event-123",
                raw_payload_sha256="d" * 64,
            )
        },
    )


def test_openlineage_projection_matches_run_event_schema_and_is_deterministic() -> None:
    envelope = _event()
    first = _projection(envelope)
    second = _projection(envelope)

    assert first == second
    assert first["schemaURL"] == OPENLINEAGE_CORE_SCHEMA_URL
    assert first["eventType"] == "RUNNING"
    assert first["producer"].endswith(f"/{REPO_SHA}/src/intelligence/openlineage.py")
    assert first["run"]["runId"] == second["run"]["runId"]
    assert get_schema_registry().validate_payload(
        OPENLINEAGE_RUN_EVENT_SCHEMA_ID, first
    )
    validate_openlineage_run_event(first)
    assert (
        json.loads(
            serialize_run_event(
                envelope,
                event_type=OpenLineageEventType.RUNNING,
                job_namespace="studious://studious-pancake",
                job_name="paper-market-observation",
                repo_sha=REPO_SHA,
                inputs=(DatasetRef("studious://market", "raw-observations"),),
                outputs=(DatasetRef("studious://market", "normalized-observations"),),
            )
        )["schemaURL"]
        == OPENLINEAGE_CORE_SCHEMA_URL
    )


def test_openlineage_projection_uses_run_scoped_facets_and_explicit_edges() -> None:
    payload = _projection()
    run_facets = payload["run"]["facets"]
    job_facets = payload["job"]["facets"]

    assert "studious_runtime_context" in run_facets
    assert "studious_strategy_context" in run_facets
    assert "studious_block_context" in run_facets
    assert "studious_lineage_edges" in run_facets
    assert job_facets == {}

    edges = run_facets["studious_lineage_edges"]["entries"]
    assert len(edges) == 1
    assert edges[0]["source"]["name"] == "raw-observations"
    assert edges[0]["target"]["name"] == "normalized-observations"
    assert edges[0]["evidence_refs"] == [
        "agg02:event:123",
        "normalization:receipt:456",
    ]
    assert len(payload["inputs"]) == 2
    assert len(payload["outputs"]) == 2
    assert len(edges) == 1


def test_openlineage_projection_never_copies_arbitrary_event_attributes() -> None:
    payload = _projection()
    encoded = json.dumps(payload, sort_keys=True)

    assert "private_marker" not in encoded
    assert "credential_DO_NOT_EXPORT_123" not in encoded
    assert "private_key" not in encoded
    assert "never-copy-this" not in encoded
    assert "attributes" not in payload["run"]["facets"]["studious_runtime_context"]


def test_openlineage_facets_use_immutable_pinned_schema_urls_and_producer() -> None:
    payload = _projection()
    run_facets = payload["run"]["facets"]

    for facet_name, facet in run_facets.items():
        assert facet["_schemaURL"].startswith(FACET_SCHEMA_BASE_URL)
        assert facet["_producer"] == payload["producer"]

    dataset_facet = payload["inputs"][0]["facets"]["studious_data_quality"]
    assert dataset_facet["_schemaURL"].startswith(FACET_SCHEMA_BASE_URL)
    assert dataset_facet["_producer"] == payload["producer"]


def test_openlineage_projection_keeps_strategy_and_live_authority_separate() -> None:
    payload = _projection()
    strategy = payload["run"]["facets"]["studious_strategy_context"]

    assert strategy["strategy_id"] == "strategy-cross-venue-01"
    assert strategy["strategy_version"] == "2.1"
    assert strategy["live_authorized"] is False


def test_openlineage_run_id_is_stable_per_attempt_and_distinct_between_attempts() -> (
    None
):
    first = _projection(_event(generation=2))
    same_attempt = _projection(_event(generation=2))
    next_attempt = _projection(_event(generation=3))

    assert first["run"]["runId"] == same_attempt["run"]["runId"]
    assert first["run"]["runId"] != next_attempt["run"]["runId"]


def test_openlineage_rejects_unpinned_custom_facet_schema_url() -> None:
    payload = _projection()
    tampered = copy.deepcopy(payload)
    tampered["run"]["facets"]["studious_runtime_context"][
        "_schemaURL"
    ] = "https://example.invalid/unpinned-facet-schema.json"

    with pytest.raises(OpenLineageProjectionError, match="schema URL is not pinned"):
        validate_openlineage_run_event(tampered)


def test_openlineage_rejects_custom_facet_with_different_producer() -> None:
    payload = _projection()
    tampered = copy.deepcopy(payload)
    tampered["run"]["facets"]["studious_runtime_context"][
        "_producer"
    ] = "https://example.invalid/other-producer"

    with pytest.raises(OpenLineageProjectionError, match="producer does not match"):
        validate_openlineage_run_event(tampered)


def test_openlineage_rejects_unpinned_repo_sha_and_invalid_data_quality_time() -> None:
    with pytest.raises(OpenLineageProjectionError, match="40-character Git SHA"):
        project_event(
            _event(),
            event_type=OpenLineageEventType.COMPLETE,
            job_namespace="studious://studious-pancake",
            job_name="test-job",
            repo_sha="not-a-sha",
            inputs=(),
            outputs=(),
        )

    with pytest.raises(OpenLineageProjectionError, match="must be RFC3339"):
        DataQualityContext(
            source_mode="ONE_SHOT",
            event_time="not-a-time",
        )


def test_openlineage_rejects_undeclared_or_duplicate_lineage_edges() -> None:
    source = DatasetRef("studious://market", "input")
    target = DatasetRef("studious://market", "output")
    undeclared = DatasetRef("studious://market", "not-declared")

    with pytest.raises(OpenLineageProjectionError, match="endpoints must be declared"):
        project_event(
            _event(),
            event_type=OpenLineageEventType.COMPLETE,
            job_namespace="studious://studious-pancake",
            job_name="test-job",
            repo_sha=REPO_SHA,
            inputs=(source,),
            outputs=(target,),
            lineage_edges=(
                ExplicitLineageEdge(
                    undeclared,
                    target,
                    "UNVERIFIED",
                    ("evidence:1",),
                ),
            ),
        )

    edge = ExplicitLineageEdge(
        source,
        target,
        "CANONICAL_OWNER",
        ("evidence:1",),
    )
    with pytest.raises(OpenLineageProjectionError, match="duplicate explicit"):
        project_event(
            _event(),
            event_type=OpenLineageEventType.COMPLETE,
            job_namespace="studious://studious-pancake",
            job_name="test-job",
            repo_sha=REPO_SHA,
            inputs=(source,),
            outputs=(target,),
            lineage_edges=(edge, edge),
        )


def test_openlineage_requires_evidence_for_each_lineage_edge() -> None:
    source = DatasetRef("studious://market", "input")
    target = DatasetRef("studious://market", "output")
    with pytest.raises(OpenLineageProjectionError, match="evidence reference"):
        ExplicitLineageEdge(
            source,
            target,
            "CLAIMED",
            (),
        )


def test_openlineage_rejects_unknown_studious_facet_names() -> None:
    payload = _projection()
    tampered = copy.deepcopy(payload)
    tampered["run"]["facets"]["studious_runtime_typo"] = {
        "_producer": payload["producer"],
        "_schemaURL": FACET_SCHEMA_BASE_URL,
    }

    with pytest.raises(OpenLineageProjectionError, match="unsupported Studious facet"):
        validate_openlineage_run_event(tampered)

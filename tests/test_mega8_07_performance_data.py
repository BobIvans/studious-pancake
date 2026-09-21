from __future__ import annotations

import pytest

from src.mega8_07.core import EvidenceBinding, Mega807Error, stable_hash
from src.mega8_07.pr271 import (
    batch_quote_in_rust,
    define_rust_sidecar_protocol,
    search_routes_in_rust,
    verify_sidecar_parity,
)
from src.mega8_07.pr272 import (
    batch_route_state_transitions,
    benchmark_vectorized_solver,
    fall_back_to_scalar_reference,
    vectorize_quote_surface,
)
from src.mega8_07.pr273 import (
    benchmark_gpu_economics,
    build_gpu_feature_batch,
    reject_unjustified_gpu_path,
    run_gpu_simulation_batch,
)
from src.mega8_07.pr274 import (
    publish_immutable_state_slice,
    revoke_stale_cache,
    subscribe_edge_cache,
    validate_cache_generation,
)
from src.mega8_07.pr275 import (
    merge_distributed_results,
    schedule_deterministic_job,
    shard_research_workload,
    verify_distributed_replay,
)
from src.mega8_07.pr276 import (
    join_event_time_streams,
    manage_watermark_lateness,
    materialize_stream_state,
    replay_stream_join,
)
from src.mega8_07.pr277 import (
    archive_cold_partition,
    restore_archived_dataset,
    test_archive_disaster_recovery,
    verify_archive_manifest,
)
from src.mega8_07.pr278 import (
    catalog_dataset_lineage,
    catalog_feature_lineage,
    export_lineage_manifest,
    search_evidence_graph,
)


def evidence() -> EvidenceBinding:
    return EvidenceBinding(
        "evidence-1",
        "a" * 64,
        "generation-1",
        "policy-1",
        1,
        100,
    )


def test_rust_sidecar_is_bounded_and_parity_verified() -> None:
    protocol = define_rust_sidecar_protocol(
        protocol_id="rust-quote-v1",
        version="v1",
        max_batch=8,
    )
    output = batch_quote_in_rust(
        protocol,
        (100, 200),
        numerator=11,
        denominator=10,
    )
    assert output == (110, 220)
    assert len(verify_sidecar_parity(output, output, protocol=protocol)) == 64
    routes = search_routes_in_rust(
        protocol,
        {"A": ("B", "C"), "B": ("C",), "C": ()},
        start="A",
        target="C",
        max_hops=2,
    )
    assert routes == (("A", "B", "C"), ("A", "C"))
    with pytest.raises(Mega807Error, match="PARITY"):
        verify_sidecar_parity((1,), (2,), protocol=protocol)


def test_vectorized_paths_preserve_scalar_semantics_and_fallback() -> None:
    assert vectorize_quote_surface((10, 20), (500_000, 1_000_000)) == (
        (5, 10),
        (10, 20),
    )
    states = batch_route_state_transitions(
        ({"reserve": 10}, {"reserve": 20}),
        ({"reserve": -2}, {"reserve": 3}),
    )
    assert states == ({"reserve": 8}, {"reserve": 23})
    bench = benchmark_vectorized_solver(
        scalar_work_units=100,
        vector_work_units=40,
        same_outputs=True,
    )
    assert bench["saved_work_units"] == 60
    assert fall_back_to_scalar_reference(
        supported_semantics=False,
        scalar_result=(1, 2),
    ) == (1, 2)


def test_gpu_lab_never_adopts_without_measured_gain() -> None:
    batch = build_gpu_feature_batch(
        ({"a": 2, "b": 4}, {"a": 3, "b": 6}),
        ("a", "b"),
    )
    assert run_gpu_simulation_batch(
        batch,
        scale_numerator=2,
        scale_denominator=1,
    ) == ((4, 8), (6, 12))
    benchmark = benchmark_gpu_economics(
        cpu_total_us=100,
        gpu_transfer_us=10,
        gpu_compute_us=20,
    )
    assert reject_unjustified_gpu_path(benchmark, minimum_gain_us=50)
    with pytest.raises(Mega807Error, match="NOT_JUSTIFIED"):
        reject_unjustified_gpu_path(
            {"gain_us": 1},
            minimum_gain_us=10,
        )


def test_immutable_cache_generation_and_revocation() -> None:
    first = publish_immutable_state_slice(
        slice_id="slice-1",
        generation="g1",
        payload={"slot": 1, "asset": "USDC"},
        evidence=evidence(),
        now=2,
    )
    second = publish_immutable_state_slice(
        slice_id="slice-2",
        generation="g2",
        payload={"slot": 2},
        evidence=evidence(),
        now=2,
    )
    assert subscribe_edge_cache(
        (first, second),
        allowed_generations=("g2",),
    ) == (second,)
    assert validate_cache_generation(first, expected_generation="g1")
    assert revoke_stale_cache((first, second), current_generation="g2") == (
        "slice-1",
    )
    with pytest.raises(Mega807Error, match="GENERATION"):
        validate_cache_generation(first, expected_generation="g2")


def test_distributed_scheduler_is_deterministic_and_complete_only() -> None:
    shards = shard_research_workload(
        ("a", "b", "c", "d"),
        shard_count=2,
    )
    assert shards == shard_research_workload(
        ("d", "c", "b", "a"),
        shard_count=2,
    )
    jobs = tuple(
        schedule_deterministic_job(
            workload_ids=("a", "b", "c", "d"),
            shard=index,
            shard_count=2,
        )
        for index in range(2)
    )
    results = {job.job_id: f"result-{job.shard}" for job in jobs}
    assert len(merge_distributed_results(jobs, results)) == 2
    assert len(verify_distributed_replay(results, results)) == 64
    with pytest.raises(Mega807Error, match="PARTIAL"):
        merge_distributed_results(jobs, {jobs[0].job_id: "only"})


def test_event_time_join_materialization_and_replay() -> None:
    left = ((10, 12, "dex", {"price": 100}),)
    right = ((11, 13, "oracle", {"price": 101}),)
    joined = join_event_time_streams(left, right, max_event_gap=2)
    assert len(joined) == 1
    assert manage_watermark_lateness(left + ((1, 2, "old", {}),), watermark=10, max_lateness=2) == left
    state = materialize_stream_state(left, revision="r1")
    assert len(state["sha256"]) == 64
    assert len(replay_stream_join(joined, joined)) == 64


def test_archive_manifest_restore_and_dr_are_exact() -> None:
    objects = {
        stable_hash("mega8-07-archive-object", b"alpha".hex()): b"alpha",
        stable_hash("mega8-07-archive-object", b"beta".hex()): b"beta",
    }
    manifest = archive_cold_partition(
        partition_id="p1",
        object_hashes=tuple(objects),
        storage_cost_units=2,
        max_cost_units=5,
    )
    assert verify_archive_manifest(manifest, objects)
    restored = restore_archived_dataset(manifest, objects)
    assert set(restored) == {b"alpha", b"beta"}
    assert len(test_archive_disaster_recovery(manifest, objects, dict(objects))) == 64


def test_catalog_is_rebuildable_from_immutable_entries() -> None:
    dataset = catalog_dataset_lineage("dataset-1", ("r1", "r2"))
    feature = catalog_feature_lineage("feature-1", ("dataset-1:r2",))
    entries = (dataset, feature)
    assert search_evidence_graph(entries, term="feature") == (feature,)
    manifest = export_lineage_manifest(entries)
    assert len(manifest["sha256"]) == 64

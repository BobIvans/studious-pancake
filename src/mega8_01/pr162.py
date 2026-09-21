"""PR-162 / NF-397..400: frozen benchmark manifests and scorecards."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .common import artifact, fail_closed, canonical_hash, require_non_negative_int, require_sha256, require_text, sorted_unique


def build_workload_manifest(
    benchmark_id: str,
    workload_ids: Sequence[str],
    dataset_revision_sha256: str,
):
    bid = require_text(benchmark_id, "benchmark_id")
    workloads = sorted_unique(workload_ids)
    dataset_hash = require_sha256(dataset_revision_sha256, "dataset_revision_sha256")
    if not workloads:
        return fail_closed(
            child="PR-162",
            nf="NF-397",
            action="build_workload_manifest",
            subject_id=bid,
            reason="INSUFFICIENT_EVIDENCE",
        )
    return artifact(
        child="PR-162",
        nf="NF-397",
        action="build_workload_manifest",
        subject_id=bid,
        payload={"workload_ids": workloads, "dataset_revision_sha256": dataset_hash},
    )


def freeze_benchmark_dataset(
    benchmark_id: str,
    dataset_revision: str,
    row_count: int,
    logical_sha256: str,
):
    bid = require_text(benchmark_id, "benchmark_id")
    revision = require_text(dataset_revision, "dataset_revision")
    rows = require_non_negative_int(row_count, "row_count")
    logical_hash = require_sha256(logical_sha256, "logical_sha256")
    return artifact(
        child="PR-162",
        nf="NF-398",
        action="freeze_benchmark_dataset",
        subject_id=bid,
        payload={
            "dataset_revision": revision,
            "row_count": rows,
            "logical_sha256": logical_hash,
            "frozen": True,
        },
    )


def run_cross_adapter_benchmark(
    benchmark_id: str,
    adapter_scores: Mapping[str, int],
):
    bid = require_text(benchmark_id, "benchmark_id")
    scores = {
        require_text(adapter, "adapter"): require_non_negative_int(score, "score")
        for adapter, score in adapter_scores.items()
    }
    if len(scores) < 2:
        return fail_closed(
            child="PR-162",
            nf="NF-399",
            action="run_cross_adapter_benchmark",
            subject_id=bid,
            reason="INSUFFICIENT_EVIDENCE",
            payload={"adapter_count": len(scores)},
        )
    return artifact(
        child="PR-162",
        nf="NF-399",
        action="run_cross_adapter_benchmark",
        subject_id=bid,
        payload={"adapter_scores": dict(sorted(scores.items()))},
    )


def publish_benchmark_card(
    benchmark_id: str,
    workload_manifest_sha256: str,
    result_artifact_hashes: Sequence[str],
    residual_blockers: Sequence[str],
):
    bid = require_text(benchmark_id, "benchmark_id")
    manifest = require_sha256(workload_manifest_sha256, "workload_manifest_sha256")
    results = tuple(
        sorted(require_sha256(value, "result_artifact_hash") for value in result_artifact_hashes)
    )
    blockers = sorted_unique(residual_blockers)
    payload = {
        "workload_manifest_sha256": manifest,
        "result_artifact_hashes": results,
        "result_set_sha256": canonical_hash(results),
        "residual_blockers": blockers,
    }
    if not results or blockers:
        return fail_closed(
            child="PR-162",
            nf="NF-400",
            action="publish_benchmark_card",
            subject_id=bid,
            reason="INSUFFICIENT_EVIDENCE",
            payload=payload,
        )
    return artifact(
        child="PR-162",
        nf="NF-400",
        action="publish_benchmark_card",
        subject_id=bid,
        payload=payload,
    )

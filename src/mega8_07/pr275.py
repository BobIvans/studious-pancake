"""PR-275 / DIST-01: deterministic sender-free research scheduling."""

from __future__ import annotations

from typing import Mapping, Sequence

from .core import Mega807Error, ResearchJob, require_positive, stable_hash


def shard_research_workload(
    workload_ids: Sequence[str], *, shard_count: int
) -> tuple[tuple[str, ...], ...]:
    count = require_positive(shard_count, "shard_count")
    shards: list[list[str]] = [[] for _ in range(count)]
    for item in sorted(set(workload_ids)):
        slot = int(stable_hash("mega8-07-shard", item)[:8], 16) % count
        shards[slot].append(item)
    return tuple(tuple(row) for row in shards)


def schedule_deterministic_job(
    *, workload_ids: Sequence[str], shard: int, shard_count: int
) -> ResearchJob:
    shards = shard_research_workload(workload_ids, shard_count=shard_count)
    if not 0 <= shard < shard_count:
        raise Mega807Error("INVALID_SHARD")
    digest = stable_hash("mega8-07-workload", list(shards[shard]))
    return ResearchJob(
        job_id=f"mega8-07-job-{digest[:16]}",
        workload_sha256=digest,
        shard=shard,
        shard_count=shard_count,
    )


def merge_distributed_results(
    expected_jobs: Sequence[ResearchJob],
    results: Mapping[str, str],
) -> tuple[tuple[str, str], ...]:
    expected = {job.job_id for job in expected_jobs}
    if set(results) != expected:
        raise Mega807Error("PARTIAL_OR_EXTRA_DISTRIBUTED_RESULTS")
    return tuple(sorted(results.items()))


def verify_distributed_replay(
    first: Mapping[str, str], second: Mapping[str, str]
) -> str:
    if dict(first) != dict(second):
        raise Mega807Error("DISTRIBUTED_REPLAY_MISMATCH")
    return stable_hash("mega8-07-distributed-replay", dict(sorted(first.items())))

"""Bounded process-based offline replay of immutable exact CPMM frames.

CPU workers cannot reserve resources or authorize execution. Parent-side frame
and deadline checks reject stale results. Process termination is not evidence
of release of a durable resource claim.
"""

from __future__ import annotations
from dataclasses import dataclass
import multiprocessing
import time
from typing import Callable

from .exact_cpmm_capacity import (
    ExactCpmmRoutePlan,
    evaluate_exact_cpmm_route,
    CpmmEvaluationError,
    CpmmEvaluationRejection,
)
from src.economics.non_monotonic_sizing import PR118SizingPointRejected


@dataclass(frozen=True, slots=True)
class ShadowReplayJob:
    job_id: str
    frame_id: str
    plan: ExactCpmmRoutePlan
    amount: int
    snapshot_now: float
    deadline_ns: int

    def __post_init__(self):
        if not self.job_id.strip() or not self.frame_id.strip():
            raise ValueError("job and frame identity required")
        if (
            type(self.amount) is not int
            or self.amount <= 0
            or type(self.deadline_ns) is not int
            or self.deadline_ns <= 0
        ):
            raise ValueError("integer amount and deadline required")


@dataclass(frozen=True, slots=True)
class ShadowReplayResult:
    job_id: str
    frame_id: str
    status: str
    evaluation_id: str | None
    output_atoms: int | None


def _evaluate(job: ShadowReplayJob) -> ShadowReplayResult:
    try:
        route = evaluate_exact_cpmm_route(
            job.plan, input_amount=job.amount, now=job.snapshot_now
        )
    except CpmmEvaluationError as exc:
        if exc.reason not in (
            CpmmEvaluationRejection.ZERO_OUTPUT,
            CpmmEvaluationRejection.INPUT_CAPACITY_EXCEEDED,
        ):
            raise
        return ShadowReplayResult(
            job.job_id, job.frame_id, exc.reason.value, None, None
        )
    except PR118SizingPointRejected as exc:
        return ShadowReplayResult(job.job_id, job.frame_id, exc.reason, None, None)
    return ShadowReplayResult(
        job.job_id,
        job.frame_id,
        "model-replay",
        route.evaluation_id,
        route.conservative_output,
    )


def run_shadow_replays(
    jobs: tuple[ShadowReplayJob, ...],
    *,
    workers: int,
    max_pending: int,
    current_frame_id: str,
    frame_reader: Callable[[], str] | None = None,
) -> tuple[ShadowReplayResult, ...]:
    if type(workers) is not int or workers not in (1, 2, 4, 8):
        raise ValueError("workers must be 1/2/4/8")
    if (
        type(max_pending) is not int
        or not 1 <= max_pending <= 4096
        or len(jobs) > max_pending
    ):
        raise ValueError("bounded queue exceeded")
    if len({j.job_id for j in jobs}) != len(jobs):
        raise ValueError("duplicate replay job")
    ordered = tuple(sorted(jobs, key=lambda j: j.job_id))
    results = []
    pool = multiprocessing.get_context("spawn").Pool(processes=workers)
    terminated = False
    try:
        active = []
        for job in ordered:
            if (
                job.frame_id != current_frame_id
                or time.monotonic_ns() >= job.deadline_ns
            ):
                results.append(
                    ShadowReplayResult(
                        job.job_id, job.frame_id, "stale-or-expired", None, None
                    )
                )
            else:
                active.append((job, pool.apply_async(_evaluate, (job,))))
        for index, (job, pending) in enumerate(active):
            timeout = max(0, (job.deadline_ns - time.monotonic_ns()) / 1_000_000_000)
            try:
                result = pending.get(timeout=timeout)
            except multiprocessing.TimeoutError:
                pool.terminate()
                terminated = True
                for canceled, _ in active[index:]:
                    results.append(
                        ShadowReplayResult(
                            canceled.job_id,
                            canceled.frame_id,
                            "deadline-expired",
                            None,
                            None,
                        )
                    )
                break
            if frame_reader is not None and frame_reader() != job.frame_id:
                result = ShadowReplayResult(
                    job.job_id, job.frame_id, "stale-frame", None, None
                )
            elif time.monotonic_ns() >= job.deadline_ns:
                result = ShadowReplayResult(
                    job.job_id, job.frame_id, "deadline-expired", None, None
                )
            results.append(result)
    except BaseException:
        pool.terminate()
        terminated = True
        raise
    finally:
        if not terminated:
            pool.close()
        pool.join()
    return tuple(sorted(results, key=lambda result: result.job_id))

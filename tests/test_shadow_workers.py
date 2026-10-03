import time
from dataclasses import replace
import pytest
from tests.test_exact_cpmm_capacity import _three_hop_plan, NOW
from src.strategy.shadow_workers import ShadowReplayJob, run_shadow_replays


def test_process_counts_have_identical_outputs_and_reject_stale_jobs():
    jobs = tuple(
        ShadowReplayJob(
            str(i),
            "frame",
            _three_hop_plan(),
            amount,
            NOW,
            time.monotonic_ns() + 60_000_000_000,
        )
        for i, amount in enumerate((10, 20, 30))
    )
    one = run_shadow_replays(jobs, workers=1, max_pending=3, current_frame_id="frame")
    for workers in (2, 4, 8):
        assert (
            run_shadow_replays(
                jobs, workers=workers, max_pending=3, current_frame_id="frame"
            )
            == one
        )
    stale = run_shadow_replays(
        (replace(jobs[0], frame_id="old"), replace(jobs[1], deadline_ns=1)),
        workers=1,
        max_pending=2,
        current_frame_id="frame",
    )
    assert all(
        result.output_atoms is None and result.status == "stale-or-expired"
        for result in stale
    )
    with pytest.raises(ValueError, match="queue"):
        run_shadow_replays(jobs, workers=1, max_pending=2, current_frame_id="frame")


def test_frame_invalidated_during_process_calculation_is_rejected():
    job = ShadowReplayJob(
        "job", "frame", _three_hop_plan(), 20, NOW, time.monotonic_ns() + 60_000_000_000
    )
    result = run_shadow_replays(
        (job,),
        workers=1,
        max_pending=1,
        current_frame_id="frame",
        frame_reader=lambda: "corrected",
    )
    assert result[0].status == "stale-frame"
    assert result[0].output_atoms is None

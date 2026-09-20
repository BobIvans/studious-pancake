import asyncio
from dataclasses import replace

import pytest

from src.paper_shadow.atomic_runtime_stages import (
    AtomicRuntimeStageError,
    AtomicVerticalRuntimeStageSuite,
)
from src.paper_shadow.runner import PaperShadowStageContext, PaperShadowStageName
from tests.test_pr075_atomic_runtime_stages import _Adapter, _Vertical, _opportunity


def _context(opportunity=None, run_id="run"):
    return PaperShadowStageContext(
        run_id, opportunity or _opportunity(), PaperShadowStageName.CAPITAL_SIZING
    )


@pytest.mark.asyncio
async def test_same_id_semantic_change_and_generation_never_reuse_old_record():
    vertical = _Vertical()
    suite = AtomicVerticalRuntimeStageSuite(adapter=_Adapter(), vertical=vertical)
    context = _context()
    await suite.capital_sizing_stage(context)
    changed = replace(context.opportunity, proposed_amount_base_units=2000)
    await suite.capital_sizing_stage(_context(changed))
    await suite.capital_sizing_stage(_context(changed, run_id="new-generation"))
    assert len(vertical.calls) == 3


@pytest.mark.asyncio
async def test_concurrent_same_candidate_is_single_flight():
    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowVertical(_Vertical):
        async def run(self, candidate):
            entered.set()
            await release.wait()
            return await super().run(candidate)

    vertical = SlowVertical()
    suite = AtomicVerticalRuntimeStageSuite(adapter=_Adapter(), vertical=vertical)
    first = asyncio.create_task(suite.capital_sizing_stage(_context()))
    await entered.wait()
    second = asyncio.create_task(suite.capital_sizing_stage(_context()))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, second)
    assert len(vertical.calls) == 1


@pytest.mark.asyncio
async def test_retention_is_bounded_and_expired_projection_cannot_rerun():
    clock = [10.0]
    vertical = _Vertical()
    suite = AtomicVerticalRuntimeStageSuite(
        adapter=_Adapter(),
        vertical=vertical,
        max_records=2,
        max_age_seconds=1,
        monotonic=lambda: clock[0],
    )
    context = _context()
    capital = await suite.capital_sizing_stage(context)
    clock[0] = 11.0
    projection = replace(
        context,
        stage=PaperShadowStageName.PLANNER,
        previous_outputs={"capital_sizing": capital},
    )
    with pytest.raises(AtomicRuntimeStageError, match="expired"):
        await suite.planner_stage(projection)
    assert len(vertical.calls) == 1
    for index in range(5):
        await suite.capital_sizing_stage(_context(run_id=f"run-{index}"))
    assert len(suite._records) == 2


@pytest.mark.asyncio
async def test_timing_reports_full_vertical_once_and_projects_later_outputs():
    clock = [10.0]

    class TimedVertical(_Vertical):
        async def run(self, candidate):
            clock[0] += 0.25
            return await super().run(candidate)

    suite = AtomicVerticalRuntimeStageSuite(
        adapter=_Adapter(), vertical=TimedVertical(), monotonic=lambda: clock[0]
    )
    context = _context()
    capital = await suite.capital_sizing_stage(context)
    planner = await suite.planner_stage(
        replace(
            context,
            stage=PaperShadowStageName.PLANNER,
            previous_outputs={"capital_sizing": capital},
        )
    )
    assert capital["full_vertical_duration_seconds"] == 0.25
    assert capital["execution_scope"] == "full_atomic_vertical"
    assert planner["stage_output_is_projection"] is True
    assert "full_vertical_duration_seconds" not in planner


@pytest.mark.asyncio
async def test_cancelled_execution_does_not_cache_partial_result_or_leak_capacity():
    entered = asyncio.Event()

    class CancelVertical(_Vertical):
        async def run(self, candidate):
            entered.set()
            await asyncio.Event().wait()

    suite = AtomicVerticalRuntimeStageSuite(
        adapter=_Adapter(), vertical=CancelVertical()
    )
    task = asyncio.create_task(suite.capital_sizing_stage(_context()))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not suite._records
    assert suite._waiting == 0
    assert not suite._lock.locked()


@pytest.mark.asyncio
async def test_upstream_evidence_drift_never_reuses_result():
    vertical = _Vertical()
    suite = AtomicVerticalRuntimeStageSuite(adapter=_Adapter(), vertical=vertical)
    context = _context()
    await suite.capital_sizing_stage(
        replace(context, previous_outputs={"provider": {"hash": "a" * 64}})
    )
    await suite.capital_sizing_stage(
        replace(context, previous_outputs={"provider": {"hash": "b" * 64}})
    )
    assert len(vertical.calls) == 2

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.paper_shadow.runner import PaperShadowRunStatus, PaperShadowRunSummary
from src.paper_shadow.structured_runtime import (
    PR150_OUTBOX_KIND,
    PaperLifecycleTransition,
    SQLitePaperLifecycleStore,
    StructuredPaperRuntimeError,
    StructuredPaperRuntimePolicy,
    StructuredPaperRuntimeState,
    build_structured_paper_runtime,
)

pytestmark = pytest.mark.unit

_READY_SUMMARY_STATUSES = {
    PaperShadowRunStatus.HEALTHY_IDLE,
    PaperShadowRunStatus.PAPER_OUTCOME,
}


class _Runtime:
    def __init__(self, summaries: tuple[PaperShadowRunSummary, ...]) -> None:
        self._summaries = list(summaries)
        self.calls = 0

    async def run_once(self) -> PaperShadowRunSummary:
        self.calls += 1
        if not self._summaries:
            raise RuntimeError("no fixture summary")
        return self._summaries.pop(0)


class _HangingRuntime:
    async def run_once(self) -> PaperShadowRunSummary:
        await asyncio.sleep(60)
        raise AssertionError("unreachable")


class _FailingRuntime:
    async def run_once(self) -> PaperShadowRunSummary:
        raise RuntimeError("simulated failure")


def _summary(
    status: PaperShadowRunStatus,
    *,
    reason: str | None = None,
    ready: bool | None = None,
) -> PaperShadowRunSummary:
    terminal_reason = reason or status.value
    ready_for_next_cycle = (
        ready if ready is not None else status in _READY_SUMMARY_STATUSES
    )
    return PaperShadowRunSummary(
        run_id="paper-run",
        status=status,
        journal_path=".runtime/paper-shadow.jsonl",
        candidates_seen=1 if status is PaperShadowRunStatus.PAPER_OUTCOME else 0,
        terminal_reason=terminal_reason,
        events_written=3,
        ready_for_next_cycle=ready_for_next_cycle,
        dependency_reasons=() if ready is not False else (terminal_reason,),
    )


@pytest.mark.asyncio
async def test_pr150_records_repeated_sender_free_cycles_to_sqlite(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(
        (
            _summary(PaperShadowRunStatus.HEALTHY_IDLE, reason="empty_market"),
            _summary(PaperShadowRunStatus.PAPER_OUTCOME, reason="paper_reconciled"),
        )
    )
    store_path = tmp_path / "paper-runtime.sqlite3"
    controller = build_structured_paper_runtime(
        runtime,
        store_path=store_path,
        max_cycles=2,
        run_id="structured-pr150",
    )

    report = await controller.run_until_stopped()

    assert report.final_state is StructuredPaperRuntimeState.PAPER_OUTCOME
    assert report.cycles_completed == 2
    assert report.sender_enabled is False
    assert report.live_enabled is False
    store = SQLitePaperLifecycleStore(store_path)
    transitions = store.read_transitions()
    outbox = store.read_outbox()
    assert [item["state"] for item in transitions] == ["healthy_idle", "paper_outcome"]
    assert [item["cycle"] for item in transitions] == [1, 2]
    assert {item["kind"] for item in outbox} == {PR150_OUTBOX_KIND}
    assert [item["outbox_id"] for item in outbox] == list(report.outbox_ids)


@pytest.mark.asyncio
async def test_pr150_blocks_after_first_non_ready_transition(tmp_path: Path) -> None:
    runtime = _Runtime(
        (
            _summary(
                PaperShadowRunStatus.BLOCKED,
                reason="blocked_missing_evidence",
                ready=False,
            ),
            _summary(PaperShadowRunStatus.PAPER_OUTCOME),
        )
    )
    controller = build_structured_paper_runtime(
        runtime,
        store_path=tmp_path / "blocked.sqlite3",
        max_cycles=5,
        run_id="blocked-pr150",
    )

    report = await controller.run_until_stopped()

    assert report.final_state is StructuredPaperRuntimeState.BLOCKED
    assert report.cycles_completed == 1
    assert runtime.calls == 1
    transitions = SQLitePaperLifecycleStore(report.store_path).read_transitions()
    assert transitions[0]["dependency_reasons"] == ["blocked_missing_evidence"]


@pytest.mark.asyncio
async def test_pr150_cycle_timeout_is_durable_fail_closed(tmp_path: Path) -> None:
    controller = build_structured_paper_runtime(
        _HangingRuntime(),
        store_path=tmp_path / "timeout.sqlite3",
        max_cycles=3,
        cycle_deadline_seconds=0.01,
        run_id="timeout-pr150",
    )

    report = await controller.run_until_stopped()

    assert report.final_state is StructuredPaperRuntimeState.TIMEOUT
    assert report.ready_for_next_cycle is False
    transition = SQLitePaperLifecycleStore(report.store_path).read_transitions()[0]
    assert transition["terminal_reason"] == "stage_deadline_exceeded"
    assert transition["details"]["live_enabled"] is False


@pytest.mark.asyncio
async def test_pr150_cycle_exception_is_durable_without_raw_secret(
    tmp_path: Path,
) -> None:
    controller = build_structured_paper_runtime(
        _FailingRuntime(),
        store_path=tmp_path / "failed.sqlite3",
        run_id="failed-pr150",
    )

    report = await controller.run_until_stopped()

    assert report.final_state is StructuredPaperRuntimeState.FAILED
    transition = SQLitePaperLifecycleStore(report.store_path).read_transitions()[0]
    assert transition["details"] == {
        "error_type": "RuntimeError",
        "live_enabled": False,
        "sender_enabled": False,
    }


def test_pr150_rejects_live_or_submission_material_in_lifecycle() -> None:
    with pytest.raises(StructuredPaperRuntimeError, match="live_enabled"):
        PaperLifecycleTransition(
            run_id="bad",
            cycle=1,
            state=StructuredPaperRuntimeState.PAPER_OUTCOME,
            terminal_reason="bad",
            candidates_seen=1,
            events_written=1,
            ready_for_next_cycle=True,
            details={"live_enabled": True},
        )

    with pytest.raises(StructuredPaperRuntimeError, match="signature"):
        PaperLifecycleTransition(
            run_id="bad",
            cycle=1,
            state=StructuredPaperRuntimeState.PAPER_OUTCOME,
            terminal_reason="bad",
            candidates_seen=1,
            events_written=1,
            ready_for_next_cycle=True,
            details={"signature": "not-allowed"},
        )


def test_pr150_policy_rejects_live_or_sender_enabled() -> None:
    with pytest.raises(StructuredPaperRuntimeError, match="live-disabled"):
        StructuredPaperRuntimePolicy(live_enabled=True)
    with pytest.raises(StructuredPaperRuntimeError, match="live-disabled"):
        StructuredPaperRuntimePolicy(sender_enabled=True)


def test_pr150_structured_runtime_has_no_sender_or_keypair_imports() -> None:
    source = Path("src/paper_shadow/structured_runtime.py").read_text(encoding="utf-8")

    forbidden = ("Keypair", "sendTransaction", "sendBundle", "src.submission")
    for token in forbidden:
        assert token not in source

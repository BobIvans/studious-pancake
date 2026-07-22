from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.paper_shadow.a2_exact_attempt_runtime import (
    A2PaperOutcomeStatus,
    ExactAttemptRuntimeItem,
    run_exact_attempt_runtime_cycle,
)
from src.paper_shadow.exact_attempt_pr152 import ExactAttemptResult, ExactAttemptStatus


HASH = "a" * 64
MSG = "b" * 64
RECON = "c" * 64


class FakeOrchestrator:
    def __init__(self, *results: ExactAttemptResult) -> None:
        self.results = list(results)
        self.requests_seen = []

    async def run(self, request):
        self.requests_seen.append(request)
        return self.results.pop(0)


def request(candidate_id: str = "candidate-1"):
    return SimpleNamespace(capital_candidate=SimpleNamespace(candidate_id=candidate_id))


def item(candidate_id: str = "candidate-1", generation: int = 0, key: str = "idem-1"):
    return ExactAttemptRuntimeItem(
        request=request(candidate_id),
        attempt_generation=generation,
        runtime_idempotency_key=key,
    )


def run_cycle(orchestrator, items):
    return asyncio.run(
        run_exact_attempt_runtime_cycle(
            cycle_id="cycle-1",
            orchestrator=orchestrator,
            items=items,
        )
    )


def test_no_trade_cycle_is_ready_for_next_cycle() -> None:
    report = run_cycle(FakeOrchestrator(), ())

    assert report.status is A2PaperOutcomeStatus.NO_TRADE
    assert report.ready_for_next_cycle is True
    assert report.live_enabled is False
    assert report.sender_imported is False
    assert report.submission_allowed is False


def test_ready_exact_attempt_becomes_reconciled_sender_free_paper_success() -> None:
    result = ExactAttemptResult(
        ExactAttemptStatus.READY_FOR_DURABLE_PAPER,
        HASH,
        attempt_id="attempt-1",
        message_hash=MSG,
        reconciliation_hash=RECON,
    )

    report = run_cycle(FakeOrchestrator(result), (item(),))

    assert report.status is A2PaperOutcomeStatus.RECONCILED_PAPER_SUCCESS
    assert report.terminal_reason == "reconciled_sender_free_paper_success"
    assert report.records[0].message_hash == MSG
    assert report.records[0].reconciliation_hash == RECON
    assert report.ready_for_next_cycle is True


def test_provider_blocked_result_stays_blocked_with_stable_reason() -> None:
    result = ExactAttemptResult(
        ExactAttemptStatus.PROVIDER_BLOCKED,
        HASH,
        blockers=("PR152_PROVIDER_EVIDENCE_EXPIRED",),
    )

    report = run_cycle(FakeOrchestrator(result), (item(),))

    assert report.status is A2PaperOutcomeStatus.BLOCKED
    assert report.terminal_reason == "PR152_PROVIDER_EVIDENCE_EXPIRED"
    assert report.ready_for_next_cycle is False


def test_vertical_blocked_maps_to_simulation_failed_terminal_state() -> None:
    result = ExactAttemptResult(
        ExactAttemptStatus.VERTICAL_BLOCKED,
        HASH,
        blockers=("PR152_VERTICAL_VALUEERROR",),
        reservation_released=True,
    )

    report = run_cycle(FakeOrchestrator(result), (item(),))

    assert report.status is A2PaperOutcomeStatus.SIMULATION_FAILED
    assert report.terminal_reason == "PR152_VERTICAL_VALUEERROR"
    assert report.records[0].status is A2PaperOutcomeStatus.SIMULATION_FAILED


def test_ready_result_without_reconciliation_hash_is_indeterminate() -> None:
    result = ExactAttemptResult(
        ExactAttemptStatus.READY_FOR_DURABLE_PAPER,
        HASH,
        attempt_id="attempt-1",
        message_hash=MSG,
        reconciliation_hash=None,
    )

    report = run_cycle(FakeOrchestrator(result), (item(),))

    assert report.status is A2PaperOutcomeStatus.INDETERMINATE
    assert (
        report.terminal_reason
        == "blocked_a2_ready_result_missing_message_or_reconciliation_hash"
    )


def test_sender_or_submission_surface_forces_indeterminate() -> None:
    result = ExactAttemptResult(
        ExactAttemptStatus.READY_FOR_DURABLE_PAPER,
        HASH,
        attempt_id="attempt-1",
        message_hash=MSG,
        reconciliation_hash=RECON,
        submission_allowed=True,
    )

    report = run_cycle(FakeOrchestrator(result), (item(),))

    assert report.status is A2PaperOutcomeStatus.INDETERMINATE
    assert report.submission_allowed is True
    assert report.ready_for_next_cycle is False


def test_duplicate_attempt_generation_rejected_before_running_orchestrator() -> None:
    orchestrator = FakeOrchestrator()

    with pytest.raises(ValueError, match="duplicate exact-attempt generation"):
        run_cycle(
            orchestrator,
            (
                item("candidate-1", generation=0, key="idem-1"),
                item("candidate-1", generation=0, key="idem-2"),
            ),
        )

    assert orchestrator.requests_seen == []


def test_report_hash_is_deterministic() -> None:
    result = ExactAttemptResult(
        ExactAttemptStatus.READY_FOR_DURABLE_PAPER,
        HASH,
        attempt_id="attempt-1",
        message_hash=MSG,
        reconciliation_hash=RECON,
    )

    report = run_cycle(FakeOrchestrator(result), (item(),))

    assert report.report_hash == report.report_hash
    assert len(report.report_hash) == 64

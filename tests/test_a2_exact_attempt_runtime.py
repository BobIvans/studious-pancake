from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.paper_shadow.a2_exact_attempt_runtime import (
    A2PaperOutcomeStatus,
    ExactAttemptRuntimeItem,
    FailureStage,
    derive_runtime_operation_id,
    run_exact_attempt_runtime_cycle,
    run_exact_attempt_runtime_cycle_for_test,
)
from src.paper_shadow.exact_attempt_pr152 import ExactAttemptResult, ExactAttemptStatus

HASH = "a" * 64
MSG = "b" * 64
PLAN = "c" * 64
RECON = "d" * 64
ATTEMPT = "e" * 64


class FakeOrchestrator:
    def __init__(self, *results: ExactAttemptResult) -> None:
        self.results = list(results)
        self.requests_seen = []

    async def run(self, request):
        self.requests_seen.append(request)
        return self.results.pop(0)


def request(candidate_id: str = "candidate-1"):
    attempt_key = SimpleNamespace(
        attempt_id=ATTEMPT,
        logical_opportunity_id=candidate_id,
        plan_hash=PLAN,
        generation=1,
    )
    return SimpleNamespace(
        attempt_key=attempt_key,
        capital_candidate=SimpleNamespace(candidate_id=candidate_id),
        provider_evidence=SimpleNamespace(evidence_hash=HASH),
        discovery_slot=100,
        reserve_idempotency_key=f"reserve:{candidate_id}",
        release_idempotency_key=f"release:{candidate_id}",
        final_fee_idempotency_key=f"fee:{candidate_id}",
    )


def item(candidate_id: str = "candidate-1", generation: int = 0, key: str | None = None):
    req = request(candidate_id)
    return ExactAttemptRuntimeItem(
        request=req,
        attempt_generation=generation,
        runtime_idempotency_key=key or derive_runtime_operation_id(req, generation),
    )


def run_test_cycle(orchestrator, items):
    return asyncio.run(
        run_exact_attempt_runtime_cycle_for_test(
            cycle_id="cycle-1",
            orchestrator=orchestrator,
            items=items,
        )
    )


def ready_result() -> ExactAttemptResult:
    return ExactAttemptResult(
        ExactAttemptStatus.READY_FOR_DURABLE_PAPER,
        HASH,
        attempt_id=ATTEMPT,
        message_hash=MSG,
        planner_digest=PLAN,
        reconciliation_hash=RECON,
    )


def test_no_trade_cycle_is_ready_for_next_cycle() -> None:
    report = run_test_cycle(FakeOrchestrator(), ())
    assert report.status is A2PaperOutcomeStatus.NO_TRADE
    assert report.ready_for_next_cycle is True
    assert report.live_enabled is False


def test_ready_exact_attempt_remains_handoff_not_success() -> None:
    report = run_test_cycle(FakeOrchestrator(ready_result()), (item(),))
    assert report.status is A2PaperOutcomeStatus.EXACT_ATTEMPT_READY_FOR_HANDOFF
    assert report.terminal_reason == "exact_attempt_ready_for_durable_paper_handoff"
    assert report.records[0].failure_stage is FailureStage.DURABLE_HANDOFF
    assert report.ready_for_next_cycle is False


def test_reproduced_non_hash_strings_are_rejected() -> None:
    result = ExactAttemptResult(
        ExactAttemptStatus.READY_FOR_DURABLE_PAPER,
        "not-a-hash",
        attempt_id=ATTEMPT,
        message_hash="x",
        planner_digest=PLAN,
        reconciliation_hash="y",
    )
    with pytest.raises(ValueError, match="provider_evidence_hash"):
        run_test_cycle(FakeOrchestrator(result), (item(),))


def test_fake_orchestrator_rejected_by_production_entrypoint() -> None:
    with pytest.raises(ValueError, match="UNTRUSTED_EXACT_ATTEMPT_PRODUCER"):
        asyncio.run(
            run_exact_attempt_runtime_cycle(
                cycle_id="cycle-1",
                orchestrator=FakeOrchestrator(ready_result()),
                items=(item(),),
            )
        )


def test_provider_blocked_is_dependency_wide_and_stops() -> None:
    first = ExactAttemptResult(
        ExactAttemptStatus.PROVIDER_BLOCKED,
        HASH,
        blockers=("PR152_PROVIDER_EVIDENCE_EXPIRED",),
    )
    orchestrator = FakeOrchestrator(first, ready_result())
    report = run_test_cycle(orchestrator, (item("one"), item("two")))
    assert report.status is A2PaperOutcomeStatus.BLOCKED
    assert report.records[0].failure_stage is FailureStage.PROVIDER
    assert len(orchestrator.requests_seen) == 1


def test_candidate_local_failure_continues_to_next_candidate() -> None:
    first = ExactAttemptResult(
        ExactAttemptStatus.CAPITAL_BLOCKED,
        HASH,
        blockers=("PR152_CAPITAL_POLICY_REJECTED",),
    )
    report = run_test_cycle(
        FakeOrchestrator(first, ready_result()),
        (item("one"), item("two")),
    )
    assert report.status is A2PaperOutcomeStatus.EXACT_ATTEMPT_READY_FOR_HANDOFF
    assert len(report.records) == 2
    assert report.records[0].failure_stage is FailureStage.CAPITAL


def test_vertical_failure_preserves_stage_taxonomy() -> None:
    result = ExactAttemptResult(
        ExactAttemptStatus.VERTICAL_BLOCKED,
        HASH,
        blockers=("PR152_RECONCILIATION_MISMATCH",),
        reservation_released=True,
    )
    report = run_test_cycle(FakeOrchestrator(result), (item(),))
    assert report.status is A2PaperOutcomeStatus.BLOCKED
    assert report.records[0].failure_stage is FailureStage.RECONCILIATION


def test_sender_or_submission_surface_forces_indeterminate() -> None:
    result = ExactAttemptResult(
        ExactAttemptStatus.READY_FOR_DURABLE_PAPER,
        HASH,
        attempt_id=ATTEMPT,
        message_hash=MSG,
        planner_digest=PLAN,
        reconciliation_hash=RECON,
        submission_allowed=True,
    )
    report = run_test_cycle(FakeOrchestrator(result), (item(),))
    assert report.status is A2PaperOutcomeStatus.INDETERMINATE
    assert report.submission_allowed is True


def test_duplicate_attempt_generation_rejected_before_running() -> None:
    orchestrator = FakeOrchestrator()
    with pytest.raises(ValueError, match="duplicate exact-attempt generation"):
        run_test_cycle(
            orchestrator,
            (
                item("candidate-1", generation=0, key="a" * 64),
                item("candidate-1", generation=0, key="b" * 64),
            ),
        )
    assert orchestrator.requests_seen == []


def test_report_hash_is_deterministic() -> None:
    report = run_test_cycle(FakeOrchestrator(ready_result()), (item(),))
    assert report.report_hash == report.report_hash
    assert len(report.report_hash) == 64

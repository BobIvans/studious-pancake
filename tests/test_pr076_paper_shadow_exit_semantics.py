from __future__ import annotations

import pytest

from src.cli import (
    EXIT_PAPER_SHADOW_BLOCKED,
    EXIT_PAPER_SHADOW_DEGRADED,
    EXIT_PAPER_SHADOW_FAILED,
    _paper_shadow_exit_code,
)
from src.paper_shadow import (
    JsonlPaperShadowJournal,
    PaperShadowRunStatus,
    PaperShadowRunSummary,
    PaperShadowRunner,
    PaperShadowRunnerConfig,
)

pytestmark = pytest.mark.unit


def _summary(status: PaperShadowRunStatus) -> PaperShadowRunSummary:
    ready_statuses = (
        PaperShadowRunStatus.HEALTHY_IDLE,
        PaperShadowRunStatus.PAPER_OUTCOME,
    )
    return PaperShadowRunSummary(
        run_id="run-pr076",
        status=status,
        journal_path="paper-shadow.jsonl",
        candidates_seen=0,
        terminal_reason=status.value,
        events_written=1,
        ready_for_next_cycle=status in ready_statuses,
    )


def test_pr076_exit_code_mapping_is_machine_readable() -> None:
    assert _paper_shadow_exit_code(_summary(PaperShadowRunStatus.HEALTHY_IDLE)) == 0
    assert _paper_shadow_exit_code(_summary(PaperShadowRunStatus.PAPER_OUTCOME)) == 0
    assert _paper_shadow_exit_code(_summary(PaperShadowRunStatus.BLOCKED)) == (
        EXIT_PAPER_SHADOW_BLOCKED
    )
    assert _paper_shadow_exit_code(_summary(PaperShadowRunStatus.DEGRADED)) == (
        EXIT_PAPER_SHADOW_DEGRADED
    )
    assert _paper_shadow_exit_code(_summary(PaperShadowRunStatus.FAILED)) == (
        EXIT_PAPER_SHADOW_FAILED
    )


@pytest.mark.asyncio
async def test_pr076_blocked_run_carries_dependency_reason(tmp_path) -> None:
    path = tmp_path / "paper-shadow.jsonl"
    journal = JsonlPaperShadowJournal(path)
    runner = PaperShadowRunner(
        PaperShadowRunnerConfig(journal_path=path, run_id="run-pr076-blocked"),
        journal=journal,
    )

    summary = await runner.run_once(
        (),
        upstream_cycle_completed=False,
        upstream_dependency_reasons=("blocked_missing_wallet_public_key",),
    )
    payload = summary.to_dict()

    assert summary.status is PaperShadowRunStatus.BLOCKED
    assert payload["schema_version"] == "pr076.paper-shadow-summary.v1"
    assert payload["readiness"] == {
        "ready_for_next_cycle": False,
        "dependency_reasons": ["blocked_missing_wallet_public_key"],
    }
    events = journal.read_events()
    assert events[-1]["event_type"] == "runner_blocked"
    assert events[-1]["details"]["dependency_reasons"] == [
        "blocked_missing_wallet_public_key"
    ]


@pytest.mark.asyncio
async def test_pr076_healthy_idle_is_success_only_after_clean_discovery(
    tmp_path,
) -> None:
    path = tmp_path / "paper-shadow.jsonl"
    runner = PaperShadowRunner(
        PaperShadowRunnerConfig(journal_path=path, run_id="run-pr076-idle"),
        journal=JsonlPaperShadowJournal(path),
    )

    summary = await runner.run_once((), upstream_cycle_completed=True)

    assert summary.status is PaperShadowRunStatus.HEALTHY_IDLE
    assert summary.ready_for_next_cycle is True
    assert summary.dependency_reasons == ()
    assert _paper_shadow_exit_code(summary) == 0


@pytest.mark.asyncio
async def test_pr076_degraded_discovery_is_not_healthy_idle(tmp_path) -> None:
    path = tmp_path / "paper-shadow.jsonl"
    runner = PaperShadowRunner(
        PaperShadowRunnerConfig(journal_path=path, run_id="run-pr076-degraded"),
        journal=JsonlPaperShadowJournal(path),
    )

    summary = await runner.run_once(
        (),
        upstream_cycle_completed=True,
        upstream_dependency_reasons=("optional_provider_unavailable",),
    )

    assert summary.status is PaperShadowRunStatus.DEGRADED
    assert summary.ready_for_next_cycle is False
    assert summary.dependency_reasons == ("optional_provider_unavailable",)
    assert _paper_shadow_exit_code(summary) == EXIT_PAPER_SHADOW_DEGRADED

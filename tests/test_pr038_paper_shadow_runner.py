from __future__ import annotations

from typing import Any, Mapping

import pytest

from src.paper_shadow import (
    JsonlPaperShadowJournal,
    PaperShadowRunStatus,
    PaperShadowRunner,
    PaperShadowRunnerConfig,
    PaperShadowStageContext,
    PaperShadowStageName,
)
from src.strategy.domain import Opportunity

pytestmark = pytest.mark.unit


@pytest.fixture
def opportunity() -> Opportunity:
    return Opportunity.create(
        strategy_name="circular_arbitrage",
        opportunity_type="two_leg_circular",
        detection_slot=123,
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        proposed_amount_base_units=1_000_000,
        expected_gross_profit=0.0,
        ttl_seconds=30.0,
        metadata={"fixture": "pr038"},
        detected_at=100.0,
    )


@pytest.mark.asyncio
async def test_runner_records_healthy_idle_without_synthetic_fill(tmp_path) -> None:
    journal = JsonlPaperShadowJournal(tmp_path / "paper-shadow.jsonl")
    runner = PaperShadowRunner(
        PaperShadowRunnerConfig(journal_path=journal.path, run_id="run-idle"),
        journal=journal,
    )

    summary = await runner.run_once(())

    assert summary.status is PaperShadowRunStatus.HEALTHY_IDLE
    assert summary.terminal_reason == "healthy_idle_no_candidates"
    events = journal.read_events()
    assert [event["event_type"] for event in events] == [
        "runner_started",
        "runner_idle",
    ]
    assert all(event["details"].get("executed") is not True for event in events)
    assert all(event["details"].get("synthetic_fill") is False for event in events)


@pytest.mark.asyncio
async def test_missing_stage_is_durable_blocked_state(tmp_path, opportunity) -> None:
    journal = JsonlPaperShadowJournal(tmp_path / "paper-shadow.jsonl")
    runner = PaperShadowRunner(
        PaperShadowRunnerConfig(journal_path=journal.path, run_id="run-blocked"),
        journal=journal,
    )

    summary = await runner.run_once((opportunity,))

    assert summary.status is PaperShadowRunStatus.BLOCKED
    assert summary.terminal_reason == "blocked_missing_stage_capital_sizing"
    events = journal.read_events()
    assert events[-1]["event_type"] == "stage_blocked"
    assert events[-1]["stage"] == "capital_sizing"
    assert events[-1]["opportunity_id"] == opportunity.opportunity_id
    assert events[-1]["details"] == {
        "executed": False,
        "required_stage": "capital_sizing",
        "synthetic_fill": False,
    }


@pytest.mark.asyncio
async def test_restart_continues_append_only_sequence(tmp_path) -> None:
    path = tmp_path / "paper-shadow.jsonl"
    first = PaperShadowRunner(
        PaperShadowRunnerConfig(journal_path=path, run_id="first"),
        journal=JsonlPaperShadowJournal(path),
    )
    await first.run_once(())

    second = PaperShadowRunner(
        PaperShadowRunnerConfig(journal_path=path, run_id="second"),
        journal=JsonlPaperShadowJournal(path),
    )
    await second.run_once(())

    sequences = [event["sequence"] for event in JsonlPaperShadowJournal(path).read_events()]
    assert sequences == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_stage_output_cannot_claim_execution(tmp_path, opportunity) -> None:
    async def unsafe_stage(
        _context: PaperShadowStageContext,
    ) -> Mapping[str, Any]:
        return {"executed": True, "signature": "forbidden"}

    journal = JsonlPaperShadowJournal(tmp_path / "paper-shadow.jsonl")
    runner = PaperShadowRunner(
        PaperShadowRunnerConfig(journal_path=journal.path, run_id="run-unsafe"),
        journal=journal,
        stages={PaperShadowStageName.CAPITAL_SIZING: unsafe_stage},
    )

    summary = await runner.run_once((opportunity,))

    assert summary.status is PaperShadowRunStatus.FAILED
    assert summary.terminal_reason == "paper_shadow_stage_failure"
    events = journal.read_events()
    assert events[-1]["event_type"] == "runner_failed"
    assert events[-1]["details"]["error_type"] == "ValueError"
    assert "live submission fields" in events[-1]["details"]["error"]

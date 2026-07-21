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
async def test_runner_blocks_empty_candidates_without_discovery_proof(tmp_path) -> None:
    journal = JsonlPaperShadowJournal(tmp_path / "paper-shadow.jsonl")
    runner = PaperShadowRunner(
        PaperShadowRunnerConfig(journal_path=journal.path, run_id="run-blocked-idle"),
        journal=journal,
    )

    summary = await runner.run_once(())

    assert summary.status is PaperShadowRunStatus.BLOCKED
    assert summary.terminal_reason == "blocked_no_discovery_composition"
    events = journal.read_events()
    assert [event["event_type"] for event in events] == [
        "runner_started",
        "runner_blocked",
    ]
    assert events[-1]["stage"] == "discovery"
    assert events[-1]["details"] == {
        "executed": False,
        "healthy_idle_proven": False,
        "required_upstream_stages": ["discovery", "detector"],
        "synthetic_fill": False,
        "upstream_cycle_completed": False,
    }
    assert all(event["details"].get("executed") is not True for event in events)
    assert all(event["details"].get("synthetic_fill") is False for event in events)


@pytest.mark.asyncio
async def test_runner_records_healthy_idle_only_after_discovery_proof(tmp_path) -> None:
    journal = JsonlPaperShadowJournal(tmp_path / "paper-shadow.jsonl")
    runner = PaperShadowRunner(
        PaperShadowRunnerConfig(journal_path=journal.path, run_id="run-idle"),
        journal=journal,
    )

    summary = await runner.run_once((), upstream_cycle_completed=True)

    assert summary.status is PaperShadowRunStatus.HEALTHY_IDLE
    assert summary.terminal_reason == "healthy_idle_no_candidates_after_discovery"
    events = journal.read_events()
    assert [event["event_type"] for event in events] == [
        "runner_started",
        "runner_idle",
    ]
    assert events[-1]["details"] == {
        "healthy_idle_proven": True,
        "sender_enabled": False,
        "synthetic_fill": False,
        "upstream_cycle_completed": True,
    }
    assert all(event["details"].get("executed") is not True for event in events)
    assert all(event["details"].get("synthetic_fill") is False for event in events)


@pytest.mark.asyncio
async def test_runtime_discovery_block_reason_is_durable(tmp_path) -> None:
    journal = JsonlPaperShadowJournal(tmp_path / "paper-shadow.jsonl")
    runner = PaperShadowRunner(
        PaperShadowRunnerConfig(journal_path=journal.path, run_id="run-blocked-pr073"),
        journal=journal,
    )
    discovery_evidence = {
        "schema_version": "pr056.discovery-evidence.v1",
        "cycle_id": "cycle-blocked",
        "cycle_succeeded": False,
        "terminal_reason": "blocked_required_discovery_incomplete",
        "configured_pairs": 1,
        "required_pairs": ["sol-usdc-loop"],
        "completed_required_pairs": [],
        "requests_attempted": 2,
        "batches_completed": 2,
        "snapshots_created": 0,
        "candidates_created": 0,
        "degraded_reasons": ["sol-usdc-loop:missing_second_leg"],
    }

    summary = await runner.run_once((), upstream_cycle_evidence=discovery_evidence)

    assert summary.status is PaperShadowRunStatus.BLOCKED
    assert summary.terminal_reason == "blocked_required_discovery_incomplete"
    assert summary.to_dict()["upstream_cycle_evidence"]["cycle_id"] == "cycle-blocked"
    events = journal.read_events()
    assert events[-1]["event_type"] == "runner_blocked"
    assert events[-1]["reason_code"] == "blocked_required_discovery_incomplete"
    assert events[-1]["details"]["blocked_dependency"] == "runtime_discovery"
    assert (
        events[-1]["details"]["upstream_discovery_evidence"]["terminal_reason"]
        == "blocked_required_discovery_incomplete"
    )
    assert events[-1]["details"]["healthy_idle_proven"] is False


@pytest.mark.asyncio
async def test_verified_empty_discovery_evidence_proves_healthy_idle(tmp_path) -> None:
    journal = JsonlPaperShadowJournal(tmp_path / "paper-shadow.jsonl")
    runner = PaperShadowRunner(
        PaperShadowRunnerConfig(journal_path=journal.path, run_id="run-idle-pr073"),
        journal=journal,
    )
    discovery_evidence = {
        "schema_version": "pr056.discovery-evidence.v1",
        "cycle_id": "cycle-empty",
        "cycle_succeeded": True,
        "terminal_reason": "discovery_cycle_completed",
        "configured_pairs": 1,
        "required_pairs": ["sol-usdc-loop"],
        "completed_required_pairs": ["sol-usdc-loop"],
        "requests_attempted": 2,
        "batches_completed": 2,
        "snapshots_created": 2,
        "candidates_created": 0,
    }

    summary = await runner.run_once((), upstream_cycle_evidence=discovery_evidence)

    assert summary.status is PaperShadowRunStatus.HEALTHY_IDLE
    assert summary.terminal_reason == "healthy_idle_no_candidates_after_discovery"
    assert summary.to_dict()["upstream_cycle_evidence"]["cycle_id"] == "cycle-empty"
    events = journal.read_events()
    assert events[0]["details"]["upstream_cycle_completed"] is True
    assert events[-1]["event_type"] == "runner_idle"
    assert events[-1]["details"]["healthy_idle_proven"] is True
    assert (
        events[-1]["details"]["upstream_discovery_evidence"]["terminal_reason"]
        == "discovery_cycle_completed"
    )


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

    sequences = [
        event["sequence"] for event in JsonlPaperShadowJournal(path).read_events()
    ]
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

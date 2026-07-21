from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.paper_shadow import (
    PR089_MISSING_ATOMIC_DEPENDENCIES,
    AtomicVerticalRuntimeInputs,
    AtomicVerticalRuntimeStageSuite,
    PaperShadowRunStatus,
    PaperShadowRuntimeDependencies,
    build_paper_shadow_runtime,
)
from src.paper_shadow.runner import PaperShadowStageContext
from src.strategy.domain import Opportunity

HASH = "a" * 64
JUPITER_HASH = "b" * 64
ACCOUNT_HASH = "c" * 64
MESSAGE_HASH = "d" * 64
RECONCILIATION_HASH = "e" * 64


@dataclass(frozen=True)
class _Evidence:
    cycle_succeeded: bool = True
    terminal_reason: str = "cycle_succeeded"
    degraded_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "test.discovery-evidence.v1",
            "cycle_id": "cycle-pr089",
            "cycle_succeeded": self.cycle_succeeded,
            "terminal_reason": self.terminal_reason,
            "degraded_reasons": list(self.degraded_reasons),
        }


@dataclass(frozen=True)
class _Report:
    opportunities: tuple[Opportunity, ...]
    evidence: _Evidence


class _Discovery:
    def __init__(
        self,
        opportunities: tuple[Opportunity, ...],
        *,
        evidence: _Evidence | None = None,
    ) -> None:
        self.opportunities = opportunities
        self.evidence = evidence or _Evidence()

    async def run_cycle(self) -> _Report:
        return _Report(opportunities=self.opportunities, evidence=self.evidence)


@dataclass(frozen=True)
class _Adapter:
    candidate: object = object()

    def build(self, context: PaperShadowStageContext) -> AtomicVerticalRuntimeInputs:
        return AtomicVerticalRuntimeInputs(
            candidate=self.candidate,  # type: ignore[arg-type]
            marginfi_provider_pin=HASH,
            jupiter_contract_pin=JUPITER_HASH,
            capital_reservation_id=f"reservation-{context.opportunity.opportunity_id}",
            account_evidence_hash=ACCOUNT_HASH,
            durable_trace_id=f"trace-{context.opportunity.opportunity_id}",
            provider_pins={"marginfi": HASH, "jupiter": JUPITER_HASH},
        )


class _Vertical:
    async def run(self, candidate: object) -> Any:
        diagnostics = SimpleNamespace(
            wire_size=512,
            static_account_count=9,
            total_resolved_account_count=12,
        )
        compiled = SimpleNamespace(
            message_hash=MESSAGE_HASH,
            diagnostics=diagnostics,
            lookup_tables=("lut-1",),
        )
        finalized = SimpleNamespace(compiled=compiled)
        reconciliation = SimpleNamespace(message_hash=MESSAGE_HASH)
        trace = SimpleNamespace(
            opportunity_id="candidate-089",
            planner_digest="f" * 64,
            sequence_fingerprint="sequence-089",
            message_hash=MESSAGE_HASH,
            provisional_response_hash="1" * 64,
            final_response_hash="2" * 64,
            logs_hash="3" * 64,
            reconciliation_hash=RECONCILIATION_HASH,
            min_context_slot=999,
            final_compute_unit_limit=120_000,
            final_fee_lamports=5_000,
            settlement_net=20,
            reconciliation_status="proven_profit",
            reconciliation_reason="state_derived",
            monitored_accounts=("payer", "repayment"),
            required_accounts=("repayment",),
        )
        return SimpleNamespace(
            trace=trace,
            finalized=finalized,
            reconciliation=reconciliation,
        )


def _opportunity() -> Opportunity:
    return Opportunity.create(
        strategy_name="fixture",
        opportunity_type="atomic-arb",
        detection_slot=900,
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        proposed_amount_base_units=1_000,
        expected_gross_profit=0.01,
        ttl_seconds=30.0,
        detected_at=1_750_000_000.0,
        metadata={"source": "pr089-fixture"},
    )


@pytest.mark.asyncio
async def test_pr089_default_candidate_blocks_on_atomic_dependency_gate(
    tmp_path,
) -> None:
    runtime = build_paper_shadow_runtime(
        object(),  # type: ignore[arg-type]
        journal_path=tmp_path / "paper-shadow.jsonl",
        discovery=_Discovery((_opportunity(),)),  # type: ignore[arg-type]
    )

    summary = await runtime.run_once()

    assert summary.status is PaperShadowRunStatus.BLOCKED
    assert summary.terminal_reason == PR089_MISSING_ATOMIC_DEPENDENCIES
    assert "blocked_missing_stage_capital_sizing" not in summary.dependency_reasons
    events = runtime.runner.journal.read_events()
    blocked = [event for event in events if event["event_type"] == "stage_blocked"]
    assert blocked[0]["reason_code"] == PR089_MISSING_ATOMIC_DEPENDENCIES
    assert blocked[0]["details"]["missing_dependencies"] == [
        "atomic_stage_suite",
        "exact_fee_workflow",
        "verified_marginfi_provider",
        "jupiter_v2_build",
    ]


@pytest.mark.asyncio
async def test_pr089_empty_market_stays_healthy_idle_without_atomic_dependencies(
    tmp_path,
) -> None:
    runtime = build_paper_shadow_runtime(
        object(),  # type: ignore[arg-type]
        journal_path=tmp_path / "paper-shadow.jsonl",
        discovery=_Discovery(()),  # type: ignore[arg-type]
    )

    summary = await runtime.run_once()

    assert summary.status is PaperShadowRunStatus.HEALTHY_IDLE
    assert summary.dependency_reasons == ()
    assert summary.terminal_reason == "healthy_idle_no_candidates_after_discovery"


@pytest.mark.asyncio
async def test_pr089_active_dependencies_wire_atomic_stage_suite(tmp_path) -> None:
    suite = AtomicVerticalRuntimeStageSuite(
        adapter=_Adapter(),
        vertical=_Vertical(),  # type: ignore[arg-type]
    )
    runtime = build_paper_shadow_runtime(
        object(),  # type: ignore[arg-type]
        journal_path=tmp_path / "paper-shadow.jsonl",
        dependencies=PaperShadowRuntimeDependencies(
            atomic_stage_suite=suite,
            exact_fee_workflow=object(),
            verified_marginfi_provider=object(),
            jupiter_v2_build=object(),
        ),
        discovery=_Discovery((_opportunity(),)),  # type: ignore[arg-type]
    )

    summary = await runtime.run_once()

    assert summary.status is PaperShadowRunStatus.PAPER_OUTCOME
    events = runtime.runner.journal.read_events()
    completed = [event for event in events if event["event_type"] == "stage_completed"]
    assert [event["stage"] for event in completed] == [
        "capital_sizing",
        "planner",
        "compiler",
        "final_simulation",
        "reconciliation",
    ]
    message_hashes = {
        event["details"]["message_hash"]
        for event in completed
        if "message_hash" in event["details"]
    }
    assert message_hashes == {MESSAGE_HASH}


def test_pr089_composition_root_does_not_import_sender() -> None:
    source = Path("src/paper_shadow/composition.py").read_text(encoding="utf-8")

    forbidden = (
        "src.submission",
        "canonical_sender",
        "permit_bound",
        "sender.submit",
        "sendTransaction",
        "sendBundle",
    )
    for token in forbidden:
        assert token not in source

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from src.paper_shadow.atomic_runtime_stages import (
    AtomicRuntimeStageError,
    AtomicRuntimeStageErrorCode,
    AtomicVerticalRuntimeInputs,
    AtomicVerticalRuntimeStageSuite,
)
from src.paper_shadow.runner import (
    PaperShadowRunStatus,
    PaperShadowRunner,
    PaperShadowRunnerConfig,
    PaperShadowStageContext,
    PaperShadowStageName,
)
from src.strategy.domain import Opportunity

HASH = "a" * 64
JUPITER_HASH = "b" * 64
ACCOUNT_HASH = "c" * 64
MESSAGE_HASH = "d" * 64
RECONCILIATION_HASH = "e" * 64


@dataclass(frozen=True)
class _Adapter:
    candidate: object = object()
    calls: list[str] | None = None

    def build(self, context: PaperShadowStageContext) -> AtomicVerticalRuntimeInputs:
        if self.calls is not None:
            self.calls.append(context.opportunity.opportunity_id)
        return AtomicVerticalRuntimeInputs(
            candidate=self.candidate,  # type: ignore[arg-type]
            marginfi_provider_pin=HASH,
            jupiter_contract_pin=JUPITER_HASH,
            capital_reservation_id="reservation-075",
            account_evidence_hash=ACCOUNT_HASH,
            durable_trace_id=f"trace-{context.opportunity.opportunity_id}",
            provider_pins={"marginfi": HASH, "jupiter": JUPITER_HASH},
        )


class _Vertical:
    def __init__(
        self, *, mutate_compiled_hash: bool = False, fail: bool = False
    ) -> None:
        self.calls: list[object] = []
        self.mutate_compiled_hash = mutate_compiled_hash
        self.fail = fail

    async def run(self, candidate: object) -> Any:
        self.calls.append(candidate)
        if self.fail:
            raise AtomicRuntimeStageError(
                AtomicRuntimeStageErrorCode.MESSAGE_HASH_DRIFT,
                "one byte mutation invalidated the atomic proof",
            )
        compiled_hash = "0" * 64 if self.mutate_compiled_hash else MESSAGE_HASH
        diagnostics = SimpleNamespace(
            wire_size=512,
            static_account_count=9,
            total_resolved_account_count=12,
        )
        compiled = SimpleNamespace(
            message_hash=compiled_hash,
            diagnostics=diagnostics,
            lookup_tables=("lut-1",),
        )
        finalized = SimpleNamespace(compiled=compiled)
        reconciliation = SimpleNamespace(message_hash=MESSAGE_HASH)
        trace = SimpleNamespace(
            opportunity_id="candidate-075",
            planner_digest="f" * 64,
            sequence_fingerprint="sequence-075",
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
        metadata={"source": "pr075-fixture"},
    )


@pytest.mark.asyncio
async def test_pr075_runner_uses_atomic_vertical_once_for_runtime_stages(
    tmp_path,
) -> None:
    adapter_calls: list[str] = []
    adapter = _Adapter(calls=adapter_calls)
    vertical = _Vertical()
    suite = AtomicVerticalRuntimeStageSuite(
        adapter=adapter,
        vertical=vertical,  # type: ignore[arg-type]
    )
    journal_path = tmp_path / "paper-shadow.jsonl"
    runner = PaperShadowRunner(
        PaperShadowRunnerConfig(journal_path=journal_path),
        stages=suite.stage_handlers(),
    )

    summary = await runner.run_once((_opportunity(),), upstream_cycle_completed=True)

    assert summary.status is PaperShadowRunStatus.PAPER_OUTCOME
    assert summary.terminal_reason == "paper_only_outcome_no_sender"
    assert len(adapter_calls) == 1
    assert len(vertical.calls) == 1
    events = runner.journal.read_events()
    completed = [event for event in events if event["event_type"] == "stage_completed"]
    assert [event["stage"] for event in completed] == [
        "capital_sizing",
        "planner",
        "compiler",
        "final_simulation",
        "reconciliation",
    ]
    assert completed[-1]["details"]["message_hash"] == MESSAGE_HASH
    assert completed[-1]["details"]["provider_pins"] == {
        "jupiter": JUPITER_HASH,
        "marginfi": HASH,
    }


@pytest.mark.asyncio
async def test_pr075_stage_outputs_never_mark_sender_or_live_enabled(tmp_path) -> None:
    suite = AtomicVerticalRuntimeStageSuite(
        adapter=_Adapter(),
        vertical=_Vertical(),  # type: ignore[arg-type]
    )
    runner = PaperShadowRunner(
        PaperShadowRunnerConfig(journal_path=tmp_path / "paper-shadow.jsonl"),
        stages=suite.stage_handlers(),
    )

    summary = await runner.run_once((_opportunity(),), upstream_cycle_completed=True)

    assert summary.status is PaperShadowRunStatus.PAPER_OUTCOME
    for event in runner.journal.read_events():
        details = event.get("details", {})
        assert details.get("sender_imported") is not True
        assert details.get("live_mutation_allowed") is not True
        assert details.get("sent") is not True
        assert details.get("submitted") is not True
        assert details.get("signature") in (None, "")


@pytest.mark.asyncio
async def test_pr075_message_hash_drift_fails_closed_before_journal_outcome(
    tmp_path,
) -> None:
    suite = AtomicVerticalRuntimeStageSuite(
        adapter=_Adapter(),
        vertical=_Vertical(mutate_compiled_hash=True),  # type: ignore[arg-type]
    )
    runner = PaperShadowRunner(
        PaperShadowRunnerConfig(journal_path=tmp_path / "paper-shadow.jsonl"),
        stages=suite.stage_handlers(),
    )

    summary = await runner.run_once((_opportunity(),), upstream_cycle_completed=True)

    assert summary.status is PaperShadowRunStatus.FAILED
    assert summary.terminal_reason == "paper_shadow_stage_failure"
    events = runner.journal.read_events()
    assert events[-1]["event_type"] == "runner_failed"
    assert "pr075_message_hash_drift" in events[-1]["details"]["error"]
    assert not any(event["event_type"] == "paper_outcome_recorded" for event in events)


def test_pr075_runtime_inputs_require_real_sha256_pins() -> None:
    with pytest.raises(AtomicRuntimeStageError) as caught:
        AtomicVerticalRuntimeInputs(
            candidate=object(),  # type: ignore[arg-type]
            marginfi_provider_pin="not-a-hash",
            jupiter_contract_pin=JUPITER_HASH,
            capital_reservation_id="reservation-075",
            account_evidence_hash=ACCOUNT_HASH,
            durable_trace_id="trace-075",
        )

    assert caught.value.code is AtomicRuntimeStageErrorCode.INVALID_PROVIDER_PIN
    assert caught.value.details["field"] == "marginfi_provider_pin"


@pytest.mark.asyncio
async def test_pr075_final_simulation_requires_planner_and_compiler_outputs() -> None:
    opportunity = _opportunity()
    suite = AtomicVerticalRuntimeStageSuite(
        adapter=_Adapter(),
        vertical=_Vertical(),  # type: ignore[arg-type]
    )
    context = PaperShadowStageContext(
        run_id="run-075",
        opportunity=opportunity,
        stage=PaperShadowStageName.FINAL_SIMULATION,
        previous_outputs={},
    )

    with pytest.raises(AtomicRuntimeStageError) as caught:
        await suite.final_simulation_stage(context)

    assert caught.value.code is AtomicRuntimeStageErrorCode.WRONG_STAGE_ORDER
    assert caught.value.details["required_stage"] == "planner"

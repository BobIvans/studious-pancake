"""Fail-closed production-grade paper/shadow runner scaffold.

PR-038 cannot honestly claim end-to-end execution until PR-033..PR-037 are in the
base branch.  This runner therefore provides the durable composition boundary and
records explicit blocked states for missing stages rather than inventing fills,
simulation reports or repayment evidence.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence
from uuid import uuid4

from src.paper_shadow.journal import JsonlPaperShadowJournal, PaperShadowEvent
from src.strategy.domain import Opportunity


class PaperShadowStageName(StrEnum):
    DISCOVERY = "discovery"
    DETECTOR = "detector"
    CAPITAL_SIZING = "capital_sizing"
    PLANNER = "planner"
    COMPILER = "compiler"
    FINAL_SIMULATION = "final_simulation"
    RECONCILIATION = "reconciliation"
    JOURNAL = "journal"


class PaperShadowRunStatus(StrEnum):
    HEALTHY_IDLE = "healthy_idle"
    BLOCKED = "blocked"
    FAILED = "failed"
    PAPER_OUTCOME = "paper_outcome"


PAPER_SHADOW_REQUIRED_STAGES: tuple[PaperShadowStageName, ...] = (
    PaperShadowStageName.CAPITAL_SIZING,
    PaperShadowStageName.PLANNER,
    PaperShadowStageName.COMPILER,
    PaperShadowStageName.FINAL_SIMULATION,
    PaperShadowStageName.RECONCILIATION,
)

UPSTREAM_DISCOVERY_STAGES: tuple[PaperShadowStageName, ...] = (
    PaperShadowStageName.DISCOVERY,
    PaperShadowStageName.DETECTOR,
)

_FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "executed",
        "landed",
        "sent",
        "signature",
        "signed_transaction",
        "submitted",
        "txid",
    }
)


@dataclass(frozen=True, slots=True)
class PaperShadowRunnerConfig:
    journal_path: Path = Path(".runtime/paper-shadow-journal.jsonl")
    run_id: str = field(default_factory=lambda: uuid4().hex)
    stop_on_first_blocked_candidate: bool = True
    shutdown_drain_timeout_seconds: float = 1.0


@dataclass(frozen=True, slots=True)
class PaperShadowStageContext:
    run_id: str
    opportunity: Opportunity
    stage: PaperShadowStageName
    previous_outputs: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "previous_outputs",
            MappingProxyType(
                {name: dict(value) for name, value in self.previous_outputs.items()}
            ),
        )


class PaperShadowStage(Protocol):
    async def __call__(
        self, context: PaperShadowStageContext
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class PaperShadowRunSummary:
    run_id: str
    status: PaperShadowRunStatus
    journal_path: str
    candidates_seen: int
    terminal_reason: str
    events_written: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "pr038.paper-shadow-summary.v1",
            "run_id": self.run_id,
            "status": self.status.value,
            "journal_path": self.journal_path,
            "candidates_seen": self.candidates_seen,
            "terminal_reason": self.terminal_reason,
            "events_written": self.events_written,
        }


class PaperShadowRunner:
    """Durable paper/shadow runner with no sender or synthetic fills."""

    def __init__(
        self,
        config: PaperShadowRunnerConfig | None = None,
        *,
        journal: JsonlPaperShadowJournal | None = None,
        stages: Mapping[PaperShadowStageName, PaperShadowStage] | None = None,
    ) -> None:
        self.config = config or PaperShadowRunnerConfig()
        self.journal = journal or JsonlPaperShadowJournal(self.config.journal_path)
        self.stages = dict(stages or {})
        self._next_sequence = self.journal.next_sequence()
        self._events_written = 0

    def _append(
        self,
        *,
        event_type: str,
        status: str,
        reason_code: str,
        stage: PaperShadowStageName | None = None,
        opportunity: Opportunity | None = None,
        message_hash: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        event = PaperShadowEvent(
            run_id=self.config.run_id,
            sequence=self._next_sequence,
            event_type=event_type,
            stage=stage.value if stage else None,
            status=status,
            reason_code=reason_code,
            opportunity_id=opportunity.opportunity_id if opportunity else None,
            message_hash=message_hash,
            details=details or {},
        )
        self.journal.append(event)
        self._next_sequence += 1
        self._events_written += 1

    def _assert_stage_output_safe(
        self, stage: PaperShadowStageName, output: Mapping[str, Any]
    ) -> None:
        present = {key for key in _FORBIDDEN_OUTPUT_KEYS if output.get(key)}
        if present:
            raise ValueError(
                f"paper/shadow stage {stage.value} returned live submission fields: "
                f"{sorted(present)}"
            )

    def _append_missing_upstream_block(self) -> None:
        self._append(
            event_type="runner_blocked",
            status="blocked",
            reason_code="blocked_no_discovery_composition",
            stage=PaperShadowStageName.DISCOVERY,
            details={
                "required_upstream_stages": [
                    stage.value for stage in UPSTREAM_DISCOVERY_STAGES
                ],
                "upstream_cycle_completed": False,
                "healthy_idle_proven": False,
                "executed": False,
                "synthetic_fill": False,
            },
        )

    async def _run_stage(
        self,
        opportunity: Opportunity,
        stage: PaperShadowStageName,
        previous_outputs: Mapping[str, Mapping[str, Any]],
    ) -> Mapping[str, Any] | None:
        handler = self.stages.get(stage)
        if handler is None:
            self._append(
                event_type="stage_blocked",
                status="blocked",
                reason_code=f"blocked_missing_stage_{stage.value}",
                stage=stage,
                opportunity=opportunity,
                details={
                    "required_stage": stage.value,
                    "executed": False,
                    "synthetic_fill": False,
                },
            )
            return None

        self._append(
            event_type="stage_started",
            status="started",
            reason_code="stage_started",
            stage=stage,
            opportunity=opportunity,
        )
        output = await handler(
            PaperShadowStageContext(
                run_id=self.config.run_id,
                opportunity=opportunity,
                stage=stage,
                previous_outputs=previous_outputs,
            )
        )
        self._assert_stage_output_safe(stage, output)
        safe_output = dict(output)
        self._append(
            event_type="stage_completed",
            status="succeeded",
            reason_code="stage_completed",
            stage=stage,
            opportunity=opportunity,
            message_hash=(
                str(safe_output["message_hash"])
                if "message_hash" in safe_output
                else None
            ),
            details=safe_output,
        )
        return safe_output

    async def run_once(
        self,
        opportunities: Sequence[Opportunity] = (),
        *,
        upstream_cycle_completed: bool = False,
    ) -> PaperShadowRunSummary:
        """Run one bounded paper/shadow pass over already-detected candidates.

        On the current main branch detector/planner/compiler/simulation stages may
        not exist yet.  Missing stages are terminal blocked outcomes, not success.
        An empty candidate set is healthy only after the composition root proves
        that discovery and detector completed a bounded upstream cycle.
        """

        self._append(
            event_type="runner_started",
            status="started",
            reason_code="paper_shadow_once_started",
            details={
                "sender_enabled": False,
                "synthetic_fill": False,
                "upstream_cycle_completed": upstream_cycle_completed,
            },
        )
        if not opportunities:
            if not upstream_cycle_completed:
                self._append_missing_upstream_block()
                return self._summary(
                    PaperShadowRunStatus.BLOCKED,
                    candidates_seen=0,
                    terminal_reason="blocked_no_discovery_composition",
                )
            self._append(
                event_type="runner_idle",
                status="succeeded",
                reason_code="healthy_idle_no_candidates_after_discovery",
                details={
                    "sender_enabled": False,
                    "synthetic_fill": False,
                    "upstream_cycle_completed": True,
                    "healthy_idle_proven": True,
                },
            )
            return self._summary(
                PaperShadowRunStatus.HEALTHY_IDLE,
                candidates_seen=0,
                terminal_reason="healthy_idle_no_candidates_after_discovery",
            )

        candidates_seen = 0
        try:
            for opportunity in opportunities:
                candidates_seen += 1
                self._append(
                    event_type="candidate_received",
                    status="succeeded",
                    reason_code="detected_candidate_ingested",
                    stage=PaperShadowStageName.DETECTOR,
                    opportunity=opportunity,
                    details={
                        "strategy_name": opportunity.strategy_name,
                        "opportunity_type": opportunity.opportunity_type,
                        "detection_slot": opportunity.detection_slot,
                        "proposed_amount_base_units": opportunity.proposed_amount_base_units,
                        "executed": False,
                        "synthetic_fill": False,
                    },
                )
                outputs: dict[str, Mapping[str, Any]] = {}
                for stage in PAPER_SHADOW_REQUIRED_STAGES:
                    output = await self._run_stage(opportunity, stage, outputs)
                    if output is None:
                        return self._summary(
                            PaperShadowRunStatus.BLOCKED,
                            candidates_seen=candidates_seen,
                            terminal_reason=f"blocked_missing_stage_{stage.value}",
                        )
                    outputs[stage.value] = output

                self._append(
                    event_type="paper_outcome_recorded",
                    status="succeeded",
                    reason_code="paper_only_outcome_no_sender",
                    stage=PaperShadowStageName.JOURNAL,
                    opportunity=opportunity,
                    details={"executed": False, "synthetic_fill": False},
                )
        except asyncio.CancelledError:
            self._append(
                event_type="runner_cancelled",
                status="cancelled",
                reason_code="runner_cancelled",
                details={"executed": False, "synthetic_fill": False},
            )
            raise
        except Exception as exc:
            self._append(
                event_type="runner_failed",
                status="failed",
                reason_code="paper_shadow_stage_failure",
                details={
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "executed": False,
                    "synthetic_fill": False,
                },
            )
            return self._summary(
                PaperShadowRunStatus.FAILED,
                candidates_seen=candidates_seen,
                terminal_reason="paper_shadow_stage_failure",
            )

        return self._summary(
            PaperShadowRunStatus.PAPER_OUTCOME,
            candidates_seen=candidates_seen,
            terminal_reason="paper_only_outcome_no_sender",
        )

    async def run_until_stopped(
        self,
        stop_event: asyncio.Event,
        opportunities: Sequence[Opportunity] = (),
        *,
        upstream_cycle_completed: bool = False,
    ) -> PaperShadowRunSummary:
        summary = await self.run_once(
            opportunities,
            upstream_cycle_completed=upstream_cycle_completed,
        )
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=self.config.shutdown_drain_timeout_seconds,
            )
        except asyncio.TimeoutError:
            pass
        self._append(
            event_type="runner_stopped",
            status="succeeded",
            reason_code="graceful_shutdown_complete",
            details={"executed": False, "synthetic_fill": False},
        )
        return summary

    def _summary(
        self,
        status: PaperShadowRunStatus,
        *,
        candidates_seen: int,
        terminal_reason: str,
    ) -> PaperShadowRunSummary:
        return PaperShadowRunSummary(
            run_id=self.config.run_id,
            status=status,
            journal_path=str(self.journal.path),
            candidates_seen=candidates_seen,
            terminal_reason=terminal_reason,
            events_written=self._events_written,
        )

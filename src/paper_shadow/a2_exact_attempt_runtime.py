"""MEGA-PR A2 exact-attempt runtime bridge.

This module consumes the merged sender-free ``ExactPaperAttemptOrchestrator``
boundary and turns a sequence of exact-attempt requests into repeatable,
machine-readable paper runtime outcomes.  It never signs, submits, polls
settlement, or enables live/canary behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Awaitable, Protocol, Sequence

from src.paper_shadow.exact_attempt_pr152 import (
    ExactAttemptRequest,
    ExactAttemptResult,
    ExactAttemptStatus,
)


A2_SCHEMA = "mega-pr-a2.exact-paper-attempt-runtime.v1"


class A2PaperOutcomeStatus(StrEnum):
    NO_TRADE = "NO_TRADE"
    BLOCKED = "BLOCKED"
    SIMULATION_FAILED = "SIMULATION_FAILED"
    RECONCILED_PAPER_SUCCESS = "RECONCILED_PAPER_SUCCESS"
    RECONCILED_PAPER_FAILURE = "RECONCILED_PAPER_FAILURE"
    INDETERMINATE = "INDETERMINATE"


class ExactAttemptRuntimePort(Protocol):
    def run(self, request: ExactAttemptRequest) -> Awaitable[ExactAttemptResult]: ...


@dataclass(frozen=True, slots=True)
class ExactAttemptRuntimeItem:
    """One request admitted into the repeated sender-free paper runtime."""

    request: ExactAttemptRequest
    attempt_generation: int
    runtime_idempotency_key: str

    def __post_init__(self) -> None:
        if self.attempt_generation < 0:
            raise ValueError("attempt_generation must be non-negative")
        if not self.runtime_idempotency_key.strip():
            raise ValueError("runtime_idempotency_key is required")


@dataclass(frozen=True, slots=True)
class ExactAttemptRuntimeRecord:
    """Durable-safe projection of one exact-attempt result."""

    item_index: int
    attempt_generation: int
    status: A2PaperOutcomeStatus
    reason_code: str
    provider_evidence_hash: str
    result_hash: str
    attempt_id: str | None = None
    message_hash: str | None = None
    reconciliation_hash: str | None = None
    sender_imported: bool = False
    submission_allowed: bool = False

    def __post_init__(self) -> None:
        if self.item_index < 0:
            raise ValueError("item_index must be non-negative")
        if self.attempt_generation < 0:
            raise ValueError("attempt_generation must be non-negative")
        for field_name in ("reason_code", "provider_evidence_hash", "result_hash"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} is required")

    def to_json(self) -> dict[str, object]:
        return {
            "item_index": self.item_index,
            "attempt_generation": self.attempt_generation,
            "status": self.status.value,
            "reason_code": self.reason_code,
            "provider_evidence_hash": self.provider_evidence_hash,
            "result_hash": self.result_hash,
            "attempt_id": self.attempt_id,
            "message_hash": self.message_hash,
            "reconciliation_hash": self.reconciliation_hash,
            "sender_imported": self.sender_imported,
            "submission_allowed": self.submission_allowed,
        }


@dataclass(frozen=True, slots=True)
class ExactAttemptRuntimeReport:
    """Batch-level result for one repeatable sender-free paper runtime cycle."""

    cycle_id: str
    status: A2PaperOutcomeStatus
    terminal_reason: str
    records: tuple[ExactAttemptRuntimeRecord, ...]
    sender_imported: bool = False
    submission_allowed: bool = False
    live_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.cycle_id.strip():
            raise ValueError("cycle_id is required")
        if not self.terminal_reason.strip():
            raise ValueError("terminal_reason is required")
        if self.live_enabled:
            raise ValueError("MEGA-PR A2 cannot enable live")
        if self.sender_imported or self.submission_allowed:
            if self.status is not A2PaperOutcomeStatus.INDETERMINATE:
                raise ValueError("unsafe sender/submission evidence must be indeterminate")

    @property
    def ready_for_next_cycle(self) -> bool:
        return self.status in {
            A2PaperOutcomeStatus.NO_TRADE,
            A2PaperOutcomeStatus.RECONCILED_PAPER_SUCCESS,
            A2PaperOutcomeStatus.RECONCILED_PAPER_FAILURE,
        }

    @property
    def report_hash(self) -> str:
        return _hash_json(self.to_json())

    def to_json(self) -> dict[str, object]:
        return {
            "schema": A2_SCHEMA,
            "cycle_id": self.cycle_id,
            "status": self.status.value,
            "terminal_reason": self.terminal_reason,
            "ready_for_next_cycle": self.ready_for_next_cycle,
            "sender_imported": self.sender_imported,
            "submission_allowed": self.submission_allowed,
            "live_enabled": self.live_enabled,
            "records": [record.to_json() for record in self.records],
        }


async def run_exact_attempt_runtime_cycle(
    *,
    cycle_id: str,
    orchestrator: ExactAttemptRuntimePort,
    items: Sequence[ExactAttemptRuntimeItem],
) -> ExactAttemptRuntimeReport:
    """Run one bounded sender-free exact-attempt cycle.

    The function intentionally stops on the first terminal candidate outcome.  It is
    a bridge from the exact-attempt orchestrator into a repeatable runtime shape,
    not a sender, signer, or live/canary path.
    """

    if not cycle_id.strip():
        raise ValueError("cycle_id is required")
    _assert_unique_runtime_items(items)

    if not items:
        return ExactAttemptRuntimeReport(
            cycle_id=cycle_id,
            status=A2PaperOutcomeStatus.NO_TRADE,
            terminal_reason="no_trade_no_exact_attempt_requests",
            records=(),
        )

    records: list[ExactAttemptRuntimeRecord] = []
    for item_index, item in enumerate(items):
        result = await orchestrator.run(item.request)
        record = _record_from_result(item_index, item, result)
        records.append(record)

        if record.sender_imported or record.submission_allowed:
            return ExactAttemptRuntimeReport(
                cycle_id=cycle_id,
                status=A2PaperOutcomeStatus.INDETERMINATE,
                terminal_reason="blocked_a2_sender_or_submission_surface_detected",
                records=tuple(records),
                sender_imported=record.sender_imported,
                submission_allowed=record.submission_allowed,
            )

        if record.status is A2PaperOutcomeStatus.RECONCILED_PAPER_SUCCESS:
            return ExactAttemptRuntimeReport(
                cycle_id=cycle_id,
                status=record.status,
                terminal_reason="reconciled_sender_free_paper_success",
                records=tuple(records),
            )

        if record.status is not A2PaperOutcomeStatus.RECONCILED_PAPER_FAILURE:
            return ExactAttemptRuntimeReport(
                cycle_id=cycle_id,
                status=record.status,
                terminal_reason=record.reason_code,
                records=tuple(records),
            )

    return ExactAttemptRuntimeReport(
        cycle_id=cycle_id,
        status=A2PaperOutcomeStatus.RECONCILED_PAPER_FAILURE,
        terminal_reason="all_exact_attempts_reconciled_paper_failure",
        records=tuple(records),
    )


def _record_from_result(
    item_index: int,
    item: ExactAttemptRuntimeItem,
    result: ExactAttemptResult,
) -> ExactAttemptRuntimeRecord:
    status, reason = _map_exact_attempt_result(result)
    return ExactAttemptRuntimeRecord(
        item_index=item_index,
        attempt_generation=item.attempt_generation,
        status=status,
        reason_code=reason,
        provider_evidence_hash=result.provider_evidence_hash,
        result_hash=result.result_hash,
        attempt_id=result.attempt_id,
        message_hash=result.message_hash,
        reconciliation_hash=result.reconciliation_hash,
        sender_imported=result.sender_imported,
        submission_allowed=result.submission_allowed,
    )


def _map_exact_attempt_result(
    result: ExactAttemptResult,
) -> tuple[A2PaperOutcomeStatus, str]:
    if result.sender_imported or result.submission_allowed:
        return (
            A2PaperOutcomeStatus.INDETERMINATE,
            "blocked_a2_sender_or_submission_surface_detected",
        )

    if result.status is ExactAttemptStatus.READY_FOR_DURABLE_PAPER:
        if not result.message_hash or not result.reconciliation_hash:
            return (
                A2PaperOutcomeStatus.INDETERMINATE,
                "blocked_a2_ready_result_missing_message_or_reconciliation_hash",
            )
        return (
            A2PaperOutcomeStatus.RECONCILED_PAPER_SUCCESS,
            "reconciled_sender_free_paper_success",
        )

    if result.status is ExactAttemptStatus.VERTICAL_BLOCKED:
        return (
            A2PaperOutcomeStatus.SIMULATION_FAILED,
            _first_blocker(result, "blocked_a2_vertical_failed"),
        )

    if result.status in {
        ExactAttemptStatus.PROVIDER_BLOCKED,
        ExactAttemptStatus.CAPITAL_BLOCKED,
        ExactAttemptStatus.FINAL_FEE_BLOCKED,
    }:
        return (A2PaperOutcomeStatus.BLOCKED, _first_blocker(result, result.status.value))

    return (A2PaperOutcomeStatus.INDETERMINATE, "blocked_a2_unknown_exact_attempt_status")


def _first_blocker(result: ExactAttemptResult, fallback: str) -> str:
    for blocker in result.blockers:
        if blocker:
            return str(blocker)
    return fallback


def _assert_unique_runtime_items(items: Sequence[ExactAttemptRuntimeItem]) -> None:
    seen: set[tuple[str, int]] = set()
    keys: set[str] = set()
    for item in items:
        candidate_id = item.request.capital_candidate.candidate_id
        identity = (candidate_id, item.attempt_generation)
        if identity in seen:
            raise ValueError("duplicate exact-attempt generation in one runtime cycle")
        seen.add(identity)
        if item.runtime_idempotency_key in keys:
            raise ValueError("duplicate runtime_idempotency_key in one runtime cycle")
        keys.add(item.runtime_idempotency_key)


def _hash_json(value: object) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


__all__ = [
    "A2_SCHEMA",
    "A2PaperOutcomeStatus",
    "ExactAttemptRuntimeItem",
    "ExactAttemptRuntimePort",
    "ExactAttemptRuntimeRecord",
    "ExactAttemptRuntimeReport",
    "run_exact_attempt_runtime_cycle",
]

"""MEGA-PR A2 exact-attempt runtime bridge hardened by PR-187.

The bridge preserves the exact-attempt handoff as a handoff.  It never promotes
``READY_FOR_DURABLE_PAPER`` to paper success.  Only a separately committed and
verified PR-187 durable paper-outcome envelope may become authoritative success
or failure evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Awaitable, Protocol, Sequence

from src.paper_shadow.exact_attempt_pr152 import (
    ExactAttemptRequest,
    ExactAttemptResult,
    ExactAttemptStatus,
    ExactPaperAttemptOrchestrator,
)

A2_SCHEMA = "mega-pr-a2.exact-paper-attempt-runtime.v2"
CANONICAL_EXACT_ATTEMPT_PRODUCER = (
    "src.paper_shadow.exact_attempt_pr152.ExactPaperAttemptOrchestrator"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class A2PaperOutcomeStatus(StrEnum):
    NO_TRADE = "NO_TRADE"
    BLOCKED = "BLOCKED"
    EXACT_ATTEMPT_READY_FOR_HANDOFF = "EXACT_ATTEMPT_READY_FOR_HANDOFF"
    DURABLE_PAPER_OUTCOME_COMMITTED = "DURABLE_PAPER_OUTCOME_COMMITTED"
    RECONCILED_PAPER_SUCCESS = "RECONCILED_PAPER_SUCCESS"
    RECONCILED_PAPER_FAILURE = "RECONCILED_PAPER_FAILURE"
    INDETERMINATE = "INDETERMINATE"
    # Compatibility-only state. PR-187 maps actual failures with FailureStage.
    SIMULATION_FAILED = "SIMULATION_FAILED"


class FailureStage(StrEnum):
    NONE = "none"
    PROVIDER = "provider"
    CAPITAL = "capital"
    PLANNER = "planner"
    COMPILE = "compile"
    SIMULATION = "simulation"
    RECONCILIATION = "reconciliation"
    FINAL_FEE = "final_fee"
    DURABLE_HANDOFF = "durable_handoff"
    SECURITY = "security"
    UNKNOWN = "unknown"


class ExactAttemptRuntimePort(Protocol):
    def run(self, request: ExactAttemptRequest) -> Awaitable[ExactAttemptResult]: ...


@dataclass(frozen=True, slots=True)
class ExactAttemptRuntimeItem:
    """One exact request admitted into a bounded sender-free runtime cycle."""

    request: ExactAttemptRequest
    attempt_generation: int
    runtime_idempotency_key: str

    def __post_init__(self) -> None:
        if self.attempt_generation < 0:
            raise ValueError("attempt_generation must be non-negative")
        if not self.runtime_idempotency_key.strip():
            raise ValueError("runtime_idempotency_key is required")

    @property
    def exact_request_hash(self) -> str:
        return exact_request_hash(self.request)

    @property
    def operation_id(self) -> str:
        return derive_runtime_operation_id(self.request, self.attempt_generation)


@dataclass(frozen=True, slots=True)
class ExactAttemptRuntimeRecord:
    """Strict projection of an exact-attempt result; never settlement evidence."""

    item_index: int
    attempt_generation: int
    status: A2PaperOutcomeStatus
    reason_code: str
    failure_stage: FailureStage
    provider_evidence_hash: str
    result_hash: str
    exact_request_hash: str
    operation_id: str
    producer_identity: str
    attempt_id: str | None = None
    message_hash: str | None = None
    planner_digest: str | None = None
    reconciliation_hash: str | None = None
    sender_imported: bool = False
    submission_allowed: bool = False

    def __post_init__(self) -> None:
        if self.item_index < 0:
            raise ValueError("item_index must be non-negative")
        if self.attempt_generation < 0:
            raise ValueError("attempt_generation must be non-negative")
        if not self.reason_code.strip():
            raise ValueError("reason_code is required")
        for name in (
            "provider_evidence_hash",
            "result_hash",
            "exact_request_hash",
            "operation_id",
        ):
            _require_sha256(getattr(self, name), name)
        for name in ("message_hash", "planner_digest", "reconciliation_hash"):
            value = getattr(self, name)
            if value is not None:
                _require_sha256(value, name)
        if not self.producer_identity.strip():
            raise ValueError("producer_identity is required")
        if self.status is A2PaperOutcomeStatus.EXACT_ATTEMPT_READY_FOR_HANDOFF:
            if not self.attempt_id:
                raise ValueError("handoff requires attempt_id")
            for name in ("message_hash", "planner_digest", "reconciliation_hash"):
                if getattr(self, name) is None:
                    raise ValueError(f"handoff requires {name}")
        if self.sender_imported or self.submission_allowed:
            if self.status is not A2PaperOutcomeStatus.INDETERMINATE:
                raise ValueError("unsafe sender/submission evidence must be indeterminate")

    def to_json(self) -> dict[str, object]:
        return {
            "item_index": self.item_index,
            "attempt_generation": self.attempt_generation,
            "status": self.status.value,
            "reason_code": self.reason_code,
            "failure_stage": self.failure_stage.value,
            "provider_evidence_hash": self.provider_evidence_hash,
            "result_hash": self.result_hash,
            "exact_request_hash": self.exact_request_hash,
            "operation_id": self.operation_id,
            "producer_identity": self.producer_identity,
            "attempt_id": self.attempt_id,
            "message_hash": self.message_hash,
            "planner_digest": self.planner_digest,
            "reconciliation_hash": self.reconciliation_hash,
            "sender_imported": self.sender_imported,
            "submission_allowed": self.submission_allowed,
        }


@dataclass(frozen=True, slots=True)
class ExactAttemptRuntimeReport:
    """Batch-level result for one bounded sender-free exact-attempt cycle."""

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
        # A handoff is intentionally not a terminal paper outcome.
        return self.status in {
            A2PaperOutcomeStatus.NO_TRADE,
            A2PaperOutcomeStatus.DURABLE_PAPER_OUTCOME_COMMITTED,
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
    """Run the production composition with canonical producer/identity binding."""

    if type(orchestrator) is not ExactPaperAttemptOrchestrator:
        raise ValueError("PR187_UNTRUSTED_EXACT_ATTEMPT_PRODUCER")
    _assert_typed_runtime_items(items)
    return await _run_cycle(
        cycle_id=cycle_id,
        orchestrator=orchestrator,
        items=items,
        producer_identity=CANONICAL_EXACT_ATTEMPT_PRODUCER,
    )


async def run_exact_attempt_runtime_cycle_for_test(
    *,
    cycle_id: str,
    orchestrator: ExactAttemptRuntimePort,
    items: Sequence[ExactAttemptRuntimeItem],
    producer_identity: str = "test-double",
) -> ExactAttemptRuntimeReport:
    """Explicit test-only seam; production composition must use the function above."""

    return await _run_cycle(
        cycle_id=cycle_id,
        orchestrator=orchestrator,
        items=items,
        producer_identity=producer_identity,
    )


async def _run_cycle(
    *,
    cycle_id: str,
    orchestrator: ExactAttemptRuntimePort,
    items: Sequence[ExactAttemptRuntimeItem],
    producer_identity: str,
) -> ExactAttemptRuntimeReport:
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
        record = _record_from_result(
            item_index,
            item,
            result,
            producer_identity=producer_identity,
        )
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

        if record.status is A2PaperOutcomeStatus.EXACT_ATTEMPT_READY_FOR_HANDOFF:
            return ExactAttemptRuntimeReport(
                cycle_id=cycle_id,
                status=record.status,
                terminal_reason="exact_attempt_ready_for_durable_paper_handoff",
                records=tuple(records),
            )

        if record.status is A2PaperOutcomeStatus.INDETERMINATE:
            return ExactAttemptRuntimeReport(
                cycle_id=cycle_id,
                status=record.status,
                terminal_reason=record.reason_code,
                records=tuple(records),
            )

        # Provider failure is dependency-wide. Other typed stages are candidate-local
        # and may continue to the next bounded candidate.
        if record.failure_stage is FailureStage.PROVIDER:
            return ExactAttemptRuntimeReport(
                cycle_id=cycle_id,
                status=A2PaperOutcomeStatus.BLOCKED,
                terminal_reason=record.reason_code,
                records=tuple(records),
            )

    return ExactAttemptRuntimeReport(
        cycle_id=cycle_id,
        status=A2PaperOutcomeStatus.BLOCKED,
        terminal_reason="all_exact_attempt_candidates_rejected",
        records=tuple(records),
    )


def _record_from_result(
    item_index: int,
    item: ExactAttemptRuntimeItem,
    result: ExactAttemptResult,
    *,
    producer_identity: str,
) -> ExactAttemptRuntimeRecord:
    _validate_exact_attempt_result(result)
    status, reason, stage = _map_exact_attempt_result(result)
    return ExactAttemptRuntimeRecord(
        item_index=item_index,
        attempt_generation=item.attempt_generation,
        status=status,
        reason_code=reason,
        failure_stage=stage,
        provider_evidence_hash=result.provider_evidence_hash,
        result_hash=result.result_hash,
        exact_request_hash=exact_request_hash(item.request),
        operation_id=derive_runtime_operation_id(item.request, item.attempt_generation),
        producer_identity=producer_identity,
        attempt_id=result.attempt_id,
        message_hash=result.message_hash,
        planner_digest=result.planner_digest,
        reconciliation_hash=result.reconciliation_hash,
        sender_imported=result.sender_imported,
        submission_allowed=result.submission_allowed,
    )


def _validate_exact_attempt_result(result: ExactAttemptResult) -> None:
    _require_sha256(result.provider_evidence_hash, "provider_evidence_hash")
    _require_sha256(result.result_hash, "result_hash")
    for name in ("message_hash", "planner_digest", "reconciliation_hash"):
        value = getattr(result, name)
        if value is not None:
            _require_sha256(value, name)
    if result.status is ExactAttemptStatus.READY_FOR_DURABLE_PAPER:
        if not result.attempt_id:
            raise ValueError("PR187_READY_RESULT_MISSING_ATTEMPT_ID")
        for name in ("message_hash", "planner_digest", "reconciliation_hash"):
            if getattr(result, name) is None:
                raise ValueError(f"PR187_READY_RESULT_MISSING_{name.upper()}")
        if result.blockers:
            raise ValueError("PR187_READY_RESULT_HAS_BLOCKERS")
        if result.reservation_released:
            raise ValueError("PR187_READY_RESULT_RESERVATION_ALREADY_RELEASED")


def _map_exact_attempt_result(
    result: ExactAttemptResult,
) -> tuple[A2PaperOutcomeStatus, str, FailureStage]:
    if result.sender_imported or result.submission_allowed:
        return (
            A2PaperOutcomeStatus.INDETERMINATE,
            "blocked_a2_sender_or_submission_surface_detected",
            FailureStage.SECURITY,
        )

    if result.status is ExactAttemptStatus.READY_FOR_DURABLE_PAPER:
        return (
            A2PaperOutcomeStatus.EXACT_ATTEMPT_READY_FOR_HANDOFF,
            "exact_attempt_ready_for_durable_paper_handoff",
            FailureStage.DURABLE_HANDOFF,
        )

    if result.status is ExactAttemptStatus.PROVIDER_BLOCKED:
        return A2PaperOutcomeStatus.BLOCKED, _first_blocker(result, result.status.value), FailureStage.PROVIDER
    if result.status is ExactAttemptStatus.CAPITAL_BLOCKED:
        return A2PaperOutcomeStatus.BLOCKED, _first_blocker(result, result.status.value), FailureStage.CAPITAL
    if result.status is ExactAttemptStatus.FINAL_FEE_BLOCKED:
        return A2PaperOutcomeStatus.BLOCKED, _first_blocker(result, result.status.value), FailureStage.FINAL_FEE
    if result.status is ExactAttemptStatus.VERTICAL_BLOCKED:
        reason = _first_blocker(result, "PR152_VERTICAL_FAILED")
        return A2PaperOutcomeStatus.BLOCKED, reason, _stage_from_reason(reason)
    return A2PaperOutcomeStatus.INDETERMINATE, "blocked_a2_unknown_exact_attempt_status", FailureStage.UNKNOWN


def _stage_from_reason(reason: str) -> FailureStage:
    upper = reason.upper()
    if "PLANNER" in upper or "CANDIDATE" in upper:
        return FailureStage.PLANNER
    if "COMPILE" in upper or "MESSAGE" in upper:
        return FailureStage.COMPILE
    if "RECONCIL" in upper:
        return FailureStage.RECONCILIATION
    if "SIMUL" in upper or "VERTICAL" in upper:
        return FailureStage.SIMULATION
    return FailureStage.UNKNOWN


def _first_blocker(result: ExactAttemptResult, fallback: str) -> str:
    for blocker in result.blockers:
        if blocker:
            return str(blocker)
    return fallback


def exact_request_hash(request: ExactAttemptRequest) -> str:
    """Bind the non-callable exact request identity used by the runtime."""

    attempt_key = request.attempt_key
    return _hash_json(
        {
            "attempt_id": attempt_key.attempt_id,
            "logical_opportunity_id": attempt_key.logical_opportunity_id,
            "plan_hash": attempt_key.plan_hash,
            "attempt_key_generation": attempt_key.generation,
            "candidate_id": request.capital_candidate.candidate_id,
            "provider_evidence_hash": request.provider_evidence.evidence_hash,
            "discovery_slot": request.discovery_slot,
            "reserve_idempotency_key": request.reserve_idempotency_key,
            "release_idempotency_key": request.release_idempotency_key,
            "final_fee_idempotency_key": request.final_fee_idempotency_key,
        }
    )


def derive_runtime_operation_id(request: ExactAttemptRequest, generation: int) -> str:
    if generation < 0:
        raise ValueError("attempt_generation must be non-negative")
    return _hash_json(
        {
            "domain": "paper-exact-attempt",
            "exact_request_hash": exact_request_hash(request),
            "attempt_generation": generation,
        }
    )


def _assert_typed_runtime_items(items: Sequence[ExactAttemptRuntimeItem]) -> None:
    for item in items:
        expected = derive_runtime_operation_id(item.request, item.attempt_generation)
        if item.runtime_idempotency_key != expected:
            raise ValueError("PR187_RUNTIME_IDEMPOTENCY_KEY_NOT_REQUEST_BOUND")


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


def _require_sha256(value: str, field_name: str) -> str:
    if not _SHA256.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")
    if len(set(value)) == 1 and value[0] in {"0", "f"}:
        raise ValueError(f"{field_name} cannot be a placeholder digest")
    return value


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
    "CANONICAL_EXACT_ATTEMPT_PRODUCER",
    "ExactAttemptRuntimeItem",
    "ExactAttemptRuntimePort",
    "ExactAttemptRuntimeRecord",
    "ExactAttemptRuntimeReport",
    "FailureStage",
    "derive_runtime_operation_id",
    "exact_request_hash",
    "run_exact_attempt_runtime_cycle",
    "run_exact_attempt_runtime_cycle_for_test",
]

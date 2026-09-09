"""MPR-2602 durable paper-only completion and replay bridge.

The accepted PR-02 authority remains the only durable owner.  This module adds
no database and performs no signing or submission.  A qualified A2 handoff is
promoted to paper success only after the existing lifecycle attempt, reservation,
immutable PR-02 terminal, lifecycle event and outbox are committed atomically.
Restart replay verifies that committed evidence and never repeats the vertical.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from typing import Mapping, Sequence

from src.durability.unified_authority_pr02 import (
    AuthorityFence,
    IntentKind,
    ReservationTerminalState,
    TerminalCommit,
    UnifiedAuthorityError,
    UnifiedLifecycleAuthority,
)
from src.execution.models import ExecutionState
from src.paper_shadow.a2_exact_attempt_runtime import (
    A2PaperOutcomeStatus,
    ExactAttemptRuntimeItem,
    ExactAttemptRuntimeRecord,
    ExactAttemptRuntimeReport,
    FailureStage,
    run_exact_attempt_runtime_cycle,
)
from src.paper_shadow.exact_attempt_pr152 import ExactPaperAttemptOrchestrator

MPR2602_PAPER_TERMINAL_SCHEMA = "mpr2602.paper-attempt-terminal.v1"
MPR2602_PAPER_SUCCESS = "RECONCILED_PAPER_SUCCESS"
MPR2602_PAPER_SUCCESS_REASON = "MPR2602_PAPER_SIMULATION_RECONCILED"
MPR2602_REPLAY_REQUIRED = "MPR2602_PREPARED_REPLAY_REQUIRES_RECONCILIATION"


@dataclass(frozen=True, slots=True)
class VerifiedPaperTerminal:
    terminal_id: str
    outbox_event_id: str
    lifecycle_event_id: str
    attempt_id: str
    attempt_generation: int
    report_hash: str
    prepared_plan_hash: str
    provider_evidence_hash: str
    handoff_result_hash: str
    exact_request_hash: str
    operation_id: str
    message_hash: str
    planner_digest: str
    reconciliation_hash: str
    replayed: bool


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _hash_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _intent(authority: UnifiedLifecycleAuthority, fence: AuthorityFence):
    row = authority.db.execute(
        "SELECT * FROM pr02_intents WHERE intent_id=?", (fence.intent_id,)
    ).fetchone()
    if row is None or str(row["intent_kind"]) != IntentKind.PAPER_ATTEMPT.value:
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_INTENT_MISSING")
    return row


def _terminal_payload(
    authority: UnifiedLifecycleAuthority,
    fence: AuthorityFence,
    record: ExactAttemptRuntimeRecord,
) -> dict[str, object]:
    if record.status is not A2PaperOutcomeStatus.EXACT_ATTEMPT_READY_FOR_HANDOFF:
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_HANDOFF_REQUIRED")
    if record.attempt_id is None:
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_ATTEMPT_ID_MISSING")
    if record.message_hash is None or record.planner_digest is None:
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_PLAN_EVIDENCE_MISSING")
    if record.reconciliation_hash is None:
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_RECONCILIATION_MISSING")
    if record.sender_imported or record.submission_allowed:
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_LIVE_SURFACE_REJECTED")
    row = _intent(authority, fence)
    intent_payload = json.loads(str(row["payload_json"]))
    prepared_plan_hash = str(intent_payload.get("prepared_plan_hash", ""))
    if len(prepared_plan_hash) != 64:
        raise UnifiedAuthorityError("MPR2602_PREPARED_PLAN_HASH_MISSING")
    return {
        "schema": MPR2602_PAPER_TERMINAL_SCHEMA,
        "paper_only": True,
        "attempt_id": record.attempt_id,
        "attempt_generation": record.attempt_generation,
        "prepared_plan_hash": prepared_plan_hash,
        "provider_evidence_hash": record.provider_evidence_hash,
        "handoff_result_hash": record.result_hash,
        "exact_request_hash": record.exact_request_hash,
        "operation_id": record.operation_id,
        "message_hash": record.message_hash,
        "planner_digest": record.planner_digest,
        "reconciliation_hash": record.reconciliation_hash,
        "producer_identity": record.producer_identity,
        "sender_imported": False,
        "submission_allowed": False,
        "live_enabled": False,
        "outcome": MPR2602_PAPER_SUCCESS,
        "reason_code": MPR2602_PAPER_SUCCESS_REASON,
        "release_digest": authority.release_digest,
        "policy_bundle_hash": authority.policy_bundle_hash,
    }


def _verified_from_rows(
    authority: UnifiedLifecycleAuthority,
    fence: AuthorityFence,
    record: ExactAttemptRuntimeRecord,
    *,
    replayed: bool,
) -> VerifiedPaperTerminal:
    intent = _intent(authority, fence)
    terminal = authority.db.execute(
        "SELECT * FROM pr02_terminal_records WHERE intent_id=?",
        (fence.intent_id,),
    ).fetchone()
    if terminal is None:
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_NOT_COMMITTED")
    if str(intent["terminal_id"] or "") != str(terminal["terminal_id"]):
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_INTENT_MISMATCH")
    if str(terminal["outcome"]) != MPR2602_PAPER_SUCCESS:
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_OUTCOME_MISMATCH")
    if str(terminal["reservation_terminal_state"]) != ReservationTerminalState.RELEASED.value:
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_RESERVATION_MISMATCH")

    try:
        payload = json.loads(str(terminal["payload_json"]))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_PAYLOAD_CORRUPT") from exc
    if not isinstance(payload, dict):
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_PAYLOAD_CORRUPT")
    encoded = _canonical_json(payload)
    if hashlib.sha256(encoded.encode()).hexdigest() != str(terminal["payload_hash"]):
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_PAYLOAD_HASH_MISMATCH")
    if payload.get("schema") != MPR2602_PAPER_TERMINAL_SCHEMA:
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_SCHEMA_MISMATCH")

    intent_payload = json.loads(str(intent["payload_json"]))
    expected = {
        "attempt_id": record.attempt_id,
        "attempt_generation": record.attempt_generation,
        "provider_evidence_hash": record.provider_evidence_hash,
        "exact_request_hash": record.exact_request_hash,
        "operation_id": record.operation_id,
        "prepared_plan_hash": intent_payload.get("prepared_plan_hash"),
        "release_digest": authority.release_digest,
        "policy_bundle_hash": authority.policy_bundle_hash,
        "outcome": MPR2602_PAPER_SUCCESS,
        "paper_only": True,
        "sender_imported": False,
        "submission_allowed": False,
        "live_enabled": False,
    }
    for name, wanted in expected.items():
        if payload.get(name) != wanted:
            raise UnifiedAuthorityError(
                f"MPR2602_PAPER_TERMINAL_EXPECTED_{name.upper()}_MISMATCH"
            )

    report_hash = str(terminal["report_hash"])
    expected_terminal_id = _hash_json(
        {
            "intent_id": fence.intent_id,
            "outcome": MPR2602_PAPER_SUCCESS,
            "report_hash": report_hash,
            "release_digest": authority.release_digest,
            "policy_bundle_hash": authority.policy_bundle_hash,
        }
    )
    if str(terminal["terminal_id"]) != expected_terminal_id:
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_ID_MISMATCH")
    expected_outbox_id = _hash_json(
        {"terminal_id": expected_terminal_id, "topic": "paper.attempt.terminal"}
    )
    outbox = authority.db.execute(
        "SELECT * FROM pr02_outbox_event WHERE intent_id=?",
        (fence.intent_id,),
    ).fetchone()
    if outbox is None or str(outbox["event_id"]) != expected_outbox_id:
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_OUTBOX_MISSING")
    if hashlib.sha256(str(outbox["payload_json"]).encode()).hexdigest() != str(
        outbox["payload_hash"]
    ):
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_OUTBOX_HASH_MISMATCH")

    lifecycle_event_id = str(terminal["lifecycle_event_id"] or "")
    event = authority.db.execute(
        "SELECT * FROM durable_events WHERE event_id=? AND attempt_id=?",
        (lifecycle_event_id, record.attempt_id),
    ).fetchone()
    if event is None or str(event["event_type"]) != "mpr2602_paper_terminal_committed":
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_LIFECYCLE_EVENT_MISSING")
    if str(event["from_state"]) != str(event["to_state"]):
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_CHANGED_LIVE_STATE")

    attempt = authority.db.execute(
        "SELECT reservation_id,reservation_state,terminal_at_ns FROM durable_attempts "
        "WHERE attempt_id=?",
        (record.attempt_id,),
    ).fetchone()
    if (
        attempt is None
        or str(attempt["reservation_state"]) != ReservationTerminalState.RELEASED.value
        or attempt["terminal_at_ns"] is None
    ):
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_ATTEMPT_NOT_TERMINAL")
    reservation = authority.db.execute(
        "SELECT state FROM durable_reservations WHERE attempt_id=?",
        (record.attempt_id,),
    ).fetchone()
    if reservation is None or str(reservation["state"]) != ReservationTerminalState.RELEASED.value:
        raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_RESERVATION_NOT_RELEASED")

    authority.lifecycle.integrity_check()
    return VerifiedPaperTerminal(
        terminal_id=expected_terminal_id,
        outbox_event_id=expected_outbox_id,
        lifecycle_event_id=lifecycle_event_id,
        attempt_id=str(payload["attempt_id"]),
        attempt_generation=int(payload["attempt_generation"]),
        report_hash=report_hash,
        prepared_plan_hash=str(payload["prepared_plan_hash"]),
        provider_evidence_hash=str(payload["provider_evidence_hash"]),
        handoff_result_hash=str(payload["handoff_result_hash"]),
        exact_request_hash=str(payload["exact_request_hash"]),
        operation_id=str(payload["operation_id"]),
        message_hash=str(payload["message_hash"]),
        planner_digest=str(payload["planner_digest"]),
        reconciliation_hash=str(payload["reconciliation_hash"]),
        replayed=replayed,
    )


def commit_verified_paper_success(
    authority: UnifiedLifecycleAuthority,
    fence: AuthorityFence,
    record: ExactAttemptRuntimeRecord,
) -> VerifiedPaperTerminal:
    """Atomically finalize a sender-free paper success on the PR-02 connection."""
    if not isinstance(authority, UnifiedLifecycleAuthority):
        raise TypeError("MPR2602_UNIFIED_AUTHORITY_REQUIRED")
    payload = _terminal_payload(authority, fence, record)
    report_hash = _hash_json(payload)
    now = authority._snapshot()
    with authority.lifecycle.write_transaction():
        intent = authority._verify_fence(
            authority.db, fence, now, allow_terminal_replay=True
        )
        if intent["terminal_id"] is not None:
            return _verified_from_rows(
                authority, fence, record, replayed=True
            )
        attempt = authority.db.execute(
            "SELECT * FROM durable_attempts WHERE attempt_id=?",
            (record.attempt_id,),
        ).fetchone()
        if attempt is None or int(attempt["generation"]) != record.attempt_generation:
            raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_ATTEMPT_MISMATCH")
        current = ExecutionState(str(attempt["state"]))
        if current is not ExecutionState.PLANNED:
            raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_NON_PAPER_STATE")
        reservation_id = attempt["reservation_id"]
        reservation = authority.db.execute(
            "SELECT state FROM durable_reservations WHERE attempt_id=?",
            (record.attempt_id,),
        ).fetchone()
        if reservation_id is None or reservation is None or str(reservation["state"]) != "active":
            raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_ACTIVE_RESERVATION_REQUIRED")

        revision = int(attempt["revision"])
        lifecycle_event_id = authority.lifecycle._event(
            attempt_id=str(record.attempt_id),
            sequence=revision + 1,
            idempotency_key=f"mpr2602-paper-terminal:{fence.intent_id}",
            event_type="mpr2602_paper_terminal_committed",
            from_state=current,
            to_state=current,
            reason=MPR2602_PAPER_SUCCESS_REASON,
            payload={
                "report_hash": report_hash,
                "prepared_plan_hash": payload["prepared_plan_hash"],
                "provider_evidence_hash": record.provider_evidence_hash,
                "paper_only": True,
            },
            topic=None,
            now=now.utc_ns,
        )
        updated = authority.db.execute(
            "UPDATE durable_attempts SET revision=?,terminal_at_ns=?,updated_at_ns=? "
            "WHERE attempt_id=? AND revision=?",
            (revision + 1, now.utc_ns, now.utc_ns, record.attempt_id, revision),
        )
        if updated.rowcount != 1:
            raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_REVISION_CONFLICT")
        authority._terminalize_reservation(
            authority.db,
            attempt_id=str(record.attempt_id),
            reservation_id=str(reservation_id),
            state=ReservationTerminalState.RELEASED,
            reason_code=MPR2602_PAPER_SUCCESS_REASON,
            now_utc_ns=now.utc_ns,
        )
        commit: TerminalCommit = authority._insert_terminal_and_outbox(
            authority.db,
            row=intent,
            outcome=MPR2602_PAPER_SUCCESS,
            reason_code=MPR2602_PAPER_SUCCESS_REASON,
            report_hash=report_hash,
            payload=payload,
            now=now,
            lifecycle_event_id=lifecycle_event_id,
            reservation_id=str(reservation_id),
            reservation_state=ReservationTerminalState.RELEASED,
            topic="paper.attempt.terminal",
        )
        if commit.replayed:
            raise UnifiedAuthorityError("MPR2602_PAPER_TERMINAL_UNEXPECTED_REPLAY")
    return _verified_from_rows(authority, fence, record, replayed=False)


def verify_committed_paper_success(
    authority: UnifiedLifecycleAuthority,
    fence: AuthorityFence,
    record: ExactAttemptRuntimeRecord,
) -> VerifiedPaperTerminal:
    """Verify a prior terminal without mutating state or repeating provider/RPC work."""
    return _verified_from_rows(authority, fence, record, replayed=True)


class DurableCompletedExactAttemptRuntime:
    """Production A2 wrapper that commits and verifies the paper terminal."""

    def __init__(
        self,
        *,
        orchestrator: ExactPaperAttemptOrchestrator,
        authority: UnifiedLifecycleAuthority,
    ) -> None:
        if type(orchestrator) is not ExactPaperAttemptOrchestrator:
            raise TypeError("MPR2602_CANONICAL_EXACT_ATTEMPT_ORCHESTRATOR_REQUIRED")
        if orchestrator.authority is not authority:
            raise ValueError("MPR2602_COMPLETION_AUTHORITY_MISMATCH")
        self.orchestrator = orchestrator
        self.authority = authority

    async def __call__(
        self, cycle_id: str, items: Sequence[object]
    ) -> ExactAttemptRuntimeReport:
        typed = tuple(items)
        if not all(isinstance(item, ExactAttemptRuntimeItem) for item in typed):
            raise TypeError("MPR2602_COMPLETION_TYPED_ITEMS_REQUIRED")
        runtime_items = tuple(item for item in typed if isinstance(item, ExactAttemptRuntimeItem))
        report = await run_exact_attempt_runtime_cycle(
            cycle_id=cycle_id,
            orchestrator=self.orchestrator,
            items=runtime_items,
        )
        if report.status is A2PaperOutcomeStatus.EXACT_ATTEMPT_READY_FOR_HANDOFF:
            handoff = report.records[-1]
            fence = self._fence_for_record(handoff)
            terminal = commit_verified_paper_success(self.authority, fence, handoff)
            return self._success_report(report, handoff, terminal)
        replay = next(
            (
                record
                for record in report.records
                if record.reason_code == MPR2602_REPLAY_REQUIRED
            ),
            None,
        )
        if replay is not None:
            fence = self._fence_for_record(replay)
            terminal = verify_committed_paper_success(self.authority, fence, replay)
            return self._success_report(report, replay, terminal)
        return report

    def _fence_for_record(self, record: ExactAttemptRuntimeRecord) -> AuthorityFence:
        if record.attempt_id is None:
            raise UnifiedAuthorityError("MPR2602_COMPLETION_ATTEMPT_ID_MISSING")
        row = self.authority.db.execute(
            "SELECT * FROM pr02_intents WHERE intent_kind=? AND attempt_id=? "
            "AND attempt_generation=?",
            (
                IntentKind.PAPER_ATTEMPT.value,
                record.attempt_id,
                record.attempt_generation,
            ),
        ).fetchone()
        if row is None:
            raise UnifiedAuthorityError("MPR2602_COMPLETION_INTENT_MISSING")
        return AuthorityFence(
            intent_id=str(row["intent_id"]),
            owner_id=str(row["owner_id"]),
            fencing_token=int(row["fencing_token"]),
            boot_id=str(row["boot_id"]),
            process_generation=int(row["process_generation"]),
            release_digest=str(row["release_digest"]),
            policy_bundle_hash=str(row["policy_bundle_hash"]),
            expires_utc_ns=int(row["expires_utc_ns"]),
            expires_monotonic_ns=int(row["expires_monotonic_ns"]),
            replayed=row["terminal_id"] is not None,
        )

    @staticmethod
    def _success_report(
        report: ExactAttemptRuntimeReport,
        source: ExactAttemptRuntimeRecord,
        terminal: VerifiedPaperTerminal,
    ) -> ExactAttemptRuntimeReport:
        completed = replace(
            source,
            status=A2PaperOutcomeStatus.RECONCILED_PAPER_SUCCESS,
            reason_code=MPR2602_PAPER_SUCCESS_REASON,
            failure_stage=FailureStage.NONE,
            provider_evidence_hash=terminal.provider_evidence_hash,
            result_hash=terminal.report_hash,
            attempt_id=terminal.attempt_id,
            message_hash=terminal.message_hash,
            planner_digest=terminal.planner_digest,
            reconciliation_hash=terminal.reconciliation_hash,
            sender_imported=False,
            submission_allowed=False,
        )
        records = tuple(
            completed if item.item_index == source.item_index else item
            for item in report.records
        )
        return ExactAttemptRuntimeReport(
            cycle_id=report.cycle_id,
            status=A2PaperOutcomeStatus.RECONCILED_PAPER_SUCCESS,
            terminal_reason=MPR2602_PAPER_SUCCESS_REASON,
            records=records,
            sender_imported=False,
            submission_allowed=False,
            live_enabled=False,
        )


__all__ = [
    "DurableCompletedExactAttemptRuntime",
    "MPR2602_PAPER_SUCCESS",
    "MPR2602_PAPER_SUCCESS_REASON",
    "MPR2602_PAPER_TERMINAL_SCHEMA",
    "VerifiedPaperTerminal",
    "commit_verified_paper_success",
    "verify_committed_paper_success",
]

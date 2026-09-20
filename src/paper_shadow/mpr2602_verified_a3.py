"""A3 paper service that accepts success only with a verified PR-02 terminal."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
import time

from src.config.runtime import RuntimeConfig
from src.durability.unified_authority_pr02 import (
    AuthorityFence,
    UnifiedAuthorityError,
    UnifiedLifecycleAuthority,
)
from src.paper_shadow.a2_exact_attempt_runtime import (
    A2PaperOutcomeStatus,
    ExactAttemptRuntimeRecord,
    FailureStage,
)
from src.paper_shadow.durable_service_a3 import (
    A3RuntimeCycle,
    ExactAttemptBatchSource,
    InstalledDurablePaperService,
    InstalledPaperServiceConfig,
)
from src.paper_shadow.mpr2602_completion import verify_committed_paper_success

A3_UNVERIFIED_PAPER_TERMINAL = "blocked_a3_verified_attempt_terminal_missing"


def _projection_int(value: object, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} must be a non-bool integer")
    return value


def _record_from_projection(payload: Mapping[str, object]) -> ExactAttemptRuntimeRecord:
    return ExactAttemptRuntimeRecord(
        item_index=_projection_int(payload["item_index"], "item_index"),
        attempt_generation=_projection_int(
            payload["attempt_generation"], "attempt_generation"
        ),
        status=A2PaperOutcomeStatus(str(payload["status"])),
        reason_code=str(payload["reason_code"]),
        failure_stage=FailureStage(str(payload["failure_stage"])),
        provider_evidence_hash=str(payload["provider_evidence_hash"]),
        result_hash=str(payload["result_hash"]),
        exact_request_hash=str(payload["exact_request_hash"]),
        operation_id=str(payload["operation_id"]),
        producer_identity=str(payload["producer_identity"]),
        attempt_id=(
            None if payload.get("attempt_id") is None else str(payload["attempt_id"])
        ),
        message_hash=(
            None if payload.get("message_hash") is None else str(payload["message_hash"])
        ),
        planner_digest=(
            None
            if payload.get("planner_digest") is None
            else str(payload["planner_digest"])
        ),
        reconciliation_hash=(
            None
            if payload.get("reconciliation_hash") is None
            else str(payload["reconciliation_hash"])
        ),
        sender_imported=bool(payload.get("sender_imported", False)),
        submission_allowed=bool(payload.get("submission_allowed", False)),
    )


class VerifiedTerminalInstalledPaperService(InstalledDurablePaperService):
    """Require durable terminal replay before projecting paper success."""

    async def _run_a2_cycle(self, cycle_id, sequence, batch, *, remaining=None):
        report = await super()._run_a2_cycle(
            cycle_id, sequence, batch, remaining=remaining
        )
        if report.status.value != A2PaperOutcomeStatus.RECONCILED_PAPER_SUCCESS.value:
            return report
        success = tuple(
            record
            for record in report.records
            if record.get("status")
            == A2PaperOutcomeStatus.RECONCILED_PAPER_SUCCESS.value
        )
        if not success:
            return self._indeterminate_report(
                cycle_id, sequence, batch.evidence, A3_UNVERIFIED_PAPER_TERMINAL
            )
        try:
            for record_payload in success:
                source = _record_from_projection(record_payload)
                if source.attempt_id is None:
                    raise UnifiedAuthorityError(
                        "MPR2602_A3_TERMINAL_ATTEMPT_ID_MISSING"
                    )
                row = self.authority.db.execute(
                    "SELECT * FROM pr02_intents WHERE intent_kind='paper_attempt' "
                    "AND attempt_id=? AND attempt_generation=?",
                    (source.attempt_id, source.attempt_generation),
                ).fetchone()
                if row is None:
                    raise UnifiedAuthorityError("MPR2602_A3_TERMINAL_INTENT_MISSING")
                fence = AuthorityFence(
                    intent_id=str(row["intent_id"]),
                    owner_id=str(row["owner_id"]),
                    fencing_token=int(row["fencing_token"]),
                    boot_id=str(row["boot_id"]),
                    process_generation=int(row["process_generation"]),
                    release_digest=str(row["release_digest"]),
                    policy_bundle_hash=str(row["policy_bundle_hash"]),
                    expires_utc_ns=int(row["expires_utc_ns"]),
                    expires_monotonic_ns=int(row["expires_monotonic_ns"]),
                    replayed=True,
                )
                verify_committed_paper_success(self.authority, fence, source)
        except (KeyError, TypeError, ValueError, UnifiedAuthorityError):
            return self._indeterminate_report(
                cycle_id, sequence, batch.evidence, A3_UNVERIFIED_PAPER_TERMINAL
            )
        return report


def build_verified_terminal_paper_service(
    config: RuntimeConfig,
    *,
    db_path: Path | str,
    batch_source: ExactAttemptBatchSource,
    runtime_cycle: A3RuntimeCycle,
    authority: UnifiedLifecycleAuthority,
    clock_ns: Callable[[], int] = time.time_ns,
) -> VerifiedTerminalInstalledPaperService:
    return VerifiedTerminalInstalledPaperService(
        config,
        InstalledPaperServiceConfig(db_path=Path(db_path)),
        batch_source=batch_source,
        runtime_cycle=runtime_cycle,
        clock_ns=clock_ns,
        authority=authority,
    )


__all__ = [
    "A3_UNVERIFIED_PAPER_TERMINAL",
    "VerifiedTerminalInstalledPaperService",
    "build_verified_terminal_paper_service",
]

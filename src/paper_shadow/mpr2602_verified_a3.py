"""A3 paper service that accepts success only with a verified PR-02 terminal."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import time

from src.config.runtime import RuntimeConfig
from src.durability.unified_authority_pr02 import UnifiedAuthorityError, UnifiedLifecycleAuthority
from src.paper_shadow.a2_exact_attempt_runtime import A2PaperOutcomeStatus
from src.paper_shadow.durable_service_a3 import (
    A3RuntimeCycle,
    ExactAttemptBatchSource,
    InstalledDurablePaperService,
    InstalledPaperServiceConfig,
)
from src.paper_shadow.mpr2602_completion import verify_committed_paper_success

A3_UNVERIFIED_PAPER_TERMINAL = "blocked_a3_verified_attempt_terminal_missing"


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
            if record.get("status") == A2PaperOutcomeStatus.RECONCILED_PAPER_SUCCESS.value
        )
        if not success:
            return self._indeterminate_report(
                cycle_id, sequence, batch.evidence, A3_UNVERIFIED_PAPER_TERMINAL
            )
        try:
            for record_payload in success:
                attempt_id = str(record_payload.get("attempt_id") or "")
                generation = int(record_payload.get("attempt_generation") or 0)
                row = self.authority.db.execute(
                    "SELECT * FROM pr02_intents WHERE intent_kind='paper_attempt' "
                    "AND attempt_id=? AND attempt_generation=?",
                    (attempt_id, generation),
                ).fetchone()
                if row is None:
                    raise UnifiedAuthorityError("MPR2602_A3_TERMINAL_INTENT_MISSING")
                # Reuse the canonical A2 record from the runtime report rather than
                # trusting the JSON compatibility projection.
                source = next(
                    item
                    for item in getattr(report, "records", ())
                    if item.attempt_id == attempt_id
                    and item.attempt_generation == generation
                    and item.status is A2PaperOutcomeStatus.RECONCILED_PAPER_SUCCESS
                )
                from src.durability.unified_authority_pr02 import AuthorityFence

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
        except (KeyError, StopIteration, TypeError, ValueError, UnifiedAuthorityError):
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

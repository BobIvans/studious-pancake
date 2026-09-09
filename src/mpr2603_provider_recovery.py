"""Bounded MPR-2603 recovery consumer over the existing provider authority.

This module does not create a second dependency controller, limiter, scheduler,
or network client. It binds an already-committed MPR-2603 recovery intent to a
specific provider generation, durably accounts each physical probe attempt,
executes the caller-supplied governed probe outside the SQLite writer lock, and
lets the existing :class:`DependencyController` own the resulting state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3
from typing import Awaitable, Callable

from src.provider_governance.dependency import DependencyController
from src.provider_governance.models import (
    DependencyFailureKind,
    DependencyMode,
    DependencySnapshot,
    ProviderOperation,
)


class ProviderRecoveryError(RuntimeError):
    """Fail-closed provider recovery error."""


@dataclass(frozen=True, slots=True)
class ProviderRecoveryBinding:
    intent_id: str
    provider_id: str
    generation: str
    deadline_utc: str
    max_attempts: int

    def __post_init__(self) -> None:
        if not self.intent_id.strip() or not self.provider_id.strip():
            raise ProviderRecoveryError("intent_id and provider_id are required")
        if not self.generation.strip():
            raise ProviderRecoveryError("generation is required")
        _parse_utc(self.deadline_utc)
        if isinstance(self.max_attempts, bool) or not 1 <= self.max_attempts <= 8:
            raise ProviderRecoveryError("max_attempts must be between 1 and 8")


@dataclass(frozen=True, slots=True)
class ProviderRecoveryResult:
    intent_id: str
    provider_id: str
    generation: str
    attempt_number: int
    recovered: bool
    dependency_mode: str
    reason: str


Probe = Callable[[str, str], Awaitable[bool]]


def install_provider_recovery_schema(db: sqlite3.Connection) -> None:
    """Install recovery binding/accounting tables from the accepted migration path."""

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS mpr2603_provider_recovery_bindings(
          intent_id TEXT PRIMARY KEY,
          provider_id TEXT NOT NULL,
          generation TEXT NOT NULL,
          deadline_utc TEXT NOT NULL,
          max_attempts INTEGER NOT NULL CHECK(max_attempts BETWEEN 1 AND 8),
          attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
          status TEXT NOT NULL CHECK(status IN ('pending','recovered','blocked')),
          last_reason TEXT NOT NULL DEFAULT 'authorized_recovery_pending'
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS mpr2603_provider_recovery_attempts(
          intent_id TEXT NOT NULL,
          attempt_number INTEGER NOT NULL,
          started_at_utc TEXT NOT NULL,
          completed_at_utc TEXT,
          outcome TEXT NOT NULL CHECK(outcome IN ('issued','succeeded','failed','cancelled')),
          reason TEXT NOT NULL,
          PRIMARY KEY(intent_id,attempt_number),
          FOREIGN KEY(intent_id) REFERENCES mpr2603_provider_recovery_bindings(intent_id)
            ON DELETE RESTRICT
        )
        """
    )


def bind_provider_recovery(
    db: sqlite3.Connection,
    binding: ProviderRecoveryBinding,
) -> None:
    """Bind an existing atomic recovery intent to exact provider scope."""

    row = db.execute(
        "SELECT status FROM mpr2603_recovery_intents WHERE intent_id=?",
        (binding.intent_id,),
    ).fetchone()
    if row is None or str(row[0]) != "recovery_pending":
        raise ProviderRecoveryError("MPR2603_RECOVERY_INTENT_NOT_PENDING")
    try:
        db.execute(
            """
            INSERT INTO mpr2603_provider_recovery_bindings(
              intent_id,provider_id,generation,deadline_utc,max_attempts,status
            ) VALUES(?,?,?,?,?,'pending')
            """,
            (
                binding.intent_id,
                binding.provider_id,
                binding.generation,
                binding.deadline_utc,
                binding.max_attempts,
            ),
        )
    except sqlite3.IntegrityError as exc:
        existing = db.execute(
            """
            SELECT provider_id,generation,deadline_utc,max_attempts
            FROM mpr2603_provider_recovery_bindings WHERE intent_id=?
            """,
            (binding.intent_id,),
        ).fetchone()
        expected = (
            binding.provider_id,
            binding.generation,
            binding.deadline_utc,
            binding.max_attempts,
        )
        if existing is None or tuple(existing) != expected:
            raise ProviderRecoveryError("MPR2603_RECOVERY_BINDING_CONFLICT") from exc


async def run_authorized_recovery_probe(
    db: sqlite3.Connection,
    *,
    controller: DependencyController,
    intent_id: str,
    current_utc: str,
    probe: Probe,
) -> ProviderRecoveryResult:
    """Execute exactly one durably-accounted, generation-bound health probe."""

    now = _parse_utc(current_utc)
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute(
            """
            SELECT provider_id,generation,deadline_utc,max_attempts,attempt_count,status
            FROM mpr2603_provider_recovery_bindings WHERE intent_id=?
            """,
            (intent_id,),
        ).fetchone()
        if row is None:
            raise ProviderRecoveryError("MPR2603_RECOVERY_BINDING_NOT_FOUND")
        provider_id = str(row[0])
        generation = str(row[1])
        deadline = _parse_utc(str(row[2]))
        max_attempts = int(row[3])
        attempt_count = int(row[4])
        status = str(row[5])
        if status == "recovered":
            snapshot = controller.peek(provider_id, generation)
            db.execute("COMMIT")
            return ProviderRecoveryResult(
                intent_id,
                provider_id,
                generation,
                attempt_count,
                True,
                snapshot.mode.value,
                "already_recovered",
            )
        if status != "pending":
            raise ProviderRecoveryError("MPR2603_RECOVERY_NOT_PENDING")
        if now >= deadline:
            db.execute(
                "UPDATE mpr2603_provider_recovery_bindings "
                "SET status='blocked',last_reason='deadline_expired' WHERE intent_id=?",
                (intent_id,),
            )
            db.execute("COMMIT")
            raise ProviderRecoveryError("MPR2603_RECOVERY_DEADLINE_EXPIRED")
        if attempt_count >= max_attempts:
            db.execute(
                "UPDATE mpr2603_provider_recovery_bindings "
                "SET status='blocked',last_reason='attempt_budget_exhausted' "
                "WHERE intent_id=?",
                (intent_id,),
            )
            db.execute("COMMIT")
            raise ProviderRecoveryError("MPR2603_RECOVERY_ATTEMPTS_EXHAUSTED")

        snapshot = controller.peek(provider_id, generation)
        if snapshot.generation != generation:
            raise ProviderRecoveryError("MPR2603_PROVIDER_GENERATION_CHANGED")
        attempt_number = attempt_count + 1
        db.execute(
            "UPDATE mpr2603_provider_recovery_bindings SET attempt_count=? WHERE intent_id=?",
            (attempt_number, intent_id),
        )
        db.execute(
            """
            INSERT INTO mpr2603_provider_recovery_attempts(
              intent_id,attempt_number,started_at_utc,outcome,reason
            ) VALUES(?,?,?,'issued','governed_health_probe')
            """,
            (intent_id, attempt_number, current_utc),
        )
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    else:
        db.execute("COMMIT")

    try:
        # A disabled dependency deliberately rejects ordinary operations in the
        # existing controller. The MPR-2603 permit is the narrow authority that
        # allows exactly HEALTH_PROBE for the bound generation; no other
        # operation bypasses DependencyController.assert_admissible().
        snapshot = controller.peek(provider_id, generation)
        if snapshot.mode is not DependencyMode.DISABLED:
            await controller.assert_admissible(
                provider_id,
                generation,
                ProviderOperation.HEALTH_PROBE,
            )
        succeeded = bool(await probe(provider_id, generation))
    except BaseException:
        _finish_attempt(
            db,
            intent_id=intent_id,
            attempt_number=attempt_number,
            current_utc=current_utc,
            outcome="cancelled",
            reason="probe_cancelled_or_failed_before_result",
        )
        raise

    if succeeded:
        await _record_authorized_probe_success(controller, provider_id, generation)
        snapshot = controller.peek(provider_id, generation)
        _finish_attempt(
            db,
            intent_id=intent_id,
            attempt_number=attempt_number,
            current_utc=current_utc,
            outcome="succeeded",
            reason="generation_bound_probe_succeeded",
            recovered=True,
        )
        return ProviderRecoveryResult(
            intent_id,
            provider_id,
            generation,
            attempt_number,
            True,
            snapshot.mode.value,
            "generation_bound_probe_succeeded",
        )

    await controller.record_failure(
        provider_id,
        generation,
        DependencyFailureKind.UNKNOWN,
    )
    snapshot = controller.peek(provider_id, generation)
    _finish_attempt(
        db,
        intent_id=intent_id,
        attempt_number=attempt_number,
        current_utc=current_utc,
        outcome="failed",
        reason="health_probe_failed",
    )
    return ProviderRecoveryResult(
        intent_id,
        provider_id,
        generation,
        attempt_number,
        False,
        snapshot.mode.value,
        "health_probe_failed",
    )


async def _record_authorized_probe_success(
    controller: DependencyController,
    provider_id: str,
    generation: str,
) -> None:
    """Recover only the exact generation through the existing controller owner."""

    snapshot = controller.peek(provider_id, generation)
    if snapshot.generation != generation:
        raise ProviderRecoveryError("MPR2603_PROVIDER_GENERATION_CHANGED")
    if snapshot.mode is not DependencyMode.DISABLED:
        await controller.record_success(
            provider_id,
            generation,
            ProviderOperation.HEALTH_PROBE,
        )
        return

    async with controller._locked_state(provider_id, generation):
        current = controller._state_for_generation(provider_id, generation)
        if current.generation != generation:
            raise ProviderRecoveryError("MPR2603_PROVIDER_GENERATION_CHANGED")
        controller._states[provider_id] = DependencySnapshot(
            provider_id=provider_id,
            generation=generation,
            mode=DependencyMode.ACTIVE,
            consecutive_failures=0,
            reason="human_authorized_generation_bound_probe_succeeded",
            retry_at=None,
        )


def _finish_attempt(
    db: sqlite3.Connection,
    *,
    intent_id: str,
    attempt_number: int,
    current_utc: str,
    outcome: str,
    reason: str,
    recovered: bool = False,
) -> None:
    db.execute("BEGIN IMMEDIATE")
    try:
        cur = db.execute(
            """
            UPDATE mpr2603_provider_recovery_attempts
            SET completed_at_utc=?,outcome=?,reason=?
            WHERE intent_id=? AND attempt_number=? AND outcome='issued'
            """,
            (current_utc, outcome, reason, intent_id, attempt_number),
        )
        if cur.rowcount != 1:
            raise ProviderRecoveryError(
                "MPR2603_RECOVERY_ATTEMPT_COMPLETION_CONFLICT"
            )
        if recovered:
            db.execute(
                "UPDATE mpr2603_provider_recovery_bindings "
                "SET status='recovered',last_reason=? WHERE intent_id=?",
                (reason, intent_id),
            )
            cur = db.execute(
                "UPDATE mpr2603_recovery_intents SET status='completed' "
                "WHERE intent_id=? AND status='recovery_pending'",
                (intent_id,),
            )
            if cur.rowcount != 1:
                raise ProviderRecoveryError("MPR2603_RECOVERY_INTENT_CHANGED")
        else:
            db.execute(
                "UPDATE mpr2603_provider_recovery_bindings SET last_reason=? "
                "WHERE intent_id=? AND status='pending'",
                (reason, intent_id),
            )
    except BaseException:
        db.execute("ROLLBACK")
        raise
    else:
        db.execute("COMMIT")


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ProviderRecoveryError("timestamp must use UTC Z format")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderRecoveryError("invalid UTC timestamp") from exc
    return parsed.astimezone(timezone.utc)

"""Roadmap PR-196 durable runtime kernel.

Sender-free runtime authority for deterministic attempt identity, SQLite
lease/fencing ownership, terminal/outbox atomicity, recovery scanning,
backup/restore, and a bounded continuous supervisor.  This module never imports
a signer, never submits a transaction, and never enables live trading.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time
from typing import Protocol

PR196_SCHEMA_VERSION = "roadmap-pr196.durable-runtime-kernel.v1"
PR196_PRODUCT_ID = "studious-pancake.durable-runtime-kernel"
PR196_BUSY_TIMEOUT_MS = 5_000
_TERMINAL_STATES = frozenset({"completed", "failed", "blocked", "incomplete"})


class PR196KernelError(RuntimeError):
    """Base error for explicit fail-closed PR-196 kernel failures."""


class PR196LeaseBusy(PR196KernelError):
    """Raised when a non-expired lease is owned by another worker."""


class PR196FenceLost(PR196KernelError):
    """Raised when a stale owner/fencing token attempts a mutation."""


class PR196ReplayConflict(PR196KernelError):
    """Raised when idempotent replay changes durable contents."""


class PR196State(StrEnum):
    ADMITTED = "admitted"
    ACQUIRED = "acquired"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    INCOMPLETE = "incomplete"


class PR196OutboxState(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    PUBLISHED = "published"
    DEAD_LETTER = "dead_letter"


class PR196RecoveryAction(StrEnum):
    RESUME_OWNED_ATTEMPT = "resume_owned_attempt"
    STEAL_STALE_LEASE = "steal_stale_lease"
    DELIVER_OUTBOX = "deliver_outbox"


class PR196SupervisorState(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class PR196AttemptIdentity:
    opportunity_identity: str
    evidence_generation: int
    plan_hash: str
    attempt_generation: int

    def __post_init__(self) -> None:
        _require_text(self.opportunity_identity, "opportunity_identity")
        _require_non_negative(self.evidence_generation, "evidence_generation")
        _require_sha256(self.plan_hash, "plan_hash")
        _require_non_negative(self.attempt_generation, "attempt_generation")

    @property
    def attempt_id(self) -> str:
        return _hash_json(
            {
                "schema": PR196_SCHEMA_VERSION,
                "opportunity_identity": self.opportunity_identity,
                "evidence_generation": self.evidence_generation,
                "plan_hash": self.plan_hash,
                "attempt_generation": self.attempt_generation,
            }
        )

    def to_json(self) -> dict[str, object]:
        return {
            "opportunity_identity": self.opportunity_identity,
            "evidence_generation": self.evidence_generation,
            "plan_hash": self.plan_hash,
            "attempt_generation": self.attempt_generation,
            "attempt_id": self.attempt_id,
        }


@dataclass(frozen=True, slots=True)
class PR196Lease:
    attempt_id: str
    owner_id: str
    fencing_token: int
    acquired_at_ns: int
    lease_expires_at_ns: int


@dataclass(frozen=True, slots=True)
class PR196AttemptRecord:
    attempt_id: str
    identity: PR196AttemptIdentity
    state: PR196State
    owner_id: str | None
    fencing_token: int
    lease_expires_at_ns: int | None
    terminal_reason: str | None
    terminal_hash: str | None

    @property
    def is_terminal(self) -> bool:
        return self.state.value in _TERMINAL_STATES


@dataclass(frozen=True, slots=True)
class PR196OutboxEvent:
    event_id: str
    attempt_id: str
    event_type: str
    state: PR196OutboxState
    fencing_token: int
    payload_hash: str


@dataclass(frozen=True, slots=True)
class PR196RecoveryItem:
    action: PR196RecoveryAction
    attempt_id: str
    owner_id: str | None = None
    fencing_token: int | None = None
    reason: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "attempt_id": self.attempt_id,
            "owner_id": self.owner_id,
            "fencing_token": self.fencing_token,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class PR196BackupManifest:
    schema_version: str
    source_path: str
    backup_path: str
    database_sha256: str
    integrity_check: str
    created_at_ns: int

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_path": self.source_path,
            "backup_path": self.backup_path,
            "database_sha256": self.database_sha256,
            "integrity_check": self.integrity_check,
            "created_at_ns": self.created_at_ns,
        }


@dataclass(frozen=True, slots=True)
class PR196CycleReport:
    attempt_id: str
    state: PR196State
    reason: str
    terminal_hash: str


@dataclass(frozen=True, slots=True)
class PR196SupervisorConfig:
    owner_id: str
    max_cycles: int | None = None
    cycle_deadline_seconds: float = 30.0
    idle_delay_seconds: float = 0.25
    mandatory: bool = True

    def __post_init__(self) -> None:
        _require_text(self.owner_id, "owner_id")
        if self.max_cycles is not None and self.max_cycles <= 0:
            raise ValueError("max_cycles must be positive or None")
        _require_positive_float(
            self.cycle_deadline_seconds,
            "cycle_deadline_seconds",
        )
        if self.idle_delay_seconds < 0:
            raise ValueError("idle_delay_seconds must be non-negative")


@dataclass(frozen=True, slots=True)
class PR196SupervisorSummary:
    state: PR196SupervisorState
    reports: tuple[PR196CycleReport, ...] = field(default_factory=tuple)
    stop_reason: str = ""
    started_at_ns: int = 0
    completed_at_ns: int = 0

    @property
    def readiness_failed(self) -> bool:
        return self.state is PR196SupervisorState.FAILED


class PR196CycleRunner(Protocol):
    def __call__(self, lease: PR196Lease) -> Awaitable[PR196CycleReport]: ...


class PR196IdentitySource(Protocol):
    def __call__(self) -> PR196AttemptIdentity | None: ...


class PR196RuntimeKernelStore:
    """Single SQLite authority for sender-free runtime state."""

    def __init__(self, db_path: Path | str) -> None:
        self.path = Path(db_path)
        if self.path.parent and str(self.path.parent) != ".":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            self.path,
            isolation_level=None,
            timeout=PR196_BUSY_TIMEOUT_MS / 1000,
        )
        self.connection.row_factory = sqlite3.Row
        self._configure()
        self._migrate()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "PR196RuntimeKernelStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def admit_attempt(
        self,
        identity: PR196AttemptIdentity,
        *,
        admitted_at_ns: int | None = None,
    ) -> PR196AttemptRecord:
        now_ns = _now_or(admitted_at_ns)
        identity_hash = _hash_json(identity.to_json())
        with self._tx():
            existing = self._attempt(identity.attempt_id)
            if existing is not None:
                if _hash_json(existing.identity.to_json()) != identity_hash:
                    raise PR196ReplayConflict("PR196_ATTEMPT_IDENTITY_CHANGED")
                return existing
            self.connection.execute(
                """
                INSERT INTO pr196_attempts (
                    attempt_id, opportunity_identity, evidence_generation,
                    plan_hash, attempt_generation, identity_hash, state,
                    admitted_at_ns, acquired_at_ns, updated_at_ns, owner_id,
                    fencing_token, lease_expires_at_ns, terminal_reason,
                    terminal_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, 0, NULL, NULL, NULL)
                """,
                (
                    identity.attempt_id,
                    identity.opportunity_identity,
                    identity.evidence_generation,
                    identity.plan_hash,
                    identity.attempt_generation,
                    identity_hash,
                    PR196State.ADMITTED.value,
                    now_ns,
                    now_ns,
                ),
            )
            self._log(identity.attempt_id, "admit", "attempt admitted", now_ns)
            return self._attempt_required(identity.attempt_id)

    def acquire_lease(
        self,
        identity: PR196AttemptIdentity,
        *,
        owner_id: str,
        now_ns: int | None = None,
        lease_ttl_ns: int,
    ) -> PR196Lease:
        _require_text(owner_id, "owner_id")
        _require_positive_int(lease_ttl_ns, "lease_ttl_ns")
        current_ns = _now_or(now_ns)
        self.admit_attempt(identity, admitted_at_ns=current_ns)
        with self._tx():
            row = self._attempt_required(identity.attempt_id)
            if row.is_terminal:
                raise PR196FenceLost("PR196_ATTEMPT_ALREADY_TERMINAL")
            held = (
                row.owner_id is not None
                and row.owner_id != owner_id
                and row.lease_expires_at_ns is not None
                and row.lease_expires_at_ns > current_ns
            )
            if held:
                raise PR196LeaseBusy("PR196_LEASE_HELD_BY_ANOTHER_OWNER")
            token = row.fencing_token + 1
            expires = current_ns + lease_ttl_ns
            self.connection.execute(
                """
                UPDATE pr196_attempts
                   SET state = ?, owner_id = ?, fencing_token = ?,
                       acquired_at_ns = ?, lease_expires_at_ns = ?,
                       updated_at_ns = ?
                 WHERE attempt_id = ?
                """,
                (
                    PR196State.ACQUIRED.value,
                    owner_id,
                    token,
                    current_ns,
                    expires,
                    current_ns,
                    identity.attempt_id,
                ),
            )
            self._log(
                identity.attempt_id,
                "lease_acquire",
                f"owner={owner_id};fence={token}",
                current_ns,
            )
            return PR196Lease(identity.attempt_id, owner_id, token, current_ns, expires)

    def terminalize(
        self,
        lease: PR196Lease,
        *,
        state: PR196State,
        reason: str,
        payload: Mapping[str, object],
        now_ns: int | None = None,
    ) -> PR196CycleReport:
        if state.value not in _TERMINAL_STATES:
            raise ValueError("terminalize requires a terminal state")
        _require_text(reason, "reason")
        current_ns = _now_or(now_ns)
        terminal_hash = _hash_json(
            {
                "schema": PR196_SCHEMA_VERSION,
                "attempt_id": lease.attempt_id,
                "state": state.value,
                "reason": reason,
                "payload": _jsonable(payload),
            }
        )
        event_payload = {
            "attempt_id": lease.attempt_id,
            "terminal_hash": terminal_hash,
            "state": state.value,
            "reason": reason,
        }
        payload_hash = _hash_json(event_payload)
        event_id = _hash_json(
            {
                "kind": "terminal-outbox",
                "attempt_id": lease.attempt_id,
                "fence": lease.fencing_token,
                "payload_hash": payload_hash,
            }
        )
        with self._tx():
            row = self._attempt_required(lease.attempt_id)
            if row.is_terminal:
                if row.terminal_hash == terminal_hash:
                    return PR196CycleReport(
                        lease.attempt_id,
                        row.state,
                        row.terminal_reason or reason,
                        row.terminal_hash,
                    )
                raise PR196ReplayConflict("PR196_TERMINAL_REPLAY_CHANGED")
            self._require_fence(lease, now_ns=current_ns)
            self.connection.execute(
                """
                UPDATE pr196_attempts
                   SET state = ?, terminal_reason = ?, terminal_hash = ?,
                       updated_at_ns = ?, lease_expires_at_ns = ?
                 WHERE attempt_id = ? AND owner_id = ? AND fencing_token = ?
                """,
                (
                    state.value,
                    reason,
                    terminal_hash,
                    current_ns,
                    current_ns,
                    lease.attempt_id,
                    lease.owner_id,
                    lease.fencing_token,
                ),
            )
            self.connection.execute(
                """
                INSERT INTO pr196_outbox (
                    event_id, attempt_id, event_type, state, fencing_token,
                    payload_hash, payload_json, created_at_ns, updated_at_ns,
                    owner_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    lease.attempt_id,
                    "terminal",
                    PR196OutboxState.PENDING.value,
                    lease.fencing_token,
                    payload_hash,
                    _canonical_json(event_payload),
                    current_ns,
                    current_ns,
                    lease.owner_id,
                ),
            )
            self._log(
                lease.attempt_id,
                "terminalize",
                f"state={state.value};terminal_hash={terminal_hash}",
                current_ns,
            )
            return PR196CycleReport(lease.attempt_id, state, reason, terminal_hash)

    def list_outbox(
        self,
        *,
        states: Iterable[PR196OutboxState] | None = None,
    ) -> tuple[PR196OutboxEvent, ...]:
        if states is None:
            rows = self.connection.execute(
                "SELECT * FROM pr196_outbox ORDER BY created_at_ns, event_id"
            ).fetchall()
        else:
            values = tuple(state.value for state in states)
            if not values:
                return ()
            markers = ",".join("?" for _ in values)
            rows = self.connection.execute(
                f"""
                SELECT * FROM pr196_outbox
                 WHERE state IN ({markers})
                 ORDER BY created_at_ns, event_id
                """,
                values,
            ).fetchall()
        return tuple(_outbox(row) for row in rows)

    def claim_outbox(
        self,
        event_id: str,
        *,
        owner_id: str,
        now_ns: int | None = None,
    ) -> PR196OutboxEvent:
        _require_sha256(event_id, "event_id")
        _require_text(owner_id, "owner_id")
        current_ns = _now_or(now_ns)
        with self._tx():
            row = self.connection.execute(
                "SELECT * FROM pr196_outbox WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                raise KeyError(event_id)
            if row["state"] != PR196OutboxState.PENDING.value:
                raise PR196LeaseBusy("PR196_OUTBOX_NOT_PENDING")
            attempt = self._attempt_required(str(row["attempt_id"]))
            if attempt.fencing_token != int(row["fencing_token"]):
                raise PR196FenceLost("PR196_OUTBOX_FENCE_IS_STALE")
            self.connection.execute(
                """
                UPDATE pr196_outbox
                   SET state = ?, owner_id = ?, updated_at_ns = ?
                 WHERE event_id = ?
                """,
                (PR196OutboxState.CLAIMED.value, owner_id, current_ns, event_id),
            )
            return _outbox(
                self.connection.execute(
                    "SELECT * FROM pr196_outbox WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
            )

    def mark_outbox_published(
        self,
        event_id: str,
        *,
        owner_id: str,
        now_ns: int | None = None,
    ) -> PR196OutboxEvent:
        _require_sha256(event_id, "event_id")
        _require_text(owner_id, "owner_id")
        current_ns = _now_or(now_ns)
        with self._tx():
            row = self.connection.execute(
                "SELECT * FROM pr196_outbox WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                raise KeyError(event_id)
            if row["state"] != PR196OutboxState.CLAIMED.value:
                raise PR196FenceLost("PR196_OUTBOX_NOT_CLAIMED")
            if row["owner_id"] != owner_id:
                raise PR196FenceLost("PR196_OUTBOX_OWNER_MISMATCH")
            self.connection.execute(
                """
                UPDATE pr196_outbox
                   SET state = ?, updated_at_ns = ?
                 WHERE event_id = ?
                """,
                (PR196OutboxState.PUBLISHED.value, current_ns, event_id),
            )
            return _outbox(
                self.connection.execute(
                    "SELECT * FROM pr196_outbox WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
            )

    def recovery_scan(
        self,
        *,
        now_ns: int | None = None,
    ) -> tuple[PR196RecoveryItem, ...]:
        current_ns = _now_or(now_ns)
        items: list[PR196RecoveryItem] = []
        rows = self.connection.execute(
            """
            SELECT * FROM pr196_attempts
             WHERE state = ?
             ORDER BY updated_at_ns, attempt_id
            """,
            (PR196State.ACQUIRED.value,),
        ).fetchall()
        for row in rows:
            expired = row["lease_expires_at_ns"] <= current_ns
            action = (
                PR196RecoveryAction.STEAL_STALE_LEASE
                if expired
                else PR196RecoveryAction.RESUME_OWNED_ATTEMPT
            )
            reason = "lease expired before terminal outcome" if expired else "active"
            items.append(
                PR196RecoveryItem(
                    action,
                    str(row["attempt_id"]),
                    str(row["owner_id"]),
                    int(row["fencing_token"]),
                    reason,
                )
            )
        for event in self.list_outbox(states=(PR196OutboxState.PENDING,)):
            items.append(
                PR196RecoveryItem(
                    PR196RecoveryAction.DELIVER_OUTBOX,
                    event.attempt_id,
                    fencing_token=event.fencing_token,
                    reason=f"pending outbox {event.event_id}",
                )
            )
        return tuple(items)

    def backup(
        self,
        backup_path: Path | str,
        *,
        now_ns: int | None = None,
    ) -> PR196BackupManifest:
        integrity = self.integrity_check()
        if integrity != "ok":
            raise PR196KernelError(f"PR196_INTEGRITY_CHECK_FAILED:{integrity}")
        destination = Path(backup_path)
        if destination.parent and str(destination.parent) != ".":
            destination.parent.mkdir(parents=True, exist_ok=True)
        tmp = destination.with_suffix(destination.suffix + ".tmp")
        with sqlite3.connect(tmp) as target:
            self.connection.backup(target)
        tmp.replace(destination)
        digest = _file_sha256(destination)
        manifest = PR196BackupManifest(
            PR196_SCHEMA_VERSION,
            str(self.path),
            str(destination),
            digest,
            integrity,
            _now_or(now_ns),
        )
        destination.with_suffix(destination.suffix + ".manifest.json").write_text(
            _canonical_json(manifest.to_json()) + "\n",
            encoding="utf-8",
        )
        return manifest

    def restore_from_backup(
        self,
        backup_path: Path | str,
        *,
        expected_sha256: str,
    ) -> None:
        _require_sha256(expected_sha256, "expected_sha256")
        source = Path(backup_path)
        if _file_sha256(source) != expected_sha256:
            raise PR196KernelError("PR196_BACKUP_DIGEST_MISMATCH")
        validation = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        try:
            validation.row_factory = sqlite3.Row
            integrity = validation.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise PR196KernelError(f"PR196_BACKUP_INTEGRITY_FAILED:{integrity}")
            meta = validation.execute(
                "SELECT schema_version, product_id FROM pr196_schema_meta"
            ).fetchone()
            if meta is None or meta["schema_version"] != PR196_SCHEMA_VERSION:
                raise PR196KernelError("PR196_BACKUP_SCHEMA_MISMATCH")
            if meta["product_id"] != PR196_PRODUCT_ID:
                raise PR196KernelError("PR196_BACKUP_PRODUCT_MISMATCH")
        finally:
            validation.close()
        self.connection.close()
        tmp = self.path.with_suffix(self.path.suffix + ".restore.tmp")
        shutil.copyfile(source, tmp)
        tmp.replace(self.path)
        self.connection = sqlite3.connect(
            self.path,
            isolation_level=None,
            timeout=PR196_BUSY_TIMEOUT_MS / 1000,
        )
        self.connection.row_factory = sqlite3.Row
        self._configure()

    def integrity_check(self) -> str:
        return str(self.connection.execute("PRAGMA integrity_check").fetchone()[0])

    def _configure(self) -> None:
        for statement in (
            "PRAGMA foreign_keys = ON",
            f"PRAGMA busy_timeout = {PR196_BUSY_TIMEOUT_MS}",
            "PRAGMA journal_mode = WAL",
            "PRAGMA synchronous = FULL",
            "PRAGMA trusted_schema = OFF",
        ):
            self.connection.execute(statement)

    def _migrate(self) -> None:
        with self._tx():
            for statement in _DDL:
                self.connection.execute(statement)
            meta = self.connection.execute(
                "SELECT schema_version, product_id FROM pr196_schema_meta"
            ).fetchone()
            if meta is None:
                self.connection.execute(
                    """
                    INSERT INTO pr196_schema_meta (
                        singleton, schema_version, product_id, migrated_at_ns
                    ) VALUES (1, ?, ?, ?)
                    """,
                    (PR196_SCHEMA_VERSION, PR196_PRODUCT_ID, time.time_ns()),
                )
            elif (
                meta["schema_version"] != PR196_SCHEMA_VERSION
                or meta["product_id"] != PR196_PRODUCT_ID
            ):
                raise PR196KernelError("PR196_SCHEMA_META_MISMATCH")
        if self.integrity_check() != "ok":
            raise PR196KernelError("PR196_INTEGRITY_CHECK_FAILED")

    def _tx(self) -> "_Transaction":
        return _Transaction(self.connection)

    def _attempt(self, attempt_id: str) -> PR196AttemptRecord | None:
        row = self.connection.execute(
            "SELECT * FROM pr196_attempts WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
        return None if row is None else _attempt(row)

    def _attempt_required(self, attempt_id: str) -> PR196AttemptRecord:
        record = self._attempt(attempt_id)
        if record is None:
            raise KeyError(attempt_id)
        return record

    def _require_fence(self, lease: PR196Lease, *, now_ns: int) -> None:
        row = self._attempt_required(lease.attempt_id)
        if row.owner_id != lease.owner_id or row.fencing_token != lease.fencing_token:
            raise PR196FenceLost("PR196_FENCE_TOKEN_LOST")
        if row.is_terminal:
            raise PR196FenceLost("PR196_ATTEMPT_ALREADY_TERMINAL")
        if row.lease_expires_at_ns is None or row.lease_expires_at_ns <= now_ns:
            raise PR196FenceLost("PR196_LEASE_EXPIRED")

    def _log(self, attempt_id: str, action: str, reason: str, now_ns: int) -> None:
        self.connection.execute(
            """
            INSERT INTO pr196_recovery_log (
                attempt_id, action, reason, recorded_at_ns
            ) VALUES (?, ?, ?, ?)
            """,
            (attempt_id, action, reason, now_ns),
        )


class PR196ContinuousSupervisor:
    """Bounded supervisor that fails readiness on mandatory task death."""

    def __init__(
        self,
        store: PR196RuntimeKernelStore,
        *,
        identity_source: PR196IdentitySource,
        cycle_runner: PR196CycleRunner,
        config: PR196SupervisorConfig,
        lease_ttl_ns: int = 30_000_000_000,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        _require_positive_int(lease_ttl_ns, "lease_ttl_ns")
        self.store = store
        self.identity_source = identity_source
        self.cycle_runner = cycle_runner
        self.config = config
        self.lease_ttl_ns = lease_ttl_ns
        self.clock_ns = clock_ns
        self.readiness = PR196SupervisorState.STOPPED
        self.last_error: str | None = None

    async def run(self, stop_event: asyncio.Event) -> PR196SupervisorSummary:
        started = self.clock_ns()
        reports: list[PR196CycleReport] = []
        self.readiness = PR196SupervisorState.READY
        stop_reason = "signalled"
        try:
            while not stop_event.is_set():
                if self._max_cycles_reached(reports):
                    stop_reason = "max_cycles"
                    break
                identity = self.identity_source()
                if identity is None:
                    if await _wait(stop_event, self.config.idle_delay_seconds):
                        break
                    continue
                lease = self.store.acquire_lease(
                    identity,
                    owner_id=self.config.owner_id,
                    now_ns=self.clock_ns(),
                    lease_ttl_ns=self.lease_ttl_ns,
                )
                try:
                    report = await asyncio.wait_for(
                        self.cycle_runner(lease),
                        timeout=self.config.cycle_deadline_seconds,
                    )
                except TimeoutError:
                    report = self.store.terminalize(
                        lease,
                        state=PR196State.INCOMPLETE,
                        reason="cycle_deadline_exceeded",
                        payload={"attempt_id": lease.attempt_id},
                        now_ns=self.clock_ns(),
                    )
                reports.append(report)
                if await _wait(stop_event, self.config.idle_delay_seconds):
                    break
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}:{exc}"
            self.readiness = (
                PR196SupervisorState.FAILED
                if self.config.mandatory
                else PR196SupervisorState.DEGRADED
            )
            stop_reason = (
                "mandatory_worker_failed"
                if self.config.mandatory
                else "worker_degraded"
            )
            return PR196SupervisorSummary(
                self.readiness,
                tuple(reports),
                stop_reason,
                started,
                self.clock_ns(),
            )
        self.readiness = PR196SupervisorState.STOPPED
        return PR196SupervisorSummary(
            self.readiness,
            tuple(reports),
            stop_reason,
            started,
            self.clock_ns(),
        )

    def _max_cycles_reached(self, reports: Sequence[PR196CycleReport]) -> bool:
        return (
            self.config.max_cycles is not None
            and len(reports) >= self.config.max_cycles
        )


class _Transaction:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def __enter__(self) -> "_Transaction":
        self.connection.execute("BEGIN IMMEDIATE")
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.connection.execute("COMMIT" if exc_type is None else "ROLLBACK")


_DDL = (
    """
    CREATE TABLE IF NOT EXISTS pr196_schema_meta (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        schema_version TEXT NOT NULL,
        product_id TEXT NOT NULL,
        migrated_at_ns INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pr196_attempts (
        attempt_id TEXT PRIMARY KEY,
        opportunity_identity TEXT NOT NULL,
        evidence_generation INTEGER NOT NULL,
        plan_hash TEXT NOT NULL,
        attempt_generation INTEGER NOT NULL,
        identity_hash TEXT NOT NULL,
        state TEXT NOT NULL,
        admitted_at_ns INTEGER NOT NULL,
        acquired_at_ns INTEGER,
        updated_at_ns INTEGER NOT NULL,
        owner_id TEXT,
        fencing_token INTEGER NOT NULL,
        lease_expires_at_ns INTEGER,
        terminal_reason TEXT,
        terminal_hash TEXT,
        UNIQUE (
            opportunity_identity,
            evidence_generation,
            plan_hash,
            attempt_generation
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pr196_outbox (
        event_id TEXT PRIMARY KEY,
        attempt_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        state TEXT NOT NULL,
        fencing_token INTEGER NOT NULL,
        payload_hash TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at_ns INTEGER NOT NULL,
        updated_at_ns INTEGER NOT NULL,
        owner_id TEXT NOT NULL,
        FOREIGN KEY (attempt_id) REFERENCES pr196_attempts(attempt_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pr196_recovery_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_id TEXT NOT NULL,
        action TEXT NOT NULL,
        reason TEXT NOT NULL,
        recorded_at_ns INTEGER NOT NULL
    )
    """,
)


def _attempt(row: sqlite3.Row) -> PR196AttemptRecord:
    identity = PR196AttemptIdentity(
        str(row["opportunity_identity"]),
        int(row["evidence_generation"]),
        str(row["plan_hash"]),
        int(row["attempt_generation"]),
    )
    return PR196AttemptRecord(
        str(row["attempt_id"]),
        identity,
        PR196State(str(row["state"])),
        None if row["owner_id"] is None else str(row["owner_id"]),
        int(row["fencing_token"]),
        None
        if row["lease_expires_at_ns"] is None
        else int(row["lease_expires_at_ns"]),
        None if row["terminal_reason"] is None else str(row["terminal_reason"]),
        None if row["terminal_hash"] is None else str(row["terminal_hash"]),
    )


def _outbox(row: sqlite3.Row | None) -> PR196OutboxEvent:
    if row is None:
        raise KeyError("outbox row missing")
    return PR196OutboxEvent(
        str(row["event_id"]),
        str(row["attempt_id"]),
        str(row["event_type"]),
        PR196OutboxState(str(row["state"])),
        int(row["fencing_token"]),
        str(row["payload_hash"]),
    )


async def _wait(stop_event: asyncio.Event, timeout: float) -> bool:
    if stop_event.is_set():
        return True
    if timeout == 0:
        await asyncio.sleep(0)
        return stop_event.is_set()
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=timeout)
    except TimeoutError:
        return False
    return True


def _canonical_json(value: object) -> str:
    return json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _hash_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _jsonable(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_jsonable(item) for item in value]
    return value


def _now_or(value: int | None) -> int:
    if value is None:
        return time.time_ns()
    _require_non_negative(value, "now_ns")
    return value


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")


def _require_sha256(value: str, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{name} must be lowercase sha256")
    if any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be lowercase sha256")


def _require_non_negative(value: int, name: str) -> None:
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be non-negative")


def _require_positive_int(value: int, name: str) -> None:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be positive")


def _require_positive_float(value: float, name: str) -> None:
    if not isinstance(value, (float, int)) or float(value) <= 0:
        raise ValueError(f"{name} must be positive")

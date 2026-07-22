"""MEGA-PR A3 installed durable sender-free paper service.

The installed paper command now records one transactional SQLite service cycle.
The default source stays fail-closed until B3 provides verified exact-attempt
work; no sender, signer, live, RPC, or fake settlement surface is enabled here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

from src.config.runtime import RuntimeConfig
from src.paper_shadow.a2_exact_attempt_runtime import (
    A2PaperOutcomeStatus,
    ExactAttemptRuntimeReport,
)

A3_SCHEMA = "mega-pr-a3.installed-durable-paper-service.v1"
A3_DEFAULT_DB_PATH = Path(".runtime/paper-service.sqlite3")
A3_DEFAULT_OWNER_ID = "installed-durable-paper-service"
A3_B3_EVIDENCE_MISSING = "blocked_a3_b3_provider_evidence_missing"
A3_RUNTIME_UNWIRED = "blocked_a3_exact_attempt_runtime_unwired"
A3_RUNTIME_TIMEOUT = "blocked_a3_global_cycle_deadline_exceeded"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS a3_paper_service_cycles(
 cycle_id TEXT PRIMARY KEY,
 run_id TEXT NOT NULL,
 sequence INTEGER NOT NULL CHECK(sequence>=1),
 schema_version TEXT NOT NULL,
 status TEXT NOT NULL,
 terminal_reason TEXT NOT NULL,
 ready_for_next_cycle INTEGER NOT NULL CHECK(ready_for_next_cycle IN (0,1)),
 provider_evidence_hash TEXT NOT NULL,
 report_hash TEXT NOT NULL,
 source_surface TEXT NOT NULL,
 owner_id TEXT NOT NULL,
 fencing_token INTEGER NOT NULL CHECK(fencing_token>=1),
 lease_expires_at_ns INTEGER NOT NULL,
 started_at_ns INTEGER NOT NULL,
 completed_at_ns INTEGER NOT NULL,
 sender_imported INTEGER NOT NULL CHECK(sender_imported IN (0,1)),
 submission_allowed INTEGER NOT NULL CHECK(submission_allowed IN (0,1)),
 live_enabled INTEGER NOT NULL CHECK(live_enabled IN (0,1)),
 report_json TEXT NOT NULL,
 UNIQUE(run_id, sequence)
);
CREATE TABLE IF NOT EXISTS a3_paper_service_outbox(
 outbox_id INTEGER PRIMARY KEY,
 cycle_id TEXT NOT NULL UNIQUE
  REFERENCES a3_paper_service_cycles(cycle_id) ON DELETE RESTRICT,
 topic TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending',
 owner_id TEXT NOT NULL,
 fencing_token INTEGER NOT NULL CHECK(fencing_token>=1),
 created_at_ns INTEGER NOT NULL,
 completed_at_ns INTEGER
);
"""


class A3PaperServiceStatus(StrEnum):
    NO_TRADE = "NO_TRADE"
    BLOCKED = "BLOCKED"
    SIMULATION_FAILED = "SIMULATION_FAILED"
    RECONCILED_PAPER_SUCCESS = "RECONCILED_PAPER_SUCCESS"
    RECONCILED_PAPER_FAILURE = "RECONCILED_PAPER_FAILURE"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True, slots=True)
class A3ProviderEvidenceState:
    """B3 evidence admission state consumed by the installed A3 service."""

    provider_evidence_hash: str
    ready: bool
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _is_sha256(self.provider_evidence_hash):
            raise ValueError("provider_evidence_hash must be lowercase sha256")
        if self.ready and self.blockers:
            raise ValueError("ready provider evidence cannot carry blockers")
        if not self.ready and not self.blockers:
            raise ValueError("blocked provider evidence needs a reason")
        object.__setattr__(self, "blockers", _dedupe(self.blockers))

    @classmethod
    def missing_b3(cls, config: RuntimeConfig) -> "A3ProviderEvidenceState":
        payload = {
            "schema": A3_SCHEMA,
            "configuration": _safe_config_fingerprint(config),
            "reason": A3_B3_EVIDENCE_MISSING,
        }
        return cls(
            provider_evidence_hash=_hash_json(payload),
            ready=False,
            blockers=(A3_B3_EVIDENCE_MISSING,),
        )

    def to_json(self) -> dict[str, object]:
        return {
            "provider_evidence_hash": self.provider_evidence_hash,
            "ready": self.ready,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class A3ExactAttemptBatch:
    """Exact-attempt work admitted into one durable service cycle."""

    evidence: A3ProviderEvidenceState
    items: tuple[object, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))


@dataclass(frozen=True, slots=True)
class InstalledPaperServiceConfig:
    db_path: Path = A3_DEFAULT_DB_PATH
    run_id: str = "installed-paper-service"
    source_surface: str = "installed-cli"
    owner_id: str = A3_DEFAULT_OWNER_ID
    cycle_deadline_seconds: float = 30.0
    lease_ttl_ns: int = 30_000_000_000

    def __post_init__(self) -> None:
        object.__setattr__(self, "db_path", Path(self.db_path))
        if not self.run_id.strip():
            raise ValueError("run_id is required")
        if not self.source_surface.strip() or not self.owner_id.strip():
            raise ValueError("source_surface and owner_id are required")
        if self.cycle_deadline_seconds <= 0:
            raise ValueError("cycle_deadline_seconds must be positive")
        if self.lease_ttl_ns <= 0:
            raise ValueError("lease_ttl_ns must be positive")


@dataclass(frozen=True, slots=True)
class InstalledDurablePaperServiceReport:
    cycle_id: str
    status: A3PaperServiceStatus
    terminal_reason: str
    db_path: str
    provider_evidence_hash: str
    report_hash: str
    ready_for_next_cycle: bool
    sequence: int
    sender_imported: bool = False
    submission_allowed: bool = False
    live_enabled: bool = False
    source_surface: str = "installed-cli"
    records: tuple[Mapping[str, object], ...] = field(default_factory=tuple)
    b3_blockers: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.live_enabled:
            raise ValueError("A3 service cannot enable live")
        if self.sender_imported or self.submission_allowed:
            if self.status is not A3PaperServiceStatus.INDETERMINATE:
                raise ValueError(
                    "unsafe sender/submission evidence must be indeterminate"
                )
        object.__setattr__(self, "records", _record_tuple(self.records))
        object.__setattr__(self, "b3_blockers", _dedupe(self.b3_blockers))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": A3_SCHEMA,
            "cycle_id": self.cycle_id,
            "sequence": self.sequence,
            "status": self.status.value,
            "terminal_reason": self.terminal_reason,
            "db_path": self.db_path,
            "provider_evidence_hash": self.provider_evidence_hash,
            "report_hash": self.report_hash,
            "ready_for_next_cycle": self.ready_for_next_cycle,
            "sender_imported": self.sender_imported,
            "submission_allowed": self.submission_allowed,
            "live_enabled": self.live_enabled,
            "source_surface": self.source_surface,
            "b3_blockers": list(self.b3_blockers),
            "records": [dict(item) for item in self.records],
        }


ExactAttemptBatchSource = Callable[[], A3ExactAttemptBatch]
A3RuntimeCycle = Callable[[str, Sequence[object]], Awaitable[ExactAttemptRuntimeReport]]


class InstalledDurablePaperService:
    """One installed, transactional, sender-free paper-mode service."""

    def __init__(
        self,
        config: RuntimeConfig,
        service_config: InstalledPaperServiceConfig | None = None,
        *,
        batch_source: ExactAttemptBatchSource | None = None,
        runtime_cycle: A3RuntimeCycle | None = None,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self.runtime_config = config
        self.config = service_config or InstalledPaperServiceConfig()
        self.batch_source = batch_source or self._default_blocked_batch
        self.runtime_cycle = runtime_cycle
        self.clock_ns = clock_ns
        self.db = _connect(self.config.db_path)
        self.db.executescript(_SCHEMA)

    async def run_once(self) -> InstalledDurablePaperServiceReport:
        sequence = self._next_sequence()
        started_at_ns = self.clock_ns()
        cycle_id = self._cycle_id(sequence, started_at_ns)
        batch = self.batch_source()
        report = await self._report_for_batch(cycle_id, sequence, batch)
        self._commit_report(
            report,
            started_at_ns=started_at_ns,
            completed_at_ns=self.clock_ns(),
        )
        return report

    def recovery_state(self) -> tuple[Mapping[str, object], ...]:
        rows = self.db.execute(
            "SELECT cycle_id,status,terminal_reason,owner_id,fencing_token,"
            "lease_expires_at_ns FROM a3_paper_service_cycles "
            "ORDER BY sequence"
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def _default_blocked_batch(self) -> A3ExactAttemptBatch:
        evidence = A3ProviderEvidenceState.missing_b3(self.runtime_config)
        return A3ExactAttemptBatch(evidence)

    async def _report_for_batch(
        self,
        cycle_id: str,
        sequence: int,
        batch: A3ExactAttemptBatch,
    ) -> InstalledDurablePaperServiceReport:
        if batch.evidence.blockers:
            return self._blocked_report(
                cycle_id,
                sequence,
                batch.evidence,
                batch.evidence.blockers[0],
            )
        if self.runtime_cycle is None:
            return self._blocked_report(
                cycle_id,
                sequence,
                batch.evidence,
                A3_RUNTIME_UNWIRED,
            )
        return await self._run_a2_cycle(cycle_id, sequence, batch)

    async def _run_a2_cycle(
        self,
        cycle_id: str,
        sequence: int,
        batch: A3ExactAttemptBatch,
    ) -> InstalledDurablePaperServiceReport:
        assert self.runtime_cycle is not None
        try:
            a2_report = await asyncio.wait_for(
                self.runtime_cycle(cycle_id, batch.items),
                timeout=self.config.cycle_deadline_seconds,
            )
        except asyncio.TimeoutError:
            return self._blocked_report(
                cycle_id,
                sequence,
                batch.evidence,
                A3_RUNTIME_TIMEOUT,
            )
        except Exception as exc:
            return self._indeterminate_report(
                cycle_id,
                sequence,
                batch.evidence,
                f"blocked_a3_runtime_cycle_failed_{type(exc).__name__}",
            )
        return InstalledDurablePaperServiceReport(
            cycle_id=cycle_id,
            status=_status_from_a2(a2_report.status),
            terminal_reason=a2_report.terminal_reason,
            db_path=str(self.config.db_path),
            provider_evidence_hash=batch.evidence.provider_evidence_hash,
            report_hash=a2_report.report_hash,
            ready_for_next_cycle=a2_report.ready_for_next_cycle,
            sequence=sequence,
            sender_imported=a2_report.sender_imported,
            submission_allowed=a2_report.submission_allowed,
            live_enabled=a2_report.live_enabled,
            source_surface=self.config.source_surface,
            records=tuple(record.to_json() for record in a2_report.records),
        )

    def _blocked_report(
        self,
        cycle_id: str,
        sequence: int,
        evidence: A3ProviderEvidenceState,
        reason: str,
    ) -> InstalledDurablePaperServiceReport:
        blockers = tuple(evidence.blockers or (reason,))
        payload = {
            "cycle_id": cycle_id,
            "reason": reason,
            "provider_evidence_hash": evidence.provider_evidence_hash,
            "blockers": list(blockers),
        }
        return InstalledDurablePaperServiceReport(
            cycle_id=cycle_id,
            status=A3PaperServiceStatus.BLOCKED,
            terminal_reason=reason,
            db_path=str(self.config.db_path),
            provider_evidence_hash=evidence.provider_evidence_hash,
            report_hash=_hash_json(payload),
            ready_for_next_cycle=False,
            sequence=sequence,
            source_surface=self.config.source_surface,
            b3_blockers=blockers,
        )

    def _indeterminate_report(
        self,
        cycle_id: str,
        sequence: int,
        evidence: A3ProviderEvidenceState,
        reason: str,
    ) -> InstalledDurablePaperServiceReport:
        payload = {"cycle_id": cycle_id, "reason": reason}
        return InstalledDurablePaperServiceReport(
            cycle_id=cycle_id,
            status=A3PaperServiceStatus.INDETERMINATE,
            terminal_reason=reason,
            db_path=str(self.config.db_path),
            provider_evidence_hash=evidence.provider_evidence_hash,
            report_hash=_hash_json(payload),
            ready_for_next_cycle=False,
            sequence=sequence,
            source_surface=self.config.source_surface,
        )

    def _next_sequence(self) -> int:
        row = self.db.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence "
            "FROM a3_paper_service_cycles"
        ).fetchone()
        return int(row["sequence"])

    def _cycle_id(self, sequence: int, started_at_ns: int) -> str:
        return _hash_json(
            {
                "schema": A3_SCHEMA,
                "run_id": self.config.run_id,
                "sequence": sequence,
                "started_at_ns": started_at_ns,
                "config_fingerprint": _safe_config_fingerprint(self.runtime_config),
            }
        )

    def _commit_report(
        self,
        report: InstalledDurablePaperServiceReport,
        *,
        started_at_ns: int,
        completed_at_ns: int,
    ) -> None:
        report_json = _canonical_json(report.to_dict())
        with self.db:
            self.db.execute(
                "INSERT INTO a3_paper_service_cycles VALUES"
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                _cycle_row(
                    report,
                    self.config,
                    started_at_ns,
                    completed_at_ns,
                    report_json,
                ),
            )
            self.db.execute(
                "INSERT INTO a3_paper_service_outbox("
                "cycle_id,topic,payload_json,owner_id,fencing_token,created_at_ns) "
                "VALUES(?,?,?,?,?,?)",
                (
                    report.cycle_id,
                    "paper.service.cycle_recorded",
                    report_json,
                    self.config.owner_id,
                    1,
                    completed_at_ns,
                ),
            )


def build_installed_durable_paper_service(
    config: RuntimeConfig,
    *,
    db_path: Path | str | None = None,
    batch_source: ExactAttemptBatchSource | None = None,
    runtime_cycle: A3RuntimeCycle | None = None,
    clock_ns: Callable[[], int] = time.time_ns,
) -> InstalledDurablePaperService:
    service_config = InstalledPaperServiceConfig(
        db_path=Path(db_path) if db_path is not None else A3_DEFAULT_DB_PATH,
    )
    return InstalledDurablePaperService(
        config,
        service_config,
        batch_source=batch_source,
        runtime_cycle=runtime_cycle,
        clock_ns=clock_ns,
    )


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def _cycle_row(
    report: InstalledDurablePaperServiceReport,
    config: InstalledPaperServiceConfig,
    started_at_ns: int,
    completed_at_ns: int,
    report_json: str,
) -> tuple[object, ...]:
    return (
        report.cycle_id,
        config.run_id,
        report.sequence,
        A3_SCHEMA,
        report.status.value,
        report.terminal_reason,
        int(report.ready_for_next_cycle),
        report.provider_evidence_hash,
        report.report_hash,
        config.source_surface,
        config.owner_id,
        1,
        started_at_ns + config.lease_ttl_ns,
        started_at_ns,
        completed_at_ns,
        int(report.sender_imported),
        int(report.submission_allowed),
        int(report.live_enabled),
        report_json,
    )


def _status_from_a2(status: A2PaperOutcomeStatus) -> A3PaperServiceStatus:
    return A3PaperServiceStatus(status.value)


def _safe_config_fingerprint(config: RuntimeConfig) -> str:
    fingerprint = getattr(config, "fingerprint", None)
    if callable(fingerprint):
        return str(fingerprint())
    return "unavailable"


def _record_tuple(
    records: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    return tuple(dict(item) for item in records)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _hash_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _is_sha256(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


__all__ = [
    "A3_B3_EVIDENCE_MISSING",
    "A3_DEFAULT_DB_PATH",
    "A3_RUNTIME_TIMEOUT",
    "A3_RUNTIME_UNWIRED",
    "A3_SCHEMA",
    "A3ExactAttemptBatch",
    "A3PaperServiceStatus",
    "A3ProviderEvidenceState",
    "InstalledDurablePaperService",
    "InstalledDurablePaperServiceReport",
    "InstalledPaperServiceConfig",
    "build_installed_durable_paper_service",
]

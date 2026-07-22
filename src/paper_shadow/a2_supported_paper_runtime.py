"""MEGA-PR A2 supported sender-free paper runtime.

This module is the active runtime slice after the exact-attempt bridge.  It
consumes reviewed recorded exact-attempt reports, persists them through one
SQLite lifecycle/outbox authority, and returns a repeatable supported paper
runtime summary.  It never opens provider/RPC network connections, signs,
submits, imports key material, or enables live mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Mapping

from src.paper_shadow.a2_exact_attempt_runtime import (
    A2PaperOutcomeStatus,
    ExactAttemptRuntimeRecord,
    ExactAttemptRuntimeReport,
)

A2_SUPPORTED_RUNTIME_SCHEMA = "mega-pr-a2.supported-paper-runtime.v1"
A2_RECORDED_EVIDENCE_SCHEMA = "mega-pr-a2.supported-paper-runtime.recorded-evidence.v1"
A2_SQLITE_SCHEMA = "mega-pr-a2.supported-paper-runtime.sqlite.v1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class SupportedPaperRuntimeError(ValueError):
    """Raised when recorded paper runtime evidence is malformed or unsafe."""


class SupportedPaperRuntimeProfile(StrEnum):
    DEFAULT_BLOCKED = "default"
    RECORDED_EVIDENCE = "recorded-evidence"


@dataclass(frozen=True, slots=True)
class RecordedEvidenceCycle:
    """One reviewed exact-attempt runtime report admitted for replay/persistence."""

    cycle_id: str
    recorded_evidence_hash: str
    exact_attempt_report_hash: str
    report: ExactAttemptRuntimeReport

    def __post_init__(self) -> None:
        _require_nonempty(self.cycle_id, "cycle_id")
        _require_sha256(self.recorded_evidence_hash, "recorded_evidence_hash")
        _require_sha256(self.exact_attempt_report_hash, "exact_attempt_report_hash")
        actual_hash = _hash_json(self.report.to_json())
        if actual_hash != self.exact_attempt_report_hash:
            raise SupportedPaperRuntimeError(
                "exact_attempt_report_hash does not match report payload"
            )
        _assert_sender_free_report(self.report)
        if self.report.cycle_id != self.cycle_id:
            raise SupportedPaperRuntimeError("cycle_id differs from report.cycle_id")


@dataclass(frozen=True, slots=True)
class RecordedEvidenceManifest:
    """Reviewed recorded-evidence profile used by ``flashloan-bot run --mode paper``."""

    release_digest: str
    policy_bundle_hash: str
    source_wheel_parity_hash: str
    reviewed_by: str
    review_evidence_hash: str
    cycles: tuple[RecordedEvidenceCycle, ...]
    schema_version: str = A2_RECORDED_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != A2_RECORDED_EVIDENCE_SCHEMA:
            raise SupportedPaperRuntimeError("unsupported recorded evidence schema")
        _require_sha256(self.release_digest, "release_digest")
        _require_sha256(self.policy_bundle_hash, "policy_bundle_hash")
        _require_sha256(self.source_wheel_parity_hash, "source_wheel_parity_hash")
        _require_sha256(self.review_evidence_hash, "review_evidence_hash")
        _require_nonempty(self.reviewed_by, "reviewed_by")
        object.__setattr__(self, "cycles", tuple(self.cycles))
        seen: set[str] = set()
        for cycle in self.cycles:
            if cycle.cycle_id in seen:
                raise SupportedPaperRuntimeError("duplicate recorded cycle_id")
            seen.add(cycle.cycle_id)


@dataclass(frozen=True, slots=True)
class SupportedPaperRuntimeSummary:
    """Machine-readable result from the supported A2 paper runtime."""

    profile: SupportedPaperRuntimeProfile
    state_db_path: str
    cycles_processed: int
    final_status: A2PaperOutcomeStatus
    terminal_reason: str
    report_hashes: tuple[str, ...]
    outbox_events_written: int
    ready_for_next_cycle: bool
    schema_version: str = A2_SUPPORTED_RUNTIME_SCHEMA
    live_enabled: bool = False
    sender_reachable: bool = False
    signer_reachable: bool = False
    jsonl_authoritative: bool = False

    def __post_init__(self) -> None:
        _require_nonempty(self.state_db_path, "state_db_path")
        _require_nonempty(self.terminal_reason, "terminal_reason")
        if self.cycles_processed < 0:
            raise SupportedPaperRuntimeError("cycles_processed must be non-negative")
        if self.outbox_events_written < 0:
            raise SupportedPaperRuntimeError("outbox_events_written must be non-negative")
        for report_hash in self.report_hashes:
            _require_sha256(report_hash, "report_hash")
        if self.live_enabled or self.sender_reachable or self.signer_reachable:
            raise SupportedPaperRuntimeError("A2 supported runtime must remain sender-free")
        if self.jsonl_authoritative:
            raise SupportedPaperRuntimeError("JSONL cannot be authoritative A2 state")
        object.__setattr__(self, "report_hashes", tuple(self.report_hashes))

    @property
    def summary_hash(self) -> str:
        return _hash_json(self.to_json())

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile": self.profile.value,
            "state_db_path": self.state_db_path,
            "cycles_processed": self.cycles_processed,
            "final_status": self.final_status.value,
            "terminal_reason": self.terminal_reason,
            "report_hashes": list(self.report_hashes),
            "outbox_events_written": self.outbox_events_written,
            "ready_for_next_cycle": self.ready_for_next_cycle,
            "live_enabled": self.live_enabled,
            "sender_reachable": self.sender_reachable,
            "signer_reachable": self.signer_reachable,
            "jsonl_authoritative": self.jsonl_authoritative,
        }


class SupportedPaperRuntimeStore:
    """SQLite lifecycle/outbox authority for A2 recorded paper cycles."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            self._configure(connection)
            self._create_schema(connection)

    def persist_cycle(
        self,
        *,
        manifest: RecordedEvidenceManifest,
        cycle: RecordedEvidenceCycle,
        observed_at_ns: int | None = None,
    ) -> int:
        """Persist one cycle and return newly written outbox-event count.

        Replaying the same cycle/report is idempotent. Replaying the same
        ``cycle_id`` with a different report hash fails closed.
        """

        self.initialize()
        observed = int(time.time_ns() if observed_at_ns is None else observed_at_ns)
        report = cycle.report
        report_hash = cycle.exact_attempt_report_hash
        with sqlite3.connect(self.path) as connection:
            self._configure(connection)
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT report_hash FROM paper_cycles WHERE cycle_id = ?",
                (cycle.cycle_id,),
            ).fetchone()
            if existing is not None:
                if str(existing[0]) != report_hash:
                    connection.rollback()
                    raise SupportedPaperRuntimeError(
                        "cycle_id already exists with a different report hash"
                    )
                connection.rollback()
                return 0

            connection.execute(
                """
                INSERT INTO paper_cycles (
                    cycle_id, schema_version, report_hash, status, terminal_reason,
                    ready_for_next_cycle, recorded_evidence_hash, release_digest,
                    policy_bundle_hash, source_wheel_parity_hash, review_evidence_hash,
                    observed_at_ns
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cycle.cycle_id,
                    report.schema_version,
                    report_hash,
                    report.status.value,
                    report.terminal_reason,
                    int(report.ready_for_next_cycle),
                    cycle.recorded_evidence_hash,
                    manifest.release_digest,
                    manifest.policy_bundle_hash,
                    manifest.source_wheel_parity_hash,
                    manifest.review_evidence_hash,
                    observed,
                ),
            )
            for record in report.records:
                connection.execute(
                    """
                    INSERT INTO paper_cycle_records (
                        cycle_id, item_index, attempt_generation, status,
                        reason_code, provider_evidence_hash, result_hash, attempt_id,
                        message_hash, reconciliation_hash
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cycle.cycle_id,
                        record.item_index,
                        record.attempt_generation,
                        record.status.value,
                        record.reason_code,
                        record.provider_evidence_hash,
                        record.result_hash,
                        record.attempt_id,
                        record.message_hash,
                        record.reconciliation_hash,
                    ),
                )

            outbox_id = _hash_json(
                {
                    "schema": A2_SQLITE_SCHEMA,
                    "cycle_id": cycle.cycle_id,
                    "report_hash": report_hash,
                    "event_type": "paper_cycle_recorded",
                }
            )
            connection.execute(
                """
                INSERT INTO paper_outbox (
                    event_id, cycle_id, event_type, payload_hash, delivered,
                    created_at_ns
                )
                VALUES (?, ?, ?, ?, 0, ?)
                """,
                (
                    outbox_id,
                    cycle.cycle_id,
                    "paper_cycle_recorded",
                    report_hash,
                    observed,
                ),
            )
            connection.commit()
            return 1

    @staticmethod
    def _configure(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            INSERT OR IGNORE INTO schema_metadata(key, value)
            VALUES ('schema_version', 'mega-pr-a2.supported-paper-runtime.sqlite.v1');

            CREATE TABLE IF NOT EXISTS paper_cycles (
                cycle_id TEXT PRIMARY KEY,
                schema_version TEXT NOT NULL,
                report_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                terminal_reason TEXT NOT NULL,
                ready_for_next_cycle INTEGER NOT NULL CHECK (ready_for_next_cycle IN (0, 1)),
                recorded_evidence_hash TEXT NOT NULL,
                release_digest TEXT NOT NULL,
                policy_bundle_hash TEXT NOT NULL,
                source_wheel_parity_hash TEXT NOT NULL,
                review_evidence_hash TEXT NOT NULL,
                observed_at_ns INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS paper_cycle_records (
                cycle_id TEXT NOT NULL,
                item_index INTEGER NOT NULL,
                attempt_generation INTEGER NOT NULL,
                status TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                provider_evidence_hash TEXT NOT NULL,
                result_hash TEXT NOT NULL,
                attempt_id TEXT,
                message_hash TEXT,
                reconciliation_hash TEXT,
                PRIMARY KEY (cycle_id, item_index),
                FOREIGN KEY (cycle_id) REFERENCES paper_cycles(cycle_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS paper_outbox (
                event_id TEXT PRIMARY KEY,
                cycle_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                delivered INTEGER NOT NULL CHECK (delivered IN (0, 1)),
                created_at_ns INTEGER NOT NULL,
                FOREIGN KEY (cycle_id) REFERENCES paper_cycles(cycle_id)
                    ON DELETE CASCADE
            );
            """
        )


def load_recorded_evidence_manifest(path: Path | str) -> RecordedEvidenceManifest:
    raw_path = Path(path)
    try:
        data = json.loads(raw_path.read_text(encoding="utf-8"))
    except OSError as exc:  # pragma: no cover - exercised by CLI integration
        raise SupportedPaperRuntimeError(
            f"cannot read recorded evidence manifest: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise SupportedPaperRuntimeError("recorded evidence manifest is not valid JSON") from exc
    if not isinstance(data, dict):
        raise SupportedPaperRuntimeError("recorded evidence manifest must be a JSON object")
    return manifest_from_json(data)


def manifest_from_json(data: Mapping[str, Any]) -> RecordedEvidenceManifest:
    cycles_value = data.get("cycles", ())
    if not isinstance(cycles_value, list):
        raise SupportedPaperRuntimeError("cycles must be a list")
    return RecordedEvidenceManifest(
        schema_version=str(data.get("schema_version", "")),
        release_digest=str(data.get("release_digest", "")),
        policy_bundle_hash=str(data.get("policy_bundle_hash", "")),
        source_wheel_parity_hash=str(data.get("source_wheel_parity_hash", "")),
        reviewed_by=str(data.get("reviewed_by", "")),
        review_evidence_hash=str(data.get("review_evidence_hash", "")),
        cycles=tuple(_cycle_from_json(item) for item in cycles_value),
    )


def run_supported_paper_runtime_from_manifest(
    *,
    manifest_path: Path | str,
    state_db_path: Path | str,
    max_cycles: int | None = None,
) -> SupportedPaperRuntimeSummary:
    manifest = load_recorded_evidence_manifest(manifest_path)
    return run_supported_paper_runtime(
        manifest=manifest,
        state_db_path=state_db_path,
        max_cycles=max_cycles,
    )


def run_supported_paper_runtime(
    *,
    manifest: RecordedEvidenceManifest,
    state_db_path: Path | str,
    max_cycles: int | None = None,
) -> SupportedPaperRuntimeSummary:
    if max_cycles is not None and max_cycles <= 0:
        raise SupportedPaperRuntimeError("max_cycles must be positive when supplied")
    selected = manifest.cycles if max_cycles is None else manifest.cycles[:max_cycles]
    store = SupportedPaperRuntimeStore(state_db_path)
    outbox_events = 0
    hashes: list[str] = []
    final_status = A2PaperOutcomeStatus.NO_TRADE
    terminal_reason = "no_recorded_exact_attempt_cycles"
    ready = True

    for cycle in selected:
        outbox_events += store.persist_cycle(manifest=manifest, cycle=cycle)
        report = cycle.report
        hashes.append(cycle.exact_attempt_report_hash)
        final_status = report.status
        terminal_reason = report.terminal_reason
        ready = report.ready_for_next_cycle
        if not ready:
            break

    return SupportedPaperRuntimeSummary(
        profile=SupportedPaperRuntimeProfile.RECORDED_EVIDENCE,
        state_db_path=str(Path(state_db_path)),
        cycles_processed=len(hashes),
        final_status=final_status,
        terminal_reason=terminal_reason,
        report_hashes=tuple(hashes),
        outbox_events_written=outbox_events,
        ready_for_next_cycle=ready,
    )


def report_from_json(data: Mapping[str, Any]) -> ExactAttemptRuntimeReport:
    records_value = data.get("records", ())
    if not isinstance(records_value, list):
        raise SupportedPaperRuntimeError("report.records must be a list")
    return ExactAttemptRuntimeReport(
        cycle_id=str(data.get("cycle_id", "")),
        status=A2PaperOutcomeStatus(str(data.get("status", ""))),
        terminal_reason=str(data.get("terminal_reason", "")),
        records=tuple(_record_from_json(item) for item in records_value),
        sender_imported=bool(data.get("sender_imported", False)),
        submission_allowed=bool(data.get("submission_allowed", False)),
        live_enabled=bool(data.get("live_enabled", False)),
    )


def _cycle_from_json(data: Any) -> RecordedEvidenceCycle:
    if not isinstance(data, dict):
        raise SupportedPaperRuntimeError("cycle entry must be an object")
    report_value = data.get("report")
    if not isinstance(report_value, dict):
        raise SupportedPaperRuntimeError("cycle.report must be an object")
    report = report_from_json(report_value)
    return RecordedEvidenceCycle(
        cycle_id=str(data.get("cycle_id", "")),
        recorded_evidence_hash=str(data.get("recorded_evidence_hash", "")),
        exact_attempt_report_hash=str(data.get("exact_attempt_report_hash", "")),
        report=report,
    )


def _record_from_json(data: Any) -> ExactAttemptRuntimeRecord:
    if not isinstance(data, dict):
        raise SupportedPaperRuntimeError("record entry must be an object")
    return ExactAttemptRuntimeRecord(
        item_index=int(data.get("item_index", -1)),
        attempt_generation=int(data.get("attempt_generation", -1)),
        status=A2PaperOutcomeStatus(str(data.get("status", ""))),
        reason_code=str(data.get("reason_code", "")),
        provider_evidence_hash=str(data.get("provider_evidence_hash", "")),
        result_hash=str(data.get("result_hash", "")),
        attempt_id=_optional_string(data.get("attempt_id")),
        message_hash=_optional_string(data.get("message_hash")),
        reconciliation_hash=_optional_string(data.get("reconciliation_hash")),
        sender_imported=bool(data.get("sender_imported", False)),
        submission_allowed=bool(data.get("submission_allowed", False)),
    )


def _assert_sender_free_report(report: ExactAttemptRuntimeReport) -> None:
    if report.live_enabled or report.sender_imported or report.submission_allowed:
        raise SupportedPaperRuntimeError("recorded report exposes live/sender/submission")
    for record in report.records:
        if record.sender_imported or record.submission_allowed:
            raise SupportedPaperRuntimeError(
                "recorded report record exposes sender/submission"
            )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _require_nonempty(value: str, name: str) -> None:
    if not str(value).strip():
        raise SupportedPaperRuntimeError(f"{name} is required")


def _require_sha256(value: str, name: str) -> None:
    if not _SHA256.fullmatch(str(value)):
        raise SupportedPaperRuntimeError(f"{name} must be a lowercase sha256 digest")


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
    "A2_RECORDED_EVIDENCE_SCHEMA",
    "A2_SQLITE_SCHEMA",
    "A2_SUPPORTED_RUNTIME_SCHEMA",
    "RecordedEvidenceCycle",
    "RecordedEvidenceManifest",
    "SupportedPaperRuntimeError",
    "SupportedPaperRuntimeProfile",
    "SupportedPaperRuntimeStore",
    "SupportedPaperRuntimeSummary",
    "load_recorded_evidence_manifest",
    "manifest_from_json",
    "report_from_json",
    "run_supported_paper_runtime",
    "run_supported_paper_runtime_from_manifest",
]

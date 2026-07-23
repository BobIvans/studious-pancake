"""PR-206 reboot-safe time, semantic replay, and verified state.

This sender-free corrective authority extends the historical PR-195 SQLite
schema without introducing a second lifecycle writer.  Every PR-206 operation
updates the PR-195 materialized row, immutable event, durable UTC deadline, and
canonical idempotency record in one ``BEGIN IMMEDIATE`` transaction.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from src.pr195_durable_lifecycle import (
    CapitalReservationError,
    DuplicateLifecycleKeyError,
    DurableLifecycleStore,
    LifecycleTransitionError,
    ManualLifecycleClock,
    OpportunityLifecycle,
    PR195_DURABLE_LIFECYCLE_MIGRATION,
    PR195_DURABLE_LIFECYCLE_SCHEMA,
    SystemLifecycleClock,
    TrustedLifecycleTime,
    WalletReservation,
)

SCHEMA_VERSION = "pr206.durable-state.v1"
MIGRATION_VERSION = 206
TOOL_VERSION = "pr206-tool.v1"
ZERO_HASH = "0" * 64

_ACTIVE_STATES = frozenset({"pending", "claimed"})
_TERMINAL_STATES = frozenset(
    {"expired", "released", "rejected", "terminal_success", "terminal_failure"}
)
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"claimed", "expired", "released", "rejected"}),
    "claimed": frozenset(
        {
            "expired",
            "released",
            "rejected",
            "terminal_success",
            "terminal_failure",
        }
    ),
    "expired": frozenset(),
    "released": frozenset(),
    "rejected": frozenset(),
    "terminal_success": frozenset(),
    "terminal_failure": frozenset(),
}


class PR206DurableStateError(RuntimeError):
    """Base class for fail-closed PR-206 state errors."""


class SemanticIdempotencyCollision(PR206DurableStateError):
    """The same semantic identity was reused for a different request."""


class MigrationDriftError(PR206DurableStateError):
    """The migration ledger differs from the compiled schema chain."""


class ProjectionMismatchError(PR206DurableStateError):
    """A materialized row is not reproduced by immutable event replay."""


class DurableDeadlineError(PR206DurableStateError):
    """Trusted time moved backwards or a durable deadline is ambiguous."""


class ReservationConflictError(PR206DurableStateError):
    """Reservation identity or settled accounting conflicts with a replay."""


@dataclass(frozen=True, slots=True)
class PR206ReadinessReport:
    """Store-derived readiness; no caller-supplied completion booleans."""

    schema_version: str
    ready: bool
    migration_rows_verified: int
    projections_verified: int
    idempotency_rows_verified: int
    terminal_rows_verified: int
    boot_reconciled: bool
    reason_codes: tuple[str, ...]
    live_enabled: bool = False
    sender_or_signer_enabled: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "ready": self.ready,
            "migration_rows_verified": self.migration_rows_verified,
            "projections_verified": self.projections_verified,
            "idempotency_rows_verified": self.idempotency_rows_verified,
            "terminal_rows_verified": self.terminal_rows_verified,
            "boot_reconciled": self.boot_reconciled,
            "reason_codes": list(self.reason_codes),
            "live_enabled": self.live_enabled,
            "sender_or_signer_enabled": self.sender_or_signer_enabled,
        }


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pr206_migrations(
  version INTEGER PRIMARY KEY,
  schema_name TEXT NOT NULL,
  checksum TEXT NOT NULL,
  parent_version INTEGER NOT NULL,
  parent_schema_name TEXT NOT NULL,
  parent_checksum TEXT NOT NULL,
  tool_version TEXT NOT NULL,
  applied_utc_ns INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS pr206_store_meta(
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  last_boot_id TEXT NOT NULL,
  last_process_generation INTEGER NOT NULL CHECK(last_process_generation>=1),
  last_monotonic_ns INTEGER NOT NULL CHECK(last_monotonic_ns>=0),
  last_utc_ns INTEGER NOT NULL CHECK(last_utc_ns>=0)
);
CREATE TABLE IF NOT EXISTS pr206_semantic_idempotency(
  operation_kind TEXT NOT NULL,
  principal TEXT NOT NULL,
  generation INTEGER NOT NULL CHECK(generation>=1),
  idempotency_key TEXT NOT NULL,
  legacy_idempotency_key TEXT NOT NULL UNIQUE,
  request_json TEXT NOT NULL,
  request_digest TEXT NOT NULL,
  result_json TEXT NOT NULL,
  result_digest TEXT NOT NULL,
  created_utc_ns INTEGER NOT NULL,
  PRIMARY KEY(operation_kind,principal,generation,idempotency_key)
);
CREATE TABLE IF NOT EXISTS pr206_opportunity_truth(
  opportunity_id TEXT PRIMARY KEY
    REFERENCES pr195_opportunities(opportunity_id) ON DELETE RESTRICT,
  expires_utc_ns INTEGER NOT NULL,
  retention_until_utc_ns INTEGER,
  event_head_hash TEXT NOT NULL,
  event_count INTEGER NOT NULL CHECK(event_count>=0)
);
CREATE TABLE IF NOT EXISTS pr206_reservation_terminal_truth(
  reservation_id TEXT PRIMARY KEY
    REFERENCES pr195_wallet_reservations(reservation_id) ON DELETE RESTRICT,
  principal TEXT NOT NULL,
  generation INTEGER NOT NULL CHECK(generation>=1),
  idempotency_key TEXT NOT NULL,
  request_json TEXT NOT NULL,
  request_digest TEXT NOT NULL,
  result_json TEXT NOT NULL,
  result_digest TEXT NOT NULL,
  finalized_utc_ns INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS pr206_idempotency_no_update
BEFORE UPDATE ON pr206_semantic_idempotency
BEGIN
  SELECT RAISE(ABORT, 'pr206 semantic idempotency is immutable');
END;
CREATE TRIGGER IF NOT EXISTS pr206_idempotency_no_delete
BEFORE DELETE ON pr206_semantic_idempotency
BEGIN
  SELECT RAISE(ABORT, 'pr206 semantic idempotency is immutable');
END;
CREATE TRIGGER IF NOT EXISTS pr206_terminal_truth_no_update
BEFORE UPDATE ON pr206_reservation_terminal_truth
BEGIN
  SELECT RAISE(ABORT, 'pr206 terminal truth is immutable');
END;
CREATE TRIGGER IF NOT EXISTS pr206_terminal_truth_no_delete
BEFORE DELETE ON pr206_reservation_terminal_truth
BEGIN
  SELECT RAISE(ABORT, 'pr206 terminal truth is immutable');
END;
""".strip()
_SCHEMA_CHECKSUM = hashlib.sha256(_SCHEMA_SQL.encode("utf-8")).hexdigest()
_PARENT_CHECKSUM = hashlib.sha256(
    PR195_DURABLE_LIFECYCLE_SCHEMA.encode("utf-8")
).hexdigest()


class PR206DurableStateStore(DurableLifecycleStore):
    """PR-195-compatible authority with atomic PR-206 corrective controls."""

    def __init__(
        self,
        path: str | Path,
        *,
        trusted_clock: SystemLifecycleClock | ManualLifecycleClock | None = None,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        super().__init__(
            path,
            trusted_clock=trusted_clock,
            busy_timeout_ms=busy_timeout_ms,
        )
        try:
            self._install_schema()
            self._verify_migrations()
            self._bootstrap_truth_and_time()
            self.verify_all_projections()
        except Exception:
            self.db.close()
            raise

    def _install_schema(self) -> None:
        now = self._now()
        with self.db:
            self.db.executescript(_SCHEMA_SQL)
            self.db.execute(
                "INSERT OR IGNORE INTO pr206_migrations("
                "version,schema_name,checksum,parent_version,parent_schema_name,"
                "parent_checksum,tool_version,applied_utc_ns) VALUES(?,?,?,?,?,?,?,?)",
                (
                    MIGRATION_VERSION,
                    SCHEMA_VERSION,
                    _SCHEMA_CHECKSUM,
                    PR195_DURABLE_LIFECYCLE_MIGRATION,
                    PR195_DURABLE_LIFECYCLE_SCHEMA,
                    _PARENT_CHECKSUM,
                    TOOL_VERSION,
                    now.utc_ns,
                ),
            )

    def _verify_migrations(self) -> int:
        parent = self.db.execute(
            "SELECT schema_name,checksum FROM pr195_durable_migrations "
            "WHERE version=?",
            (PR195_DURABLE_LIFECYCLE_MIGRATION,),
        ).fetchone()
        expected_parent = (PR195_DURABLE_LIFECYCLE_SCHEMA, _PARENT_CHECKSUM)
        actual_parent = (
            str(parent["schema_name"]) if parent is not None else "",
            str(parent["checksum"]) if parent is not None else "",
        )
        if actual_parent != expected_parent:
            raise MigrationDriftError(
                "PR-195 migration ledger mismatch: "
                f"{actual_parent!r} != {expected_parent!r}"
            )

        current = self.db.execute(
            "SELECT * FROM pr206_migrations WHERE version=?",
            (MIGRATION_VERSION,),
        ).fetchone()
        expected_current = (
            SCHEMA_VERSION,
            _SCHEMA_CHECKSUM,
            PR195_DURABLE_LIFECYCLE_MIGRATION,
            PR195_DURABLE_LIFECYCLE_SCHEMA,
            _PARENT_CHECKSUM,
            TOOL_VERSION,
        )
        actual_current = (
            str(current["schema_name"]) if current is not None else "",
            str(current["checksum"]) if current is not None else "",
            int(current["parent_version"]) if current is not None else -1,
            str(current["parent_schema_name"]) if current is not None else "",
            str(current["parent_checksum"]) if current is not None else "",
            str(current["tool_version"]) if current is not None else "",
        )
        if actual_current != expected_current:
            raise MigrationDriftError(
                "PR-206 migration ledger mismatch: "
                f"{actual_current!r} != {expected_current!r}"
            )
        return 2

    def _bootstrap_truth_and_time(self) -> None:
        with self._write_transaction() as now:
            rows = self.db.execute(
                "SELECT * FROM pr195_opportunities ORDER BY opportunity_id"
            ).fetchall()
            for row in rows:
                opportunity_id = str(row["opportunity_id"])
                existing = self.db.execute(
                    "SELECT 1 FROM pr206_opportunity_truth WHERE opportunity_id=?",
                    (opportunity_id,),
                ).fetchone()
                if existing is not None:
                    continue
                expiry_delta = int(row["expires_monotonic_ns"]) - int(
                    row["created_monotonic_ns"]
                )
                if expiry_delta < 0:
                    raise DurableDeadlineError(
                        "legacy opportunity expiry precedes its creation"
                    )
                retention_until_utc_ns: int | None = None
                raw_retention = row["dedupe_block_until_monotonic_ns"]
                if raw_retention is not None:
                    retention_delta = int(raw_retention) - int(
                        row["updated_monotonic_ns"]
                    )
                    if retention_delta < 0:
                        raise DurableDeadlineError(
                            "legacy retention deadline precedes its transition"
                        )
                    retention_until_utc_ns = (
                        int(row["updated_utc_ns"]) + retention_delta
                    )
                head, count = self._event_head_locked(opportunity_id)
                self.db.execute(
                    "INSERT INTO pr206_opportunity_truth("
                    "opportunity_id,expires_utc_ns,retention_until_utc_ns,"
                    "event_head_hash,event_count) VALUES(?,?,?,?,?)",
                    (
                        opportunity_id,
                        int(row["created_utc_ns"]) + expiry_delta,
                        retention_until_utc_ns,
                        head,
                        count,
                    ),
                )
            self._rebase_legacy_deadlines_locked(now)

    @contextmanager
    def _write_transaction(self) -> Iterator[TrustedLifecycleTime]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            now = self._now()
            self._record_clock_locked(now)
            yield now
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        else:
            self.db.execute("COMMIT")

    def _record_clock_locked(self, now: TrustedLifecycleTime) -> None:
        previous = self.db.execute(
            "SELECT * FROM pr206_store_meta WHERE singleton=1"
        ).fetchone()
        if previous is not None:
            previous_utc = int(previous["last_utc_ns"])
            if now.utc_ns < previous_utc:
                raise DurableDeadlineError("trusted UTC moved backwards")
            same_boot = str(previous["last_boot_id"]) == now.boot_id
            if same_boot:
                if now.process_generation < int(previous["last_process_generation"]):
                    raise DurableDeadlineError(
                        "process generation moved backwards within one boot"
                    )
                if now.monotonic_ns < int(previous["last_monotonic_ns"]):
                    raise DurableDeadlineError(
                        "monotonic clock moved backwards within one boot"
                    )
        self.db.execute(
            "INSERT INTO pr206_store_meta VALUES(1,?,?,?,?) "
            "ON CONFLICT(singleton) DO UPDATE SET "
            "last_boot_id=excluded.last_boot_id,"
            "last_process_generation=excluded.last_process_generation,"
            "last_monotonic_ns=excluded.last_monotonic_ns,"
            "last_utc_ns=excluded.last_utc_ns",
            (
                now.boot_id,
                now.process_generation,
                now.monotonic_ns,
                now.utc_ns,
            ),
        )

    def _rebase_legacy_deadlines_locked(self, now: TrustedLifecycleTime) -> None:
        rows = self.db.execute(
            "SELECT o.opportunity_id,o.lifecycle_key,o.state,t.expires_utc_ns,"
            "t.retention_until_utc_ns FROM pr195_opportunities o "
            "JOIN pr206_opportunity_truth t USING(opportunity_id)"
        ).fetchall()
        for row in rows:
            expires_monotonic_ns = now.monotonic_ns + max(
                0, int(row["expires_utc_ns"]) - now.utc_ns
            )
            retention_monotonic_ns: int | None = None
            if row["retention_until_utc_ns"] is not None:
                retention_monotonic_ns = now.monotonic_ns + max(
                    0, int(row["retention_until_utc_ns"]) - now.utc_ns
                )
            self.db.execute(
                "UPDATE pr195_opportunities SET expires_monotonic_ns=?,"
                "dedupe_block_until_monotonic_ns=? WHERE opportunity_id=?",
                (
                    expires_monotonic_ns,
                    retention_monotonic_ns,
                    str(row["opportunity_id"]),
                ),
            )
            key = self.db.execute(
                "SELECT 1 FROM pr195_lifecycle_keys WHERE lifecycle_key=?",
                (str(row["lifecycle_key"]),),
            ).fetchone()
            if key is not None:
                self.db.execute(
                    "UPDATE pr195_lifecycle_keys SET expires_monotonic_ns=?,"
                    "dedupe_block_until_monotonic_ns=? WHERE lifecycle_key=?",
                    (
                        expires_monotonic_ns,
                        retention_monotonic_ns,
                        str(row["lifecycle_key"]),
                    ),
                )

    def _event_head_locked(self, opportunity_id: str) -> tuple[str, int]:
        rows = self.db.execute(
            "SELECT event_hash FROM pr195_opportunity_events "
            "WHERE opportunity_id=? ORDER BY revision",
            (opportunity_id,),
        ).fetchall()
        return (str(rows[-1]["event_hash"]) if rows else ZERO_HASH, len(rows))

    def _legacy_key(
        self,
        *,
        operation_kind: str,
        principal: str,
        generation: int,
        idempotency_key: str,
    ) -> str:
        return "pr206:" + _digest(
            {
                "operation_kind": operation_kind,
                "principal": principal,
                "generation": generation,
                "idempotency_key": idempotency_key,
            }
        )

    def _semantic_replay_locked(
        self,
        *,
        operation_kind: str,
        principal: str,
        generation: int,
        idempotency_key: str,
        request: Mapping[str, object],
    ) -> dict[str, Any] | None:
        _validate_identity(operation_kind, principal, generation, idempotency_key)
        row = self.db.execute(
            "SELECT * FROM pr206_semantic_idempotency WHERE operation_kind=? "
            "AND principal=? AND generation=? AND idempotency_key=?",
            (operation_kind, principal, generation, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        expected_legacy_key = self._legacy_key(
            operation_kind=operation_kind,
            principal=principal,
            generation=generation,
            idempotency_key=idempotency_key,
        )
        if str(row["legacy_idempotency_key"]) != expected_legacy_key:
            raise ProjectionMismatchError("semantic legacy key mismatch")
        request_json = str(row["request_json"])
        if _sha256(request_json) != str(row["request_digest"]):
            raise ProjectionMismatchError("semantic request digest mismatch")
        if request_json != _stable_json(request):
            raise SemanticIdempotencyCollision(
                "idempotency identity reused for a different canonical request"
            )
        result_json = str(row["result_json"])
        if _sha256(result_json) != str(row["result_digest"]):
            raise ProjectionMismatchError("semantic result digest mismatch")
        result = json.loads(result_json)
        if not isinstance(result, dict):
            raise ProjectionMismatchError("semantic result is not an object")
        self._verify_semantic_linkage_locked(row, result)
        return result

    def _record_semantic_locked(
        self,
        *,
        operation_kind: str,
        principal: str,
        generation: int,
        idempotency_key: str,
        request: Mapping[str, object],
        result: Mapping[str, object],
        now: TrustedLifecycleTime,
    ) -> str:
        request_json = _stable_json(request)
        result_json = _stable_json(result)
        legacy_key = self._legacy_key(
            operation_kind=operation_kind,
            principal=principal,
            generation=generation,
            idempotency_key=idempotency_key,
        )
        self.db.execute(
            "INSERT INTO pr206_semantic_idempotency("
            "operation_kind,principal,generation,idempotency_key,"
            "legacy_idempotency_key,request_json,request_digest,result_json,"
            "result_digest,created_utc_ns) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                operation_kind,
                principal,
                generation,
                idempotency_key,
                legacy_key,
                request_json,
                _sha256(request_json),
                result_json,
                _sha256(result_json),
                now.utc_ns,
            ),
        )
        return legacy_key

    def _ensure_legacy_key_unused_locked(
        self,
        *,
        raw_key: str,
        legacy_key: str,
    ) -> None:
        for table in ("pr195_opportunity_events", "pr195_wallet_reservations"):
            found = self.db.execute(
                f"SELECT 1 FROM {table} WHERE idempotency_key IN (?,?) LIMIT 1",
                (raw_key, legacy_key),
            ).fetchone()
            if found is not None:
                raise SemanticIdempotencyCollision(
                    "legacy state exists without a canonical PR-206 request digest"
                )

    def _insert_event_locked(
        self,
        *,
        opportunity_id: str,
        revision: int,
        idempotency_key: str,
        event_type: str,
        from_state: str | None,
        to_state: str,
        reason_code: str,
        evidence: Mapping[str, object] | None,
        now: TrustedLifecycleTime,
    ) -> str:
        previous = self.db.execute(
            "SELECT event_hash FROM pr195_opportunity_events "
            "WHERE opportunity_id=? ORDER BY revision DESC LIMIT 1",
            (opportunity_id,),
        ).fetchone()
        previous_hash = str(previous["event_hash"]) if previous else ZERO_HASH
        evidence_json = _stable_json(dict(evidence or {}))
        evidence_hash = _sha256(evidence_json)
        event_hash = _event_hash(
            opportunity_id=opportunity_id,
            revision=revision,
            event_type=event_type,
            from_state=from_state,
            to_state=to_state,
            reason_code=reason_code,
            evidence_hash=evidence_hash,
            previous_event_hash=previous_hash,
            now=now,
        )
        self.db.execute(
            "INSERT INTO pr195_opportunity_events("
            "event_id,opportunity_id,revision,idempotency_key,event_type,"
            "from_state,to_state,reason_code,evidence_json,evidence_hash,"
            "previous_event_hash,event_hash,boot_id,process_generation,"
            "monotonic_ns,utc_ns) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                uuid4().hex,
                opportunity_id,
                revision,
                idempotency_key,
                event_type,
                from_state,
                to_state,
                reason_code,
                evidence_json,
                evidence_hash,
                previous_hash,
                event_hash,
                now.boot_id,
                now.process_generation,
                now.monotonic_ns,
                now.utc_ns,
            ),
        )
        return event_hash

    def admit_opportunity(
        self,
        *,
        opportunity_id: str,
        lifecycle_key: str,
        expires_after_ns: int,
        idempotency_key: str,
        terminal_retention_ns: int,
        evidence: Mapping[str, object] | None = None,
        principal: str = "runtime",
        generation: int = 1,
    ) -> OpportunityLifecycle:
        if not opportunity_id.strip() or not lifecycle_key.strip():
            raise ValueError("opportunity_id and lifecycle_key are required")
        if expires_after_ns <= 0 or terminal_retention_ns < 0:
            raise ValueError("expiry and retention values are invalid")
        request = {
            "opportunity_id": opportunity_id,
            "lifecycle_key": lifecycle_key,
            "expires_after_ns": expires_after_ns,
            "terminal_retention_ns": terminal_retention_ns,
            "evidence": dict(evidence or {}),
        }
        with self._write_transaction() as now:
            self._expire_due_locked(
                now,
                terminal_retention_ns=terminal_retention_ns,
            )
            self._compact_dedupe_locked(now)
            replay = self._semantic_replay_locked(
                operation_kind="admit_opportunity",
                principal=principal,
                generation=generation,
                idempotency_key=idempotency_key,
                request=request,
            )
            if replay is not None:
                return OpportunityLifecycle(**replay)
            legacy_key = self._legacy_key(
                operation_kind="admit_opportunity",
                principal=principal,
                generation=generation,
                idempotency_key=idempotency_key,
            )
            self._ensure_legacy_key_unused_locked(
                raw_key=idempotency_key,
                legacy_key=legacy_key,
            )
            duplicate_id = self._opportunity_row(opportunity_id)
            if duplicate_id is not None:
                raise LifecycleTransitionError("opportunity_id already exists")
            blocker = self.db.execute(
                "SELECT opportunity_id FROM pr195_lifecycle_keys "
                "WHERE lifecycle_key=?",
                (lifecycle_key,),
            ).fetchone()
            if blocker is not None:
                raise DuplicateLifecycleKeyError(
                    "lifecycle key is active or retained: "
                    f"{lifecycle_key} -> {blocker['opportunity_id']}"
                )
            expires_monotonic_ns = now.monotonic_ns + expires_after_ns
            self.db.execute(
                "INSERT INTO pr195_opportunities("
                "opportunity_id,lifecycle_key,state,revision,terminal,"
                "expires_monotonic_ns,dedupe_block_until_monotonic_ns,"
                "created_boot_id,created_process_generation,created_monotonic_ns,"
                "created_utc_ns,updated_boot_id,updated_process_generation,"
                "updated_monotonic_ns,updated_utc_ns) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    opportunity_id,
                    lifecycle_key,
                    "pending",
                    0,
                    0,
                    expires_monotonic_ns,
                    None,
                    now.boot_id,
                    now.process_generation,
                    now.monotonic_ns,
                    now.utc_ns,
                    now.boot_id,
                    now.process_generation,
                    now.monotonic_ns,
                    now.utc_ns,
                ),
            )
            self.db.execute(
                "INSERT INTO pr195_lifecycle_keys("
                "lifecycle_key,opportunity_id,state,expires_monotonic_ns,"
                "dedupe_block_until_monotonic_ns,updated_boot_id,"
                "updated_process_generation,updated_monotonic_ns,updated_utc_ns) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    lifecycle_key,
                    opportunity_id,
                    "pending",
                    expires_monotonic_ns,
                    None,
                    now.boot_id,
                    now.process_generation,
                    now.monotonic_ns,
                    now.utc_ns,
                ),
            )
            event_head = self._insert_event_locked(
                opportunity_id=opportunity_id,
                revision=0,
                idempotency_key=legacy_key,
                event_type="opportunity_admitted",
                from_state=None,
                to_state="pending",
                reason_code="OPPORTUNITY_ADMITTED",
                evidence=evidence,
                now=now,
            )
            self.db.execute(
                "INSERT INTO pr206_opportunity_truth("
                "opportunity_id,expires_utc_ns,retention_until_utc_ns,"
                "event_head_hash,event_count) VALUES(?,?,?,?,?)",
                (
                    opportunity_id,
                    now.utc_ns + expires_after_ns,
                    None,
                    event_head,
                    1,
                ),
            )
            row = self._opportunity_row(opportunity_id)
            if row is None:
                raise ProjectionMismatchError("admitted opportunity disappeared")
            result = _opportunity_from_row(row)
            self._record_semantic_locked(
                operation_kind="admit_opportunity",
                principal=principal,
                generation=generation,
                idempotency_key=idempotency_key,
                request=request,
                result=asdict(result),
                now=now,
            )
            self._verify_projection_locked(opportunity_id)
            return result

    def claim_opportunity(
        self,
        *,
        opportunity_id: str,
        expected_revision: int,
        idempotency_key: str,
        evidence: Mapping[str, object] | None = None,
        principal: str = "runtime",
        generation: int = 1,
    ) -> OpportunityLifecycle:
        return self._transition(
            opportunity_id=opportunity_id,
            expected_revision=expected_revision,
            target_state="claimed",
            idempotency_key=idempotency_key,
            reason_code="OPPORTUNITY_CLAIMED",
            terminal_retention_ns=0,
            evidence=evidence,
            principal=principal,
            generation=generation,
        )

    def finish_opportunity(
        self,
        *,
        opportunity_id: str,
        expected_revision: int,
        target_state: str,
        idempotency_key: str,
        terminal_retention_ns: int,
        reason_code: str,
        evidence: Mapping[str, object] | None = None,
        principal: str = "runtime",
        generation: int = 1,
    ) -> OpportunityLifecycle:
        if target_state not in _TERMINAL_STATES:
            raise LifecycleTransitionError("finish target must be terminal")
        if terminal_retention_ns < 0:
            raise ValueError("terminal retention must be non-negative")
        return self._transition(
            opportunity_id=opportunity_id,
            expected_revision=expected_revision,
            target_state=target_state,
            idempotency_key=idempotency_key,
            reason_code=reason_code,
            terminal_retention_ns=terminal_retention_ns,
            evidence=evidence,
            principal=principal,
            generation=generation,
        )

    def _transition(
        self,
        *,
        opportunity_id: str,
        expected_revision: int,
        target_state: str,
        idempotency_key: str,
        reason_code: str,
        terminal_retention_ns: int,
        evidence: Mapping[str, object] | None,
        principal: str,
        generation: int,
    ) -> OpportunityLifecycle:
        if expected_revision < 0:
            raise ValueError("expected_revision must be non-negative")
        request = {
            "opportunity_id": opportunity_id,
            "expected_revision": expected_revision,
            "target_state": target_state,
            "reason_code": reason_code,
            "terminal_retention_ns": terminal_retention_ns,
            "evidence": dict(evidence or {}),
        }
        with self._write_transaction() as now:
            if self._opportunity_row(opportunity_id) is not None:
                self._verify_projection_locked(opportunity_id)
            replay = self._semantic_replay_locked(
                operation_kind="transition_opportunity",
                principal=principal,
                generation=generation,
                idempotency_key=idempotency_key,
                request=request,
            )
            if replay is not None:
                return OpportunityLifecycle(**replay)
            legacy_key = self._legacy_key(
                operation_kind="transition_opportunity",
                principal=principal,
                generation=generation,
                idempotency_key=idempotency_key,
            )
            self._ensure_legacy_key_unused_locked(
                raw_key=idempotency_key,
                legacy_key=legacy_key,
            )
            result = self._transition_locked(
                opportunity_id=opportunity_id,
                expected_revision=expected_revision,
                target_state=target_state,
                legacy_idempotency_key=legacy_key,
                reason_code=reason_code,
                terminal_retention_ns=terminal_retention_ns,
                evidence=evidence,
                now=now,
            )
            self._record_semantic_locked(
                operation_kind="transition_opportunity",
                principal=principal,
                generation=generation,
                idempotency_key=idempotency_key,
                request=request,
                result=asdict(result),
                now=now,
            )
            self._verify_projection_locked(opportunity_id)
            return result

    def _transition_locked(
        self,
        *,
        opportunity_id: str,
        expected_revision: int,
        target_state: str,
        legacy_idempotency_key: str,
        reason_code: str,
        terminal_retention_ns: int,
        evidence: Mapping[str, object] | None,
        now: TrustedLifecycleTime,
    ) -> OpportunityLifecycle:
        row = self._opportunity_row(opportunity_id)
        if row is None:
            raise LifecycleTransitionError("opportunity not found")
        current_state = str(row["state"])
        if current_state not in _ALLOWED_TRANSITIONS:
            raise LifecycleTransitionError("unknown materialized lifecycle state")
        revision = int(row["revision"])
        if revision != expected_revision:
            raise LifecycleTransitionError("optimistic lifecycle revision conflict")
        if target_state not in _ALLOWED_TRANSITIONS[current_state]:
            raise LifecycleTransitionError(
                f"illegal lifecycle transition {current_state}->{target_state}"
            )
        next_revision = revision + 1
        terminal = target_state in _TERMINAL_STATES
        retention_monotonic_ns = (
            now.monotonic_ns + terminal_retention_ns if terminal else None
        )
        cursor = self.db.execute(
            "UPDATE pr195_opportunities SET state=?,revision=?,terminal=?,"
            "dedupe_block_until_monotonic_ns=?,updated_boot_id=?,"
            "updated_process_generation=?,updated_monotonic_ns=?,updated_utc_ns=? "
            "WHERE opportunity_id=? AND revision=?",
            (
                target_state,
                next_revision,
                int(terminal),
                retention_monotonic_ns,
                now.boot_id,
                now.process_generation,
                now.monotonic_ns,
                now.utc_ns,
                opportunity_id,
                revision,
            ),
        )
        if cursor.rowcount != 1:
            raise LifecycleTransitionError("lifecycle update lost its revision fence")
        key_cursor = self.db.execute(
            "UPDATE pr195_lifecycle_keys SET state=?,"
            "dedupe_block_until_monotonic_ns=?,updated_boot_id=?,"
            "updated_process_generation=?,updated_monotonic_ns=?,updated_utc_ns=? "
            "WHERE lifecycle_key=? AND opportunity_id=?",
            (
                "terminal" if terminal else target_state,
                retention_monotonic_ns,
                now.boot_id,
                now.process_generation,
                now.monotonic_ns,
                now.utc_ns,
                str(row["lifecycle_key"]),
                opportunity_id,
            ),
        )
        if key_cursor.rowcount != 1:
            raise ProjectionMismatchError("lifecycle key projection is missing")
        event_head = self._insert_event_locked(
            opportunity_id=opportunity_id,
            revision=next_revision,
            idempotency_key=legacy_idempotency_key,
            event_type=(
                "opportunity_expired"
                if target_state == "expired"
                else "opportunity_transition"
            ),
            from_state=current_state,
            to_state=target_state,
            reason_code=reason_code,
            evidence=evidence,
            now=now,
        )
        retention_utc_ns = now.utc_ns + terminal_retention_ns if terminal else None
        truth_cursor = self.db.execute(
            "UPDATE pr206_opportunity_truth SET retention_until_utc_ns=?,"
            "event_head_hash=?,event_count=? WHERE opportunity_id=?",
            (
                retention_utc_ns,
                event_head,
                next_revision + 1,
                opportunity_id,
            ),
        )
        if truth_cursor.rowcount != 1:
            raise ProjectionMismatchError("PR-206 opportunity truth is missing")
        updated = self._opportunity_row(opportunity_id)
        if updated is None:
            raise ProjectionMismatchError("transitioned opportunity disappeared")
        return _opportunity_from_row(updated)

    def expire_due_opportunities(
        self,
        *,
        terminal_retention_ns: int,
        limit: int | None = None,
    ) -> tuple[OpportunityLifecycle, ...]:
        if terminal_retention_ns < 0:
            raise ValueError("terminal retention must be non-negative")
        with self._write_transaction() as now:
            return tuple(
                self._expire_due_locked(
                    now,
                    terminal_retention_ns=terminal_retention_ns,
                    limit=limit,
                )
            )

    def _expire_due_locked(
        self,
        now: TrustedLifecycleTime,
        *,
        terminal_retention_ns: int,
        limit: int | None = None,
    ) -> list[OpportunityLifecycle]:
        sql = (
            "SELECT o.opportunity_id,o.revision,t.expires_utc_ns "
            "FROM pr195_opportunities o "
            "JOIN pr206_opportunity_truth t USING(opportunity_id) "
            "WHERE o.state IN ('pending','claimed') AND t.expires_utc_ns<=? "
            "ORDER BY t.expires_utc_ns,o.opportunity_id"
        )
        params: tuple[object, ...] = (now.utc_ns,)
        if limit is not None:
            if limit < 1:
                return []
            sql += " LIMIT ?"
            params = (now.utc_ns, limit)
        rows = self.db.execute(sql, params).fetchall()
        expired: list[OpportunityLifecycle] = []
        for row in rows:
            opportunity_id = str(row["opportunity_id"])
            revision = int(row["revision"])
            self._verify_projection_locked(opportunity_id)
            auto_key = "pr206:auto-expire:" + _digest(
                {
                    "opportunity_id": opportunity_id,
                    "revision": revision + 1,
                    "expires_utc_ns": int(row["expires_utc_ns"]),
                }
            )
            expired.append(
                self._transition_locked(
                    opportunity_id=opportunity_id,
                    expected_revision=revision,
                    target_state="expired",
                    legacy_idempotency_key=auto_key,
                    reason_code="OPPORTUNITY_EXPIRED",
                    terminal_retention_ns=terminal_retention_ns,
                    evidence={
                        "expires_utc_ns": int(row["expires_utc_ns"]),
                        "observed_utc_ns": now.utc_ns,
                    },
                    now=now,
                )
            )
        return expired

    def compact_released_dedupe(self) -> int:
        with self._write_transaction() as now:
            return self._compact_dedupe_locked(now)

    def _compact_dedupe_locked(self, now: TrustedLifecycleTime) -> int:
        cursor = self.db.execute(
            "DELETE FROM pr195_lifecycle_keys WHERE opportunity_id IN ("
            "SELECT opportunity_id FROM pr206_opportunity_truth "
            "WHERE retention_until_utc_ns IS NOT NULL "
            "AND retention_until_utc_ns<=?)",
            (now.utc_ns,),
        )
        return int(cursor.rowcount)

    def reserve_wallet_lamports(
        self,
        *,
        reservation_id: str,
        wallet_id: str,
        attempt_id: str,
        lamports: int,
        wallet_limit_lamports: int,
        idempotency_key: str,
        principal: str | None = None,
        generation: int = 1,
    ) -> WalletReservation:
        authority = principal or wallet_id
        if authority != wallet_id:
            raise ReservationConflictError("wallet authority must equal wallet_id")
        if (
            not reservation_id.strip()
            or not wallet_id.strip()
            or not attempt_id.strip()
        ):
            raise ValueError("reservation, wallet and attempt are required")
        if lamports <= 0 or wallet_limit_lamports < 0:
            raise ValueError("lamports and wallet limit are invalid")
        request = {
            "reservation_id": reservation_id,
            "wallet_id": wallet_id,
            "attempt_id": attempt_id,
            "lamports": lamports,
            "wallet_limit_lamports": wallet_limit_lamports,
        }
        with self._write_transaction() as now:
            replay = self._semantic_replay_locked(
                operation_kind="reserve_wallet",
                principal=authority,
                generation=generation,
                idempotency_key=idempotency_key,
                request=request,
            )
            if replay is not None:
                return WalletReservation(**replay)
            legacy_key = self._legacy_key(
                operation_kind="reserve_wallet",
                principal=authority,
                generation=generation,
                idempotency_key=idempotency_key,
            )
            self._ensure_legacy_key_unused_locked(
                raw_key=idempotency_key,
                legacy_key=legacy_key,
            )
            if self._reservation_row(reservation_id) is not None:
                raise ReservationConflictError("reservation_id already exists")
            active = self.db.execute(
                "SELECT COALESCE(SUM(lamports),0) AS total "
                "FROM pr195_wallet_reservations WHERE wallet_id=? AND state='active'",
                (wallet_id,),
            ).fetchone()
            active_lamports = int(active["total"] or 0)
            if active_lamports + lamports > wallet_limit_lamports:
                raise CapitalReservationError(
                    "wallet reservation exceeds limit: "
                    f"{active_lamports}+{lamports}>{wallet_limit_lamports}"
                )
            self.db.execute(
                "INSERT INTO pr195_wallet_reservations("
                "reservation_id,wallet_id,attempt_id,lamports,state,revision,"
                "idempotency_key,charged_fee_lamports,created_boot_id,"
                "created_process_generation,created_monotonic_ns,created_utc_ns,"
                "updated_boot_id,updated_process_generation,updated_monotonic_ns,"
                "updated_utc_ns) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    reservation_id,
                    wallet_id,
                    attempt_id,
                    lamports,
                    "active",
                    0,
                    legacy_key,
                    0,
                    now.boot_id,
                    now.process_generation,
                    now.monotonic_ns,
                    now.utc_ns,
                    now.boot_id,
                    now.process_generation,
                    now.monotonic_ns,
                    now.utc_ns,
                ),
            )
            row = self._reservation_row(reservation_id)
            if row is None:
                raise ProjectionMismatchError("reservation disappeared after insert")
            result = _reservation_from_row(row)
            self._record_semantic_locked(
                operation_kind="reserve_wallet",
                principal=authority,
                generation=generation,
                idempotency_key=idempotency_key,
                request=request,
                result=asdict(result),
                now=now,
            )
            return result

    def release_wallet_reservation(
        self,
        *,
        reservation_id: str,
        expected_revision: int,
        charged_fee_lamports: int,
        idempotency_key: str,
        principal: str,
        generation: int = 1,
    ) -> WalletReservation:
        if expected_revision < 0 or charged_fee_lamports < 0:
            raise ValueError("revision and charged fee must be non-negative")
        request = {
            "reservation_id": reservation_id,
            "expected_revision": expected_revision,
            "charged_fee_lamports": charged_fee_lamports,
        }
        request_json = _stable_json(request)
        request_digest = _sha256(request_json)
        with self._write_transaction() as now:
            replay = self._semantic_replay_locked(
                operation_kind="release_wallet",
                principal=principal,
                generation=generation,
                idempotency_key=idempotency_key,
                request=request,
            )
            if replay is not None:
                return WalletReservation(**replay)
            row = self._reservation_row(reservation_id)
            if row is None:
                raise ReservationConflictError("reservation not found")
            if str(row["wallet_id"]) != principal:
                raise ReservationConflictError("reservation principal mismatch")
            if str(row["state"]) != "active":
                truth = self.db.execute(
                    "SELECT * FROM pr206_reservation_terminal_truth "
                    "WHERE reservation_id=?",
                    (reservation_id,),
                ).fetchone()
                if truth is None:
                    raise ReservationConflictError(
                        "terminal reservation lacks authoritative PR-206 accounting"
                    )
                if str(truth["request_digest"]) != request_digest:
                    raise ReservationConflictError(
                        "terminal replay conflicts with settled accounting"
                    )
                raise ReservationConflictError(
                    "terminal replay must use its original idempotency identity"
                )
            revision = int(row["revision"])
            if revision != expected_revision:
                raise ReservationConflictError("reservation revision conflict")
            state = "charged_failure" if charged_fee_lamports else "released"
            cursor = self.db.execute(
                "UPDATE pr195_wallet_reservations SET state=?,revision=?,"
                "charged_fee_lamports=?,updated_boot_id=?,"
                "updated_process_generation=?,updated_monotonic_ns=?,updated_utc_ns=? "
                "WHERE reservation_id=? AND revision=? AND state='active'",
                (
                    state,
                    revision + 1,
                    charged_fee_lamports,
                    now.boot_id,
                    now.process_generation,
                    now.monotonic_ns,
                    now.utc_ns,
                    reservation_id,
                    revision,
                ),
            )
            if cursor.rowcount != 1:
                raise ReservationConflictError(
                    "reservation terminal update lost its revision fence"
                )
            updated = self._reservation_row(reservation_id)
            if updated is None:
                raise ProjectionMismatchError("terminal reservation disappeared")
            result = _reservation_from_row(updated)
            self._record_semantic_locked(
                operation_kind="release_wallet",
                principal=principal,
                generation=generation,
                idempotency_key=idempotency_key,
                request=request,
                result=asdict(result),
                now=now,
            )
            result_json = _stable_json(asdict(result))
            self.db.execute(
                "INSERT INTO pr206_reservation_terminal_truth("
                "reservation_id,principal,generation,idempotency_key,request_json,"
                "request_digest,result_json,result_digest,finalized_utc_ns) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    reservation_id,
                    principal,
                    generation,
                    idempotency_key,
                    request_json,
                    request_digest,
                    result_json,
                    _sha256(result_json),
                    now.utc_ns,
                ),
            )
            return result

    def get_opportunity(self, opportunity_id: str) -> OpportunityLifecycle | None:
        started = not self.db.in_transaction
        if started:
            self.db.execute("BEGIN")
        try:
            row = self._opportunity_row(opportunity_id)
            if row is None:
                result = None
            else:
                self._verify_projection_locked(opportunity_id)
                result = _opportunity_from_row(row)
        except Exception:
            if started:
                self.db.execute("ROLLBACK")
            raise
        else:
            if started:
                self.db.execute("COMMIT")
            return result

    def verify_projection(self, opportunity_id: str) -> None:
        started = not self.db.in_transaction
        if started:
            self.db.execute("BEGIN")
        try:
            self._verify_projection_locked(opportunity_id)
        except Exception:
            if started:
                self.db.execute("ROLLBACK")
            raise
        else:
            if started:
                self.db.execute("COMMIT")

    def _verify_projection_locked(self, opportunity_id: str) -> None:
        materialized = self._opportunity_row(opportunity_id)
        truth = self.db.execute(
            "SELECT * FROM pr206_opportunity_truth WHERE opportunity_id=?",
            (opportunity_id,),
        ).fetchone()
        events = self.db.execute(
            "SELECT * FROM pr195_opportunity_events "
            "WHERE opportunity_id=? ORDER BY revision",
            (opportunity_id,),
        ).fetchall()
        if materialized is None or truth is None or not events:
            raise ProjectionMismatchError("projection or immutable events are missing")
        previous_hash = ZERO_HASH
        previous_state: str | None = None
        for index, event in enumerate(events):
            if int(event["revision"]) != index:
                raise ProjectionMismatchError("event revisions are not contiguous")
            event_from_state = (
                str(event["from_state"]) if event["from_state"] is not None else None
            )
            event_to_state = str(event["to_state"])
            if index == 0:
                if event_from_state is not None or event_to_state != "pending":
                    raise ProjectionMismatchError("invalid admission event")
            else:
                if event_from_state != previous_state:
                    raise ProjectionMismatchError("event state chain mismatch")
                if (
                    previous_state not in _ALLOWED_TRANSITIONS
                    or event_to_state not in _ALLOWED_TRANSITIONS[previous_state]
                ):
                    raise ProjectionMismatchError("illegal event transition")
            if str(event["previous_event_hash"]) != previous_hash:
                raise ProjectionMismatchError("event previous hash mismatch")
            evidence_json = str(event["evidence_json"])
            if _sha256(evidence_json) != str(event["evidence_hash"]):
                raise ProjectionMismatchError("event evidence hash mismatch")
            expected_hash = _event_hash(
                opportunity_id=opportunity_id,
                revision=index,
                event_type=str(event["event_type"]),
                from_state=event_from_state,
                to_state=event_to_state,
                reason_code=str(event["reason_code"]),
                evidence_hash=str(event["evidence_hash"]),
                previous_event_hash=previous_hash,
                now=TrustedLifecycleTime(
                    str(event["boot_id"]),
                    int(event["process_generation"]),
                    int(event["monotonic_ns"]),
                    int(event["utc_ns"]),
                ),
            )
            if expected_hash != str(event["event_hash"]):
                raise ProjectionMismatchError("event hash mismatch")
            previous_hash = expected_hash
            previous_state = event_to_state
        last = events[-1]
        if previous_state != str(materialized["state"]):
            raise ProjectionMismatchError("materialized state differs from replay")
        if len(events) - 1 != int(materialized["revision"]):
            raise ProjectionMismatchError("materialized revision differs from replay")
        if bool(materialized["terminal"]) != (previous_state in _TERMINAL_STATES):
            raise ProjectionMismatchError(
                "materialized terminal flag differs from replay"
            )
        materialized_update = (
            str(materialized["updated_boot_id"]),
            int(materialized["updated_process_generation"]),
            int(materialized["updated_monotonic_ns"]),
            int(materialized["updated_utc_ns"]),
        )
        event_update = (
            str(last["boot_id"]),
            int(last["process_generation"]),
            int(last["monotonic_ns"]),
            int(last["utc_ns"]),
        )
        if materialized_update != event_update:
            raise ProjectionMismatchError(
                "materialized update identity differs from event replay"
            )
        if previous_hash != str(truth["event_head_hash"]):
            raise ProjectionMismatchError("event head differs from replay")
        if len(events) != int(truth["event_count"]):
            raise ProjectionMismatchError("event count differs from replay")
        key = self.db.execute(
            "SELECT * FROM pr195_lifecycle_keys WHERE lifecycle_key=?",
            (str(materialized["lifecycle_key"]),),
        ).fetchone()
        if previous_state in _ACTIVE_STATES:
            if key is None:
                raise ProjectionMismatchError("active lifecycle key is missing")
            expected_key = (
                opportunity_id,
                previous_state,
            )
            actual_key = (
                str(key["opportunity_id"]),
                str(key["state"]),
            )
            if actual_key != expected_key:
                raise ProjectionMismatchError("active lifecycle key mismatch")
        elif key is not None:
            if str(key["opportunity_id"]) != opportunity_id:
                raise ProjectionMismatchError("terminal lifecycle key owner mismatch")
            if str(key["state"]) != "terminal":
                raise ProjectionMismatchError("terminal lifecycle key state mismatch")
        elif truth["retention_until_utc_ns"] is None:
            raise ProjectionMismatchError("terminal retention truth is missing")

    def verify_all_projections(self) -> int:
        started = not self.db.in_transaction
        if started:
            self.db.execute("BEGIN")
        try:
            rows = self.db.execute(
                "SELECT opportunity_id FROM pr195_opportunities "
                "ORDER BY opportunity_id"
            ).fetchall()
            for row in rows:
                self._verify_projection_locked(str(row["opportunity_id"]))
        except Exception:
            if started:
                self.db.execute("ROLLBACK")
            raise
        else:
            if started:
                self.db.execute("COMMIT")
            return len(rows)

    def _verify_semantic_linkage_locked(
        self,
        row: sqlite3.Row,
        result: Mapping[str, object],
    ) -> None:
        operation_kind = str(row["operation_kind"])
        legacy_key = str(row["legacy_idempotency_key"])
        if operation_kind in {"admit_opportunity", "transition_opportunity"}:
            event = self.db.execute(
                "SELECT opportunity_id,revision,to_state FROM "
                "pr195_opportunity_events WHERE idempotency_key=?",
                (legacy_key,),
            ).fetchone()
            if event is None:
                raise ProjectionMismatchError("semantic event linkage is missing")
            expected = (
                str(result.get("opportunity_id", "")),
                int(result.get("revision", -1)),
                str(result.get("state", "")),
            )
            actual = (
                str(event["opportunity_id"]),
                int(event["revision"]),
                str(event["to_state"]),
            )
            if actual != expected:
                raise ProjectionMismatchError("semantic event result mismatch")
            self._verify_projection_locked(str(event["opportunity_id"]))
        elif operation_kind == "reserve_wallet":
            reservation = self.db.execute(
                "SELECT * FROM pr195_wallet_reservations WHERE idempotency_key=?",
                (legacy_key,),
            ).fetchone()
            if reservation is None:
                raise ProjectionMismatchError("semantic reservation linkage is missing")
            expected = (
                str(result.get("reservation_id", "")),
                str(result.get("wallet_id", "")),
                str(result.get("attempt_id", "")),
                int(result.get("lamports", -1)),
            )
            actual = (
                str(reservation["reservation_id"]),
                str(reservation["wallet_id"]),
                str(reservation["attempt_id"]),
                int(reservation["lamports"]),
            )
            if actual != expected:
                raise ProjectionMismatchError("semantic reservation result mismatch")
        elif operation_kind == "release_wallet":
            terminal = self.db.execute(
                "SELECT * FROM pr206_reservation_terminal_truth "
                "WHERE reservation_id=?",
                (str(result.get("reservation_id", "")),),
            ).fetchone()
            if terminal is None:
                raise ProjectionMismatchError("terminal semantic linkage is missing")
            identity = (
                str(terminal["principal"]),
                int(terminal["generation"]),
                str(terminal["idempotency_key"]),
            )
            expected_identity = (
                str(row["principal"]),
                int(row["generation"]),
                str(row["idempotency_key"]),
            )
            if identity != expected_identity:
                raise ProjectionMismatchError("terminal semantic identity mismatch")
        else:
            raise ProjectionMismatchError(
                f"unknown semantic operation kind {operation_kind!r}"
            )

    def inspect_readiness(
        self,
        *,
        live_enabled: bool = False,
        sender_or_signer_enabled: bool = False,
    ) -> PR206ReadinessReport:
        reasons: list[str] = []
        migrations = 0
        projections = 0
        idempotency_verified = 0
        terminal_verified = 0
        boot_reconciled = False
        self.db.execute("BEGIN")
        try:
            try:
                migrations = self._verify_migrations()
            except MigrationDriftError:
                reasons.append("MIGRATION_LEDGER_DRIFT")
            meta = self.db.execute(
                "SELECT * FROM pr206_store_meta WHERE singleton=1"
            ).fetchone()
            if meta is None:
                reasons.append("BOOT_RECONCILIATION_MISSING")
            else:
                now = self._now()
                boot_reconciled = now.utc_ns >= int(meta["last_utc_ns"])
                if str(meta["last_boot_id"]) == now.boot_id:
                    boot_reconciled = boot_reconciled and (
                        now.monotonic_ns >= int(meta["last_monotonic_ns"])
                    )
                if not boot_reconciled:
                    reasons.append("TRUSTED_TIME_ROLLBACK")
            try:
                rows = self.db.execute(
                    "SELECT opportunity_id FROM pr195_opportunities"
                ).fetchall()
                for row in rows:
                    self._verify_projection_locked(str(row["opportunity_id"]))
                projections = len(rows)
            except ProjectionMismatchError:
                reasons.append("MATERIALIZED_PROJECTION_MISMATCH")
            semantic_rows = self.db.execute(
                "SELECT * FROM pr206_semantic_idempotency"
            ).fetchall()
            for row in semantic_rows:
                request_json = str(row["request_json"])
                result_json = str(row["result_json"])
                if _sha256(request_json) != str(row["request_digest"]):
                    reasons.append("IDEMPOTENCY_REQUEST_DIGEST_MISMATCH")
                    break
                if _sha256(result_json) != str(row["result_digest"]):
                    reasons.append("IDEMPOTENCY_RESULT_DIGEST_MISMATCH")
                    break
                result = json.loads(result_json)
                if not isinstance(result, dict):
                    reasons.append("IDEMPOTENCY_RESULT_INVALID")
                    break
                expected_legacy_key = self._legacy_key(
                    operation_kind=str(row["operation_kind"]),
                    principal=str(row["principal"]),
                    generation=int(row["generation"]),
                    idempotency_key=str(row["idempotency_key"]),
                )
                if str(row["legacy_idempotency_key"]) != expected_legacy_key:
                    reasons.append("IDEMPOTENCY_NAMESPACE_MISMATCH")
                    break
                self._verify_semantic_linkage_locked(row, result)
                idempotency_verified += 1
            terminal_rows = self.db.execute(
                "SELECT * FROM pr206_reservation_terminal_truth"
            ).fetchall()
            for row in terminal_rows:
                if _sha256(str(row["request_json"])) != str(row["request_digest"]):
                    reasons.append("TERMINAL_REQUEST_DIGEST_MISMATCH")
                    break
                if _sha256(str(row["result_json"])) != str(row["result_digest"]):
                    reasons.append("TERMINAL_RESULT_DIGEST_MISMATCH")
                    break
                reservation = self._reservation_row(str(row["reservation_id"]))
                if reservation is None or str(reservation["state"]) == "active":
                    reasons.append("TERMINAL_RESERVATION_STATE_MISMATCH")
                    break
                result = json.loads(str(row["result_json"]))
                if not isinstance(result, dict):
                    reasons.append("TERMINAL_RESULT_INVALID")
                    break
                actual = (
                    str(reservation["reservation_id"]),
                    str(reservation["state"]),
                    int(reservation["revision"]),
                    int(reservation["charged_fee_lamports"]),
                )
                expected = (
                    str(result.get("reservation_id", "")),
                    str(result.get("state", "")),
                    int(result.get("revision", -1)),
                    int(result.get("charged_fee_lamports", -1)),
                )
                if actual != expected:
                    reasons.append("TERMINAL_RESULT_STATE_MISMATCH")
                    break
                terminal_verified += 1
        except (ProjectionMismatchError, json.JSONDecodeError, TypeError, ValueError):
            reasons.append("AUTHORITATIVE_STORE_INSPECTION_FAILED")
        finally:
            self.db.execute("ROLLBACK")
        if live_enabled:
            reasons.append("LIVE_ENABLEMENT_NOT_ALLOWED_IN_PR206")
        if sender_or_signer_enabled:
            reasons.append("SENDER_OR_SIGNER_NOT_ALLOWED_IN_PR206")
        return PR206ReadinessReport(
            schema_version=SCHEMA_VERSION,
            ready=not reasons,
            migration_rows_verified=migrations,
            projections_verified=projections,
            idempotency_rows_verified=idempotency_verified,
            terminal_rows_verified=terminal_verified,
            boot_reconciled=boot_reconciled,
            reason_codes=tuple(dict.fromkeys(reasons)),
            live_enabled=live_enabled,
            sender_or_signer_enabled=sender_or_signer_enabled,
        )


def _validate_identity(
    operation_kind: str,
    principal: str,
    generation: int,
    idempotency_key: str,
) -> None:
    if (
        not operation_kind.strip()
        or not principal.strip()
        or not idempotency_key.strip()
    ):
        raise ValueError("operation, principal and idempotency key are required")
    if generation < 1:
        raise ValueError("generation must be positive")


def _stable_json(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _digest(payload: Mapping[str, object]) -> str:
    return _sha256(_stable_json(payload))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _event_hash(
    *,
    opportunity_id: str,
    revision: int,
    event_type: str,
    from_state: str | None,
    to_state: str,
    reason_code: str,
    evidence_hash: str,
    previous_event_hash: str,
    now: TrustedLifecycleTime,
) -> str:
    return _digest(
        {
            "schema": PR195_DURABLE_LIFECYCLE_SCHEMA,
            "opportunity_id": opportunity_id,
            "revision": revision,
            "event_type": event_type,
            "from_state": from_state,
            "to_state": to_state,
            "reason_code": reason_code,
            "evidence_hash": evidence_hash,
            "previous_event_hash": previous_event_hash,
            "boot_id": now.boot_id,
            "process_generation": str(now.process_generation),
            "monotonic_ns": str(now.monotonic_ns),
            "utc_ns": str(now.utc_ns),
        }
    )


def _opportunity_from_row(row: sqlite3.Row) -> OpportunityLifecycle:
    raw_retention = row["dedupe_block_until_monotonic_ns"]
    return OpportunityLifecycle(
        opportunity_id=str(row["opportunity_id"]),
        lifecycle_key=str(row["lifecycle_key"]),
        state=str(row["state"]),
        revision=int(row["revision"]),
        terminal=bool(row["terminal"]),
        expires_monotonic_ns=int(row["expires_monotonic_ns"]),
        dedupe_block_until_monotonic_ns=(
            int(raw_retention) if raw_retention is not None else None
        ),
    )


def _reservation_from_row(row: sqlite3.Row) -> WalletReservation:
    return WalletReservation(
        reservation_id=str(row["reservation_id"]),
        wallet_id=str(row["wallet_id"]),
        attempt_id=str(row["attempt_id"]),
        lamports=int(row["lamports"]),
        state=str(row["state"]),
        revision=int(row["revision"]),
        charged_fee_lamports=int(row["charged_fee_lamports"]),
    )


__all__ = [
    "DurableDeadlineError",
    "ManualLifecycleClock",
    "MigrationDriftError",
    "PR206DurableStateError",
    "PR206DurableStateStore",
    "PR206ReadinessReport",
    "ProjectionMismatchError",
    "ReservationConflictError",
    "SCHEMA_VERSION",
    "SemanticIdempotencyCollision",
    "SystemLifecycleClock",
]

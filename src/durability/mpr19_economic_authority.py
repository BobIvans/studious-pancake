"""MPR-19 crash-consistent durable economic authority.

Offline, sender-free checkpoint for the MPR-19 durable cutover.  It puts
attempt identity, capital reservations, event journal, outbox delivery and
restore verification behind one SQLite writer using explicit BEGIN IMMEDIATE
transactions.  It never signs, submits, or reaches provider/RPC/Jito services.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Callable, Mapping

MPR19_SCHEMA_VERSION = "mpr19.durable-economic-authority.v1"
_SCHEMA_ID = "mpr19-0001"
_ZERO_HASH = "0" * 64


class MPR19AuthorityError(RuntimeError):
    """Raised when a durable economic authority invariant fails closed."""


class AttemptState(StrEnum):
    RECORDED = "RECORDED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INDETERMINATE = "INDETERMINATE"


class ReservationState(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"
    FROZEN = "FROZEN"


class OutboxState(StrEnum):
    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    DELIVERED = "DELIVERED"
    DEAD_LETTER = "DEAD_LETTER"


@dataclass(frozen=True, slots=True)
class AttemptRequest:
    opportunity_id: str
    wallet_id: str
    strategy: str
    capital_lamports: int
    payload: Mapping[str, object]
    outbox_topic: str = "economic.attempt.created"

    def __post_init__(self) -> None:
        for name in ("opportunity_id", "wallet_id", "strategy", "outbox_topic"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        _strict_positive_int(self.capital_lamports, "capital_lamports")
        _canonical_json(self.payload)

    @property
    def attempt_id(self) -> str:
        return _identity(
            "attempt",
            {
                "opportunity_id": self.opportunity_id,
                "wallet_id": self.wallet_id,
                "strategy": self.strategy,
                "payload": self.payload,
            },
        )

    @property
    def reservation_id(self) -> str:
        return _identity("reservation", {"attempt_id": self.attempt_id})


@dataclass(frozen=True, slots=True)
class AttemptSnapshot:
    attempt_id: str
    reservation_id: str
    state: AttemptState
    reservation_state: ReservationState
    revision: int
    outbox_event_id: str
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class OutboxClaim:
    event_id: str
    owner_id: str
    claim_token: str
    claim_expires_ns: int


@dataclass(frozen=True, slots=True)
class ReplayReport:
    event_count: int
    terminal_count: int
    outbox_pending_count: int
    digest: str


StepHook = Callable[[str], None]


class MPR19EconomicAuthority:
    """One SQLite writer authority for MPR-19 durable economic effects."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        _prepare_private_db_path(self.path)
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=5.0)
        self.db.row_factory = sqlite3.Row
        for statement in (
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=FULL",
            "PRAGMA foreign_keys=ON",
            "PRAGMA trusted_schema=OFF",
            "PRAGMA busy_timeout=5000",
        ):
            self.db.execute(statement)
        self._migrate()
        _chmod_private_file(self.path)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "MPR19EconomicAuthority":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def create_attempt(
        self,
        request: AttemptRequest,
        *,
        now_ns: int,
        step_hook: StepHook | None = None,
    ) -> AttemptSnapshot:
        _strict_non_negative_int(now_ns, "now_ns")
        request_json = _canonical_json(request.payload)
        request_hash = hashlib.sha256(request_json.encode()).hexdigest()
        outbox_event_id = _identity(
            "outbox", {"attempt_id": request.attempt_id, "topic": request.outbox_topic}
        )
        self.db.execute("BEGIN IMMEDIATE")
        try:
            existing = self.db.execute(
                "SELECT request_hash FROM mpr19_attempts WHERE attempt_id=?",
                (request.attempt_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["request_hash"]) != request_hash:
                    raise MPR19AuthorityError("MPR19_ATTEMPT_IDENTITY_COLLISION")
                self.db.execute("ROLLBACK")
                return self._snapshot(request.attempt_id, replayed=True)
            self.db.execute(
                "INSERT INTO mpr19_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    request.attempt_id,
                    request.opportunity_id,
                    request.wallet_id,
                    request.strategy,
                    AttemptState.RECORDED.value,
                    1,
                    request_json,
                    request_hash,
                    now_ns,
                    now_ns,
                    None,
                    None,
                    outbox_event_id,
                ),
            )
            self._after("attempt_inserted", step_hook)
            self.db.execute(
                "INSERT INTO mpr19_capital_reservations VALUES(?,?,?,?,?,?,?)",
                (
                    request.reservation_id,
                    request.attempt_id,
                    request.wallet_id,
                    request.capital_lamports,
                    ReservationState.ACTIVE.value,
                    None,
                    now_ns,
                ),
            )
            self._after("reservation_inserted", step_hook)
            self._append_event(
                request.attempt_id,
                "attempt.created",
                {
                    "state": AttemptState.RECORDED.value,
                    "reservation_state": ReservationState.ACTIVE.value,
                    "request_hash": request_hash,
                    "capital_lamports": request.capital_lamports,
                },
                now_ns=now_ns,
            )
            self._after("journal_appended", step_hook)
            outbox_payload = {
                "attempt_id": request.attempt_id,
                "request_hash": request_hash,
                "reservation_id": request.reservation_id,
                "state": AttemptState.RECORDED.value,
            }
            self._insert_outbox(
                event_id=outbox_event_id,
                attempt_id=request.attempt_id,
                topic=request.outbox_topic,
                payload=outbox_payload,
                now_ns=now_ns,
            )
            self._after("outbox_queued", step_hook)
            self.db.execute("COMMIT")
        except Exception:
            self._rollback_if_open()
            raise
        return self._snapshot(request.attempt_id, replayed=False)

    def terminalize_attempt(
        self,
        *,
        attempt_id: str,
        expected_revision: int,
        terminal_state: AttemptState,
        reservation_state: ReservationState,
        reason_code: str,
        now_ns: int,
    ) -> AttemptSnapshot:
        if terminal_state is AttemptState.RECORDED:
            raise ValueError("terminal_state must be terminal")
        if reservation_state is ReservationState.ACTIVE:
            raise ValueError("reservation_state must be terminal")
        _strict_positive_int(expected_revision, "expected_revision")
        _strict_non_negative_int(now_ns, "now_ns")
        if not reason_code.strip():
            raise ValueError("reason_code is required")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            updated = self.db.execute(
                "UPDATE mpr19_attempts SET state=?,revision=revision+1,terminal_ns=?,"
                "reason_code=?,updated_ns=? WHERE attempt_id=? AND revision=? AND state=?",
                (
                    terminal_state.value,
                    now_ns,
                    reason_code,
                    now_ns,
                    attempt_id,
                    expected_revision,
                    AttemptState.RECORDED.value,
                ),
            )
            if updated.rowcount != 1:
                raise MPR19AuthorityError("MPR19_ATTEMPT_CAS_REVISION_MISMATCH")
            reservation = self.db.execute(
                "UPDATE mpr19_capital_reservations SET state=?,release_reason=?,updated_ns=? "
                "WHERE attempt_id=? AND state=?",
                (
                    reservation_state.value,
                    reason_code,
                    now_ns,
                    attempt_id,
                    ReservationState.ACTIVE.value,
                ),
            )
            if reservation.rowcount != 1:
                raise MPR19AuthorityError("MPR19_RESERVATION_CAS_MISMATCH")
            payload = {
                "state": terminal_state.value,
                "reservation_state": reservation_state.value,
                "reason_code": reason_code,
            }
            self._append_event(attempt_id, "attempt.terminal", payload, now_ns=now_ns)
            self._insert_outbox(
                event_id=_identity(
                    "outbox",
                    {"attempt_id": attempt_id, "topic": "economic.attempt.terminal"},
                ),
                attempt_id=attempt_id,
                topic="economic.attempt.terminal",
                payload={"attempt_id": attempt_id, **payload},
                now_ns=now_ns,
            )
            self.db.execute("COMMIT")
        except Exception:
            self._rollback_if_open()
            raise
        return self._snapshot(attempt_id, replayed=False)

    def claim_outbox(
        self, *, owner_id: str, now_ns: int, lease_ttl_ns: int
    ) -> OutboxClaim | None:
        if not owner_id.strip():
            raise ValueError("owner_id is required")
        _strict_non_negative_int(now_ns, "now_ns")
        _strict_positive_int(lease_ttl_ns, "lease_ttl_ns")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT * FROM mpr19_outbox_events WHERE state=? OR "
                "(state=? AND claim_expires_ns<=?) ORDER BY created_ns,event_id LIMIT 1",
                (OutboxState.QUEUED.value, OutboxState.CLAIMED.value, now_ns),
            ).fetchone()
            if row is None:
                self.db.execute("ROLLBACK")
                return None
            token = _identity(
                "claim",
                {
                    "event_id": row["event_id"],
                    "owner_id": owner_id,
                    "retry_count": int(row["retry_count"]) + 1,
                    "now_ns": now_ns,
                },
            )
            updated = self.db.execute(
                "UPDATE mpr19_outbox_events SET state=?,owner_id=?,claim_token=?,"
                "claim_expires_ns=?,retry_count=retry_count+1,updated_ns=? "
                "WHERE event_id=? AND (state=? OR (state=? AND claim_expires_ns<=?))",
                (
                    OutboxState.CLAIMED.value,
                    owner_id,
                    token,
                    now_ns + lease_ttl_ns,
                    now_ns,
                    row["event_id"],
                    OutboxState.QUEUED.value,
                    OutboxState.CLAIMED.value,
                    now_ns,
                ),
            )
            if updated.rowcount != 1:
                raise MPR19AuthorityError("MPR19_OUTBOX_CLAIM_CAS_MISMATCH")
            self.db.execute(
                "INSERT INTO mpr19_outbox_attempts(event_id,owner_id,claim_token,result,reason_code,observed_ns) "
                "VALUES(?,?,?,?,?,?)",
                (row["event_id"], owner_id, token, "CLAIMED", "claimed", now_ns),
            )
            self.db.execute("COMMIT")
            return OutboxClaim(str(row["event_id"]), owner_id, token, now_ns + lease_ttl_ns)
        except Exception:
            self._rollback_if_open()
            raise

    def complete_outbox(
        self, claim: OutboxClaim, *, delivered: bool, reason_code: str, now_ns: int
    ) -> OutboxState:
        if not reason_code.strip():
            raise ValueError("reason_code is required")
        _strict_non_negative_int(now_ns, "now_ns")
        target = OutboxState.DELIVERED if delivered else OutboxState.DEAD_LETTER
        self.db.execute("BEGIN IMMEDIATE")
        try:
            updated = self.db.execute(
                "UPDATE mpr19_outbox_events SET state=?,last_reason=?,updated_ns=? "
                "WHERE event_id=? AND state=? AND owner_id=? AND claim_token=? "
                "AND claim_expires_ns>?",
                (
                    target.value,
                    reason_code,
                    now_ns,
                    claim.event_id,
                    OutboxState.CLAIMED.value,
                    claim.owner_id,
                    claim.claim_token,
                    now_ns,
                ),
            )
            if updated.rowcount != 1:
                raise MPR19AuthorityError("MPR19_OUTBOX_STALE_OWNER_OR_EXPIRED_CLAIM")
            self.db.execute(
                "INSERT INTO mpr19_outbox_attempts(event_id,owner_id,claim_token,result,reason_code,observed_ns) "
                "VALUES(?,?,?,?,?,?)",
                (
                    claim.event_id,
                    claim.owner_id,
                    claim.claim_token,
                    target.value,
                    reason_code,
                    now_ns,
                ),
            )
            self.db.execute("COMMIT")
        except Exception:
            self._rollback_if_open()
            raise
        return target

    def verify_replay_integrity(self) -> ReplayReport:
        rows = self.db.execute(
            "SELECT * FROM mpr19_event_journal ORDER BY sequence"
        ).fetchall()
        previous = _ZERO_HASH
        reconstructed: dict[str, tuple[str, str]] = {}
        terminal_count = 0
        for row in rows:
            payload_json = str(row["payload_json"])
            payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
            if payload_hash != str(row["payload_hash"]):
                raise MPR19AuthorityError("MPR19_JOURNAL_PAYLOAD_DIGEST_MISMATCH")
            if previous != str(row["previous_hash"]):
                raise MPR19AuthorityError("MPR19_JOURNAL_CHAIN_MISMATCH")
            expected_hash = _identity(
                "journal",
                {
                    "sequence": int(row["sequence"]),
                    "attempt_id": row["attempt_id"],
                    "event_type": row["event_type"],
                    "payload_hash": payload_hash,
                    "previous_hash": previous,
                    "created_ns": int(row["created_ns"]),
                },
            )
            if expected_hash != str(row["event_hash"]):
                raise MPR19AuthorityError("MPR19_JOURNAL_EVENT_HASH_MISMATCH")
            payload = json.loads(payload_json)
            if row["event_type"] == "attempt.created":
                reconstructed[str(row["attempt_id"])] = (
                    AttemptState.RECORDED.value,
                    ReservationState.ACTIVE.value,
                )
            elif row["event_type"] == "attempt.terminal":
                terminal_count += 1
                reconstructed[str(row["attempt_id"])] = (
                    str(payload["state"]),
                    str(payload["reservation_state"]),
                )
            previous = expected_hash
        for attempt_id, (state, reservation_state) in reconstructed.items():
            attempt = self.db.execute(
                "SELECT state FROM mpr19_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            reservation = self.db.execute(
                "SELECT state FROM mpr19_capital_reservations WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if attempt is None or str(attempt["state"]) != state:
                raise MPR19AuthorityError("MPR19_REPLAY_ATTEMPT_STATE_DIVERGED")
            if reservation is None or str(reservation["state"]) != reservation_state:
                raise MPR19AuthorityError("MPR19_REPLAY_RESERVATION_STATE_DIVERGED")
        pending = self.db.execute(
            "SELECT COUNT(*) FROM mpr19_outbox_events WHERE state IN (?,?)",
            (OutboxState.QUEUED.value, OutboxState.CLAIMED.value),
        ).fetchone()[0]
        return ReplayReport(len(rows), terminal_count, int(pending), previous)

    def backup_to(self, destination: str | Path) -> Path:
        target = Path(destination)
        _prepare_private_db_path(target)
        tmp = target.with_suffix(target.suffix + ".tmp")
        if tmp.exists():
            tmp.unlink()
        backup = sqlite3.connect(tmp)
        try:
            self.db.backup(backup)
        finally:
            backup.close()
        _chmod_private_file(tmp)
        restored = MPR19EconomicAuthority(tmp)
        try:
            restored.verify_replay_integrity()
        finally:
            restored.close()
        os.replace(tmp, target)
        _chmod_private_file(target)
        return target

    @classmethod
    def restore_verified(cls, backup: str | Path, destination: str | Path) -> "MPR19EconomicAuthority":
        source = Path(backup)
        if not source.is_file() or source.is_symlink():
            raise MPR19AuthorityError("MPR19_BACKUP_SOURCE_INVALID")
        target = Path(destination)
        _prepare_private_db_path(target)
        tmp = target.with_suffix(target.suffix + ".restore-tmp")
        if tmp.exists():
            tmp.unlink()
        shutil.copy2(source, tmp, follow_symlinks=False)
        _chmod_private_file(tmp)
        authority = cls(tmp)
        try:
            authority.verify_replay_integrity()
            authority.close()
            os.replace(tmp, target)
            _chmod_private_file(target)
            return cls(target)
        except Exception:
            authority.close()
            if tmp.exists():
                tmp.unlink()
            raise

    def _migrate(self) -> None:
        checksum = hashlib.sha256(_SCHEMA.encode()).hexdigest()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.executescript(_SCHEMA)
            row = self.db.execute(
                "SELECT checksum FROM mpr19_migrations WHERE migration_id=?",
                (_SCHEMA_ID,),
            ).fetchone()
            if row is None:
                self.db.execute(
                    "INSERT INTO mpr19_migrations VALUES(?,?,?)",
                    (_SCHEMA_ID, checksum, MPR19_SCHEMA_VERSION),
                )
            elif str(row["checksum"]) != checksum:
                raise MPR19AuthorityError("MPR19_MIGRATION_CHECKSUM_MISMATCH")
            self.db.execute("COMMIT")
        except Exception:
            self._rollback_if_open()
            raise

    def _insert_outbox(
        self,
        *,
        event_id: str,
        attempt_id: str,
        topic: str,
        payload: Mapping[str, object],
        now_ns: int,
    ) -> None:
        payload_json = _canonical_json(payload)
        self.db.execute(
            "INSERT INTO mpr19_outbox_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                attempt_id,
                topic,
                payload_json,
                hashlib.sha256(payload_json.encode()).hexdigest(),
                OutboxState.QUEUED.value,
                None,
                None,
                None,
                0,
                now_ns,
                None,
                now_ns,
                now_ns,
            ),
        )

    def _append_event(
        self, attempt_id: str, event_type: str, payload: Mapping[str, object], *, now_ns: int
    ) -> None:
        payload_json = _canonical_json(payload)
        payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
        row = self.db.execute(
            "SELECT event_hash FROM mpr19_event_journal ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_hash = _ZERO_HASH if row is None else str(row["event_hash"])
        sequence = int(
            self.db.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM mpr19_event_journal"
            ).fetchone()[0]
        )
        event_hash = _identity(
            "journal",
            {
                "sequence": sequence,
                "attempt_id": attempt_id,
                "event_type": event_type,
                "payload_hash": payload_hash,
                "previous_hash": previous_hash,
                "created_ns": now_ns,
            },
        )
        self.db.execute(
            "INSERT INTO mpr19_event_journal VALUES(?,?,?,?,?,?,?,?,?)",
            (
                sequence,
                _identity("event", {"event_hash": event_hash}),
                attempt_id,
                event_type,
                payload_json,
                payload_hash,
                previous_hash,
                event_hash,
                now_ns,
            ),
        )

    def _snapshot(self, attempt_id: str, *, replayed: bool) -> AttemptSnapshot:
        row = self.db.execute(
            "SELECT a.*,r.reservation_id,r.state AS reservation_state "
            "FROM mpr19_attempts a JOIN mpr19_capital_reservations r "
            "ON a.attempt_id=r.attempt_id WHERE a.attempt_id=?",
            (attempt_id,),
        ).fetchone()
        if row is None:
            raise MPR19AuthorityError("MPR19_ATTEMPT_NOT_FOUND")
        return AttemptSnapshot(
            attempt_id=str(row["attempt_id"]),
            reservation_id=str(row["reservation_id"]),
            state=AttemptState(str(row["state"])),
            reservation_state=ReservationState(str(row["reservation_state"])),
            revision=int(row["revision"]),
            outbox_event_id=str(row["outbox_event_id"]),
            replayed=replayed,
        )

    def _rollback_if_open(self) -> None:
        if self.db.in_transaction:
            self.db.execute("ROLLBACK")

    @staticmethod
    def _after(step: str, hook: StepHook | None) -> None:
        if hook is not None:
            hook(step)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS mpr19_migrations(
 migration_id TEXT PRIMARY KEY,
 checksum TEXT NOT NULL,
 schema_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mpr19_attempts(
 attempt_id TEXT PRIMARY KEY,
 opportunity_id TEXT NOT NULL,
 wallet_id TEXT NOT NULL,
 strategy TEXT NOT NULL,
 state TEXT NOT NULL,
 revision INTEGER NOT NULL CHECK(revision>=1),
 request_json TEXT NOT NULL,
 request_hash TEXT NOT NULL,
 created_ns INTEGER NOT NULL,
 updated_ns INTEGER NOT NULL,
 terminal_ns INTEGER,
 reason_code TEXT,
 outbox_event_id TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS mpr19_capital_reservations(
 reservation_id TEXT PRIMARY KEY,
 attempt_id TEXT NOT NULL UNIQUE REFERENCES mpr19_attempts(attempt_id) ON DELETE RESTRICT,
 wallet_id TEXT NOT NULL,
 amount_lamports INTEGER NOT NULL CHECK(amount_lamports>0),
 state TEXT NOT NULL,
 release_reason TEXT,
 updated_ns INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS mpr19_event_journal(
 sequence INTEGER PRIMARY KEY,
 event_id TEXT NOT NULL UNIQUE,
 attempt_id TEXT NOT NULL REFERENCES mpr19_attempts(attempt_id) ON DELETE RESTRICT,
 event_type TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 payload_hash TEXT NOT NULL,
 previous_hash TEXT NOT NULL,
 event_hash TEXT NOT NULL UNIQUE,
 created_ns INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS mpr19_outbox_events(
 event_id TEXT PRIMARY KEY,
 attempt_id TEXT NOT NULL REFERENCES mpr19_attempts(attempt_id) ON DELETE RESTRICT,
 topic TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 payload_hash TEXT NOT NULL,
 state TEXT NOT NULL,
 owner_id TEXT,
 claim_token TEXT,
 claim_expires_ns INTEGER,
 retry_count INTEGER NOT NULL CHECK(retry_count>=0),
 next_attempt_ns INTEGER NOT NULL,
 last_reason TEXT,
 created_ns INTEGER NOT NULL,
 updated_ns INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS mpr19_outbox_attempts(
 attempt_no INTEGER PRIMARY KEY AUTOINCREMENT,
 event_id TEXT NOT NULL REFERENCES mpr19_outbox_events(event_id) ON DELETE RESTRICT,
 owner_id TEXT NOT NULL,
 claim_token TEXT NOT NULL,
 result TEXT NOT NULL,
 reason_code TEXT NOT NULL,
 observed_ns INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS mpr19_journal_no_update
 BEFORE UPDATE ON mpr19_event_journal
 BEGIN SELECT RAISE(ABORT,'MPR19_JOURNAL_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS mpr19_journal_no_delete
 BEFORE DELETE ON mpr19_event_journal
 BEGIN SELECT RAISE(ABORT,'MPR19_JOURNAL_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS mpr19_outbox_attempt_no_update
 BEFORE UPDATE ON mpr19_outbox_attempts
 BEGIN SELECT RAISE(ABORT,'MPR19_OUTBOX_ATTEMPT_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS mpr19_outbox_attempt_no_delete
 BEFORE DELETE ON mpr19_outbox_attempts
 BEGIN SELECT RAISE(ABORT,'MPR19_OUTBOX_ATTEMPT_IMMUTABLE'); END;
"""


def _identity(kind: str, payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        _canonical_json({"schema": MPR19_SCHEMA_VERSION, "kind": kind, "payload": payload}).encode()
    ).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _canonical_value(value: object) -> object:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("bool/float/NaN are not valid durable identity values")
    if isinstance(value, int):
        if value < 0:
            raise ValueError("negative integers are not valid durable identity values")
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError("durable identity object keys must be non-empty strings")
            result[key] = _canonical_value(item)
        return result
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    raise ValueError(f"unsupported durable identity value: {type(value).__name__}")


def _strict_non_negative_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _strict_positive_int(value: int, name: str) -> None:
    _strict_non_negative_int(value, name)
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _prepare_private_db_path(path: Path) -> None:
    if path.exists() and path.is_symlink():
        raise MPR19AuthorityError("MPR19_DB_PATH_SYMLINK")
    parent = path.parent
    if parent.exists() and parent.is_symlink():
        raise MPR19AuthorityError("MPR19_DB_PARENT_SYMLINK")
    parent.mkdir(parents=True, exist_ok=True)
    os.chmod(parent, 0o700)


def _chmod_private_file(path: Path) -> None:
    if path.exists():
        os.chmod(path, 0o600)


__all__ = [
    "AttemptRequest",
    "AttemptSnapshot",
    "AttemptState",
    "MPR19AuthorityError",
    "MPR19EconomicAuthority",
    "OutboxClaim",
    "OutboxState",
    "ReplayReport",
    "ReservationState",
]

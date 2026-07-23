"""PR-195 canonical control-plane and durable lifecycle authority.

This module is deliberately sender-free.  It provides a small cutover-ready
control-plane kernel for PR-195: forward-only schema migration, schema
fingerprint evidence, boot-bound fencing, exact-revision transitions, immutable
events, config-generation binding, latch evidence, and fatal production config
key validation.

It does not sign, send, simulate, or enable live trading.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time
from uuid import uuid4

PR195_SCHEMA_VERSION = "pr195.canonical-control-plane.v1"
PR195_TARGET_MIGRATION = 4
ZERO_HASH = "0" * 64

_TERMINAL_STATES = frozenset(
    {"terminal_success", "terminal_failure", "rejected", "released"}
)

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "created": frozenset({"planned", "rejected"}),
    "planned": frozenset({"config_bound", "rejected"}),
    "config_bound": frozenset({"reserved", "rejected"}),
    "reserved": frozenset({"permit_issued", "released", "rejected"}),
    "permit_issued": frozenset(
        {"submission_intent_recorded", "permit_revoked", "rejected"}
    ),
    "submission_intent_recorded": frozenset(
        {"submission_uncertain", "reconciling"}
    ),
    "submission_uncertain": frozenset(
        {"reconciling", "latched_manual_review"}
    ),
    "reconciling": frozenset(
        {"terminal_success", "terminal_failure", "latched_manual_review"}
    ),
    "latched_manual_review": frozenset({"reconciling", "terminal_failure"}),
    "permit_revoked": frozenset({"released", "rejected"}),
    "released": frozenset(),
    "rejected": frozenset(),
    "terminal_success": frozenset(),
    "terminal_failure": frozenset(),
}


class PR195ControlPlaneError(RuntimeError):
    """Base error for PR-195 control-plane violations."""


class UnknownSchemaVersionError(PR195ControlPlaneError):
    """Raised when the DB is newer than this binary can interpret."""


class SchemaFingerprintError(PR195ControlPlaneError):
    """Raised when the durable schema does not match its fingerprint."""


class TransitionConflictError(PR195ControlPlaneError):
    """Raised on stale revision or optimistic write conflict."""


class IllegalTransitionError(PR195ControlPlaneError):
    """Raised when callers try to bypass the canonical state machine."""


class FenceLostError(PR195ControlPlaneError):
    """Raised when a boot/process fence is stale, expired, or cross-owner."""


class ConfigContractError(PR195ControlPlaneError):
    """Raised when runtime config material is not admitted."""


@dataclass(frozen=True, slots=True)
class TrustedTimeIdentity:
    boot_id: str
    process_generation: int
    monotonic_ns: int
    utc_ns: int
    max_uncertainty_ns: int = 0

    def __post_init__(self) -> None:
        if not self.boot_id.strip():
            raise ValueError("boot_id is required")
        if self.process_generation < 1:
            raise ValueError("process_generation must be positive")
        if self.monotonic_ns < 0 or self.utc_ns < 0:
            raise ValueError("time values must be non-negative")
        if self.max_uncertainty_ns < 0:
            raise ValueError("max_uncertainty_ns must be non-negative")


@dataclass(frozen=True, slots=True)
class ProcessFence:
    resource_key: str
    owner_id: str
    fencing_token: int
    boot_id: str
    process_generation: int
    expires_monotonic_ns: int
    expires_utc_ns: int


@dataclass(frozen=True, slots=True)
class BackupManifest:
    path: str
    sha256: str
    size_bytes: int
    created_utc_ns: int

    def to_json(self) -> dict[str, object]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "created_utc_ns": self.created_utc_ns,
        }


@dataclass(frozen=True, slots=True)
class SchemaFingerprint:
    schema_version: str
    migration_version: int
    digest: str
    objects: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "migration_version": self.migration_version,
            "digest": self.digest,
            "objects": list(self.objects),
        }


@dataclass(frozen=True, slots=True)
class ControlAttempt:
    attempt_id: str
    generation: int
    config_generation_hash: str
    state: str
    revision: int
    terminal: bool


@dataclass(frozen=True, slots=True)
class ControlTransition:
    attempt_id: str
    from_state: str | None
    to_state: str
    revision: int
    event_hash: str


@dataclass(frozen=True, slots=True)
class ConfigGeneration:
    generation_hash: str
    release_hash: str
    policy_hash: str
    approved_by: str
    evidence_hash: str
    active: bool = False


class SystemTrustedClock:
    """Same-process trusted clock identity used when no test clock is injected."""

    def __init__(self, *, boot_id: str | None = None) -> None:
        self.boot_id = boot_id or uuid4().hex
        self.process_generation = 1

    def snapshot(self) -> TrustedTimeIdentity:
        return TrustedTimeIdentity(
            boot_id=self.boot_id,
            process_generation=self.process_generation,
            monotonic_ns=time.monotonic_ns(),
            utc_ns=time.time_ns(),
            max_uncertainty_ns=0,
        )


class ManualTrustedClock:
    """Deterministic test clock with explicit boot-domain control."""

    def __init__(
        self,
        *,
        boot_id: str = "boot-a",
        process_generation: int = 1,
        monotonic_ns: int = 1_000_000,
        utc_ns: int = 2_000_000,
    ) -> None:
        self.boot_id = boot_id
        self.process_generation = process_generation
        self.monotonic_ns = monotonic_ns
        self.utc_ns = utc_ns

    def snapshot(self) -> TrustedTimeIdentity:
        return TrustedTimeIdentity(
            self.boot_id,
            self.process_generation,
            self.monotonic_ns,
            self.utc_ns,
        )

    def advance(self, ns: int) -> None:
        if ns < 0:
            raise ValueError("advance must be non-negative")
        self.monotonic_ns += ns
        self.utc_ns += ns

    def reboot(self, *, boot_id: str, process_generation: int | None = None) -> None:
        self.boot_id = boot_id
        self.process_generation = process_generation or self.process_generation + 1
        self.monotonic_ns = 0


_MIGRATIONS: tuple[tuple[int, str, str], ...] = (
    (
        1,
        "base-attempts-and-events",
        """
        CREATE TABLE IF NOT EXISTS pr195_migrations(
          version INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          checksum TEXT NOT NULL,
          schema_fingerprint TEXT NOT NULL,
          backup_manifest_json TEXT,
          applied_utc_ns INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pr195_attempts(
          attempt_id TEXT PRIMARY KEY,
          generation INTEGER NOT NULL CHECK(generation>=1),
          config_generation_hash TEXT NOT NULL,
          state TEXT NOT NULL,
          revision INTEGER NOT NULL CHECK(revision>=0),
          terminal INTEGER NOT NULL CHECK(terminal IN (0,1)),
          reservation_id TEXT,
          permit_id TEXT,
          created_boot_id TEXT NOT NULL,
          created_process_generation INTEGER NOT NULL,
          created_monotonic_ns INTEGER NOT NULL,
          created_utc_ns INTEGER NOT NULL,
          updated_boot_id TEXT NOT NULL,
          updated_process_generation INTEGER NOT NULL,
          updated_monotonic_ns INTEGER NOT NULL,
          updated_utc_ns INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pr195_attempt_events(
          event_id TEXT PRIMARY KEY,
          attempt_id TEXT NOT NULL
            REFERENCES pr195_attempts(attempt_id) ON DELETE RESTRICT,
          revision INTEGER NOT NULL CHECK(revision>=0),
          idempotency_key TEXT NOT NULL UNIQUE,
          event_type TEXT NOT NULL,
          from_state TEXT,
          to_state TEXT NOT NULL,
          reason_code TEXT,
          evidence_json TEXT NOT NULL,
          evidence_hash TEXT NOT NULL,
          previous_event_hash TEXT NOT NULL,
          event_hash TEXT NOT NULL,
          boot_id TEXT NOT NULL,
          process_generation INTEGER NOT NULL,
          monotonic_ns INTEGER NOT NULL,
          utc_ns INTEGER NOT NULL,
          UNIQUE(attempt_id, revision)
        );
        CREATE INDEX IF NOT EXISTS idx_pr195_attempt_events_attempt
          ON pr195_attempt_events(attempt_id, revision);
        """,
    ),
    (
        2,
        "config-generations-and-fences",
        """
        CREATE TABLE IF NOT EXISTS pr195_config_generations(
          generation_hash TEXT PRIMARY KEY,
          release_hash TEXT NOT NULL,
          policy_hash TEXT NOT NULL,
          approved_by TEXT NOT NULL,
          evidence_hash TEXT NOT NULL,
          active INTEGER NOT NULL CHECK(active IN (0,1)),
          created_boot_id TEXT NOT NULL,
          created_process_generation INTEGER NOT NULL,
          created_monotonic_ns INTEGER NOT NULL,
          created_utc_ns INTEGER NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pr195_active_generation
          ON pr195_config_generations(active) WHERE active=1;
        CREATE TABLE IF NOT EXISTS pr195_fences(
          resource_key TEXT PRIMARY KEY,
          owner_id TEXT NOT NULL,
          fencing_token INTEGER NOT NULL CHECK(fencing_token>=1),
          boot_id TEXT NOT NULL,
          process_generation INTEGER NOT NULL CHECK(process_generation>=1),
          acquired_monotonic_ns INTEGER NOT NULL,
          expires_monotonic_ns INTEGER NOT NULL,
          acquired_utc_ns INTEGER NOT NULL,
          expires_utc_ns INTEGER NOT NULL,
          CHECK(expires_monotonic_ns>acquired_monotonic_ns)
        );
        """,
    ),
    (
        3,
        "latches",
        """
        CREATE TABLE IF NOT EXISTS pr195_latches(
          latch_id TEXT PRIMARY KEY,
          active INTEGER NOT NULL CHECK(active IN (0,1)),
          reason_code TEXT NOT NULL,
          evidence_json TEXT NOT NULL,
          evidence_hash TEXT NOT NULL,
          acknowledged_by TEXT,
          clear_approval_hash TEXT,
          created_boot_id TEXT NOT NULL,
          created_process_generation INTEGER NOT NULL,
          created_monotonic_ns INTEGER NOT NULL,
          created_utc_ns INTEGER NOT NULL,
          cleared_boot_id TEXT,
          cleared_process_generation INTEGER,
          cleared_monotonic_ns INTEGER,
          cleared_utc_ns INTEGER
        );
        """,
    ),
    (
        4,
        "immutability-triggers",
        """
        CREATE TRIGGER IF NOT EXISTS pr195_events_no_update
        BEFORE UPDATE ON pr195_attempt_events
        BEGIN
          SELECT RAISE(ABORT, 'pr195 events are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS pr195_events_no_delete
        BEFORE DELETE ON pr195_attempt_events
        BEGIN
          SELECT RAISE(ABORT, 'pr195 events are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS pr195_migrations_no_delete
        BEFORE DELETE ON pr195_migrations
        BEGIN
          SELECT RAISE(ABORT, 'pr195 migrations are immutable');
        END;
        """,
    ),
)


class CanonicalControlPlaneStore:
    """One transactionally consistent PR-195 lifecycle authority."""

    def __init__(
        self,
        path: str | Path,
        *,
        trusted_clock: SystemTrustedClock | ManualTrustedClock | None = None,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        self.path = str(path)
        self.trusted_clock = trusted_clock or SystemTrustedClock()
        self.db = sqlite3.connect(
            self.path,
            isolation_level=None,
            timeout=busy_timeout_ms / 1000,
            check_same_thread=False,
        )
        self.db.row_factory = sqlite3.Row
        for pragma in (
            f"PRAGMA busy_timeout={busy_timeout_ms}",
            "PRAGMA foreign_keys=ON",
            "PRAGMA synchronous=FULL",
            "PRAGMA trusted_schema=OFF",
        ):
            self.db.execute(pragma)
        if self.path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.backup_manifest = self._migrate_forward_only()
        self.assert_schema_fingerprint()

    def __enter__(self) -> "CanonicalControlPlaneStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.db.close()

    def _now(self) -> TrustedTimeIdentity:
        return self.trusted_clock.snapshot()

    def _existing_version(self) -> int:
        try:
            row = self.db.execute(
                "SELECT MAX(version) AS version FROM pr195_migrations"
            ).fetchone()
        except sqlite3.OperationalError:
            return 0
        return int(row["version"] or 0)

    def _database_has_content(self) -> bool:
        row = self.db.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type IN ('table','index','trigger','view') "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchone()
        return int(row[0]) > 0

    def _backup_before_migrate(self) -> BackupManifest | None:
        if self.path == ":memory:" or not Path(self.path).exists():
            return None
        if not self._database_has_content():
            return None
        now = self._now()
        backup = Path(f"{self.path}.pr195-backup-{now.utc_ns}.sqlite")
        self.db.commit()
        self.db.close()
        shutil.copy2(self.path, backup)
        data = backup.read_bytes()
        manifest = BackupManifest(
            path=str(backup),
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            created_utc_ns=now.utc_ns,
        )
        self.db = sqlite3.connect(
            self.path,
            isolation_level=None,
            timeout=5.0,
            check_same_thread=False,
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA trusted_schema=OFF")
        if self.path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        return manifest

    def _migrate_forward_only(self) -> BackupManifest | None:
        existing = self._existing_version()
        if existing > PR195_TARGET_MIGRATION:
            raise UnknownSchemaVersionError(
                f"database version {existing} is newer than "
                f"PR-195 target {PR195_TARGET_MIGRATION}"
            )
        backup = None
        if existing < PR195_TARGET_MIGRATION:
            backup = self._backup_before_migrate()
        now = self._now()
        backup_json = (
            json.dumps(backup.to_json(), sort_keys=True) if backup is not None else None
        )
        for version, name, sql in _MIGRATIONS:
            if version <= existing:
                continue
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            self.db.executescript(sql)
            fingerprint = self.schema_fingerprint().digest
            with self.db:
                self.db.execute(
                    "INSERT INTO pr195_migrations VALUES(?,?,?,?,?,?)",
                    (version, name, checksum, fingerprint, backup_json, now.utc_ns),
                )
                self.db.execute(f"PRAGMA user_version={version}")
        return backup

    def schema_fingerprint(self) -> SchemaFingerprint:
        rows = self.db.execute(
            "SELECT type,name,sql FROM sqlite_master "
            "WHERE sql IS NOT NULL AND name LIKE 'pr195_%' "
            "ORDER BY type,name"
        ).fetchall()
        objects = tuple(
            f"{row['type']}:{row['name']}:{' '.join(str(row['sql']).split())}"
            for row in rows
        )
        payload = json.dumps(
            {
                "schema_version": PR195_SCHEMA_VERSION,
                "migration_version": PR195_TARGET_MIGRATION,
                "objects": objects,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return SchemaFingerprint(
            PR195_SCHEMA_VERSION,
            PR195_TARGET_MIGRATION,
            hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            objects,
        )

    def assert_schema_fingerprint(self) -> None:
        version = self._existing_version()
        if version != PR195_TARGET_MIGRATION:
            raise SchemaFingerprintError(
                f"expected migration {PR195_TARGET_MIGRATION}, got {version}"
            )
        fingerprint = self.schema_fingerprint().digest
        row = self.db.execute(
            "SELECT schema_fingerprint FROM pr195_migrations "
            "WHERE version=?",
            (PR195_TARGET_MIGRATION,),
        ).fetchone()
        if row is None or str(row["schema_fingerprint"]) != fingerprint:
            raise SchemaFingerprintError("PR-195 schema fingerprint mismatch")

    def record_config_generation(self, generation: ConfigGeneration) -> None:
        now = self._now()
        for digest in (
            generation.generation_hash,
            generation.release_hash,
            generation.policy_hash,
            generation.evidence_hash,
        ):
            _require_sha256(digest)
        with self.db:
            if generation.active:
                self.db.execute(
                    "UPDATE pr195_config_generations SET active=0 WHERE active=1"
                )
            self.db.execute(
                "INSERT INTO pr195_config_generations VALUES(?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(generation_hash) DO UPDATE SET "
                "release_hash=excluded.release_hash,"
                "policy_hash=excluded.policy_hash,"
                "approved_by=excluded.approved_by,"
                "evidence_hash=excluded.evidence_hash,"
                "active=excluded.active",
                (
                    generation.generation_hash,
                    generation.release_hash,
                    generation.policy_hash,
                    generation.approved_by,
                    generation.evidence_hash,
                    int(generation.active),
                    now.boot_id,
                    now.process_generation,
                    now.monotonic_ns,
                    now.utc_ns,
                ),
            )

    def active_config_generation_hash(self) -> str:
        row = self.db.execute(
            "SELECT generation_hash FROM pr195_config_generations WHERE active=1"
        ).fetchone()
        if row is None:
            raise ConfigContractError("runtime has no active signed generation")
        return str(row["generation_hash"])

    def create_attempt(
        self,
        *,
        attempt_id: str,
        generation: int,
        config_generation_hash: str | None = None,
        idempotency_key: str,
        evidence: Mapping[str, object] | None = None,
    ) -> ControlAttempt:
        if not attempt_id.strip() or generation < 1:
            raise ValueError("attempt_id and positive generation are required")
        config_hash = config_generation_hash or self.active_config_generation_hash()
        _require_sha256(config_hash)
        now = self._now()
        with self.db:
            found = self.db.execute(
                "SELECT * FROM pr195_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if found is not None:
                duplicate = self.db.execute(
                    "SELECT 1 FROM pr195_attempt_events WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                if duplicate:
                    return _attempt_from_row(found)
                raise TransitionConflictError("attempt already exists")
            self.db.execute(
                "INSERT INTO pr195_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    attempt_id,
                    generation,
                    config_hash,
                    "created",
                    0,
                    0,
                    None,
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
            event_hash = self._insert_event(
                attempt_id=attempt_id,
                revision=0,
                idempotency_key=idempotency_key,
                event_type="attempt_created",
                from_state=None,
                to_state="created",
                reason_code="ATTEMPT_CREATED",
                evidence=evidence,
                now=now,
            )
        attempt = self.get_attempt(attempt_id)
        if attempt is None:
            raise PR195ControlPlaneError("attempt disappeared")
        if not event_hash:
            raise PR195ControlPlaneError("event hash missing")
        return attempt

    def get_attempt(self, attempt_id: str) -> ControlAttempt | None:
        row = self.db.execute(
            "SELECT * FROM pr195_attempts WHERE attempt_id=?",
            (attempt_id,),
        ).fetchone()
        return _attempt_from_row(row) if row is not None else None

    def acquire_fence(
        self,
        resource_key: str,
        *,
        owner_id: str,
        ttl_ns: int,
    ) -> ProcessFence:
        if not resource_key.strip() or not owner_id.strip() or ttl_ns <= 0:
            raise ValueError("resource, owner and positive ttl are required")
        now = self._now()
        expires_mono = now.monotonic_ns + ttl_ns
        expires_utc = now.utc_ns + ttl_ns
        with self.db:
            row = self.db.execute(
                "SELECT * FROM pr195_fences WHERE resource_key=?",
                (resource_key,),
            ).fetchone()
            if row is not None:
                same_domain = (
                    row["boot_id"] == now.boot_id
                    and int(row["process_generation"]) == now.process_generation
                )
                live = same_domain and (
                    int(row["expires_monotonic_ns"]) > now.monotonic_ns
                )
                if live and row["owner_id"] != owner_id:
                    raise FenceLostError("resource has another live owner")
                token = int(row["fencing_token"]) + 1
            else:
                token = 1
            self.db.execute(
                "INSERT INTO pr195_fences VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(resource_key) DO UPDATE SET "
                "owner_id=excluded.owner_id,"
                "fencing_token=excluded.fencing_token,"
                "boot_id=excluded.boot_id,"
                "process_generation=excluded.process_generation,"
                "acquired_monotonic_ns=excluded.acquired_monotonic_ns,"
                "expires_monotonic_ns=excluded.expires_monotonic_ns,"
                "acquired_utc_ns=excluded.acquired_utc_ns,"
                "expires_utc_ns=excluded.expires_utc_ns",
                (
                    resource_key,
                    owner_id,
                    token,
                    now.boot_id,
                    now.process_generation,
                    now.monotonic_ns,
                    expires_mono,
                    now.utc_ns,
                    expires_utc,
                ),
            )
        return ProcessFence(
            resource_key,
            owner_id,
            token,
            now.boot_id,
            now.process_generation,
            expires_mono,
            expires_utc,
        )

    def append_transition(
        self,
        *,
        attempt_id: str,
        expected_revision: int,
        target_state: str,
        idempotency_key: str,
        fence: ProcessFence,
        reason_code: str,
        evidence: Mapping[str, object] | None = None,
        reservation_id: str | None = None,
        permit_id: str | None = None,
    ) -> ControlTransition:
        target = _state(target_state)
        now = self._now()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self._verify_fence(fence, f"attempt:{attempt_id}", now)
            duplicate = self.db.execute(
                "SELECT * FROM pr195_attempt_events WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if duplicate is not None:
                if duplicate["attempt_id"] != attempt_id:
                    raise TransitionConflictError("idempotency collision")
                self.db.execute("COMMIT")
                return ControlTransition(
                    attempt_id,
                    duplicate["from_state"],
                    duplicate["to_state"],
                    int(duplicate["revision"]),
                    str(duplicate["event_hash"]),
                )
            row = self.db.execute(
                "SELECT * FROM pr195_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise TransitionConflictError("attempt not found")
            current = _state(str(row["state"]))
            revision = int(row["revision"])
            if revision != expected_revision:
                raise TransitionConflictError("optimistic revision conflict")
            if target not in _ALLOWED_TRANSITIONS[current]:
                raise IllegalTransitionError(f"illegal transition {current}->{target}")
            next_revision = revision + 1
            terminal = int(target in _TERMINAL_STATES)
            cur = self.db.execute(
                "UPDATE pr195_attempts SET state=?,revision=?,terminal=?,"
                "reservation_id=COALESCE(?,reservation_id),"
                "permit_id=COALESCE(?,permit_id),"
                "updated_boot_id=?,updated_process_generation=?,"
                "updated_monotonic_ns=?,updated_utc_ns=? "
                "WHERE attempt_id=? AND revision=?",
                (
                    target,
                    next_revision,
                    terminal,
                    reservation_id,
                    permit_id,
                    now.boot_id,
                    now.process_generation,
                    now.monotonic_ns,
                    now.utc_ns,
                    attempt_id,
                    revision,
                ),
            )
            if cur.rowcount != 1:
                raise TransitionConflictError("optimistic write conflict")
            event_hash = self._insert_event(
                attempt_id=attempt_id,
                revision=next_revision,
                idempotency_key=idempotency_key,
                event_type="state_transition",
                from_state=current,
                to_state=target,
                reason_code=reason_code,
                evidence=evidence,
                now=now,
            )
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        else:
            self.db.execute("COMMIT")
        return ControlTransition(
            attempt_id,
            current,
            target,
            next_revision,
            event_hash,
        )

    def _verify_fence(
        self,
        fence: ProcessFence,
        expected_resource: str,
        now: TrustedTimeIdentity,
    ) -> None:
        if fence.resource_key != expected_resource:
            raise FenceLostError("fence resource does not match transition")
        row = self.db.execute(
            "SELECT * FROM pr195_fences WHERE resource_key=?",
            (expected_resource,),
        ).fetchone()
        valid = (
            row is not None
            and row["owner_id"] == fence.owner_id
            and int(row["fencing_token"]) == fence.fencing_token
            and str(row["boot_id"]) == now.boot_id == fence.boot_id
            and int(row["process_generation"]) == now.process_generation
            and now.process_generation == fence.process_generation
            and int(row["expires_monotonic_ns"]) > now.monotonic_ns
        )
        if not valid:
            raise FenceLostError("stale, expired, or cross-boot fence")

    def _insert_event(
        self,
        *,
        attempt_id: str,
        revision: int,
        idempotency_key: str,
        event_type: str,
        from_state: str | None,
        to_state: str,
        reason_code: str,
        evidence: Mapping[str, object] | None,
        now: TrustedTimeIdentity,
    ) -> str:
        previous = self.db.execute(
            "SELECT event_hash FROM pr195_attempt_events WHERE attempt_id=? "
            "ORDER BY revision DESC LIMIT 1",
            (attempt_id,),
        ).fetchone()
        previous_hash = str(previous["event_hash"]) if previous else ZERO_HASH
        evidence_json = _stable_json(dict(evidence or {}))
        evidence_hash = hashlib.sha256(evidence_json.encode("utf-8")).hexdigest()
        event_hash = _hash_event(
            attempt_id=attempt_id,
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
            "INSERT INTO pr195_attempt_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                uuid4().hex,
                attempt_id,
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

    def event_chain(self, attempt_id: str) -> tuple[ControlTransition, ...]:
        rows = self.db.execute(
            "SELECT * FROM pr195_attempt_events WHERE attempt_id=? "
            "ORDER BY revision",
            (attempt_id,),
        ).fetchall()
        return tuple(
            ControlTransition(
                str(row["attempt_id"]),
                row["from_state"],
                str(row["to_state"]),
                int(row["revision"]),
                str(row["event_hash"]),
            )
            for row in rows
        )

    def reconstruct_attempt_state(self, attempt_id: str) -> ControlAttempt:
        attempt = self.get_attempt(attempt_id)
        if attempt is None:
            raise TransitionConflictError("attempt not found")
        events = self.event_chain(attempt_id)
        if not events:
            raise SchemaFingerprintError("attempt has no event history")
        last = events[-1]
        if last.to_state != attempt.state or last.revision != attempt.revision:
            raise SchemaFingerprintError("current row diverges from event chain")
        return attempt

    def open_latch(
        self,
        *,
        latch_id: str,
        reason_code: str,
        evidence: Mapping[str, object],
    ) -> str:
        now = self._now()
        evidence_json = _stable_json(dict(evidence))
        evidence_hash = hashlib.sha256(evidence_json.encode("utf-8")).hexdigest()
        with self.db:
            self.db.execute(
                "INSERT INTO pr195_latches VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    latch_id,
                    1,
                    reason_code,
                    evidence_json,
                    evidence_hash,
                    None,
                    None,
                    now.boot_id,
                    now.process_generation,
                    now.monotonic_ns,
                    now.utc_ns,
                    None,
                    None,
                    None,
                    None,
                ),
            )
        return evidence_hash

    def clear_latch(
        self,
        *,
        latch_id: str,
        acknowledged_by: str,
        clear_approval_hash: str,
    ) -> None:
        _require_sha256(clear_approval_hash)
        if not acknowledged_by.strip():
            raise ValueError("acknowledged_by is required")
        now = self._now()
        with self.db:
            cur = self.db.execute(
                "UPDATE pr195_latches SET active=0,acknowledged_by=?,"
                "clear_approval_hash=?,cleared_boot_id=?,"
                "cleared_process_generation=?,cleared_monotonic_ns=?,"
                "cleared_utc_ns=? WHERE latch_id=? AND active=1",
                (
                    acknowledged_by,
                    clear_approval_hash,
                    now.boot_id,
                    now.process_generation,
                    now.monotonic_ns,
                    now.utc_ns,
                    latch_id,
                ),
            )
            if cur.rowcount != 1:
                raise TransitionConflictError("latch not active or not found")

    def validate_unknown_flashloan_env(
        self,
        environ: Mapping[str, str],
        *,
        allowed_names: set[str] | frozenset[str],
        production: bool = True,
    ) -> tuple[str, ...]:
        unknown = tuple(
            sorted(
                key
                for key in environ
                if key.startswith("FLASHLOAN_") and key not in allowed_names
            )
        )
        if production and unknown:
            raise ConfigContractError(
                "unknown FLASHLOAN_* keys in production: " + ", ".join(unknown)
            )
        return unknown

    def live_capability_allowed(self) -> bool:
        return False


def _attempt_from_row(row: sqlite3.Row) -> ControlAttempt:
    return ControlAttempt(
        attempt_id=str(row["attempt_id"]),
        generation=int(row["generation"]),
        config_generation_hash=str(row["config_generation_hash"]),
        state=str(row["state"]),
        revision=int(row["revision"]),
        terminal=bool(row["terminal"]),
    )


def _state(value: str) -> str:
    normalized = value.strip()
    if normalized not in _ALLOWED_TRANSITIONS:
        raise IllegalTransitionError(f"unknown PR-195 state {value!r}")
    return normalized


def _stable_json(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _hash_event(
    *,
    attempt_id: str,
    revision: int,
    event_type: str,
    from_state: str | None,
    to_state: str,
    reason_code: str,
    evidence_hash: str,
    previous_event_hash: str,
    now: TrustedTimeIdentity,
) -> str:
    return hashlib.sha256(
        _stable_json(
            {
                "schema": PR195_SCHEMA_VERSION,
                "attempt_id": attempt_id,
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
        ).encode("utf-8")
    ).hexdigest()


def _require_sha256(value: str) -> None:
    if len(value) != 64:
        raise ValueError("sha256 digest must be 64 hex characters")
    int(value, 16)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "BackupManifest",
    "CanonicalControlPlaneStore",
    "ConfigContractError",
    "ConfigGeneration",
    "ControlAttempt",
    "ControlTransition",
    "FenceLostError",
    "IllegalTransitionError",
    "ManualTrustedClock",
    "PR195ControlPlaneError",
    "PR195_SCHEMA_VERSION",
    "ProcessFence",
    "SchemaFingerprint",
    "SchemaFingerprintError",
    "SystemTrustedClock",
    "TransitionConflictError",
    "TrustedTimeIdentity",
    "UnknownSchemaVersionError",
    "sha256_text",
]

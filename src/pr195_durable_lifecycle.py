"""PR-195 durable lifecycle follow-up gates.

This module is deliberately sender-free.  It strengthens the merged PR-195
control-plane foundation with the two durable boundaries that must exist before
the queue/runtime work in PR-198 can rely on it:

* a transactional opportunity lifecycle key authority so expiry releases the
  pending dedupe state instead of leaving an opportunity blocked forever;
* a serializable wallet-reservation authority so concurrent paper/live writers
  cannot reserve the same native balance twice.

The implementation is intentionally small and offline-only.  It performs no
network access, transaction construction, signing, submission or live trading.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

ZERO_HASH = "0" * 64
PR195_DURABLE_LIFECYCLE_SCHEMA = "pr195.durable-lifecycle.v1"
PR195_DURABLE_LIFECYCLE_MIGRATION = 1

_ACTIVE_OPPORTUNITY_STATES = frozenset({"pending", "claimed"})
_TERMINAL_OPPORTUNITY_STATES = frozenset(
    {"expired", "terminal_success", "terminal_failure", "rejected", "released"}
)
_ALLOWED_OPPORTUNITY_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"claimed", "expired", "rejected", "released"}),
    "claimed": frozenset({"terminal_success", "terminal_failure", "expired", "rejected", "released"}),
    "expired": frozenset(),
    "terminal_success": frozenset(),
    "terminal_failure": frozenset(),
    "rejected": frozenset(),
    "released": frozenset(),
}


class PR195DurableLifecycleError(RuntimeError):
    """Base class for PR-195 durable lifecycle violations."""


class DuplicateLifecycleKeyError(PR195DurableLifecycleError):
    """Raised when an active or retained lifecycle key blocks admission."""


class LifecycleTransitionError(PR195DurableLifecycleError):
    """Raised for stale revisions, missing rows or illegal transitions."""


class CapitalReservationError(PR195DurableLifecycleError):
    """Raised when a wallet reservation would violate the serializable budget."""


@dataclass(frozen=True, slots=True)
class TrustedLifecycleTime:
    boot_id: str
    process_generation: int
    monotonic_ns: int
    utc_ns: int

    def __post_init__(self) -> None:
        if not self.boot_id.strip():
            raise ValueError("boot_id is required")
        if self.process_generation < 1:
            raise ValueError("process_generation must be positive")
        if self.monotonic_ns < 0 or self.utc_ns < 0:
            raise ValueError("time values must be non-negative")


class SystemLifecycleClock:
    """Same-process lifecycle clock used when tests do not inject one."""

    def __init__(self, *, boot_id: str | None = None) -> None:
        self.boot_id = boot_id or uuid4().hex
        self.process_generation = 1

    def snapshot(self) -> TrustedLifecycleTime:
        return TrustedLifecycleTime(
            self.boot_id,
            self.process_generation,
            time.monotonic_ns(),
            time.time_ns(),
        )


class ManualLifecycleClock:
    """Deterministic lifecycle clock for crash/restart/expiry tests."""

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

    def snapshot(self) -> TrustedLifecycleTime:
        return TrustedLifecycleTime(
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


@dataclass(frozen=True, slots=True)
class OpportunityLifecycle:
    opportunity_id: str
    lifecycle_key: str
    state: str
    revision: int
    terminal: bool
    expires_monotonic_ns: int
    dedupe_block_until_monotonic_ns: int | None


@dataclass(frozen=True, slots=True)
class WalletReservation:
    reservation_id: str
    wallet_id: str
    attempt_id: str
    lamports: int
    state: str
    revision: int
    charged_fee_lamports: int


class DurableLifecycleStore:
    """SQLite/WAL authority for PR-195 opportunity dedupe and reservations."""

    def __init__(
        self,
        path: str | Path,
        *,
        trusted_clock: SystemLifecycleClock | ManualLifecycleClock | None = None,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        self.path = str(path)
        self.trusted_clock = trusted_clock or SystemLifecycleClock()
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
        self._migrate()

    def __enter__(self) -> "DurableLifecycleStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.db.close()

    def _now(self) -> TrustedLifecycleTime:
        return self.trusted_clock.snapshot()

    def _migrate(self) -> None:
        with self.db:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS pr195_durable_migrations(
                  version INTEGER PRIMARY KEY,
                  schema_name TEXT NOT NULL,
                  checksum TEXT NOT NULL,
                  applied_utc_ns INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pr195_opportunities(
                  opportunity_id TEXT PRIMARY KEY,
                  lifecycle_key TEXT NOT NULL,
                  state TEXT NOT NULL,
                  revision INTEGER NOT NULL CHECK(revision>=0),
                  terminal INTEGER NOT NULL CHECK(terminal IN (0,1)),
                  expires_monotonic_ns INTEGER NOT NULL,
                  dedupe_block_until_monotonic_ns INTEGER,
                  created_boot_id TEXT NOT NULL,
                  created_process_generation INTEGER NOT NULL,
                  created_monotonic_ns INTEGER NOT NULL,
                  created_utc_ns INTEGER NOT NULL,
                  updated_boot_id TEXT NOT NULL,
                  updated_process_generation INTEGER NOT NULL,
                  updated_monotonic_ns INTEGER NOT NULL,
                  updated_utc_ns INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pr195_lifecycle_keys(
                  lifecycle_key TEXT PRIMARY KEY,
                  opportunity_id TEXT NOT NULL
                    REFERENCES pr195_opportunities(opportunity_id) ON DELETE RESTRICT,
                  state TEXT NOT NULL,
                  expires_monotonic_ns INTEGER NOT NULL,
                  dedupe_block_until_monotonic_ns INTEGER,
                  updated_boot_id TEXT NOT NULL,
                  updated_process_generation INTEGER NOT NULL,
                  updated_monotonic_ns INTEGER NOT NULL,
                  updated_utc_ns INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pr195_opportunity_events(
                  event_id TEXT PRIMARY KEY,
                  opportunity_id TEXT NOT NULL
                    REFERENCES pr195_opportunities(opportunity_id) ON DELETE RESTRICT,
                  revision INTEGER NOT NULL CHECK(revision>=0),
                  idempotency_key TEXT NOT NULL UNIQUE,
                  event_type TEXT NOT NULL,
                  from_state TEXT,
                  to_state TEXT NOT NULL,
                  reason_code TEXT NOT NULL,
                  evidence_json TEXT NOT NULL,
                  evidence_hash TEXT NOT NULL,
                  previous_event_hash TEXT NOT NULL,
                  event_hash TEXT NOT NULL,
                  boot_id TEXT NOT NULL,
                  process_generation INTEGER NOT NULL,
                  monotonic_ns INTEGER NOT NULL,
                  utc_ns INTEGER NOT NULL,
                  UNIQUE(opportunity_id, revision)
                );

                CREATE TABLE IF NOT EXISTS pr195_wallet_reservations(
                  reservation_id TEXT PRIMARY KEY,
                  wallet_id TEXT NOT NULL,
                  attempt_id TEXT NOT NULL,
                  lamports INTEGER NOT NULL CHECK(lamports>0),
                  state TEXT NOT NULL,
                  revision INTEGER NOT NULL CHECK(revision>=0),
                  idempotency_key TEXT NOT NULL UNIQUE,
                  charged_fee_lamports INTEGER NOT NULL DEFAULT 0 CHECK(charged_fee_lamports>=0),
                  created_boot_id TEXT NOT NULL,
                  created_process_generation INTEGER NOT NULL,
                  created_monotonic_ns INTEGER NOT NULL,
                  created_utc_ns INTEGER NOT NULL,
                  updated_boot_id TEXT NOT NULL,
                  updated_process_generation INTEGER NOT NULL,
                  updated_monotonic_ns INTEGER NOT NULL,
                  updated_utc_ns INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_pr195_lifecycle_keys_state
                  ON pr195_lifecycle_keys(state, dedupe_block_until_monotonic_ns);
                CREATE INDEX IF NOT EXISTS idx_pr195_opportunities_key
                  ON pr195_opportunities(lifecycle_key, revision);
                CREATE INDEX IF NOT EXISTS idx_pr195_wallet_active
                  ON pr195_wallet_reservations(wallet_id, state);

                CREATE TRIGGER IF NOT EXISTS pr195_opportunity_events_no_update
                BEFORE UPDATE ON pr195_opportunity_events
                BEGIN
                  SELECT RAISE(ABORT, 'pr195 opportunity events are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS pr195_opportunity_events_no_delete
                BEFORE DELETE ON pr195_opportunity_events
                BEGIN
                  SELECT RAISE(ABORT, 'pr195 opportunity events are immutable');
                END;
                """
            )
            checksum = hashlib.sha256(
                PR195_DURABLE_LIFECYCLE_SCHEMA.encode("utf-8")
            ).hexdigest()
            self.db.execute(
                "INSERT OR IGNORE INTO pr195_durable_migrations VALUES(?,?,?,?)",
                (
                    PR195_DURABLE_LIFECYCLE_MIGRATION,
                    PR195_DURABLE_LIFECYCLE_SCHEMA,
                    checksum,
                    self._now().utc_ns,
                ),
            )

    def admit_opportunity(
        self,
        *,
        opportunity_id: str,
        lifecycle_key: str,
        expires_after_ns: int,
        idempotency_key: str,
        terminal_retention_ns: int,
        evidence: Mapping[str, object] | None = None,
    ) -> OpportunityLifecycle:
        if not opportunity_id.strip() or not lifecycle_key.strip():
            raise ValueError("opportunity_id and lifecycle_key are required")
        if expires_after_ns <= 0 or terminal_retention_ns < 0:
            raise ValueError("expiry and retention values are invalid")
        now = self._now()
        expires_at = now.monotonic_ns + expires_after_ns
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self._expire_due_locked(now, terminal_retention_ns=terminal_retention_ns)
            self._compact_dedupe_locked(now)
            existing_event = self.db.execute(
                "SELECT opportunity_id FROM pr195_opportunity_events WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing_event is not None:
                row = self._opportunity_row(str(existing_event["opportunity_id"]))
                if row is None:
                    raise LifecycleTransitionError("idempotent opportunity row missing")
                self.db.execute("COMMIT")
                return _opportunity_from_row(row)

            blocker = self.db.execute(
                "SELECT * FROM pr195_lifecycle_keys WHERE lifecycle_key=?",
                (lifecycle_key,),
            ).fetchone()
            if blocker is not None:
                raise DuplicateLifecycleKeyError(
                    "lifecycle key is active or retained: "
                    f"{lifecycle_key} -> {blocker['opportunity_id']}"
                )

            self.db.execute(
                "INSERT INTO pr195_opportunities VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    opportunity_id,
                    lifecycle_key,
                    "pending",
                    0,
                    0,
                    expires_at,
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
                "INSERT INTO pr195_lifecycle_keys VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    lifecycle_key,
                    opportunity_id,
                    "pending",
                    expires_at,
                    None,
                    now.boot_id,
                    now.process_generation,
                    now.monotonic_ns,
                    now.utc_ns,
                ),
            )
            self._insert_opportunity_event(
                opportunity_id=opportunity_id,
                revision=0,
                idempotency_key=idempotency_key,
                event_type="opportunity_admitted",
                from_state=None,
                to_state="pending",
                reason_code="OPPORTUNITY_ADMITTED",
                evidence=evidence,
                now=now,
            )
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")
        admitted = self.get_opportunity(opportunity_id)
        if admitted is None:
            raise LifecycleTransitionError("opportunity disappeared after commit")
        return admitted

    def claim_opportunity(
        self,
        *,
        opportunity_id: str,
        expected_revision: int,
        idempotency_key: str,
        evidence: Mapping[str, object] | None = None,
    ) -> OpportunityLifecycle:
        return self._transition_opportunity(
            opportunity_id=opportunity_id,
            expected_revision=expected_revision,
            target_state="claimed",
            idempotency_key=idempotency_key,
            reason_code="OPPORTUNITY_CLAIMED",
            terminal_retention_ns=0,
            evidence=evidence,
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
    ) -> OpportunityLifecycle:
        if target_state not in _TERMINAL_OPPORTUNITY_STATES:
            raise LifecycleTransitionError("finish target must be terminal")
        if terminal_retention_ns < 0:
            raise ValueError("terminal retention must be non-negative")
        return self._transition_opportunity(
            opportunity_id=opportunity_id,
            expected_revision=expected_revision,
            target_state=target_state,
            idempotency_key=idempotency_key,
            reason_code=reason_code,
            terminal_retention_ns=terminal_retention_ns,
            evidence=evidence,
        )

    def expire_due_opportunities(
        self,
        *,
        terminal_retention_ns: int,
        limit: int | None = None,
    ) -> tuple[OpportunityLifecycle, ...]:
        if terminal_retention_ns < 0:
            raise ValueError("terminal retention must be non-negative")
        now = self._now()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            expired_ids = self._expire_due_locked(
                now,
                terminal_retention_ns=terminal_retention_ns,
                limit=limit,
            )
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")
        return tuple(
            lifecycle
            for opportunity_id in expired_ids
            if (lifecycle := self.get_opportunity(opportunity_id)) is not None
        )

    def compact_released_dedupe(self) -> int:
        now = self._now()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            count = self._compact_dedupe_locked(now)
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")
        return count

    def _transition_opportunity(
        self,
        *,
        opportunity_id: str,
        expected_revision: int,
        target_state: str,
        idempotency_key: str,
        reason_code: str,
        terminal_retention_ns: int,
        evidence: Mapping[str, object] | None,
    ) -> OpportunityLifecycle:
        if expected_revision < 0:
            raise ValueError("expected_revision must be non-negative")
        target = _opportunity_state(target_state)
        now = self._now()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            duplicate = self.db.execute(
                "SELECT opportunity_id FROM pr195_opportunity_events WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if duplicate is not None:
                if str(duplicate["opportunity_id"]) != opportunity_id:
                    raise LifecycleTransitionError("idempotency key collision")
                row = self._opportunity_row(opportunity_id)
                if row is None:
                    raise LifecycleTransitionError("idempotent opportunity missing")
                self.db.execute("COMMIT")
                return _opportunity_from_row(row)

            row = self._opportunity_row(opportunity_id)
            if row is None:
                raise LifecycleTransitionError("opportunity not found")
            current = _opportunity_state(str(row["state"]))
            revision = int(row["revision"])
            if revision != expected_revision:
                raise LifecycleTransitionError("optimistic lifecycle revision conflict")
            if target not in _ALLOWED_OPPORTUNITY_TRANSITIONS[current]:
                raise LifecycleTransitionError(f"illegal lifecycle transition {current}->{target}")

            next_revision = revision + 1
            terminal = int(target in _TERMINAL_OPPORTUNITY_STATES)
            block_until = now.monotonic_ns + terminal_retention_ns if terminal else None
            self.db.execute(
                "UPDATE pr195_opportunities SET state=?,revision=?,terminal=?,"
                "dedupe_block_until_monotonic_ns=?,updated_boot_id=?,"
                "updated_process_generation=?,updated_monotonic_ns=?,updated_utc_ns=? "
                "WHERE opportunity_id=? AND revision=?",
                (
                    target,
                    next_revision,
                    terminal,
                    block_until,
                    now.boot_id,
                    now.process_generation,
                    now.monotonic_ns,
                    now.utc_ns,
                    opportunity_id,
                    revision,
                ),
            )
            self.db.execute(
                "UPDATE pr195_lifecycle_keys SET state=?,dedupe_block_until_monotonic_ns=?,"
                "updated_boot_id=?,updated_process_generation=?,updated_monotonic_ns=?,updated_utc_ns=? "
                "WHERE lifecycle_key=?",
                (
                    "terminal" if terminal else target,
                    block_until,
                    now.boot_id,
                    now.process_generation,
                    now.monotonic_ns,
                    now.utc_ns,
                    row["lifecycle_key"],
                ),
            )
            self._insert_opportunity_event(
                opportunity_id=opportunity_id,
                revision=next_revision,
                idempotency_key=idempotency_key,
                event_type="opportunity_transition",
                from_state=current,
                to_state=target,
                reason_code=reason_code,
                evidence=evidence,
                now=now,
            )
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")
        updated = self.get_opportunity(opportunity_id)
        if updated is None:
            raise LifecycleTransitionError("opportunity disappeared after transition")
        return updated

    def _expire_due_locked(
        self,
        now: TrustedLifecycleTime,
        *,
        terminal_retention_ns: int,
        limit: int | None = None,
    ) -> list[str]:
        limit_sql = "" if limit is None else " LIMIT ?"
        params: tuple[object, ...] = (now.monotonic_ns,)
        if limit is not None:
            if limit < 1:
                return []
            params = (now.monotonic_ns, limit)
        rows = self.db.execute(
            "SELECT * FROM pr195_lifecycle_keys "
            "WHERE state IN ('pending','claimed') AND expires_monotonic_ns<=? "
            "ORDER BY expires_monotonic_ns,lifecycle_key" + limit_sql,
            params,
        ).fetchall()
        expired: list[str] = []
        for key_row in rows:
            opportunity_id = str(key_row["opportunity_id"])
            row = self._opportunity_row(opportunity_id)
            if row is None:
                continue
            current = str(row["state"])
            if current not in _ACTIVE_OPPORTUNITY_STATES:
                continue
            next_revision = int(row["revision"]) + 1
            block_until = now.monotonic_ns + terminal_retention_ns
            self.db.execute(
                "UPDATE pr195_opportunities SET state='expired',revision=?,terminal=1,"
                "dedupe_block_until_monotonic_ns=?,updated_boot_id=?,"
                "updated_process_generation=?,updated_monotonic_ns=?,updated_utc_ns=? "
                "WHERE opportunity_id=? AND revision=?",
                (
                    next_revision,
                    block_until,
                    now.boot_id,
                    now.process_generation,
                    now.monotonic_ns,
                    now.utc_ns,
                    opportunity_id,
                    int(row["revision"]),
                ),
            )
            self.db.execute(
                "UPDATE pr195_lifecycle_keys SET state='terminal',"
                "dedupe_block_until_monotonic_ns=?,updated_boot_id=?,"
                "updated_process_generation=?,updated_monotonic_ns=?,updated_utc_ns=? "
                "WHERE lifecycle_key=?",
                (
                    block_until,
                    now.boot_id,
                    now.process_generation,
                    now.monotonic_ns,
                    now.utc_ns,
                    str(key_row["lifecycle_key"]),
                ),
            )
            self._insert_opportunity_event(
                opportunity_id=opportunity_id,
                revision=next_revision,
                idempotency_key=f"expire:{opportunity_id}:{next_revision}",
                event_type="opportunity_expired",
                from_state=current,
                to_state="expired",
                reason_code="OPPORTUNITY_EXPIRED",
                evidence={"expires_monotonic_ns": int(row["expires_monotonic_ns"])},
                now=now,
            )
            expired.append(opportunity_id)
        return expired

    def _compact_dedupe_locked(self, now: TrustedLifecycleTime) -> int:
        cur = self.db.execute(
            "DELETE FROM pr195_lifecycle_keys "
            "WHERE state='terminal' "
            "AND dedupe_block_until_monotonic_ns IS NOT NULL "
            "AND dedupe_block_until_monotonic_ns<=?",
            (now.monotonic_ns,),
        )
        return int(cur.rowcount)

    def get_opportunity(self, opportunity_id: str) -> OpportunityLifecycle | None:
        row = self._opportunity_row(opportunity_id)
        return _opportunity_from_row(row) if row is not None else None

    def _opportunity_row(self, opportunity_id: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM pr195_opportunities WHERE opportunity_id=?",
            (opportunity_id,),
        ).fetchone()

    def event_hash_chain(self, opportunity_id: str) -> tuple[str, ...]:
        rows = self.db.execute(
            "SELECT event_hash FROM pr195_opportunity_events "
            "WHERE opportunity_id=? ORDER BY revision",
            (opportunity_id,),
        ).fetchall()
        return tuple(str(row["event_hash"]) for row in rows)

    def lifecycle_key_count(self) -> int:
        row = self.db.execute("SELECT COUNT(*) FROM pr195_lifecycle_keys").fetchone()
        return int(row[0])

    def reserve_wallet_lamports(
        self,
        *,
        reservation_id: str,
        wallet_id: str,
        attempt_id: str,
        lamports: int,
        wallet_limit_lamports: int,
        idempotency_key: str,
    ) -> WalletReservation:
        if not reservation_id.strip() or not wallet_id.strip() or not attempt_id.strip():
            raise ValueError("reservation, wallet and attempt are required")
        if lamports <= 0 or wallet_limit_lamports < 0:
            raise ValueError("lamports and wallet limit are invalid")
        now = self._now()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            duplicate = self.db.execute(
                "SELECT * FROM pr195_wallet_reservations WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if duplicate is not None:
                self.db.execute("COMMIT")
                return _reservation_from_row(duplicate)
            active = self.active_reserved_lamports(wallet_id)
            if active + lamports > wallet_limit_lamports:
                raise CapitalReservationError(
                    f"wallet reservation exceeds limit: {active}+{lamports}>{wallet_limit_lamports}"
                )
            self.db.execute(
                "INSERT INTO pr195_wallet_reservations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    reservation_id,
                    wallet_id,
                    attempt_id,
                    lamports,
                    "active",
                    0,
                    idempotency_key,
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
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")
        row = self._reservation_row(reservation_id)
        if row is None:
            raise CapitalReservationError("reservation disappeared")
        return _reservation_from_row(row)

    def release_wallet_reservation(
        self,
        *,
        reservation_id: str,
        expected_revision: int,
        charged_fee_lamports: int = 0,
    ) -> WalletReservation:
        if expected_revision < 0 or charged_fee_lamports < 0:
            raise ValueError("revision and charged fee must be non-negative")
        now = self._now()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self._reservation_row(reservation_id)
            if row is None:
                raise CapitalReservationError("reservation not found")
            if str(row["state"]) != "active":
                self.db.execute("COMMIT")
                return _reservation_from_row(row)
            revision = int(row["revision"])
            if revision != expected_revision:
                raise CapitalReservationError("reservation revision conflict")
            state = "charged_failure" if charged_fee_lamports else "released"
            self.db.execute(
                "UPDATE pr195_wallet_reservations SET state=?,revision=?,"
                "charged_fee_lamports=?,updated_boot_id=?,updated_process_generation=?,"
                "updated_monotonic_ns=?,updated_utc_ns=? "
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
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")
        updated = self._reservation_row(reservation_id)
        if updated is None:
            raise CapitalReservationError("reservation disappeared")
        return _reservation_from_row(updated)

    def active_reserved_lamports(self, wallet_id: str) -> int:
        row = self.db.execute(
            "SELECT COALESCE(SUM(lamports),0) AS total "
            "FROM pr195_wallet_reservations WHERE wallet_id=? AND state='active'",
            (wallet_id,),
        ).fetchone()
        return int(row["total"] or 0)

    def _reservation_row(self, reservation_id: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM pr195_wallet_reservations WHERE reservation_id=?",
            (reservation_id,),
        ).fetchone()

    def _insert_opportunity_event(
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
        evidence_hash = hashlib.sha256(evidence_json.encode("utf-8")).hexdigest()
        event_hash = _hash_event(
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
            "INSERT INTO pr195_opportunity_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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


def _opportunity_state(value: str) -> str:
    normalized = value.strip()
    if normalized not in _ALLOWED_OPPORTUNITY_TRANSITIONS:
        raise LifecycleTransitionError(f"unknown opportunity lifecycle state {value!r}")
    return normalized


def _opportunity_from_row(row: sqlite3.Row) -> OpportunityLifecycle:
    raw_until = row["dedupe_block_until_monotonic_ns"]
    return OpportunityLifecycle(
        opportunity_id=str(row["opportunity_id"]),
        lifecycle_key=str(row["lifecycle_key"]),
        state=str(row["state"]),
        revision=int(row["revision"]),
        terminal=bool(row["terminal"]),
        expires_monotonic_ns=int(row["expires_monotonic_ns"]),
        dedupe_block_until_monotonic_ns=int(raw_until) if raw_until is not None else None,
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
    return hashlib.sha256(
        _stable_json(
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
        ).encode("utf-8")
    ).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "CapitalReservationError",
    "DuplicateLifecycleKeyError",
    "DurableLifecycleStore",
    "LifecycleTransitionError",
    "ManualLifecycleClock",
    "OpportunityLifecycle",
    "PR195DurableLifecycleError",
    "PR195_DURABLE_LIFECYCLE_SCHEMA",
    "SystemLifecycleClock",
    "TrustedLifecycleTime",
    "WalletReservation",
    "sha256_text",
]

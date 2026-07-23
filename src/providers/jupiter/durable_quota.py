"""Durable Jupiter quota, cooldown and semantic cache authority.

MEGA-PR-01 V6 requires the Jupiter quota boundary to be shared by API account
across processes and restarts. This module is intentionally transport-free: it
does not call Jupiter, RPC, Jito, a signer or sender. It provides the same
reserve/mark-used/release/cache shape as the in-memory manager, backed by a
single SQLite authority that serializes mutations with BEGIN IMMEDIATE.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import time
from typing import Callable, Iterator, Mapping
from uuid import uuid4

from .quota import (
    JupiterQuotaError,
    JupiterQuotaManager,
    JupiterQuotaPurpose,
    QuotaReservation,
)

SCHEMA_VERSION = "mega-pr-01.v6.jupiter-durable-quota.v1"
MIGRATION_ID = "001_durable_jupiter_quota"
MIGRATION_CHECKSUM = "a1b8d5e2c36c893c93c13d2f50db4d531e4cf36b88958f1c8879edee7fb8c845"


@dataclass(frozen=True, slots=True)
class DurableQuotaConfig:
    db_path: Path
    api_account_id: str
    limit: int = 60
    window_seconds: float = 60.0
    finalization_reserve: int = 4

    def __post_init__(self) -> None:
        object.__setattr__(self, "db_path", Path(self.db_path))
        if not self.api_account_id.strip():
            raise ValueError("api_account_id is required")
        if self.limit <= 0:
            raise ValueError("limit must be positive")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if self.finalization_reserve < 0 or self.finalization_reserve >= self.limit:
            raise ValueError("finalization_reserve must be >= 0 and smaller than limit")


class DurableJupiterQuotaManager(JupiterQuotaManager):
    """SQLite-backed account-wide Jupiter quota authority."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        api_account_id: str,
        limit: int = 60,
        window_seconds: float = 60.0,
        finalization_reserve: int = 4,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(
            limit=limit,
            window_seconds=window_seconds,
            finalization_reserve=finalization_reserve,
            clock=clock,
        )
        self.config = DurableQuotaConfig(
            db_path=Path(db_path),
            api_account_id=api_account_id,
            limit=limit,
            window_seconds=window_seconds,
            finalization_reserve=finalization_reserve,
        )
        self.db_path = self.config.db_path
        self.api_account_id = self.config.api_account_id
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS quota_schema_migrations (
                    migration_id TEXT PRIMARY KEY,
                    checksum TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jupiter_quota_events (
                    account_id TEXT NOT NULL,
                    reservation_id TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    request_fingerprint TEXT NOT NULL,
                    reserved_at REAL NOT NULL,
                    issued INTEGER NOT NULL DEFAULT 0,
                    released INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(account_id, reservation_id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jupiter_quota_window
                    ON jupiter_quota_events(account_id, reserved_at)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jupiter_quota_cooldowns (
                    account_id TEXT PRIMARY KEY,
                    retry_after_until REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jupiter_semantic_cache (
                    account_id TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    provenance_json TEXT NOT NULL,
                    PRIMARY KEY(account_id, cache_key)
                )
                """
            )
            row = connection.execute(
                """
                SELECT checksum FROM quota_schema_migrations
                WHERE migration_id = ?
                """,
                (MIGRATION_ID,),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO quota_schema_migrations(migration_id, checksum)
                    VALUES (?, ?)
                    """,
                    (MIGRATION_ID, MIGRATION_CHECKSUM),
                )
            elif row["checksum"] != MIGRATION_CHECKSUM:
                raise JupiterQuotaError("durable-quota-schema-checksum-mismatch")

    def _prune_locked(self, connection: sqlite3.Connection, now: float) -> None:
        cutoff = now - self.window
        connection.execute(
            """
            DELETE FROM jupiter_quota_events
            WHERE account_id = ? AND reserved_at <= ?
            """,
            (self.api_account_id, cutoff),
        )
        connection.execute(
            """
            DELETE FROM jupiter_semantic_cache
            WHERE account_id = ? AND expires_at <= ?
            """,
            (self.api_account_id, now),
        )
        row = connection.execute(
            """
            SELECT retry_after_until FROM jupiter_quota_cooldowns
            WHERE account_id = ?
            """,
            (self.api_account_id,),
        ).fetchone()
        if row is not None and float(row["retry_after_until"]) <= now:
            connection.execute(
                "DELETE FROM jupiter_quota_cooldowns WHERE account_id = ?",
                (self.api_account_id,),
            )

    def _occupancy_locked(self, connection: sqlite3.Connection) -> int:
        return int(
            connection.execute(
                """
                SELECT COUNT(*) FROM jupiter_quota_events
                WHERE account_id = ? AND released = 0
                """,
                (self.api_account_id,),
            ).fetchone()[0]
        )

    def _cooldown_until_locked(self, connection: sqlite3.Connection) -> float | None:
        row = connection.execute(
            """
            SELECT retry_after_until FROM jupiter_quota_cooldowns
            WHERE account_id = ?
            """,
            (self.api_account_id,),
        ).fetchone()
        return None if row is None else float(row["retry_after_until"])

    def _cache_count_locked(self, connection: sqlite3.Connection) -> int:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM jupiter_semantic_cache WHERE account_id = ?",
                (self.api_account_id,),
            ).fetchone()[0]
        )

    def _capacity_for(self, purpose: JupiterQuotaPurpose) -> int:
        if purpose is JupiterQuotaPurpose.FINALIZATION:
            return self.limit
        return max(0, self.limit - self.finalization_reserve)

    async def reserve(
        self,
        purpose: JupiterQuotaPurpose | str = JupiterQuotaPurpose.DISCOVERY,
        *,
        request_fingerprint: str = "",
    ) -> QuotaReservation:
        normalized = JupiterQuotaPurpose.normalize(purpose)
        start = self.clock()
        with self._transaction() as connection:
            now = self.clock()
            self._prune_locked(connection, now)
            cooldown_until = self._cooldown_until_locked(connection)
            if cooldown_until is not None and now < cooldown_until:
                self.metrics.denied += 1
                self.metrics.last_denial_reason = "retry-after-active"
                self.metrics.circuit_state = "rate_limited"
                raise JupiterQuotaError("retry-after-active")
            occupancy = self._occupancy_locked(connection)
            if occupancy >= self._capacity_for(normalized):
                self.metrics.denied += 1
                self.metrics.last_denial_reason = "account-wide-quota-exhausted"
                self.metrics.circuit_state = "rate_limited"
                if normalized is not JupiterQuotaPurpose.FINALIZATION:
                    self.metrics.finalization_reserve_starvation += 1
                raise JupiterQuotaError("account-wide-quota-exhausted")
            token = QuotaReservation(
                reservation_id=uuid4().hex,
                purpose=normalized,
                reserved_at=now,
                request_fingerprint=request_fingerprint,
            )
            connection.execute(
                """
                INSERT INTO jupiter_quota_events(
                    account_id, reservation_id, purpose, request_fingerprint,
                    reserved_at, issued, released
                ) VALUES (?, ?, ?, ?, ?, 0, 0)
                """,
                (
                    self.api_account_id,
                    token.reservation_id,
                    normalized.value,
                    request_fingerprint,
                    now,
                ),
            )
            self.metrics.reserved += 1
            self.metrics.total_queue_seconds += max(0.0, now - start)
            self.metrics.circuit_state = "ready"
            return token

    async def mark_used(self, token: QuotaReservation) -> None:
        with self._transaction() as connection:
            updated = connection.execute(
                """
                UPDATE jupiter_quota_events
                SET issued = 1
                WHERE account_id = ?
                  AND reservation_id = ?
                  AND request_fingerprint = ?
                  AND released = 0
                  AND issued = 0
                """,
                (self.api_account_id, token.reservation_id, token.request_fingerprint),
            ).rowcount
            if updated:
                self.metrics.used += 1

    async def release_unissued(self, token: QuotaReservation) -> None:
        with self._transaction() as connection:
            updated = connection.execute(
                """
                UPDATE jupiter_quota_events
                SET released = 1
                WHERE account_id = ?
                  AND reservation_id = ?
                  AND request_fingerprint = ?
                  AND issued = 0
                  AND released = 0
                """,
                (self.api_account_id, token.reservation_id, token.request_fingerprint),
            ).rowcount
            if updated:
                self.metrics.released += 1

    def record_429(self, retry_after: float | None = None) -> None:
        self.record_http_429(retry_after)

    def record_http_429(self, retry_after: float | None = None) -> None:
        now = self.clock()
        until = now + max(0.0, retry_after or 0.0)
        with self._transaction() as connection:
            self._prune_locked(connection, now)
            current = self._cooldown_until_locked(connection) or now
            next_until = max(current, until)
            connection.execute(
                """
                INSERT INTO jupiter_quota_cooldowns(account_id, retry_after_until)
                VALUES (?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    retry_after_until = excluded.retry_after_until
                WHERE excluded.retry_after_until
                    > jupiter_quota_cooldowns.retry_after_until
                """,
                (self.api_account_id, next_until),
            )
            self.metrics.rate_limited_429s += 1
            self.metrics.retry_after_until = next_until
            self.metrics.circuit_state = "rate_limited"

    def snapshot(self) -> dict[str, int | float | str | None]:
        now = self.clock()
        with self._transaction() as connection:
            self._prune_locked(connection, now)
            cooldown_until = self._cooldown_until_locked(connection)
            occupancy = self._occupancy_locked(connection)
            cache_count = self._cache_count_locked(connection)
        retry_for = None if cooldown_until is None else max(0.0, cooldown_until - now)
        return self.metrics.snapshot(now=now) | {
            "schema_version": SCHEMA_VERSION,
            "api_account_id": self.api_account_id,
            "limit": self.limit,
            "window_seconds": self.window,
            "finalization_reserve": self.finalization_reserve,
            "window_occupancy": occupancy,
            "cache_size": cache_count,
            "retry_after_for_seconds": retry_for,
        }

    def cache_get(self, key: str) -> object | None:
        now = self.clock()
        with self._transaction() as connection:
            self._prune_locked(connection, now)
            row = connection.execute(
                """
                SELECT value_json FROM jupiter_semantic_cache
                WHERE account_id = ? AND cache_key = ? AND expires_at > ?
                """,
                (self.api_account_id, key, now),
            ).fetchone()
            if row is None:
                self.metrics.cache_misses += 1
                return None
            value = json.loads(str(row["value_json"]))
            self.metrics.cache_hits += 1
            return value

    def cache_put(
        self,
        key: str,
        value: object,
        *,
        ttl_seconds: float,
        provenance: Mapping[str, str] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            return
        now = self.clock()
        value_json = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        )
        provenance_json = json.dumps(
            dict(provenance or {}),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        with self._transaction() as connection:
            self._prune_locked(connection, now)
            connection.execute(
                """
                INSERT INTO jupiter_semantic_cache(
                    account_id, cache_key, value_json, expires_at, provenance_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(account_id, cache_key) DO UPDATE SET
                    value_json = excluded.value_json,
                    expires_at = excluded.expires_at,
                    provenance_json = excluded.provenance_json
                """,
                (
                    self.api_account_id,
                    key,
                    value_json,
                    now + ttl_seconds,
                    provenance_json,
                ),
            )

    def active_purposes(self) -> tuple[JupiterQuotaPurpose, ...]:
        now = self.clock()
        with self._transaction() as connection:
            self._prune_locked(connection, now)
            rows = connection.execute(
                """
                SELECT purpose FROM jupiter_quota_events
                WHERE account_id = ? AND released = 0
                ORDER BY reserved_at ASC, reservation_id ASC
                """,
                (self.api_account_id,),
            ).fetchall()
        return tuple(JupiterQuotaPurpose.normalize(str(row["purpose"])) for row in rows)


__all__ = [
    "DurableJupiterQuotaManager",
    "DurableQuotaConfig",
    "MIGRATION_CHECKSUM",
    "SCHEMA_VERSION",
]

"""Durable Jupiter quota, cooldown and semantic cache authority.

MEGA-PR-01 V6 requires the Jupiter quota boundary to be shared by API account
across processes and restarts. This module is intentionally transport-free: it
does not call Jupiter, RPC, Jito, a signer or sender. It provides the same
reserve/mark-used/release/cache surface as the in-process manager, backed by a
SQLite file that serializes mutations with ``BEGIN IMMEDIATE``.
"""
from __future__ import annotations

from pathlib import Path
import json
import sqlite3
import time
from collections.abc import Callable, Mapping
from uuid import uuid4

from .quota import (
    JupiterQuotaError,
    JupiterQuotaMetrics,
    JupiterQuotaPurpose,
    QuotaReservation,
)


SCHEMA_VERSION = "mega-pr-01.jupiter-durable-quota.v1"


class DurableJupiterQuotaManager:
    """SQLite-backed quota authority shared by one Jupiter API account."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        api_account_id: str = "default",
        limit: int = 60,
        window_seconds: float = 60.0,
        finalization_reserve: int = 4,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if finalization_reserve < 0 or finalization_reserve >= limit:
            raise ValueError("finalization_reserve must be >= 0 and smaller than limit")
        if not api_account_id.strip():
            raise ValueError("api_account_id is required")
        self.db_path = Path(db_path)
        self.api_account_id = api_account_id
        self.limit = int(limit)
        self.window = float(window_seconds)
        self.finalization_reserve = int(finalization_reserve)
        self.clock = clock
        self.metrics = JupiterQuotaMetrics()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jupiter_quota_schema (
                    version TEXT PRIMARY KEY,
                    installed_at_unix REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jupiter_quota_events (
                    account_id TEXT NOT NULL,
                    reservation_id TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    reserved_at REAL NOT NULL,
                    request_fingerprint TEXT NOT NULL,
                    issued INTEGER NOT NULL DEFAULT 0 CHECK (issued IN (0, 1)),
                    released INTEGER NOT NULL DEFAULT 0 CHECK (released IN (0, 1)),
                    PRIMARY KEY (account_id, reservation_id)
                );
                CREATE INDEX IF NOT EXISTS idx_jupiter_quota_window
                    ON jupiter_quota_events(account_id, reserved_at, released);
                CREATE TABLE IF NOT EXISTS jupiter_quota_cooldowns (
                    account_id TEXT PRIMARY KEY,
                    retry_after_until REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jupiter_quota_cache (
                    account_id TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    value_json TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    PRIMARY KEY (account_id, cache_key)
                );
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO jupiter_quota_schema(version, installed_at_unix)
                VALUES (?, ?)
                """,
                (SCHEMA_VERSION, self.clock()),
            )

    def _begin(self, connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")

    def _commit(self, connection: sqlite3.Connection) -> None:
        connection.execute("COMMIT")

    def _rollback(self, connection: sqlite3.Connection) -> None:
        try:
            connection.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass

    def _prune_locked(self, connection: sqlite3.Connection, now: float) -> None:
        oldest = now - self.window
        connection.execute(
            """
            DELETE FROM jupiter_quota_events
            WHERE account_id = ? AND reserved_at <= ?
            """,
            (self.api_account_id, oldest),
        )
        connection.execute(
            """
            DELETE FROM jupiter_quota_cooldowns
            WHERE account_id = ? AND retry_after_until <= ?
            """,
            (self.api_account_id, now),
        )
        connection.execute(
            """
            DELETE FROM jupiter_quota_cache
            WHERE account_id = ? AND expires_at <= ?
            """,
            (self.api_account_id, now),
        )

    def _capacity_for(self, purpose: JupiterQuotaPurpose) -> int:
        if purpose is JupiterQuotaPurpose.FINALIZATION:
            return self.limit
        return max(0, self.limit - self.finalization_reserve)

    def _deny(self, reason: str) -> None:
        self.metrics.denied += 1
        self.metrics.last_denial_reason = reason
        self.metrics.circuit_state = "rate_limited"

    async def reserve(
        self,
        purpose: JupiterQuotaPurpose | str = JupiterQuotaPurpose.DISCOVERY,
        *,
        request_fingerprint: str = "",
    ) -> QuotaReservation:
        """Reserve one slot atomically across processes for this API account."""

        normalized = JupiterQuotaPurpose.normalize(purpose)
        start = self.clock()
        now = self.clock()
        with self._connect() as connection:
            try:
                self._begin(connection)
                self._prune_locked(connection, now)
                cooldown = connection.execute(
                    """
                    SELECT retry_after_until FROM jupiter_quota_cooldowns
                    WHERE account_id = ?
                    """,
                    (self.api_account_id,),
                ).fetchone()
                if cooldown is not None and float(cooldown[0]) > now:
                    self.metrics.retry_after_until = float(cooldown[0])
                    self._deny("retry-after-active")
                    self._commit(connection)
                    raise JupiterQuotaError("retry-after-active")

                occupancy = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM jupiter_quota_events
                        WHERE account_id = ? AND released = 0
                        """,
                        (self.api_account_id,),
                    ).fetchone()[0]
                )
                cap = self._capacity_for(normalized)
                if occupancy >= cap:
                    if normalized is not JupiterQuotaPurpose.FINALIZATION:
                        self.metrics.finalization_reserve_starvation += 1
                    self._deny("account-wide-quota-exhausted")
                    self._commit(connection)
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
                        account_id, reservation_id, purpose, reserved_at,
                        request_fingerprint, issued, released
                    ) VALUES (?, ?, ?, ?, ?, 0, 0)
                    """,
                    (
                        self.api_account_id,
                        token.reservation_id,
                        token.purpose.value,
                        token.reserved_at,
                        token.request_fingerprint,
                    ),
                )
                self.metrics.reserved += 1
                self.metrics.total_queue_seconds += max(0.0, now - start)
                self.metrics.circuit_state = "ready"
                self._commit(connection)
                return token
            except Exception:
                self._rollback(connection)
                raise

    async def mark_used(self, token: QuotaReservation) -> None:
        with self._connect() as connection:
            self._begin(connection)
            try:
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
                self._commit(connection)
            except Exception:
                self._rollback(connection)
                raise

    async def release_unissued(self, token: QuotaReservation) -> None:
        with self._connect() as connection:
            self._begin(connection)
            try:
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
                self._commit(connection)
            except Exception:
                self._rollback(connection)
                raise

    def record_429(self, retry_after: float | None = None) -> None:
        self.record_http_429(retry_after)

    def record_http_429(self, retry_after: float | None = None) -> None:
        now = self.clock()
        self.metrics.rate_limited_429s += 1
        self.metrics.circuit_state = "rate_limited"
        if retry_after is None:
            return
        until = now + max(0.0, float(retry_after))
        with self._connect() as connection:
            self._begin(connection)
            try:
                existing = connection.execute(
                    """
                    SELECT retry_after_until FROM jupiter_quota_cooldowns
                    WHERE account_id = ?
                    """,
                    (self.api_account_id,),
                ).fetchone()
                if existing is not None:
                    until = max(until, float(existing[0]))
                connection.execute(
                    """
                    INSERT INTO jupiter_quota_cooldowns(account_id, retry_after_until)
                    VALUES (?, ?)
                    ON CONFLICT(account_id) DO UPDATE SET
                        retry_after_until = excluded.retry_after_until
                    """,
                    (self.api_account_id, until),
                )
                self.metrics.retry_after_until = until
                self._commit(connection)
            except Exception:
                self._rollback(connection)
                raise

    def snapshot(self) -> dict[str, int | float | str | None]:
        now = self.clock()
        with self._connect() as connection:
            self._begin(connection)
            try:
                self._prune_locked(connection, now)
                occupancy = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM jupiter_quota_events
                        WHERE account_id = ? AND released = 0
                        """,
                        (self.api_account_id,),
                    ).fetchone()[0]
                )
                cache_size = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM jupiter_quota_cache
                        WHERE account_id = ?
                        """,
                        (self.api_account_id,),
                    ).fetchone()[0]
                )
                cooldown = connection.execute(
                    """
                    SELECT retry_after_until FROM jupiter_quota_cooldowns
                    WHERE account_id = ?
                    """,
                    (self.api_account_id,),
                ).fetchone()
                retry_until = float(cooldown[0]) if cooldown is not None else None
                self.metrics.retry_after_until = retry_until
                if retry_until is None and self.metrics.circuit_state == "rate_limited":
                    self.metrics.circuit_state = "ready"
                self._commit(connection)
            except Exception:
                self._rollback(connection)
                raise
        return self.metrics.snapshot(now=now) | {
            "schema_version": SCHEMA_VERSION,
            "api_account_id": self.api_account_id,
            "limit": self.limit,
            "window_seconds": self.window,
            "finalization_reserve": self.finalization_reserve,
            "window_occupancy": occupancy,
            "cache_size": cache_size,
        }

    def cache_get(self, key: str) -> object | None:
        now = self.clock()
        with self._connect() as connection:
            self._begin(connection)
            try:
                self._prune_locked(connection, now)
                row = connection.execute(
                    """
                    SELECT value_json FROM jupiter_quota_cache
                    WHERE account_id = ? AND cache_key = ?
                    """,
                    (self.api_account_id, key),
                ).fetchone()
                self._commit(connection)
            except Exception:
                self._rollback(connection)
                raise
        if row is None:
            self.metrics.cache_misses += 1
            return None
        self.metrics.cache_hits += 1
        return json.loads(str(row[0]))

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
        value_json = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        provenance_json = json.dumps(
            dict(provenance or {}),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        expires_at = self.clock() + ttl_seconds
        with self._connect() as connection:
            self._begin(connection)
            try:
                self._prune_locked(connection, self.clock())
                connection.execute(
                    """
                    INSERT INTO jupiter_quota_cache(
                        account_id, cache_key, expires_at, value_json, provenance_json
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(account_id, cache_key) DO UPDATE SET
                        expires_at = excluded.expires_at,
                        value_json = excluded.value_json,
                        provenance_json = excluded.provenance_json
                    """,
                    (
                        self.api_account_id,
                        key,
                        expires_at,
                        value_json,
                        provenance_json,
                    ),
                )
                self._commit(connection)
            except Exception:
                self._rollback(connection)
                raise

    def active_purposes(self) -> tuple[JupiterQuotaPurpose, ...]:
        now = self.clock()
        with self._connect() as connection:
            self._begin(connection)
            try:
                self._prune_locked(connection, now)
                rows = connection.execute(
                    """
                    SELECT purpose FROM jupiter_quota_events
                    WHERE account_id = ? AND released = 0
                    ORDER BY reserved_at, reservation_id
                    """,
                    (self.api_account_id,),
                ).fetchall()
                self._commit(connection)
            except Exception:
                self._rollback(connection)
                raise
        return tuple(JupiterQuotaPurpose.normalize(row[0]) for row in rows)


__all__ = ["DurableJupiterQuotaManager", "SCHEMA_VERSION"]

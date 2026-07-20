"""Durable native-SOL capital reservations for PR-057.

The PR-032 :class:`AtomicCapitalLedger` is intentionally process-local.  This
module adds a small SQLite-backed ledger that preserves the same fail-closed
capital policy while making active reservations recoverable after a runner
restart.  It does not sign, simulate, or submit transactions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time
from typing import Iterable
from uuid import uuid4

from src.economics.capital import (
    CapitalCandidate,
    CapitalDecision,
    CapitalEngineError,
    CapitalLedgerSnapshot,
    CapitalPolicy,
    CapitalReservation,
    NoTradeReason,
)
from src.domain.money import U64_MAX


_ACTIVE = "active"
_RELEASED = "released"


@dataclass(frozen=True, slots=True)
class DurableReservationEvent:
    """Append-only-ish event emitted by the durable reservation boundary."""

    event_type: str
    reservation_id: str
    candidate_id: str
    reserved_lamports: int
    created_at: float
    released_at: float | None = None


def _strict_lamports(value: int, *, field: str, upper: int = U64_MAX) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CapitalEngineError(f"{field} must be integer lamports")
    if value < 0 or value > upper:
        raise CapitalEngineError(f"{field} outside allowed lamport range")
    return value


def _strict_signed(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CapitalEngineError(f"{field} must be integer lamports")
    return value


class DurableCapitalLedger:
    """SQLite-backed capital ledger with crash-recoverable active reservations."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        wallet_lamports: int,
        policy: CapitalPolicy,
    ) -> None:
        self.db_path = Path(db_path)
        self.wallet_lamports = _strict_lamports(
            wallet_lamports,
            field="wallet_lamports",
        )
        self.policy = policy
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS capital_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    reserved_lamports INTEGER NOT NULL CHECK(reserved_lamports >= 0),
                    conservative_net_profit_lamports INTEGER NOT NULL,
                    message_hash TEXT,
                    policy_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active', 'released')),
                    created_at REAL NOT NULL,
                    released_at REAL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_capital_reservations_status
                ON capital_reservations(status, policy_fingerprint)
                """
            )

    def update_wallet_lamports(self, wallet_lamports: int) -> None:
        self.wallet_lamports = _strict_lamports(
            wallet_lamports,
            field="wallet_lamports",
        )

    def active_reserved_lamports(self) -> int:
        with self._connect() as connection:
            return self._active_reserved_lamports(connection)

    def available_native_lamports(self) -> int:
        reserved = self.active_reserved_lamports()
        return max(
            0,
            self.wallet_lamports - self.policy.protected_reserve_lamports - reserved,
        )

    def recover_active_reservations(self) -> tuple[CapitalReservation, ...]:
        """Return all active reservations for the current policy fingerprint."""

        with self._connect() as connection:
            return self._active_reservations(connection)

    def evaluate(self, candidate: CapitalCandidate) -> CapitalDecision:
        with self._connect() as connection:
            return self._evaluate(connection, candidate)

    def reserve(self, candidate: CapitalCandidate) -> CapitalDecision:
        """Atomically evaluate and persist an active reservation when allowed."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            decision = self._evaluate(connection, candidate)
            if not decision.allowed:
                connection.rollback()
                return decision

            reservation_id = self._new_reservation_id(candidate.candidate_id)
            now = time.time()
            connection.execute(
                """
                INSERT INTO capital_reservations (
                    reservation_id,
                    candidate_id,
                    reserved_lamports,
                    conservative_net_profit_lamports,
                    message_hash,
                    policy_fingerprint,
                    status,
                    created_at,
                    released_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    reservation_id,
                    candidate.candidate_id,
                    decision.required_native_lamports,
                    decision.conservative_net_profit_lamports,
                    candidate.message_hash,
                    self.policy.fingerprint,
                    _ACTIVE,
                    now,
                ),
            )
            connection.commit()
            return CapitalDecision(
                allowed=True,
                reason=NoTradeReason.TRADE_PERMITTED,
                candidate_id=candidate.candidate_id,
                available_native_lamports=decision.available_native_lamports,
                required_native_lamports=decision.required_native_lamports,
                conservative_net_profit_lamports=(
                    decision.conservative_net_profit_lamports
                ),
                policy_fingerprint=self.policy.fingerprint,
                reservation_id=reservation_id,
            )

    def release(self, reservation_id: str) -> bool:
        """Release a reservation idempotently.

        Returns True only when an active reservation transitioned to released.
        """

        if not reservation_id:
            raise CapitalEngineError("reservation_id is required")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE capital_reservations
                   SET status = ?, released_at = ?
                 WHERE reservation_id = ? AND status = ?
                """,
                (_RELEASED, time.time(), reservation_id, _ACTIVE),
            )
            connection.commit()
            return cursor.rowcount == 1

    def snapshot(self) -> CapitalLedgerSnapshot:
        with self._connect() as connection:
            reservations = self._active_reservations(connection)
            reserved = sum(item.reserved_lamports for item in reservations)
            available = max(
                0,
                self.wallet_lamports
                - self.policy.protected_reserve_lamports
                - reserved,
            )
            return CapitalLedgerSnapshot(
                wallet_lamports=self.wallet_lamports,
                protected_reserve_lamports=self.policy.protected_reserve_lamports,
                active_reserved_lamports=reserved,
                available_native_lamports=available,
                reservations=reservations,
            )

    def _active_reserved_lamports(self, connection: sqlite3.Connection) -> int:
        rows = self._active_rows(connection)
        return sum(
            _strict_lamports(row["reserved_lamports"], field="reserved_lamports")
            for row in rows
        )

    def _active_reservations(
        self,
        connection: sqlite3.Connection,
    ) -> tuple[CapitalReservation, ...]:
        return tuple(
            self._reservation_from_row(row) for row in self._active_rows(connection)
        )

    def _active_rows(self, connection: sqlite3.Connection) -> Iterable[sqlite3.Row]:
        return connection.execute(
            """
            SELECT reservation_id,
                   candidate_id,
                   reserved_lamports,
                   conservative_net_profit_lamports,
                   message_hash,
                   policy_fingerprint
              FROM capital_reservations
             WHERE status = ? AND policy_fingerprint = ?
             ORDER BY created_at ASC, reservation_id ASC
            """,
            (_ACTIVE, self.policy.fingerprint),
        ).fetchall()

    def _reservation_from_row(self, row: sqlite3.Row) -> CapitalReservation:
        return CapitalReservation(
            reservation_id=str(row["reservation_id"]),
            candidate_id=str(row["candidate_id"]),
            reserved_lamports=_strict_lamports(
                row["reserved_lamports"],
                field="reserved_lamports",
            ),
            conservative_net_profit_lamports=_strict_signed(
                row["conservative_net_profit_lamports"],
                field="conservative_net_profit_lamports",
            ),
            message_hash=row["message_hash"],
            policy_fingerprint=str(row["policy_fingerprint"]),
        )

    def _evaluate(
        self,
        connection: sqlite3.Connection,
        candidate: CapitalCandidate,
    ) -> CapitalDecision:
        reserved = self._active_reserved_lamports(connection)
        available = max(
            0,
            self.wallet_lamports - self.policy.protected_reserve_lamports - reserved,
        )
        required = candidate.required_wallet_lamports(self.policy)
        net = candidate.conservative_net_profit_lamports()
        reason = NoTradeReason.TRADE_PERMITTED

        if candidate.native_costs.priority_fee_lamports > (
            self.policy.maximum_priority_fee_lamports
        ):
            reason = NoTradeReason.PRIORITY_FEE_EXCEEDS_POLICY
        elif (
            candidate.native_costs.jito_tip_lamports
            > self.policy.maximum_jito_tip_lamports
        ):
            reason = NoTradeReason.JITO_TIP_EXCEEDS_POLICY
        elif (
            candidate.native_costs.peak_rent_lamports
            > self.policy.maximum_peak_rent_lamports
        ):
            reason = NoTradeReason.PEAK_RENT_EXCEEDS_POLICY
        elif (
            self.policy.maximum_flash_loan_lamports is not None
            and candidate.requested_flash_loan_lamports
            > self.policy.maximum_flash_loan_lamports
        ):
            reason = NoTradeReason.FLASH_LOAN_SIZE_EXCEEDS_POLICY
        elif candidate.gross_profit_lamports() <= 0:
            reason = NoTradeReason.NON_POSITIVE_GROSS_PROFIT
        elif net <= 0:
            reason = NoTradeReason.NON_POSITIVE_CONSERVATIVE_NET_PROFIT
        elif net < self.policy.minimum_net_profit_lamports:
            reason = NoTradeReason.BELOW_MINIMUM_NET_PROFIT
        elif available < required:
            reason = NoTradeReason.INSUFFICIENT_NATIVE_BALANCE

        return CapitalDecision(
            allowed=reason is NoTradeReason.TRADE_PERMITTED,
            reason=reason,
            candidate_id=candidate.candidate_id,
            available_native_lamports=available,
            required_native_lamports=required,
            conservative_net_profit_lamports=net,
            policy_fingerprint=self.policy.fingerprint,
        )

    def _new_reservation_id(self, candidate_id: str) -> str:
        safe_candidate = "".join(
            character
            for character in candidate_id[:24]
            if character.isalnum() or character in "-_"
        )
        suffix = safe_candidate or "candidate"
        return f"capres-{int(time.time() * 1000)}-{uuid4().hex[:12]}-{suffix}"


def active_reservation_ids(snapshot: CapitalLedgerSnapshot) -> tuple[str, ...]:
    """Small helper for runners that need stable lifecycle-bound IDs."""

    return tuple(item.reservation_id for item in snapshot.reservations)

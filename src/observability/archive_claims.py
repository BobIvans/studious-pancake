from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Iterable

from .archive_schema import ensure_archive_schema
from .archive_types import ArchiveError, ExportClaim
from .store import ObservabilityStore


class ArchiveClaimStore:
    """Own fenced leases over pending observability outbox rows."""

    def __init__(self, store: ObservabilityStore):
        self.store = store
        self.db = store.db
        ensure_archive_schema(self.db)

    def database_epoch(self) -> str:
        row = self.db.execute(
            "SELECT value FROM audit_meta WHERE key='database_epoch'"
        ).fetchone()
        if row is None:
            raise ArchiveError("ARCHIVE_DATABASE_EPOCH_MISSING")
        return str(row["value"])

    def claim_pending(
        self,
        *,
        exporter_id: str,
        lease_seconds: float,
        limit: int = 10_000,
        now: float | None = None,
    ) -> ExportClaim | None:
        if not exporter_id.strip():
            raise ValueError("exporter_id must be non-empty")
        if lease_seconds <= 0 or limit <= 0:
            raise ValueError("lease_seconds and limit must be positive")
        claimed_at = time.time() if now is None else now
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self._expire_claims_locked(claimed_at)
            rows = self.db.execute(
                """
                SELECT outbox.id AS outbox_id, outbox.event_id
                FROM outbox
                WHERE outbox.status='pending'
                  AND outbox.work_type='export'
                  AND NOT EXISTS(
                      SELECT 1 FROM archive_export_claim_item AS item
                      WHERE item.outbox_id=outbox.id
                  )
                ORDER BY outbox.id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            if not rows:
                self.db.execute("COMMIT")
                return None
            claim = self._insert_claim_locked(
                exporter_id=exporter_id,
                claimed_at=claimed_at,
                lease_seconds=lease_seconds,
                rows=rows,
            )
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")
        return claim

    def claim_specific_events(
        self,
        *,
        exporter_id: str,
        event_ids: Iterable[str],
        lease_seconds: float,
        now: float | None = None,
    ) -> ExportClaim:
        requested = tuple(event_ids)
        if not requested or len(set(requested)) != len(requested):
            raise ArchiveError("ARCHIVE_RECOVERY_EVENT_SET_INVALID")
        claimed_at = time.time() if now is None else now
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self._expire_claims_locked(claimed_at)
            placeholders = ",".join("?" for _ in requested)
            rows = self.db.execute(
                f"""
                SELECT outbox.id AS outbox_id, outbox.event_id
                FROM outbox
                WHERE outbox.event_id IN ({placeholders})
                  AND outbox.status='pending'
                  AND outbox.work_type='export'
                  AND NOT EXISTS(
                      SELECT 1 FROM archive_export_claim_item AS item
                      WHERE item.outbox_id=outbox.id
                  )
                """,
                requested,
            ).fetchall()
            if len(rows) != len(requested):
                raise ArchiveError("ARCHIVE_RECOVERY_ROWS_NOT_CLAIMABLE")
            rows_by_event = {str(row["event_id"]): row for row in rows}
            if set(rows_by_event) != set(requested):
                raise ArchiveError("ARCHIVE_RECOVERY_EVENT_SET_MISMATCH")
            ordered_rows = tuple(rows_by_event[event_id] for event_id in requested)
            claim = self._insert_claim_locked(
                exporter_id=exporter_id,
                claimed_at=claimed_at,
                lease_seconds=lease_seconds,
                rows=ordered_rows,
            )
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")
        return claim

    def _insert_claim_locked(
        self,
        *,
        exporter_id: str,
        claimed_at: float,
        lease_seconds: float,
        rows: Iterable[sqlite3.Row],
    ) -> ExportClaim:
        materialized = tuple(rows)
        claim_id = uuid.uuid4().hex
        database_epoch = self.database_epoch()
        lease_expires_at = claimed_at + lease_seconds
        cursor = self.db.execute(
            """
            INSERT INTO archive_export_claim(
                claim_id, exporter_id, database_epoch,
                claimed_at, lease_expires_at, state
            )
            VALUES(?,?,?,?,?,'active')
            """,
            (
                claim_id,
                exporter_id,
                database_epoch,
                claimed_at,
                lease_expires_at,
            ),
        )
        fencing_token = int(cursor.lastrowid)
        for ordinal, row in enumerate(materialized):
            self.db.execute(
                """
                INSERT INTO archive_export_claim_item(
                    claim_id, outbox_id, event_id, ordinal
                )
                VALUES(?,?,?,?)
                """,
                (claim_id, int(row["outbox_id"]), str(row["event_id"]), ordinal),
            )
        return ExportClaim(
            claim_id=claim_id,
            exporter_id=exporter_id,
            fencing_token=fencing_token,
            database_epoch=database_epoch,
            claimed_at=claimed_at,
            lease_expires_at=lease_expires_at,
            outbox_ids=tuple(int(row["outbox_id"]) for row in materialized),
            event_ids=tuple(str(row["event_id"]) for row in materialized),
        )

    def rows_for_claim(self, claim: ExportClaim) -> list[sqlite3.Row]:
        self._assert_claim_identity(claim)
        return list(
            self.db.execute(
                """
                SELECT event_log.*, outbox.id AS outbox_id, item.ordinal
                FROM archive_export_claim_item AS item
                JOIN outbox ON outbox.id=item.outbox_id
                JOIN event_log ON event_log.event_id=outbox.event_id
                WHERE item.claim_id=? AND outbox.status='pending'
                ORDER BY item.ordinal
                """,
                (claim.claim_id,),
            )
        )

    def expire_claims(self, *, now: float | None = None) -> int:
        current = time.time() if now is None else now
        self.db.execute("BEGIN IMMEDIATE")
        try:
            expired = self._expire_claims_locked(current)
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")
        return expired

    def _expire_claims_locked(self, now: float) -> int:
        claims = self.db.execute(
            """
            SELECT claim_id FROM archive_export_claim
            WHERE state='active' AND lease_expires_at<=?
            """,
            (now,),
        ).fetchall()
        for row in claims:
            claim_id = str(row["claim_id"])
            self.db.execute(
                """
                DELETE FROM archive_export_claim_item
                WHERE claim_id=?
                  AND outbox_id IN(SELECT id FROM outbox WHERE status='pending')
                """,
                (claim_id,),
            )
            self.db.execute(
                """
                UPDATE archive_export_claim
                SET state='expired', completed_at=?
                WHERE claim_id=? AND state='active'
                """,
                (now, claim_id),
            )
        return len(claims)

    def claim_is_active(self, claim_id: str, *, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        row = self.db.execute(
            """
            SELECT state, lease_expires_at FROM archive_export_claim
            WHERE claim_id=?
            """,
            (claim_id,),
        ).fetchone()
        return bool(
            row is not None
            and str(row["state"]) == "active"
            and float(row["lease_expires_at"]) > current
        )

    def _assert_claim_identity(self, claim: ExportClaim) -> None:
        row = self.db.execute(
            """
            SELECT exporter_id, fencing_token, database_epoch, state
            FROM archive_export_claim WHERE claim_id=?
            """,
            (claim.claim_id,),
        ).fetchone()
        self._validate_claim_row(row, claim)

    def _assert_claim_identity_locked(
        self,
        claim: ExportClaim,
        *,
        now: float,
    ) -> None:
        row = self.db.execute(
            """
            SELECT exporter_id, fencing_token, database_epoch,
                   state, lease_expires_at
            FROM archive_export_claim WHERE claim_id=?
            """,
            (claim.claim_id,),
        ).fetchone()
        self._validate_claim_row(row, claim)
        if float(row["lease_expires_at"]) <= now:
            raise ArchiveError("ARCHIVE_CLAIM_LEASE_EXPIRED")

    @staticmethod
    def _validate_claim_row(row: sqlite3.Row | None, claim: ExportClaim) -> None:
        if row is None:
            raise ArchiveError("ARCHIVE_CLAIM_UNKNOWN")
        if (
            str(row["exporter_id"]) != claim.exporter_id
            or int(row["fencing_token"]) != claim.fencing_token
            or str(row["database_epoch"]) != claim.database_epoch
        ):
            raise ArchiveError("ARCHIVE_CLAIM_FENCE_MISMATCH")
        if str(row["state"]) != "active":
            raise ArchiveError("ARCHIVE_CLAIM_NOT_ACTIVE")

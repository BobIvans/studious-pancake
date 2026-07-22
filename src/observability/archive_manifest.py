from __future__ import annotations

from collections.abc import Mapping
import json
import sqlite3
import time
from typing import Any

from .archive_claims import ArchiveClaimStore
from .archive_types import ArchiveError, ExportClaim, RemoteArchiveAck


class ArchiveCoordinator(ArchiveClaimStore):
    """Commit immutable segments and their exact outbox/event linkage."""

    def commit_segment(
        self,
        *,
        claim: ExportClaim,
        manifest: Mapping[str, object],
        rows: list[sqlite3.Row],
        completed_at: float | None = None,
    ) -> None:
        if not rows:
            raise ArchiveError("ARCHIVE_EMPTY_SEGMENT")
        committed_at = time.time() if completed_at is None else completed_at
        outbox_ids = tuple(int(row["outbox_id"]) for row in rows)
        event_ids = tuple(str(row["event_id"]) for row in rows)
        if len(set(outbox_ids)) != len(outbox_ids):
            raise ArchiveError("ARCHIVE_DUPLICATE_OUTBOX_IN_SEGMENT")
        if len(set(event_ids)) != len(event_ids):
            raise ArchiveError("ARCHIVE_DUPLICATE_EVENT_IN_SEGMENT")
        if manifest.get("database_epoch") != claim.database_epoch:
            raise ArchiveError("ARCHIVE_DATABASE_EPOCH_MISMATCH")
        if tuple(manifest.get("event_ids", ())) != event_ids:
            raise ArchiveError("ARCHIVE_MANIFEST_EVENT_ORDER_MISMATCH")
        if int(manifest.get("event_count", -1)) != len(rows):
            raise ArchiveError("ARCHIVE_MANIFEST_COUNT_MISMATCH")

        self.db.execute("BEGIN IMMEDIATE")
        try:
            self._assert_claim_identity_locked(claim, now=committed_at)
            self._assert_claim_items_pending(claim, outbox_ids, event_ids)
            self._insert_manifest_locked(manifest, created_at=committed_at)
            segment_id = str(manifest["segment_id"])
            for ordinal, row in enumerate(rows):
                self.db.execute(
                    """
                    INSERT INTO archive_segment_event(
                        segment_id, ordinal, outbox_id, event_id
                    )
                    VALUES(?,?,?,?)
                    """,
                    (
                        segment_id,
                        ordinal,
                        int(row["outbox_id"]),
                        str(row["event_id"]),
                    ),
                )
            placeholders = ",".join("?" for _ in outbox_ids)
            cursor = self.db.execute(
                f"""
                UPDATE outbox SET status='done', completed_at=?
                WHERE id IN ({placeholders})
                  AND status='pending' AND work_type='export'
                """,
                (committed_at, *outbox_ids),
            )
            if cursor.rowcount != len(outbox_ids):
                raise ArchiveError("ARCHIVE_OUTBOX_CAS_FAILED")
            outstanding = self.db.execute(
                """
                SELECT COUNT(*) AS count
                FROM archive_export_claim_item AS item
                JOIN outbox ON outbox.id=item.outbox_id
                WHERE item.claim_id=? AND outbox.status='pending'
                """,
                (claim.claim_id,),
            ).fetchone()
            if int(outstanding["count"]) == 0:
                self.db.execute(
                    """
                    UPDATE archive_export_claim
                    SET state='completed', completed_at=?
                    WHERE claim_id=? AND fencing_token=? AND state='active'
                    """,
                    (committed_at, claim.claim_id, claim.fencing_token),
                )
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    def _assert_claim_items_pending(
        self,
        claim: ExportClaim,
        outbox_ids: tuple[int, ...],
        event_ids: tuple[str, ...],
    ) -> None:
        items = self.db.execute(
            """
            SELECT item.outbox_id, item.event_id, outbox.status
            FROM archive_export_claim_item AS item
            JOIN outbox ON outbox.id=item.outbox_id
            WHERE item.claim_id=?
            """,
            (claim.claim_id,),
        ).fetchall()
        claim_map = {
            (int(item["outbox_id"]), str(item["event_id"])): str(item["status"])
            for item in items
        }
        for pair in zip(outbox_ids, event_ids, strict=True):
            if claim_map.get(pair) != "pending":
                raise ArchiveError("ARCHIVE_CLAIM_ITEM_NOT_PENDING")

    def _insert_manifest_locked(
        self,
        manifest: Mapping[str, object],
        *,
        created_at: float,
    ) -> None:
        segment_id = str(manifest["segment_id"])
        manifest_id = str(manifest["manifest_id"])
        path = str(manifest["path"])
        checksum = str(manifest["checksum"])
        existing = self.db.execute(
            """
            SELECT * FROM archive_segment_manifest
            WHERE segment_id=? OR manifest_id=? OR partition_path=?
            """,
            (segment_id, manifest_id, path),
        ).fetchone()
        if existing is not None:
            expected = {
                "segment_id": segment_id,
                "manifest_id": manifest_id,
                "partition_path": path,
                "checksum": checksum,
                "event_count": int(manifest["event_count"]),
            }
            if {key: existing[key] for key in expected} != expected:
                raise ArchiveError("ARCHIVE_MANIFEST_IDENTITY_CONFLICT")
            return

        remote_required = bool(manifest.get("remote_required", False))
        self.db.execute(
            """
            INSERT INTO archive_segment_manifest(
                segment_id, manifest_id, partition_path, object_key,
                checksum, event_count, first_event_id, last_event_id,
                first_outbox_id, last_outbox_id, date_utc, event_type,
                database_epoch, release_id, policy_bundle_hash,
                schema_version, redaction_version, tool_version,
                claim_id, fencing_token, authoritative,
                remote_required, remote_status, created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)
            """,
            (
                segment_id,
                manifest_id,
                path,
                str(manifest["object_key"]),
                checksum,
                int(manifest["event_count"]),
                str(manifest["first_event_id"]),
                str(manifest["last_event_id"]),
                int(manifest["first_outbox_id"]),
                int(manifest["last_outbox_id"]),
                str(manifest["date_utc"]),
                str(manifest["event_type"]),
                str(manifest["database_epoch"]),
                str(manifest["release_id"]),
                str(manifest["policy_bundle_hash"]),
                int(manifest["schema_version"]),
                str(manifest["redaction_version"]),
                str(manifest["tool_version"]),
                str(manifest["claim_id"]),
                int(manifest["fencing_token"]),
                1 if remote_required else 0,
                "pending" if remote_required else "not_required",
                created_at,
            ),
        )
        self.db.execute(
            """
            INSERT INTO export_manifest(
                manifest_id, partition_path, checksum, event_count,
                first_event_id, last_event_id, schema_version,
                redaction_version, created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                manifest_id,
                path,
                checksum,
                int(manifest["event_count"]),
                str(manifest["first_event_id"]),
                str(manifest["last_event_id"]),
                int(manifest["schema_version"]),
                str(manifest["redaction_version"]),
                created_at,
            ),
        )

    def record_remote_ack(
        self,
        *,
        segment_id: str,
        ack: RemoteArchiveAck,
        acknowledged_at: float | None = None,
    ) -> None:
        row = self.db.execute(
            """
            SELECT checksum, object_key
            FROM archive_segment_manifest
            WHERE segment_id=?
            """,
            (segment_id,),
        ).fetchone()
        if row is None:
            raise ArchiveError("ARCHIVE_REMOTE_ACK_UNKNOWN_SEGMENT")
        if ack.object_digest != str(row["checksum"]):
            raise ArchiveError("ARCHIVE_REMOTE_DIGEST_MISMATCH")
        if ack.object_key != str(row["object_key"]):
            raise ArchiveError("ARCHIVE_REMOTE_OBJECT_KEY_MISMATCH")
        now = time.time() if acknowledged_at is None else acknowledged_at
        metadata_json = json.dumps(
            ack.metadata or {}, sort_keys=True, separators=(",", ":")
        )
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute(
                """
                INSERT INTO archive_remote_ack(
                    segment_id, archive_name, object_key, object_version,
                    object_digest, metadata_json, acknowledged_at
                )
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(segment_id, archive_name) DO UPDATE SET
                    object_key=excluded.object_key,
                    object_version=excluded.object_version,
                    object_digest=excluded.object_digest,
                    metadata_json=excluded.metadata_json,
                    acknowledged_at=excluded.acknowledged_at
                """,
                (
                    segment_id,
                    ack.archive_name,
                    ack.object_key,
                    ack.object_version,
                    ack.object_digest,
                    metadata_json,
                    now,
                ),
            )
            self.db.execute(
                """
                UPDATE archive_segment_manifest
                SET remote_status='acked', remote_error=NULL
                WHERE segment_id=?
                """,
                (segment_id,),
            )
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    def record_remote_failure(self, *, segment_id: str, reason: str) -> None:
        self.db.execute(
            """
            UPDATE archive_segment_manifest
            SET remote_status='failed', remote_error=? WHERE segment_id=?
            """,
            (reason[:512], segment_id),
        )

    def manifests_needing_remote_ack(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.execute(
                """
                SELECT * FROM archive_segment_manifest
                WHERE remote_required=1 AND remote_status!='acked'
                ORDER BY created_at, segment_id
                """
            )
        ]

    def manifest_for_path(self, path: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT * FROM archive_segment_manifest WHERE partition_path=?",
            (path,),
        ).fetchone()
        return dict(row) if row is not None else None

    def authoritative_manifests(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.execute(
                """
                SELECT * FROM archive_segment_manifest
                WHERE authoritative=1 ORDER BY created_at, segment_id
                """
            )
        ]

    def linked_event_ids(self, segment_id: str) -> tuple[str, ...]:
        return tuple(
            str(row["event_id"])
            for row in self.db.execute(
                """
                SELECT event_id FROM archive_segment_event
                WHERE segment_id=? ORDER BY ordinal
                """,
                (segment_id,),
            )
        )

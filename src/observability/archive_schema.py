from __future__ import annotations

import sqlite3
import time

from .archive_types import ARCHIVE_SCHEMA_NAME, ARCHIVE_SCHEMA_VERSION


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS archive_meta(
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS archive_export_claim(
        fencing_token INTEGER PRIMARY KEY AUTOINCREMENT,
        claim_id TEXT NOT NULL UNIQUE,
        exporter_id TEXT NOT NULL,
        database_epoch TEXT NOT NULL,
        claimed_at REAL NOT NULL,
        lease_expires_at REAL NOT NULL,
        state TEXT NOT NULL,
        completed_at REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS archive_export_claim_item(
        claim_id TEXT NOT NULL,
        outbox_id INTEGER NOT NULL UNIQUE,
        event_id TEXT NOT NULL UNIQUE,
        ordinal INTEGER NOT NULL,
        PRIMARY KEY(claim_id, outbox_id),
        FOREIGN KEY(claim_id) REFERENCES archive_export_claim(claim_id),
        FOREIGN KEY(outbox_id) REFERENCES outbox(id),
        FOREIGN KEY(event_id) REFERENCES event_log(event_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS archive_segment_manifest(
        segment_id TEXT PRIMARY KEY,
        manifest_id TEXT NOT NULL UNIQUE,
        partition_path TEXT NOT NULL UNIQUE,
        object_key TEXT NOT NULL UNIQUE,
        checksum TEXT NOT NULL,
        event_count INTEGER NOT NULL,
        first_event_id TEXT NOT NULL,
        last_event_id TEXT NOT NULL,
        first_outbox_id INTEGER NOT NULL,
        last_outbox_id INTEGER NOT NULL,
        date_utc TEXT NOT NULL,
        event_type TEXT NOT NULL,
        database_epoch TEXT NOT NULL,
        release_id TEXT NOT NULL,
        policy_bundle_hash TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        redaction_version TEXT NOT NULL,
        tool_version TEXT NOT NULL,
        claim_id TEXT NOT NULL,
        fencing_token INTEGER NOT NULL,
        authoritative INTEGER NOT NULL,
        remote_required INTEGER NOT NULL,
        remote_status TEXT NOT NULL,
        remote_error TEXT,
        created_at REAL NOT NULL,
        FOREIGN KEY(claim_id) REFERENCES archive_export_claim(claim_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS archive_segment_event(
        segment_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        outbox_id INTEGER NOT NULL UNIQUE,
        event_id TEXT NOT NULL UNIQUE,
        PRIMARY KEY(segment_id, ordinal),
        FOREIGN KEY(segment_id) REFERENCES archive_segment_manifest(segment_id),
        FOREIGN KEY(outbox_id) REFERENCES outbox(id),
        FOREIGN KEY(event_id) REFERENCES event_log(event_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS archive_remote_ack(
        segment_id TEXT NOT NULL,
        archive_name TEXT NOT NULL,
        object_key TEXT NOT NULL,
        object_version TEXT NOT NULL,
        object_digest TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        acknowledged_at REAL NOT NULL,
        PRIMARY KEY(segment_id, archive_name),
        FOREIGN KEY(segment_id) REFERENCES archive_segment_manifest(segment_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_archive_claim_state_lease
    ON archive_export_claim(state, lease_expires_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_archive_manifest_remote
    ON archive_segment_manifest(remote_required, remote_status)
    """,
)


def ensure_archive_schema(db: sqlite3.Connection) -> None:
    db.execute("BEGIN IMMEDIATE")
    try:
        for statement in SCHEMA_STATEMENTS:
            db.execute(statement)
        metadata = {
            "schema_name": ARCHIVE_SCHEMA_NAME,
            "schema_version": str(ARCHIVE_SCHEMA_VERSION),
            "activated_at": repr(time.time()),
        }
        for key, value in metadata.items():
            db.execute(
                "INSERT OR IGNORE INTO archive_meta(key,value) VALUES(?,?)",
                (key, value),
            )
    except Exception:
        db.execute("ROLLBACK")
        raise
    db.execute("COMMIT")

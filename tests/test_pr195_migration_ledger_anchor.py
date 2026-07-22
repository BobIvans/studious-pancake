from __future__ import annotations

import sqlite3

import pytest

from src.database_schema_authority_pr195 import (
    DatabaseProductSpec,
    DatabaseSchemaAuthority,
    DatabaseSchemaAuthorityError,
    canonical_schema_manifest,
    schema_migrations_digest,
)


def _migrated() -> tuple[sqlite3.Connection, DatabaseSchemaAuthority]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE app_record(id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE schema_migrations("
        "version INTEGER PRIMARY KEY, applied_at REAL, "
        "schema_name TEXT, schema_checksum TEXT)"
    )
    conn.execute(
        "INSERT INTO schema_migrations VALUES(18,1.0,'audit',?)",
        ("a" * 64,),
    )
    DatabaseSchemaAuthority.install_authority_schema(conn)
    spec = DatabaseProductSpec(
        product_id="observability",
        schema_family="observability-family",
        application_schema_version=19,
        current_epoch=19,
        reader_min_epoch=19,
        reader_max_epoch=19,
        writer_min_epoch=19,
        writer_max_epoch=19,
        expected_schema_manifest_sha256=canonical_schema_manifest(conn).sha256,
    )
    authority = DatabaseSchemaAuthority(spec, now_utc_ns=lambda: 10_000_000_000)
    legacy_digest = schema_migrations_digest(conn)
    fence = authority.acquire_fence(
        conn,
        owner_id="migration-owner",
        expected_epoch=0,
        lease_seconds=30,
    )
    authority.bootstrap_identity(
        conn,
        environment="paper",
        cluster_genesis="reviewed-genesis",
        release_id="release-pr195",
        legacy_migrations_sha256=legacy_digest,
    )
    authority.append_migration(
        conn,
        migration_id="epoch-19",
        from_epoch=18,
        to_epoch=19,
        script_sha256="1" * 64,
        applied_schema_sha256=canonical_schema_manifest(conn).sha256,
        release_id="release-pr195",
        fence=fence,
    )
    authority.release_fence(conn, fence)
    return conn, authority


def test_runtime_rejects_deleted_migration_ledger() -> None:
    conn, authority = _migrated()
    try:
        conn.execute("DELETE FROM migration_ledger_pr195")
        with pytest.raises(DatabaseSchemaAuthorityError, match="LEDGER_MISSING"):
            authority.verify_runtime(
                conn,
                environment="paper",
                cluster_genesis="reviewed-genesis",
                legacy_migrations_sha256=schema_migrations_digest(conn),
            )
    finally:
        conn.close()


def test_migration_chain_must_terminate_at_database_epoch() -> None:
    conn, authority = _migrated()
    try:
        with pytest.raises(DatabaseSchemaAuthorityError, match="EPOCH_MISMATCH"):
            authority.verify_migration_chain(conn, expected_epoch=20)
    finally:
        conn.close()

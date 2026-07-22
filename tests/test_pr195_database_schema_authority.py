from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from src.database_schema_authority_pr195 import (
    DatabasePathRegistry,
    DatabaseProductSpec,
    DatabaseSchemaAuthority,
    DatabaseSchemaAuthorityError,
    canonical_schema_manifest,
    schema_migrations_digest,
)


def _connection(path: Path | str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _expected_manifest() -> str:
    conn = _connection()
    try:
        conn.execute(
            "CREATE TABLE app_record(id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE schema_migrations("
            "version INTEGER PRIMARY KEY, applied_at REAL, "
            "schema_name TEXT, schema_checksum TEXT)"
        )
        DatabaseSchemaAuthority.install_authority_schema(conn)
        return canonical_schema_manifest(conn).sha256
    finally:
        conn.close()


def _spec(product: str = "observability", *, epoch: int = 19) -> DatabaseProductSpec:
    return DatabaseProductSpec(
        product_id=product,
        schema_family=f"{product}-family",
        application_schema_version=epoch,
        current_epoch=epoch,
        reader_min_epoch=epoch,
        reader_max_epoch=epoch,
        writer_min_epoch=epoch,
        writer_max_epoch=epoch,
        expected_schema_manifest_sha256=_expected_manifest(),
    )


def _migrated_connection() -> tuple[sqlite3.Connection, DatabaseSchemaAuthority]:
    conn = _connection()
    conn.execute(
        "CREATE TABLE app_record(id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE schema_migrations("
        "version INTEGER PRIMARY KEY, applied_at REAL, "
        "schema_name TEXT, schema_checksum TEXT)"
    )
    conn.execute(
        "INSERT INTO schema_migrations VALUES(18,1.0,'audit','a' || printf('%063d',0))"
    )
    authority = DatabaseSchemaAuthority(_spec(), now_utc_ns=lambda: 10_000_000_000)
    authority.install_authority_schema(conn)
    legacy = schema_migrations_digest(conn)
    fence = authority.acquire_fence(
        conn,
        owner_id="migration-owner-a",
        expected_epoch=0,
        lease_seconds=30,
    )
    authority.bootstrap_identity(
        conn,
        environment="paper",
        cluster_genesis="genesis-mainnet",
        release_id="release-195",
        legacy_migrations_sha256=legacy,
    )
    authority.append_migration(
        conn,
        migration_id="epoch-19",
        from_epoch=18,
        to_epoch=19,
        script_sha256="1" * 64,
        applied_schema_sha256=canonical_schema_manifest(conn).sha256,
        release_id="release-195",
        fence=fence,
    )
    authority.release_fence(conn, fence)
    return conn, authority


def test_identity_rejects_foreign_product_on_same_path() -> None:
    conn, _ = _migrated_connection()
    try:
        foreign = DatabaseSchemaAuthority(_spec("opportunity-dedup"))
        with pytest.raises(DatabaseSchemaAuthorityError, match="PRODUCT_ID_MISMATCH"):
            foreign.verify_identity(
                conn,
                environment="paper",
                cluster_genesis="genesis-mainnet",
                legacy_migrations_sha256=schema_migrations_digest(conn),
            )
    finally:
        conn.close()


def test_rogue_schema_object_is_not_adopted() -> None:
    conn, authority = _migrated_connection()
    try:
        conn.execute("CREATE TABLE rogue_table(value TEXT)")
        with pytest.raises(DatabaseSchemaAuthorityError, match="SCHEMA_MANIFEST_DRIFT"):
            authority.verify_runtime(
                conn,
                environment="paper",
                cluster_genesis="genesis-mainnet",
                legacy_migrations_sha256=schema_migrations_digest(conn),
            )
    finally:
        conn.close()


def test_modified_migration_entry_breaks_hash_chain() -> None:
    conn, authority = _migrated_connection()
    try:
        conn.execute(
            "UPDATE migration_ledger_pr195 SET script_sha256=? WHERE sequence=1",
            ("2" * 64,),
        )
        with pytest.raises(DatabaseSchemaAuthorityError, match="ENTRY_TAMPERED"):
            authority.verify_migration_chain(conn)
    finally:
        conn.close()


def test_future_epoch_fails_closed() -> None:
    conn, authority = _migrated_connection()
    try:
        conn.execute(
            "UPDATE database_identity_pr195 SET database_epoch=20 WHERE singleton=1"
        )
        with pytest.raises(DatabaseSchemaAuthorityError, match="FUTURE_EPOCH"):
            authority.verify_identity(
                conn,
                environment="paper",
                cluster_genesis="genesis-mainnet",
                legacy_migrations_sha256=schema_migrations_digest(conn),
            )
    finally:
        conn.close()


def test_active_migration_fence_blocks_second_owner() -> None:
    conn = _connection()
    authority = DatabaseSchemaAuthority(_spec(), now_utc_ns=lambda: 1_000_000_000)
    authority.install_authority_schema(conn)
    authority.acquire_fence(
        conn,
        owner_id="owner-a",
        expected_epoch=0,
        lease_seconds=30,
    )
    with pytest.raises(DatabaseSchemaAuthorityError, match="FENCE_HELD"):
        authority.acquire_fence(
            conn,
            owner_id="owner-b",
            expected_epoch=0,
            lease_seconds=30,
        )
    conn.close()


def test_lost_fencing_token_cannot_append_migration() -> None:
    conn = _connection()
    authority = DatabaseSchemaAuthority(_spec(), now_utc_ns=lambda: 1_000_000_000)
    authority.install_authority_schema(conn)
    old = authority.acquire_fence(
        conn,
        owner_id="owner-a",
        expected_epoch=0,
        lease_seconds=30,
    )
    authority.acquire_fence(
        conn,
        owner_id="owner-a",
        expected_epoch=0,
        lease_seconds=30,
    )
    with pytest.raises(DatabaseSchemaAuthorityError, match="FENCE_LOST"):
        authority.append_migration(
            conn,
            migration_id="epoch-19",
            from_epoch=18,
            to_epoch=19,
            script_sha256="1" * 64,
            applied_schema_sha256=_expected_manifest(),
            release_id="release-195",
            fence=old,
        )
    conn.close()


def test_path_registry_rejects_two_products_on_one_file(tmp_path: Path) -> None:
    shared = tmp_path / "shared.sqlite"
    with pytest.raises(DatabaseSchemaAuthorityError, match="PATH_PRODUCT_CONFLICT"):
        DatabasePathRegistry.assert_unique(
            {"observability": shared, "opportunity-dedup": shared}
        )


def test_runtime_rejects_active_migration_lease() -> None:
    conn, authority = _migrated_connection()
    try:
        authority.acquire_fence(
            conn,
            owner_id="deployment-controller",
            expected_epoch=19,
            lease_seconds=30,
        )
        with pytest.raises(DatabaseSchemaAuthorityError, match="MIGRATION_IN_PROGRESS"):
            authority.verify_runtime(
                conn,
                environment="paper",
                cluster_genesis="genesis-mainnet",
                legacy_migrations_sha256=schema_migrations_digest(conn),
            )
    finally:
        conn.close()

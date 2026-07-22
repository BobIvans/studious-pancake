from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from src.observability.authoritative_store_pr195 import (
    AuthoritativeObservabilityStore,
    PR195_OBSERVABILITY_EPOCH,
)
from src.observability.store import ObservabilityError


IDENTITY = {
    "environment": "paper",
    "cluster_genesis": "mainnet-genesis-reviewed",
    "release_id": "release-pr195-tests",
}


def _migrate(path: Path) -> None:
    with AuthoritativeObservabilityStore(
        path,
        migration_mode=True,
        migration_owner="pytest-migration-owner",
        **IDENTITY,
    ):
        pass


def _migration_checksum(path: Path, version: int) -> str:
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT schema_checksum FROM schema_migrations WHERE version=?",
            (version,),
        ).fetchone()
    assert row is not None
    return str(row[0])


def test_rogue_table_is_rejected_before_checksum_rewrite(tmp_path: Path) -> None:
    path = tmp_path / "observability.sqlite"
    _migrate(path)
    checksum_before = _migration_checksum(path, 18)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE rogue_table(value TEXT)")

    with pytest.raises(ObservabilityError, match="UNEXPECTED_SCHEMA_OBJECTS"):
        AuthoritativeObservabilityStore(
            path,
            migration_mode=True,
            migration_owner="second-owner",
            **IDENTITY,
        )

    assert _migration_checksum(path, 18) == checksum_before


def test_runtime_mode_never_auto_migrates_new_database(tmp_path: Path) -> None:
    path = tmp_path / "unmigrated.sqlite"
    with pytest.raises(ObservabilityError, match="DATABASE_IDENTITY_MISSING"):
        AuthoritativeObservabilityStore(path, **IDENTITY)
    with sqlite3.connect(path) as conn:
        names = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "event_log" not in names
    assert "database_identity_pr195" not in names


def test_runtime_accepts_exact_migrated_schema(tmp_path: Path) -> None:
    path = tmp_path / "observability.sqlite"
    _migrate(path)
    with AuthoritativeObservabilityStore(path, **IDENTITY) as store:
        assert int(store.db.execute("PRAGMA user_version").fetchone()[0]) == (
            PR195_OBSERVABILITY_EPOCH
        )


def test_wrong_constraint_with_same_columns_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "observability.sqlite"
    _migrate(path)
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE attempt_projection")
        conn.execute(
            """
            CREATE TABLE attempt_projection(
                attempt_id TEXT PRIMARY KEY,
                aggregate_id TEXT NOT NULL,
                last_sequence_no INTEGER NOT NULL,
                terminal TEXT NOT NULL,
                outcome TEXT,
                reason_code TEXT,
                updated_at REAL NOT NULL
            )
            """
        )

    with pytest.raises(ObservabilityError, match="SCHEMA_MANIFEST_DRIFT"):
        AuthoritativeObservabilityStore(path, **IDENTITY)


def test_foreign_product_identity_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "observability.sqlite"
    _migrate(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE database_identity_pr195 SET product_id='opportunity-dedup' "
            "WHERE singleton=1"
        )

    with pytest.raises(ObservabilityError, match="PRODUCT_ID_MISMATCH"):
        AuthoritativeObservabilityStore(path, **IDENTITY)


def test_future_epoch_is_rejected_before_runtime_write(tmp_path: Path) -> None:
    path = tmp_path / "observability.sqlite"
    _migrate(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE database_identity_pr195 SET database_epoch=? WHERE singleton=1",
            (PR195_OBSERVABILITY_EPOCH + 1,),
        )

    with pytest.raises(ObservabilityError, match="FUTURE_EPOCH"):
        AuthoritativeObservabilityStore(path, **IDENTITY)


def test_modified_legacy_migration_history_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "observability.sqlite"
    _migrate(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE schema_migrations SET schema_checksum=? WHERE version=18",
            ("f" * 64,),
        )

    with pytest.raises(ObservabilityError, match="LEGACY_MIGRATIONS_MISMATCH"):
        AuthoritativeObservabilityStore(path, **IDENTITY)


def test_active_migration_lease_blocks_runtime(tmp_path: Path) -> None:
    path = tmp_path / "observability.sqlite"
    _migrate(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            UPDATE migration_fence_pr195
            SET owner_id='other-deployer', lease_expires_utc_ns=9223372036854775807
            WHERE singleton=1
            """
        )

    with pytest.raises(ObservabilityError, match="MIGRATION_IN_PROGRESS"):
        AuthoritativeObservabilityStore(path, **IDENTITY)

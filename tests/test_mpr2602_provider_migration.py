"""Provider extension transactions on the accepted lifecycle database owner."""

from __future__ import annotations

import sqlite3

import pytest

from src.database_schema_authority_pr195 import (
    DatabaseProductSpec,
    DatabaseSchemaAuthority,
    DatabaseSchemaAuthorityError,
    canonical_schema_manifest,
)
from src.durability.unified_authority_pr02 import UnifiedLifecycleAuthority
from src.time_authority import TimeSnapshot, TimeSourceStatus

pytestmark = pytest.mark.unit
MIGRATION = "mpr2602.provider-obligations.v1"


class Clock:
    boot_id = "migration-fixture"
    process_generation = 1

    def snapshot(self):
        return TimeSnapshot(
            utc_ns=1_000_000,
            monotonic_ns=10_000,
            boot_id=self.boot_id,
            process_generation=self.process_generation,
            time_source_status=TimeSourceStatus.SYNCHRONIZED,
            max_uncertainty_ns=1,
        )

    def assert_healthy_for_sensitive_operation(self):
        return self.snapshot()


def _store(path=":memory:"):
    return UnifiedLifecycleAuthority(
        path,
        release_digest="a" * 64,
        policy_bundle_hash="b" * 64,
        time_authority=Clock(),
        owner_id="migration-test",
    )


def _rows(store, table):
    return tuple(tuple(row) for row in store.db.execute(f"SELECT * FROM {table}"))


def _snapshot(store):
    return (
        canonical_schema_manifest(store.db).sha256,
        _rows(store, "database_identity_pr195"),
        _rows(store, "migration_ledger_pr195"),
        _rows(store, "migration_fence_pr195"),
    )


def _migration(store, statements, migration_id="fixture.extension"):
    identity = store.db.execute("SELECT * FROM database_identity_pr195").fetchone()
    names = (
        "product_id",
        "schema_family",
        "application_schema_version",
        "reader_min_epoch",
        "reader_max_epoch",
        "writer_min_epoch",
        "writer_max_epoch",
        "expected_schema_manifest_sha256",
    )
    spec = DatabaseProductSpec(
        **{name: identity[name] for name in names},
        current_epoch=identity["database_epoch"],
    )
    DatabaseSchemaAuthority(
        spec, now_utc_ns=lambda: 1_000_000
    ).apply_additive_migration(
        store.db,
        migration_id=migration_id,
        statements=statements,
        owner_id="migration-test",
        release_id="a" * 64,
        environment=store.environment,
        cluster_genesis=store.cluster_genesis,
        legacy_migrations_sha256=identity["legacy_migrations_sha256"],
    )


def test_provider_extension_repeat_is_exact_replay():
    with _store() as store:
        store.install_provider_governance_schema()
        first = _snapshot(store)
        store.install_provider_governance_schema()
        assert _snapshot(store) == first
        assert (
            store.db.execute(
                "SELECT COUNT(*) FROM migration_ledger_pr195 WHERE migration_id=?",
                (MIGRATION,),
            ).fetchone()[0]
            == 1
        )


def test_caller_rollback_reverts_extension_ddl_identity_and_ledger():
    with _store() as store:
        before = _snapshot(store)
        with pytest.raises(RuntimeError, match="caller cancelled"):
            with store.lifecycle.write_transaction():
                store.install_provider_governance_schema()
                assert _snapshot(store) != before
                raise RuntimeError("caller cancelled")
        assert _snapshot(store) == before
        store.install_provider_governance_schema()


def test_partial_invalid_migration_rolls_back_earlier_ddl():
    with _store() as store:
        before = _snapshot(store)
        with pytest.raises(sqlite3.Error):
            with store.lifecycle.write_transaction():
                _migration(
                    store,
                    (
                        "CREATE TABLE fixture_partial (id INTEGER)",
                        "CREATE TABLE malformed (",
                    ),
                )
        assert _snapshot(store) == before


def test_migration_cannot_run_without_caller_transaction():
    with _store() as store:
        before = _snapshot(store)
        with pytest.raises(DatabaseSchemaAuthorityError, match="TRANSACTION_REQUIRED"):
            _migration(store, ("CREATE TABLE fixture_partial (id INTEGER)",))
        assert _snapshot(store) == before


def test_reused_migration_id_rejects_changed_script():
    with _store() as store:
        with store.lifecycle.write_transaction():
            _migration(store, ("CREATE TABLE fixture_extension (id INTEGER)",))
        before = _snapshot(store)
        with pytest.raises(DatabaseSchemaAuthorityError, match="SCRIPT_MISMATCH"):
            with store.lifecycle.write_transaction():
                _migration(store, ("CREATE TABLE fixture_other (id INTEGER)",))
        assert _snapshot(store) == before


def test_unledgered_schema_tampering_cannot_be_blessed_by_provider_extension():
    with _store() as store:
        with store.lifecycle.write_transaction():
            store.db.execute("CREATE TABLE injected_unledgered (id INTEGER)")
        before = _snapshot(store)
        with pytest.raises(DatabaseSchemaAuthorityError):
            store.install_provider_governance_schema()
        assert _snapshot(store) == before


@pytest.mark.parametrize("statement", ["DROP TABLE pr02_terminal_records", "COMMIT"])
def test_additive_migration_rejects_destructive_or_transaction_control_sql(statement):
    with _store() as store:
        before = _snapshot(store)
        with pytest.raises(DatabaseSchemaAuthorityError):
            with store.lifecycle.write_transaction():
                _migration(store, (statement,))
        assert _snapshot(store) == before


def test_provider_extension_preserves_foundation_objects_and_database_identity():
    with _store() as store:
        before_objects = canonical_schema_manifest(store.db).objects
        identity = dict(
            store.db.execute("SELECT * FROM database_identity_pr195").fetchone()
        )
        ledger = _rows(store, "migration_ledger_pr195")
        store.install_provider_governance_schema()
        after_objects = canonical_schema_manifest(store.db).objects
        assert all(obj in after_objects for obj in before_objects)
        current = dict(
            store.db.execute("SELECT * FROM database_identity_pr195").fetchone()
        )
        for key, value in identity.items():
            if key != "expected_schema_manifest_sha256":
                assert current[key] == value
        assert _rows(store, "migration_ledger_pr195")[: len(ledger)] == ledger
        fence = store.begin_cycle_intent(
            run_id="after-migration",
            sequence=1,
            config_fingerprint="c" * 64,
            source_surface="installed-cli",
        )
        assert fence.intent_id


def test_provider_extension_survives_actual_file_close_and_reopen(tmp_path):
    path = tmp_path / "provider.sqlite3"
    with _store(path) as store:
        store.install_provider_governance_schema()
        before = _snapshot(store)
    with _store(path) as reopened:
        reopened.install_provider_governance_schema()
        # Opening advances the migration fence, but identity/schema/ledger do not change.
        assert _snapshot(reopened)[:3] == before[:3]

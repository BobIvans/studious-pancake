"""PR-195 authoritative schema epoch wrapper for the observability database."""

from __future__ import annotations

from functools import lru_cache
import hashlib
from pathlib import Path
import sqlite3
import time
from typing import Any

from src.database_schema_authority_pr195 import (
    IDENTITY_TABLE,
    DatabaseProductSpec,
    DatabaseSchemaAuthority,
    DatabaseSchemaAuthorityError,
    MigrationFence,
    canonical_schema_manifest,
    existing_schema_objects,
    schema_migrations_digest,
)
from .store import (
    AUDIT_MIGRATION_VERSION,
    ObservabilityError,
    ObservabilityStore as LegacyObservabilityStore,
)

PR195_OBSERVABILITY_PRODUCT_ID = "flashloan-observability"
PR195_OBSERVABILITY_SCHEMA_FAMILY = "observability-event-projection"
PR195_OBSERVABILITY_EPOCH = 19
PR195_OBSERVABILITY_SCHEMA_VERSION = 19
PR195_MIGRATION_ID = "pr195-observability-schema-authority-epoch-19"
PR195_MIGRATION_SCRIPT_SHA256 = hashlib.sha256(
    b"pr195:observability:identity+manifest+ledger+fence:v1"
).hexdigest()


@lru_cache(maxsize=1)
def expected_observability_manifest_sha256() -> str:
    """Build the exact expected schema from source, never from the target DB."""
    store = LegacyObservabilityStore(":memory:")
    try:
        DatabaseSchemaAuthority.install_authority_schema(store.db)
        return canonical_schema_manifest(store.db).sha256
    finally:
        store.close()


@lru_cache(maxsize=1)
def expected_observability_object_names() -> frozenset[str]:
    store = LegacyObservabilityStore(":memory:")
    try:
        DatabaseSchemaAuthority.install_authority_schema(store.db)
        return existing_schema_objects(store.db)
    finally:
        store.close()


def observability_product_spec() -> DatabaseProductSpec:
    return DatabaseProductSpec(
        product_id=PR195_OBSERVABILITY_PRODUCT_ID,
        schema_family=PR195_OBSERVABILITY_SCHEMA_FAMILY,
        application_schema_version=PR195_OBSERVABILITY_SCHEMA_VERSION,
        current_epoch=PR195_OBSERVABILITY_EPOCH,
        reader_min_epoch=PR195_OBSERVABILITY_EPOCH,
        reader_max_epoch=PR195_OBSERVABILITY_EPOCH,
        writer_min_epoch=PR195_OBSERVABILITY_EPOCH,
        writer_max_epoch=PR195_OBSERVABILITY_EPOCH,
        expected_schema_manifest_sha256=(
            expected_observability_manifest_sha256()
        ),
    )


class AuthoritativeObservabilityStore(LegacyObservabilityStore):
    """Observability store with immutable identity and startup-only migration."""

    def __init__(
        self,
        path: str | Path,
        *,
        environment: str,
        cluster_genesis: str,
        release_id: str,
        migration_mode: bool = False,
        migration_owner: str | None = None,
        migration_lease_seconds: float = 30.0,
        busy_timeout_ms: int = 2500,
        now_utc_ns: Any | None = None,
    ) -> None:
        self._pr195_environment = environment
        self._pr195_cluster_genesis = cluster_genesis
        self._pr195_release_id = release_id
        self._pr195_migration_mode = migration_mode
        self._pr195_migration_owner = migration_owner
        self._pr195_migration_lease_seconds = migration_lease_seconds
        self._pr195_authority = DatabaseSchemaAuthority(
            observability_product_spec(),
            **({} if now_utc_ns is None else {"now_utc_ns": now_utc_ns}),
        )
        self._preflight_existing_database(path)
        super().__init__(path, busy_timeout_ms=busy_timeout_ms)

    def _preflight_existing_database(self, path: str | Path) -> None:
        if str(path) == ":memory:":
            return
        database_path = Path(path)
        if not database_path.exists() or database_path.stat().st_size == 0:
            return
        uri = f"file:{database_path.resolve()}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True)
            conn.row_factory = sqlite3.Row
            try:
                actual = existing_schema_objects(conn)
                unexpected = actual - expected_observability_object_names()
                if unexpected:
                    raise ObservabilityError(
                        "OBSERVABILITY_UNEXPECTED_SCHEMA_OBJECTS:"
                        + ",".join(sorted(unexpected))
                    )
                if IDENTITY_TABLE in actual:
                    self._pr195_authority.verify_identity(
                        conn,
                        environment=self._pr195_environment,
                        cluster_genesis=self._pr195_cluster_genesis,
                        legacy_migrations_sha256=schema_migrations_digest(conn),
                    )
            finally:
                conn.close()
        except DatabaseSchemaAuthorityError as exc:
            raise ObservabilityError(str(exc)) from exc
        except sqlite3.Error as exc:
            raise ObservabilityError(
                "OBSERVABILITY_SCHEMA_PREFLIGHT_FAILED"
            ) from exc

    def migrate(self) -> None:
        if not self._pr195_migration_mode:
            self._verify_runtime_only()
            return
        owner = self._pr195_migration_owner
        if owner is None or not owner.strip():
            raise ObservabilityError("OBSERVABILITY_MIGRATION_OWNER_REQUIRED")

        fence: MigrationFence | None = None
        try:
            DatabaseSchemaAuthority.install_authority_schema(self.db)
            self.db.execute("BEGIN IMMEDIATE")
            current_epoch = self._current_identity_epoch(default=0)
            fence = self._pr195_authority.acquire_fence(
                self.db,
                owner_id=owner,
                expected_epoch=current_epoch,
                lease_seconds=self._pr195_migration_lease_seconds,
            )
            self.db.execute("COMMIT")

            LegacyObservabilityStore.migrate(self)

            self.db.execute("BEGIN IMMEDIATE")
            manifest = canonical_schema_manifest(self.db)
            expected_manifest = expected_observability_manifest_sha256()
            if manifest.sha256 != expected_manifest:
                raise ObservabilityError(
                    "OBSERVABILITY_EXACT_SCHEMA_MANIFEST_DRIFT"
                )
            legacy_digest = schema_migrations_digest(self.db)
            self._pr195_authority.bootstrap_identity(
                self.db,
                environment=self._pr195_environment,
                cluster_genesis=self._pr195_cluster_genesis,
                release_id=self._pr195_release_id,
                legacy_migrations_sha256=legacy_digest,
            )
            self._pr195_authority.append_migration(
                self.db,
                migration_id=PR195_MIGRATION_ID,
                from_epoch=AUDIT_MIGRATION_VERSION,
                to_epoch=PR195_OBSERVABILITY_EPOCH,
                script_sha256=PR195_MIGRATION_SCRIPT_SHA256,
                applied_schema_sha256=manifest.sha256,
                release_id=self._pr195_release_id,
                fence=fence,
            )
            self.db.execute(f"PRAGMA user_version={PR195_OBSERVABILITY_EPOCH}")
            self._pr195_authority.release_fence(self.db, fence)
            self.db.execute("COMMIT")
        except (DatabaseSchemaAuthorityError, sqlite3.Error) as exc:
            self._rollback_if_needed()
            self._release_fence_best_effort(fence)
            raise ObservabilityError(str(exc)) from exc
        except Exception:
            self._rollback_if_needed()
            self._release_fence_best_effort(fence)
            raise

    def _stamp_migration(
        self,
        *,
        version: int,
        schema_name: str,
        schema_checksum: str,
    ) -> None:
        """Insert legacy rows once; never rewrite historical migration metadata."""
        row = self.db.execute(
            "SELECT schema_name,schema_checksum FROM schema_migrations WHERE version=?",
            (version,),
        ).fetchone()
        if row is None:
            self.db.execute(
                """
                INSERT INTO schema_migrations(
                    version,applied_at,schema_name,schema_checksum
                ) VALUES(?,?,?,?)
                """,
                (version, time.time(), schema_name, schema_checksum),
            )
            return
        if str(row["schema_name"]) != schema_name:
            raise ObservabilityError(
                "OBSERVABILITY_MIGRATION_HISTORY_CONFLICT"
            )
        # Existing checksum is historical evidence. It is deliberately preserved.

    def _verify_runtime_only(self) -> None:
        try:
            legacy_digest = schema_migrations_digest(self.db)
            self._pr195_authority.verify_runtime(
                self.db,
                environment=self._pr195_environment,
                cluster_genesis=self._pr195_cluster_genesis,
                legacy_migrations_sha256=legacy_digest,
            )
            user_version = int(self.db.execute("PRAGMA user_version").fetchone()[0])
            if user_version != PR195_OBSERVABILITY_EPOCH:
                raise ObservabilityError(
                    "OBSERVABILITY_DATABASE_EPOCH_MISMATCH"
                )
        except DatabaseSchemaAuthorityError as exc:
            raise ObservabilityError(str(exc)) from exc
        except sqlite3.Error as exc:
            raise ObservabilityError("DATABASE_IDENTITY_MISSING") from exc

    def _current_identity_epoch(self, *, default: int) -> int:
        row = self.db.execute(
            f"SELECT database_epoch FROM {IDENTITY_TABLE} WHERE singleton=1"
        ).fetchone()
        return default if row is None else int(row["database_epoch"])

    def _rollback_if_needed(self) -> None:
        if self.db.in_transaction:
            self.db.execute("ROLLBACK")

    def _release_fence_best_effort(
        self,
        fence: MigrationFence | None,
    ) -> None:
        if fence is None:
            return
        try:
            self.db.execute("BEGIN IMMEDIATE")
            self._pr195_authority.release_fence(self.db, fence)
            self.db.execute("COMMIT")
        except Exception:
            self._rollback_if_needed()


__all__ = [
    "AuthoritativeObservabilityStore",
    "PR195_MIGRATION_ID",
    "PR195_OBSERVABILITY_EPOCH",
    "PR195_OBSERVABILITY_PRODUCT_ID",
    "expected_observability_manifest_sha256",
    "observability_product_spec",
]

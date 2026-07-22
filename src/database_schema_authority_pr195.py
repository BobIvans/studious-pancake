"""PR-195 database product identity, schema epochs, and migration fencing."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Mapping
import uuid

PR195_AUTHORITY_SCHEMA = "pr195.database-schema-authority.v1"
ZERO_HASH = "0" * 64
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IDENTITY_TABLE = "database_identity_pr195"
MIGRATION_LEDGER_TABLE = "migration_ledger_pr195"
MIGRATION_FENCE_TABLE = "migration_fence_pr195"
AUTHORITY_TABLES = frozenset(
    {IDENTITY_TABLE, MIGRATION_LEDGER_TABLE, MIGRATION_FENCE_TABLE}
)


class DatabaseSchemaAuthorityError(RuntimeError):
    """Fail-closed PR-195 database authority error."""


@dataclass(frozen=True, slots=True)
class DatabaseProductSpec:
    product_id: str
    schema_family: str
    application_schema_version: int
    current_epoch: int
    reader_min_epoch: int
    reader_max_epoch: int
    writer_min_epoch: int
    writer_max_epoch: int
    expected_schema_manifest_sha256: str

    def __post_init__(self) -> None:
        if not self.product_id.strip() or not self.schema_family.strip():
            raise ValueError("product_id and schema_family are required")
        if self.application_schema_version <= 0 or self.current_epoch <= 0:
            raise ValueError("schema version and epoch must be positive")
        if not self.reader_min_epoch <= self.current_epoch <= self.reader_max_epoch:
            raise ValueError("current epoch is outside reader compatibility")
        if not self.writer_min_epoch <= self.current_epoch <= self.writer_max_epoch:
            raise ValueError("current epoch is outside writer compatibility")
        _require_sha256(
            self.expected_schema_manifest_sha256,
            "expected_schema_manifest_sha256",
        )


@dataclass(frozen=True, slots=True)
class DatabaseIdentity:
    database_uuid: str
    product_id: str
    schema_family: str
    environment: str
    cluster_genesis: str
    created_by_release: str
    created_at_utc_ns: int
    application_schema_version: int
    database_epoch: int
    reader_min_epoch: int
    reader_max_epoch: int
    writer_min_epoch: int
    writer_max_epoch: int
    expected_schema_manifest_sha256: str
    legacy_migrations_sha256: str


@dataclass(frozen=True, slots=True)
class MigrationFence:
    owner_id: str
    fencing_token: int
    lease_expires_utc_ns: int
    expected_epoch: int


@dataclass(frozen=True, slots=True)
class SchemaManifest:
    objects: tuple[Mapping[str, str], ...]
    sha256: str


class DatabasePathRegistry:
    @staticmethod
    def assert_unique(product_paths: Mapping[str, str | Path]) -> None:
        owners: dict[str, str] = {}
        for product, raw_path in product_paths.items():
            path = str(Path(raw_path).expanduser().resolve(strict=False))
            other = owners.get(path)
            if other is not None and other != product:
                raise DatabaseSchemaAuthorityError(
                    f"DATABASE_PATH_PRODUCT_CONFLICT:{other}:{product}:{path}"
                )
            owners[path] = product


class DatabaseSchemaAuthority:
    def __init__(
        self,
        spec: DatabaseProductSpec,
        *,
        now_utc_ns: Any = time.time_ns,
    ) -> None:
        self.spec = spec
        self._now_utc_ns = now_utc_ns

    @staticmethod
    def install_authority_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS {IDENTITY_TABLE}(
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                database_uuid TEXT NOT NULL UNIQUE,
                product_id TEXT NOT NULL,
                schema_family TEXT NOT NULL,
                environment TEXT NOT NULL,
                cluster_genesis TEXT NOT NULL,
                created_by_release TEXT NOT NULL,
                created_at_utc_ns INTEGER NOT NULL,
                application_schema_version INTEGER NOT NULL,
                database_epoch INTEGER NOT NULL,
                reader_min_epoch INTEGER NOT NULL,
                reader_max_epoch INTEGER NOT NULL,
                writer_min_epoch INTEGER NOT NULL,
                writer_max_epoch INTEGER NOT NULL,
                expected_schema_manifest_sha256 TEXT NOT NULL,
                legacy_migrations_sha256 TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS {MIGRATION_LEDGER_TABLE}(
                sequence INTEGER PRIMARY KEY,
                migration_id TEXT NOT NULL UNIQUE,
                from_epoch INTEGER NOT NULL,
                to_epoch INTEGER NOT NULL,
                script_sha256 TEXT NOT NULL,
                previous_entry_hash TEXT NOT NULL,
                applied_schema_sha256 TEXT NOT NULL,
                release_id TEXT NOT NULL,
                fencing_token INTEGER NOT NULL,
                applied_at_utc_ns INTEGER NOT NULL,
                entry_hash TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS {MIGRATION_FENCE_TABLE}(
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                owner_id TEXT NOT NULL,
                fencing_token INTEGER NOT NULL,
                lease_expires_utc_ns INTEGER NOT NULL,
                expected_epoch INTEGER NOT NULL
            );
            """
        )

    def acquire_fence(
        self,
        conn: sqlite3.Connection,
        *,
        owner_id: str,
        expected_epoch: int,
        lease_seconds: float = 30.0,
    ) -> MigrationFence:
        if not owner_id.strip():
            raise ValueError("migration owner_id is required")
        if not 0 < lease_seconds <= 300:
            raise ValueError("migration lease must be in (0, 300] seconds")
        identity = conn.execute(
            f"SELECT database_epoch FROM {IDENTITY_TABLE} WHERE singleton=1"
        ).fetchone()
        if identity is not None and int(identity["database_epoch"]) != expected_epoch:
            raise DatabaseSchemaAuthorityError(
                "DATABASE_MIGRATION_EXPECTED_EPOCH_MISMATCH"
            )
        now = int(self._now_utc_ns())
        current = conn.execute(
            f"SELECT * FROM {MIGRATION_FENCE_TABLE} WHERE singleton=1"
        ).fetchone()
        if current is not None:
            active = int(current["lease_expires_utc_ns"]) > now
            if active and str(current["owner_id"]) != owner_id:
                raise DatabaseSchemaAuthorityError("DATABASE_MIGRATION_FENCE_HELD")
            token = int(current["fencing_token"]) + 1
        else:
            token = 1
        expires = now + int(lease_seconds * 1_000_000_000)
        conn.execute(
            f"""
            INSERT INTO {MIGRATION_FENCE_TABLE}
                (singleton,owner_id,fencing_token,lease_expires_utc_ns,expected_epoch)
            VALUES(1,?,?,?,?)
            ON CONFLICT(singleton) DO UPDATE SET
                owner_id=excluded.owner_id,
                fencing_token=excluded.fencing_token,
                lease_expires_utc_ns=excluded.lease_expires_utc_ns,
                expected_epoch=excluded.expected_epoch
            """,
            (owner_id, token, expires, expected_epoch),
        )
        return MigrationFence(owner_id, token, expires, expected_epoch)

    def release_fence(
        self, conn: sqlite3.Connection, fence: MigrationFence
    ) -> None:
        cursor = conn.execute(
            f"""
            UPDATE {MIGRATION_FENCE_TABLE} SET lease_expires_utc_ns=0
            WHERE singleton=1 AND owner_id=? AND fencing_token=?
            """,
            (fence.owner_id, fence.fencing_token),
        )
        if cursor.rowcount != 1:
            raise DatabaseSchemaAuthorityError("DATABASE_MIGRATION_FENCE_LOST")

    def bootstrap_identity(
        self,
        conn: sqlite3.Connection,
        *,
        environment: str,
        cluster_genesis: str,
        release_id: str,
        legacy_migrations_sha256: str,
    ) -> DatabaseIdentity:
        for name, value in (
            ("environment", environment),
            ("cluster_genesis", cluster_genesis),
            ("release_id", release_id),
        ):
            if not value.strip() or value.lower() in {"unknown", "placeholder"}:
                raise DatabaseSchemaAuthorityError(
                    f"DATABASE_IDENTITY_{name.upper()}_INVALID"
                )
        _require_sha256(legacy_migrations_sha256, "legacy_migrations_sha256")
        if conn.execute(
            f"SELECT 1 FROM {IDENTITY_TABLE} WHERE singleton=1"
        ).fetchone() is None:
            values = (
                uuid.uuid4().hex,
                self.spec.product_id,
                self.spec.schema_family,
                environment,
                cluster_genesis,
                release_id,
                int(self._now_utc_ns()),
                self.spec.application_schema_version,
                self.spec.current_epoch,
                self.spec.reader_min_epoch,
                self.spec.reader_max_epoch,
                self.spec.writer_min_epoch,
                self.spec.writer_max_epoch,
                self.spec.expected_schema_manifest_sha256,
                legacy_migrations_sha256,
            )
            conn.execute(
                f"INSERT INTO {IDENTITY_TABLE} VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                values,
            )
        return self.verify_identity(
            conn,
            environment=environment,
            cluster_genesis=cluster_genesis,
            legacy_migrations_sha256=legacy_migrations_sha256,
        )

    def verify_identity(
        self,
        conn: sqlite3.Connection,
        *,
        environment: str,
        cluster_genesis: str,
        legacy_migrations_sha256: str,
    ) -> DatabaseIdentity:
        row = conn.execute(
            f"SELECT * FROM {IDENTITY_TABLE} WHERE singleton=1"
        ).fetchone()
        if row is None:
            raise DatabaseSchemaAuthorityError("DATABASE_IDENTITY_MISSING")
        identity = _identity_from_row(row)
        checks = {
            "PRODUCT_ID": identity.product_id == self.spec.product_id,
            "SCHEMA_FAMILY": identity.schema_family == self.spec.schema_family,
            "ENVIRONMENT": identity.environment == environment,
            "CLUSTER": identity.cluster_genesis == cluster_genesis,
            "APP_SCHEMA": identity.application_schema_version
            == self.spec.application_schema_version,
            "EXPECTED_MANIFEST": identity.expected_schema_manifest_sha256
            == self.spec.expected_schema_manifest_sha256,
            "READER_RANGE": (
                identity.reader_min_epoch == self.spec.reader_min_epoch
                and identity.reader_max_epoch == self.spec.reader_max_epoch
            ),
            "WRITER_RANGE": (
                identity.writer_min_epoch == self.spec.writer_min_epoch
                and identity.writer_max_epoch == self.spec.writer_max_epoch
            ),
            "LEGACY_MIGRATIONS": identity.legacy_migrations_sha256
            == legacy_migrations_sha256,
        }
        for reason, ok in checks.items():
            if not ok:
                raise DatabaseSchemaAuthorityError(
                    f"DATABASE_IDENTITY_{reason}_MISMATCH"
                )
        if identity.database_epoch > self.spec.writer_max_epoch:
            raise DatabaseSchemaAuthorityError("DATABASE_FUTURE_EPOCH")
        if not (
            self.spec.writer_min_epoch
            <= identity.database_epoch
            <= self.spec.writer_max_epoch
        ):
            raise DatabaseSchemaAuthorityError("DATABASE_WRITER_EPOCH_UNSUPPORTED")
        return identity

    def append_migration(
        self,
        conn: sqlite3.Connection,
        *,
        migration_id: str,
        from_epoch: int,
        to_epoch: int,
        script_sha256: str,
        applied_schema_sha256: str,
        release_id: str,
        fence: MigrationFence,
    ) -> str:
        if from_epoch < 0 or to_epoch != self.spec.current_epoch:
            raise DatabaseSchemaAuthorityError(
                "DATABASE_MIGRATION_EPOCH_CONTRACT_INVALID"
            )
        if not release_id.strip():
            raise DatabaseSchemaAuthorityError(
                "DATABASE_MIGRATION_RELEASE_ID_INVALID"
            )
        _require_sha256(script_sha256, "script_sha256")
        _require_sha256(applied_schema_sha256, "applied_schema_sha256")
        self.assert_fence(conn, fence)
        existing = conn.execute(
            f"SELECT * FROM {MIGRATION_LEDGER_TABLE} WHERE migration_id=?",
            (migration_id,),
        ).fetchone()
        if existing is not None:
            expected = {
                "from_epoch": from_epoch,
                "to_epoch": to_epoch,
                "script_sha256": script_sha256,
                "applied_schema_sha256": applied_schema_sha256,
                "release_id": release_id,
            }
            if any(existing[key] != value for key, value in expected.items()):
                raise DatabaseSchemaAuthorityError(
                    "DATABASE_MIGRATION_IMMUTABILITY_CONFLICT"
                )
            return str(existing["entry_hash"])
        prior = conn.execute(
            f"SELECT sequence,entry_hash FROM {MIGRATION_LEDGER_TABLE} "
            "ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        sequence = 1 if prior is None else int(prior["sequence"]) + 1
        previous = ZERO_HASH if prior is None else str(prior["entry_hash"])
        applied_at = int(self._now_utc_ns())
        payload = {
            "sequence": sequence,
            "migration_id": migration_id,
            "from_epoch": from_epoch,
            "to_epoch": to_epoch,
            "script_sha256": script_sha256,
            "previous_entry_hash": previous,
            "applied_schema_sha256": applied_schema_sha256,
            "release_id": release_id,
            "fencing_token": fence.fencing_token,
            "applied_at_utc_ns": applied_at,
        }
        entry_hash = _digest(payload)
        conn.execute(
            f"INSERT INTO {MIGRATION_LEDGER_TABLE} VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                sequence,
                migration_id,
                from_epoch,
                to_epoch,
                script_sha256,
                previous,
                applied_schema_sha256,
                release_id,
                fence.fencing_token,
                applied_at,
                entry_hash,
            ),
        )
        return entry_hash

    def assert_fence(
        self, conn: sqlite3.Connection, fence: MigrationFence
    ) -> None:
        row = conn.execute(
            f"SELECT * FROM {MIGRATION_FENCE_TABLE} WHERE singleton=1"
        ).fetchone()
        if (
            row is None
            or str(row["owner_id"]) != fence.owner_id
            or int(row["fencing_token"]) != fence.fencing_token
            or int(row["lease_expires_utc_ns"]) <= int(self._now_utc_ns())
        ):
            raise DatabaseSchemaAuthorityError("DATABASE_MIGRATION_FENCE_LOST")

    def verify_runtime(
        self,
        conn: sqlite3.Connection,
        *,
        environment: str,
        cluster_genesis: str,
        legacy_migrations_sha256: str,
    ) -> DatabaseIdentity:
        identity = self.verify_identity(
            conn,
            environment=environment,
            cluster_genesis=cluster_genesis,
            legacy_migrations_sha256=legacy_migrations_sha256,
        )
        if canonical_schema_manifest(conn).sha256 != (
            self.spec.expected_schema_manifest_sha256
        ):
            raise DatabaseSchemaAuthorityError("DATABASE_SCHEMA_MANIFEST_DRIFT")
        self.verify_migration_chain(conn, expected_epoch=identity.database_epoch)
        fence = conn.execute(
            f"SELECT * FROM {MIGRATION_FENCE_TABLE} WHERE singleton=1"
        ).fetchone()
        if fence is not None and int(fence["lease_expires_utc_ns"]) > int(
            self._now_utc_ns()
        ):
            raise DatabaseSchemaAuthorityError("DATABASE_MIGRATION_IN_PROGRESS")
        return identity

    @staticmethod
    def verify_migration_chain(
        conn: sqlite3.Connection, *, expected_epoch: int | None = None
    ) -> None:
        rows = conn.execute(
            f"SELECT * FROM {MIGRATION_LEDGER_TABLE} ORDER BY sequence"
        ).fetchall()
        if not rows:
            raise DatabaseSchemaAuthorityError("DATABASE_MIGRATION_LEDGER_MISSING")
        previous = ZERO_HASH
        final_epoch: int | None = None
        for expected_sequence, row in enumerate(rows, start=1):
            if int(row["sequence"]) != expected_sequence:
                raise DatabaseSchemaAuthorityError(
                    "DATABASE_MIGRATION_SEQUENCE_GAP"
                )
            payload = {
                key: int(row[key])
                if key
                in {
                    "sequence",
                    "from_epoch",
                    "to_epoch",
                    "fencing_token",
                    "applied_at_utc_ns",
                }
                else str(row[key])
                for key in (
                    "sequence",
                    "migration_id",
                    "from_epoch",
                    "to_epoch",
                    "script_sha256",
                    "previous_entry_hash",
                    "applied_schema_sha256",
                    "release_id",
                    "fencing_token",
                    "applied_at_utc_ns",
                )
            }
            if payload["previous_entry_hash"] != previous:
                raise DatabaseSchemaAuthorityError(
                    "DATABASE_MIGRATION_CHAIN_BROKEN"
                )
            if _digest(payload) != str(row["entry_hash"]):
                raise DatabaseSchemaAuthorityError(
                    "DATABASE_MIGRATION_ENTRY_TAMPERED"
                )
            previous = str(row["entry_hash"])
            final_epoch = int(row["to_epoch"])
        if expected_epoch is not None and final_epoch != expected_epoch:
            raise DatabaseSchemaAuthorityError(
                "DATABASE_MIGRATION_LEDGER_EPOCH_MISMATCH"
            )


def canonical_schema_manifest(conn: sqlite3.Connection) -> SchemaManifest:
    rows = conn.execute(
        """
        SELECT type,name,tbl_name,sql FROM sqlite_master
        WHERE type IN ('table','index','trigger','view')
          AND name NOT LIKE 'sqlite_%'
        ORDER BY type,name
        """
    ).fetchall()
    objects = tuple(
        {
            "type": str(row["type"]),
            "name": str(row["name"]),
            "table": str(row["tbl_name"]),
            "sql": " ".join(str(row["sql"] or "").split()),
        }
        for row in rows
    )
    return SchemaManifest(objects, _digest(objects))


def existing_schema_objects(conn: sqlite3.Connection) -> frozenset[str]:
    rows = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type IN ('table','index','trigger','view')
          AND name NOT LIKE 'sqlite_%'
        """
    ).fetchall()
    return frozenset(str(row["name"]) for row in rows)


def schema_migrations_digest(conn: sqlite3.Connection) -> str:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if exists is None:
        return _digest(())
    columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(schema_migrations)")
    }
    selected = ["version"] + [
        name
        for name in ("applied_at", "schema_name", "schema_checksum")
        if name in columns
    ]
    rows = conn.execute(
        f"SELECT {','.join(selected)} FROM schema_migrations ORDER BY version"
    ).fetchall()
    return _digest(tuple({name: row[name] for name in selected} for row in rows))


def _identity_from_row(row: sqlite3.Row) -> DatabaseIdentity:
    return DatabaseIdentity(
        database_uuid=str(row["database_uuid"]),
        product_id=str(row["product_id"]),
        schema_family=str(row["schema_family"]),
        environment=str(row["environment"]),
        cluster_genesis=str(row["cluster_genesis"]),
        created_by_release=str(row["created_by_release"]),
        created_at_utc_ns=int(row["created_at_utc_ns"]),
        application_schema_version=int(row["application_schema_version"]),
        database_epoch=int(row["database_epoch"]),
        reader_min_epoch=int(row["reader_min_epoch"]),
        reader_max_epoch=int(row["reader_max_epoch"]),
        writer_min_epoch=int(row["writer_min_epoch"]),
        writer_max_epoch=int(row["writer_max_epoch"]),
        expected_schema_manifest_sha256=str(
            row["expected_schema_manifest_sha256"]
        ),
        legacy_migrations_sha256=str(row["legacy_migrations_sha256"]),
    )


def _require_sha256(value: str, field: str) -> None:
    if not _SHA256_RE.fullmatch(value) or value in {ZERO_HASH, "f" * 64}:
        raise ValueError(f"{field} must be a non-placeholder sha256")


def _digest(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


__all__ = [
    "AUTHORITY_TABLES",
    "DatabaseIdentity",
    "DatabasePathRegistry",
    "DatabaseProductSpec",
    "DatabaseSchemaAuthority",
    "DatabaseSchemaAuthorityError",
    "MigrationFence",
    "PR195_AUTHORITY_SCHEMA",
    "SchemaManifest",
    "canonical_schema_manifest",
    "existing_schema_objects",
    "schema_migrations_digest",
]

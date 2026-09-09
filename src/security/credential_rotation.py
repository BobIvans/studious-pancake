"""MPR-2618 durable credential/trust rotation and revocation fencing.

This module is metadata-only and DEFAULT-OFF. It never stores secret values and
never performs provider, signer, or network effects. Sensitive consumers must
call the fence immediately before each future use.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Callable

from src.config.credential_lifecycle import CredentialState, SecretHandle, SecretLifecycleError
from src.security.trust_anchors import (
    SignedEnvelope,
    TrustAnchorRegistry,
    TrustUsage,
    TrustVerificationResult,
)

MPR2618_SCHEMA = "studious-pancake.mpr2618.credential-trust-rotation.v1"
MPR2618_DEFAULT_ENABLED = False
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CredentialRotationError(RuntimeError):
    """Fail-closed rotation/revocation error."""


class RotationReason(StrEnum):
    PLANNED = "planned"
    COMPROMISE = "compromise"
    EXPIRED = "expired"
    BACKEND_CHANGE = "backend-change"


@dataclass(frozen=True, slots=True)
class CredentialVersion:
    secret_id: str
    version: str
    backend_ref: str
    consumer_id: str
    usage_scope: str
    state: CredentialState
    generation: int
    issued_at_ns: int
    not_before_ns: int
    expires_at_ns: int
    supersedes_version: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.secret_id, "secret_id"),
            (self.version, "version"),
            (self.backend_ref, "backend_ref"),
            (self.consumer_id, "consumer_id"),
            (self.usage_scope, "usage_scope"),
        ):
            _identifier(value, label)
        _positive_int(self.generation, "generation")
        _nonnegative_int(self.issued_at_ns, "issued_at_ns")
        _nonnegative_int(self.not_before_ns, "not_before_ns")
        _positive_int(self.expires_at_ns, "expires_at_ns")
        if self.not_before_ns < self.issued_at_ns or self.expires_at_ns <= self.not_before_ns:
            raise ValueError("invalid credential validity window")


@dataclass(frozen=True, slots=True)
class RotationPlan:
    rotation_id: str
    secret_id: str
    expected_current_version: str
    new_version: str
    validation_sha256: str
    allowed_overlap_until_ns: int | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.rotation_id, "rotation_id"),
            (self.secret_id, "secret_id"),
            (self.expected_current_version, "expected_current_version"),
            (self.new_version, "new_version"),
        ):
            _identifier(value, label)
        _sha256(self.validation_sha256, "validation_sha256")
        if self.allowed_overlap_until_ns is not None:
            _positive_int(self.allowed_overlap_until_ns, "allowed_overlap_until_ns")

    @property
    def semantic_hash(self) -> str:
        return _hash_json(
            {
                "schema": MPR2618_SCHEMA,
                "rotation_id": self.rotation_id,
                "secret_id": self.secret_id,
                "expected_current_version": self.expected_current_version,
                "new_version": self.new_version,
                "validation_sha256": self.validation_sha256,
                "allowed_overlap_until_ns": self.allowed_overlap_until_ns,
            }
        )


@dataclass(frozen=True, slots=True)
class RotationReceipt:
    rotation_id: str
    secret_id: str
    old_version: str
    new_version: str
    rotation_epoch: int
    revocation_epoch: int
    semantic_hash: str
    committed_at_ns: int


@dataclass(frozen=True, slots=True)
class RevocationReceipt:
    incident_id: str
    secret_id: str
    version: str
    reason: RotationReason
    rotation_epoch: int
    revocation_epoch: int
    committed_at_ns: int
    semantic_hash: str


@dataclass(frozen=True, slots=True)
class CredentialFence:
    secret_id: str
    version: str
    generation: int
    rotation_epoch: int
    revocation_epoch: int
    consumer_id: str
    usage_scope: str


class DurableCredentialAuthority:
    """Single durable metadata authority for current credential generations.

    Secret bytes are deliberately absent. Mutations use BEGIN IMMEDIATE so
    competing writers cannot both win a preferred-generation cutover.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._install()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _install(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS mpr2618_secret_heads(
                    secret_id TEXT PRIMARY KEY,
                    preferred_version TEXT,
                    rotation_epoch INTEGER NOT NULL,
                    revocation_epoch INTEGER NOT NULL,
                    revision INTEGER NOT NULL,
                    updated_at_ns INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mpr2618_versions(
                    secret_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    backend_ref TEXT NOT NULL,
                    consumer_id TEXT NOT NULL,
                    usage_scope TEXT NOT NULL,
                    state TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    issued_at_ns INTEGER NOT NULL,
                    not_before_ns INTEGER NOT NULL,
                    expires_at_ns INTEGER NOT NULL,
                    supersedes_version TEXT,
                    validation_sha256 TEXT,
                    overlap_until_ns INTEGER,
                    PRIMARY KEY(secret_id, version),
                    FOREIGN KEY(secret_id) REFERENCES mpr2618_secret_heads(secret_id)
                );
                CREATE TABLE IF NOT EXISTS mpr2618_rotations(
                    rotation_id TEXT PRIMARY KEY,
                    semantic_hash TEXT NOT NULL,
                    receipt_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mpr2618_revocations(
                    incident_id TEXT PRIMARY KEY,
                    semantic_hash TEXT NOT NULL,
                    receipt_json TEXT NOT NULL
                );
                """
            )

    def register(self, version: CredentialVersion, *, now_ns: int) -> None:
        _nonnegative_int(now_ns, "now_ns")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO mpr2618_secret_heads(
                        secret_id, preferred_version, rotation_epoch,
                        revocation_epoch, revision, updated_at_ns
                    ) VALUES(?, NULL, 0, 0, 0, ?)
                    """,
                    (version.secret_id, now_ns),
                )
                existing = conn.execute(
                    "SELECT * FROM mpr2618_versions WHERE secret_id=? AND version=?",
                    (version.secret_id, version.version),
                ).fetchone()
                if existing is not None:
                    if _version_semantics(existing) == _version_semantics(version):
                        conn.execute("COMMIT")
                        return
                    raise CredentialRotationError("credential version semantic conflict")
                conn.execute(
                    """
                    INSERT INTO mpr2618_versions(
                        secret_id, version, backend_ref, consumer_id, usage_scope,
                        state, generation, issued_at_ns, not_before_ns, expires_at_ns,
                        supersedes_version, validation_sha256, overlap_until_ns
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                    """,
                    (
                        version.secret_id,
                        version.version,
                        version.backend_ref,
                        version.consumer_id,
                        version.usage_scope,
                        version.state.value,
                        version.generation,
                        version.issued_at_ns,
                        version.not_before_ns,
                        version.expires_at_ns,
                        version.supersedes_version,
                    ),
                )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def set_validated(
        self,
        *,
        secret_id: str,
        version: str,
        validation_sha256: str,
        now_ns: int,
    ) -> None:
        _sha256(validation_sha256, "validation_sha256")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._row(conn, secret_id, version)
            if CredentialState(row["state"]) not in {CredentialState.STAGED, CredentialState.VALIDATED}:
                conn.execute("ROLLBACK")
                raise CredentialRotationError("only staged credential can be validated")
            conn.execute(
                "UPDATE mpr2618_versions SET state=?, validation_sha256=? WHERE secret_id=? AND version=?",
                (CredentialState.VALIDATED.value, validation_sha256, secret_id, version),
            )
            conn.execute("UPDATE mpr2618_secret_heads SET updated_at_ns=? WHERE secret_id=?", (now_ns, secret_id))
            conn.execute("COMMIT")

    def activate_initial(self, *, secret_id: str, version: str, now_ns: int) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            head = self._head(conn, secret_id)
            if head["preferred_version"] is not None:
                conn.execute("ROLLBACK")
                raise CredentialRotationError("preferred credential already exists")
            row = self._row(conn, secret_id, version)
            self._assert_activatable(row, now_ns)
            conn.execute(
                "UPDATE mpr2618_versions SET state=? WHERE secret_id=? AND version=?",
                (CredentialState.ACTIVE.value, secret_id, version),
            )
            conn.execute(
                """
                UPDATE mpr2618_secret_heads
                SET preferred_version=?, rotation_epoch=1, revision=revision+1, updated_at_ns=?
                WHERE secret_id=?
                """,
                (version, now_ns, secret_id),
            )
            conn.execute("COMMIT")

    def rotate(self, plan: RotationPlan, *, now_ns: int) -> RotationReceipt:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                replay = conn.execute(
                    "SELECT semantic_hash, receipt_json FROM mpr2618_rotations WHERE rotation_id=?",
                    (plan.rotation_id,),
                ).fetchone()
                if replay is not None:
                    if replay["semantic_hash"] != plan.semantic_hash:
                        raise CredentialRotationError("rotation_id semantic conflict")
                    receipt = RotationReceipt(**json.loads(replay["receipt_json"]))
                    conn.execute("COMMIT")
                    return receipt
                head = self._head(conn, plan.secret_id)
                if head["preferred_version"] != plan.expected_current_version:
                    raise CredentialRotationError("stale expected current credential")
                old = self._row(conn, plan.secret_id, plan.expected_current_version)
                new = self._row(conn, plan.secret_id, plan.new_version)
                if new["supersedes_version"] != plan.expected_current_version:
                    raise CredentialRotationError("supersedes_version mismatch")
                self._assert_activatable(new, now_ns)
                if new["validation_sha256"] != plan.validation_sha256:
                    raise CredentialRotationError("validation evidence mismatch")
                overlap_until = plan.allowed_overlap_until_ns
                if overlap_until is not None and overlap_until <= now_ns:
                    raise CredentialRotationError("overlap window already expired")
                next_rotation = int(head["rotation_epoch"]) + 1
                conn.execute(
                    "UPDATE mpr2618_versions SET state=?, overlap_until_ns=? WHERE secret_id=? AND version=?",
                    (CredentialState.RETIRING.value, overlap_until, plan.secret_id, old["version"]),
                )
                conn.execute(
                    "UPDATE mpr2618_versions SET state=?, overlap_until_ns=NULL WHERE secret_id=? AND version=?",
                    (CredentialState.ACTIVE.value, plan.secret_id, new["version"]),
                )
                conn.execute(
                    """
                    UPDATE mpr2618_secret_heads
                    SET preferred_version=?, rotation_epoch=?, revision=revision+1, updated_at_ns=?
                    WHERE secret_id=?
                    """,
                    (new["version"], next_rotation, now_ns, plan.secret_id),
                )
                receipt = RotationReceipt(
                    rotation_id=plan.rotation_id,
                    secret_id=plan.secret_id,
                    old_version=old["version"],
                    new_version=new["version"],
                    rotation_epoch=next_rotation,
                    revocation_epoch=int(head["revocation_epoch"]),
                    semantic_hash=plan.semantic_hash,
                    committed_at_ns=now_ns,
                )
                conn.execute(
                    "INSERT INTO mpr2618_rotations(rotation_id, semantic_hash, receipt_json) VALUES(?, ?, ?)",
                    (plan.rotation_id, plan.semantic_hash, json.dumps(_dataclass_dict(receipt), sort_keys=True)),
                )
                conn.execute("COMMIT")
                return receipt
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def revoke(
        self,
        *,
        incident_id: str,
        secret_id: str,
        version: str,
        reason: RotationReason,
        now_ns: int,
    ) -> RevocationReceipt:
        _identifier(incident_id, "incident_id")
        semantic_hash = _hash_json(
            {
                "schema": MPR2618_SCHEMA,
                "incident_id": incident_id,
                "secret_id": secret_id,
                "version": version,
                "reason": reason.value,
            }
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                replay = conn.execute(
                    "SELECT semantic_hash, receipt_json FROM mpr2618_revocations WHERE incident_id=?",
                    (incident_id,),
                ).fetchone()
                if replay is not None:
                    if replay["semantic_hash"] != semantic_hash:
                        raise CredentialRotationError("incident_id semantic conflict")
                    receipt = RevocationReceipt(**json.loads(replay["receipt_json"]))
                    conn.execute("COMMIT")
                    return receipt
                head = self._head(conn, secret_id)
                row = self._row(conn, secret_id, version)
                state = CredentialState(row["state"])
                if state is CredentialState.DESTROYED:
                    raise CredentialRotationError("destroyed credential cannot be revoked")
                next_revocation = int(head["revocation_epoch"]) + 1
                conn.execute(
                    "UPDATE mpr2618_versions SET state=? WHERE secret_id=? AND version=?",
                    (CredentialState.REVOKED.value, secret_id, version),
                )
                preferred = None if head["preferred_version"] == version else head["preferred_version"]
                conn.execute(
                    """
                    UPDATE mpr2618_secret_heads
                    SET preferred_version=?, revocation_epoch=?, revision=revision+1, updated_at_ns=?
                    WHERE secret_id=?
                    """,
                    (preferred, next_revocation, now_ns, secret_id),
                )
                receipt = RevocationReceipt(
                    incident_id=incident_id,
                    secret_id=secret_id,
                    version=version,
                    reason=reason,
                    rotation_epoch=int(head["rotation_epoch"]),
                    revocation_epoch=next_revocation,
                    committed_at_ns=now_ns,
                    semantic_hash=semantic_hash,
                )
                payload = _dataclass_dict(receipt)
                payload["reason"] = reason.value
                conn.execute(
                    "INSERT INTO mpr2618_revocations(incident_id, semantic_hash, receipt_json) VALUES(?, ?, ?)",
                    (incident_id, semantic_hash, json.dumps(payload, sort_keys=True)),
                )
                conn.execute("COMMIT")
                return receipt
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def issue_fence(
        self,
        *,
        secret_id: str,
        version: str,
        consumer_id: str,
        usage_scope: str,
        now_ns: int,
    ) -> CredentialFence:
        with self._connect() as conn:
            head = self._head(conn, secret_id)
            row = self._row(conn, secret_id, version)
            self._assert_allowed_use(head, row, consumer_id, usage_scope, now_ns)
            return CredentialFence(
                secret_id=secret_id,
                version=version,
                generation=int(row["generation"]),
                rotation_epoch=int(head["rotation_epoch"]),
                revocation_epoch=int(head["revocation_epoch"]),
                consumer_id=consumer_id,
                usage_scope=usage_scope,
            )

    def assert_current_use(self, fence: CredentialFence, *, now_ns: int) -> None:
        with self._connect() as conn:
            head = self._head(conn, fence.secret_id)
            row = self._row(conn, fence.secret_id, fence.version)
            if int(head["revocation_epoch"]) != fence.revocation_epoch:
                raise CredentialRotationError("REVOKED_CURRENT_GENERATION")
            if int(row["generation"]) != fence.generation:
                raise CredentialRotationError("STALE_CREDENTIAL_GENERATION")
            self._assert_allowed_use(head, row, fence.consumer_id, fence.usage_scope, now_ns)

    def snapshot(self, secret_id: str) -> dict[str, object]:
        with self._connect() as conn:
            head = dict(self._head(conn, secret_id))
            versions = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM mpr2618_versions WHERE secret_id=? ORDER BY generation, version",
                    (secret_id,),
                ).fetchall()
            ]
            return {"head": head, "versions": versions}

    def _assert_allowed_use(
        self,
        head: sqlite3.Row,
        row: sqlite3.Row,
        consumer_id: str,
        usage_scope: str,
        now_ns: int,
    ) -> None:
        state = CredentialState(row["state"])
        if row["consumer_id"] != consumer_id or row["usage_scope"] != usage_scope:
            raise CredentialRotationError("credential consumer/scope mismatch")
        if not int(row["not_before_ns"]) <= now_ns < int(row["expires_at_ns"]):
            raise CredentialRotationError("credential outside validity window")
        preferred = head["preferred_version"]
        if state is CredentialState.ACTIVE and preferred == row["version"]:
            return
        if state is CredentialState.RETIRING:
            overlap = row["overlap_until_ns"]
            if overlap is not None and now_ns < int(overlap):
                return
        raise CredentialRotationError("credential generation is not currently usable")

    @staticmethod
    def _assert_activatable(row: sqlite3.Row, now_ns: int) -> None:
        if CredentialState(row["state"]) is not CredentialState.VALIDATED:
            raise CredentialRotationError("credential is not validated")
        if row["validation_sha256"] is None:
            raise CredentialRotationError("credential validation evidence is missing")
        if not int(row["not_before_ns"]) <= now_ns < int(row["expires_at_ns"]):
            raise CredentialRotationError("credential outside activation window")

    @staticmethod
    def _head(conn: sqlite3.Connection, secret_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM mpr2618_secret_heads WHERE secret_id=?", (secret_id,)).fetchone()
        if row is None:
            raise CredentialRotationError("unknown secret_id")
        return row

    @staticmethod
    def _row(conn: sqlite3.Connection, secret_id: str, version: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM mpr2618_versions WHERE secret_id=? AND version=?", (secret_id, version)
        ).fetchone()
        if row is None:
            raise CredentialRotationError("unknown credential version")
        return row


class FencedSecretHandle:
    """Supported MPR-2618 handle: every reveal rechecks durable revocation state."""

    def __init__(
        self,
        handle: SecretHandle,
        *,
        authority: DurableCredentialAuthority,
        fence: CredentialFence,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self._handle = handle
        self._authority = authority
        self._fence = fence
        self._clock_ns = clock_ns

    def reveal(self) -> str:
        self._authority.assert_current_use(self._fence, now_ns=self._clock_ns())
        return self._handle.reveal()

    def revoke(self) -> None:
        self._handle.revoke()

    close = revoke

    def __repr__(self) -> str:
        return "FencedSecretHandle(value='<redacted>')"

    def __str__(self) -> str:
        return "<redacted secret>"


@dataclass(frozen=True, slots=True)
class TrustGenerationFence:
    generation: str
    revocation_epoch: int


class DurableTrustGenerationAuthority:
    """Durable current trust-registry generation pointer and revocation epoch."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mpr2618_trust_head(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    generation TEXT NOT NULL,
                    revocation_epoch INTEGER NOT NULL,
                    revision INTEGER NOT NULL,
                    updated_at_ns INTEGER NOT NULL
                )
                """
            )

    def publish(self, *, generation: str, revocation_epoch: int, now_ns: int) -> None:
        _identifier(generation, "generation")
        _nonnegative_int(revocation_epoch, "revocation_epoch")
        with sqlite3.connect(self.path, isolation_level=None, timeout=5) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM mpr2618_trust_head WHERE singleton=1").fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO mpr2618_trust_head VALUES(1, ?, ?, 1, ?)",
                    (generation, revocation_epoch, now_ns),
                )
            else:
                current_generation, current_epoch = str(row[1]), int(row[2])
                if revocation_epoch < current_epoch:
                    conn.execute("ROLLBACK")
                    raise CredentialRotationError("trust revocation epoch regression")
                if generation == current_generation and revocation_epoch == current_epoch:
                    conn.execute("COMMIT")
                    return
                conn.execute(
                    "UPDATE mpr2618_trust_head SET generation=?, revocation_epoch=?, revision=revision+1, updated_at_ns=? WHERE singleton=1",
                    (generation, revocation_epoch, now_ns),
                )
            conn.execute("COMMIT")

    def current_fence(self) -> TrustGenerationFence:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT generation, revocation_epoch FROM mpr2618_trust_head WHERE singleton=1").fetchone()
            if row is None:
                raise CredentialRotationError("trust generation not published")
            return TrustGenerationFence(str(row[0]), int(row[1]))

    def verify_current(
        self,
        *,
        registry: TrustAnchorRegistry,
        envelope: SignedEnvelope,
        payload: bytes,
        usage: TrustUsage,
        evaluated_at,
        expected_domain: str,
        expected_environment: str,
    ) -> TrustVerificationResult:
        current = self.current_fence()
        if registry.generation != current.generation:
            raise CredentialRotationError("STALE_TRUST_REGISTRY_GENERATION")
        return registry.verify(
            envelope,
            payload,
            usage=usage,
            evaluated_at=evaluated_at,
            expected_domain=expected_domain,
            expected_environment=expected_environment,
        )


def _identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"{label} must be a bounded identifier")


def _sha256(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{label} must be lowercase SHA-256")


def _positive_int(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")


def _nonnegative_int(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")


def _hash_json(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _dataclass_dict(value: object) -> dict[str, object]:
    return {name: getattr(value, name) for name in value.__dataclass_fields__}


def _version_semantics(value: sqlite3.Row | CredentialVersion) -> tuple[object, ...]:
    names = (
        "secret_id",
        "version",
        "backend_ref",
        "consumer_id",
        "usage_scope",
        "state",
        "generation",
        "issued_at_ns",
        "not_before_ns",
        "expires_at_ns",
        "supersedes_version",
    )
    if isinstance(value, CredentialVersion):
        return tuple(getattr(value, name).value if name == "state" else getattr(value, name) for name in names)
    return tuple(value[name] for name in names)


__all__ = [
    "CredentialFence",
    "CredentialRotationError",
    "CredentialVersion",
    "DurableCredentialAuthority",
    "DurableTrustGenerationAuthority",
    "FencedSecretHandle",
    "MPR2618_DEFAULT_ENABLED",
    "MPR2618_SCHEMA",
    "RevocationReceipt",
    "RotationPlan",
    "RotationReason",
    "RotationReceipt",
    "TrustGenerationFence",
]

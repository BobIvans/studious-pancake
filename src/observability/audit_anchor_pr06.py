"""Roadmap PR-06 signed audit checkpoints and create-only anchor receipts.

The authoritative checkpoint is built from a consistent SQLite backup and the
PR-184 aggregate hash chains. Raw database/WAL/SHM files are retained as
forensic companions, but they are never treated as the transactional snapshot.
A separate create-only anchor directory provides an adapter for immutable or
WORM-mounted storage without adding network access to the runtime process.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
from typing import Any, Mapping, Sequence

from src.observability.integrity import (
    ZERO_CHAIN_DIGEST,
    canonical_json,
    verify_chain_row,
)
from src.security.secure_files import (
    SecureFileError,
    copy_secure_regular_file,
    inspect_secure_regular_file,
    read_secure_regular_file,
)

PR06_CHECKPOINT_SCHEMA = "pr06.signed-audit-checkpoint.v1"
PR06_ANCHOR_SCHEMA = "pr06.external-anchor-receipt.v1"
PR06_VERIFICATION_SCHEMA = "pr06.audit-anchor-verification.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_MAX_KEY_BYTES = 4096
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_FORENSIC_BYTES = 4 * 1024 * 1024 * 1024


class AuditAnchorError(RuntimeError):
    """Fail-closed checkpoint, forensic capture, or anchor error."""


@dataclass(frozen=True, slots=True)
class ForensicArtifact:
    path: str
    role: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class AggregateHead:
    aggregate_id: str
    event_count: int
    final_sequence_no: int
    chain_digest: str


@dataclass(frozen=True, slots=True)
class SignedAuditCheckpoint:
    schema_version: str
    release_id: str
    source_commit: str
    environment: str
    policy_bundle_hash: str
    database_epoch: str
    created_at_unix_ns: int
    event_count: int
    aggregate_heads: tuple[AggregateHead, ...]
    artifacts: tuple[ForensicArtifact, ...]
    checkpoint_digest: str
    signer_pubkey: str
    signature: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "release_id": self.release_id,
            "source_commit": self.source_commit,
            "environment": self.environment,
            "policy_bundle_hash": self.policy_bundle_hash,
            "database_epoch": self.database_epoch,
            "created_at_unix_ns": self.created_at_unix_ns,
            "event_count": self.event_count,
            "aggregate_heads": [asdict(item) for item in self.aggregate_heads],
            "artifacts": [asdict(item) for item in self.artifacts],
            "checkpoint_digest": self.checkpoint_digest,
            "signer_pubkey": self.signer_pubkey,
            "signature": self.signature,
        }


@dataclass(frozen=True, slots=True)
class ExternalAnchorReceipt:
    schema_version: str
    anchor_id: str
    environment: str
    release_id: str
    policy_bundle_hash: str
    checkpoint_digest: str
    checkpoint_manifest_sha256: str
    anchored_at_unix_ns: int
    signer_pubkey: str
    signature: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AuditAnchorVerification:
    accepted: bool
    blockers: tuple[str, ...]
    checkpoint_digest: str | None
    checkpoint_manifest_sha256: str | None
    anchor_receipt_sha256: str | None
    event_count: int
    schema_version: str = PR06_VERIFICATION_SCHEMA

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _canonical_bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8")


def _require_sha256(value: str, name: str) -> str:
    if not _SHA256_RE.fullmatch(value):
        raise AuditAnchorError(f"{name} must be lowercase sha256")
    return value


def _require_text(value: str, name: str) -> str:
    if not value.strip() or value.lower() in {"unknown", "placeholder"}:
        raise AuditAnchorError(f"{name} must be a stable non-placeholder value")
    return value


def _secure_read(
    path: Path,
    *,
    max_bytes: int,
    require_owner_only: bool = False,
) -> bytes:
    try:
        return read_secure_regular_file(
            path, max_bytes=max_bytes, owner_only=require_owner_only
        ).data
    except SecureFileError as exc:
        raise AuditAnchorError(f"unsafe or unreadable file: {path.name}") from exc


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_atomic(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        _fsync_directory(path.parent)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _write_create_only(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        existing = _secure_read(path, max_bytes=_MAX_MANIFEST_BYTES)
        if existing != raw:
            raise AuditAnchorError("existing anchor receipt has different content")
        return
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(path.parent)
    except Exception:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def _load_keypair(path: Path) -> Any:
    raw = _secure_read(path, max_bytes=_MAX_KEY_BYTES, require_owner_only=True)
    try:
        values = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditAnchorError("attestation key is not valid JSON") from exc
    if not isinstance(values, list) or len(values) != 64:
        raise AuditAnchorError("attestation key must contain 64 bytes")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255
        for value in values
    ):
        raise AuditAnchorError("attestation key contains invalid bytes")
    from solders.keypair import Keypair

    return Keypair.from_bytes(bytes(values))


def _verify_signature(public_key: str, signature: str, message: bytes) -> bool:
    try:
        from solders.pubkey import Pubkey
        from solders.signature import Signature

        return bool(
            Signature.from_string(signature).verify(
                Pubkey.from_string(public_key), message
            )
        )
    except (ImportError, ValueError):
        return False


def _checkpoint_unsigned(
    *,
    release_id: str,
    source_commit: str,
    environment: str,
    policy_bundle_hash: str,
    database_epoch: str,
    created_at_unix_ns: int,
    event_count: int,
    aggregate_heads: tuple[AggregateHead, ...],
    artifacts: tuple[ForensicArtifact, ...],
    signer_pubkey: str,
) -> dict[str, object]:
    return {
        "domain": "studious-pancake.audit-checkpoint",
        "schema_version": PR06_CHECKPOINT_SCHEMA,
        "release_id": release_id,
        "source_commit": source_commit,
        "environment": environment,
        "policy_bundle_hash": policy_bundle_hash,
        "database_epoch": database_epoch,
        "created_at_unix_ns": created_at_unix_ns,
        "event_count": event_count,
        "aggregate_heads": [asdict(item) for item in aggregate_heads],
        "artifacts": [asdict(item) for item in artifacts],
        "signer_pubkey": signer_pubkey,
    }


def _anchor_unsigned(
    *,
    anchor_id: str,
    environment: str,
    release_id: str,
    policy_bundle_hash: str,
    checkpoint_digest: str,
    checkpoint_manifest_sha256: str,
    anchored_at_unix_ns: int,
    signer_pubkey: str,
) -> dict[str, object]:
    return {
        "domain": "studious-pancake.external-audit-anchor",
        "schema_version": PR06_ANCHOR_SCHEMA,
        "anchor_id": anchor_id,
        "environment": environment,
        "release_id": release_id,
        "policy_bundle_hash": policy_bundle_hash,
        "checkpoint_digest": checkpoint_digest,
        "checkpoint_manifest_sha256": checkpoint_manifest_sha256,
        "anchored_at_unix_ns": anchored_at_unix_ns,
        "signer_pubkey": signer_pubkey,
    }


def _copy_artifact(source: Path, target: Path, role: str) -> ForensicArtifact:
    try:
        copied = copy_secure_regular_file(
            source,
            target,
            max_bytes=_MAX_FORENSIC_BYTES,
            source_owner_only=False,
        )
    except SecureFileError as exc:
        raise AuditAnchorError(f"unsafe forensic source: {source.name}") from exc
    return ForensicArtifact(
        path=target.name,
        role=role,
        sha256=copied.sha256,
        size_bytes=copied.size_bytes,
    )


def _consistent_backup(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".sqlite", dir=str(target.parent)
    )
    os.close(descriptor)
    try:
        source_uri = source.resolve().as_uri() + "?mode=ro"
        source_db = sqlite3.connect(source_uri, uri=True)
        destination_db = sqlite3.connect(temporary)
        try:
            source_db.backup(destination_db)
            destination_db.execute("PRAGMA quick_check")
            destination_db.commit()
        finally:
            destination_db.close()
            source_db.close()
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _verify_snapshot_chain(
    snapshot_path: Path,
) -> tuple[str, int, tuple[AggregateHead, ...]]:
    snapshot_uri = snapshot_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(snapshot_uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        quick = connection.execute("PRAGMA quick_check").fetchone()
        if quick is None or str(quick[0]).lower() != "ok":
            raise AuditAnchorError("SQLite backup failed quick_check")
        epoch = connection.execute(
            "SELECT value FROM audit_meta WHERE key='database_epoch'"
        ).fetchone()
        if epoch is None or not str(epoch[0]).strip():
            raise AuditAnchorError("audit database epoch is missing")
        rows = connection.execute(
            "SELECT * FROM event_log ORDER BY aggregate_id,sequence_no,event_id"
        ).fetchall()
    except sqlite3.Error as exc:
        raise AuditAnchorError("audit snapshot schema is unavailable") from exc
    finally:
        connection.close()

    heads: list[AggregateHead] = []
    current_aggregate: str | None = None
    expected_previous = ZERO_CHAIN_DIGEST
    count = 0
    final_sequence = -1
    final_digest = ZERO_CHAIN_DIGEST
    for row in rows:
        aggregate_id = str(row["aggregate_id"])
        if aggregate_id != current_aggregate:
            if current_aggregate is not None:
                heads.append(
                    AggregateHead(
                        current_aggregate,
                        count,
                        final_sequence,
                        final_digest,
                    )
                )
            current_aggregate = aggregate_id
            expected_previous = ZERO_CHAIN_DIGEST
            count = 0
        divergences = verify_chain_row(
            row, expected_previous_digest=expected_previous
        )
        if divergences:
            codes = ",".join(str(item["code"]) for item in divergences)
            raise AuditAnchorError(f"audit chain verification failed: {codes}")
        expected_previous = str(row["chain_digest"])
        final_digest = expected_previous
        final_sequence = int(row["sequence_no"])
        count += 1
    if current_aggregate is not None:
        heads.append(
            AggregateHead(current_aggregate, count, final_sequence, final_digest)
        )
    return str(epoch[0]), len(rows), tuple(heads)


def capture_signed_checkpoint(
    *,
    database_path: str | os.PathLike[str],
    output_directory: str | os.PathLike[str],
    release_id: str,
    source_commit: str,
    environment: str,
    policy_bundle_hash: str,
    keypair_path: str | os.PathLike[str],
    created_at_unix_ns: int | None = None,
) -> SignedAuditCheckpoint:
    source = Path(database_path)
    output = Path(output_directory)
    _require_text(release_id, "release_id")
    _require_text(environment, "environment")
    if not _COMMIT_RE.fullmatch(source_commit):
        raise AuditAnchorError("source_commit must be a full lowercase git SHA")
    _require_sha256(policy_bundle_hash, "policy_bundle_hash")
    try:
        source_identity = inspect_secure_regular_file(
            source, max_bytes=_MAX_FORENSIC_BYTES
        )
    except SecureFileError as exc:
        raise AuditAnchorError("audit database path is unsafe") from exc
    output.mkdir(parents=True, mode=0o700, exist_ok=True)

    snapshot = output / "observability-consistent.sqlite"
    _consistent_backup(source, snapshot)
    try:
        after_backup = inspect_secure_regular_file(
            source, max_bytes=_MAX_FORENSIC_BYTES
        )
    except SecureFileError as exc:
        raise AuditAnchorError("audit database changed identity") from exc
    if (
        source_identity.device,
        source_identity.inode,
    ) != (after_backup.device, after_backup.inode):
        raise AuditAnchorError("audit database changed identity during backup")
    database_epoch, event_count, aggregate_heads = _verify_snapshot_chain(snapshot)

    artifacts: list[ForensicArtifact] = [
        _copy_artifact(snapshot, output / "observability-snapshot.sqlite", "snapshot")
    ]
    for suffix, role in (("", "raw-db"), ("-wal", "raw-wal"), ("-shm", "raw-shm")):
        candidate = Path(str(source) + suffix)
        if candidate.exists():
            artifacts.append(
                _copy_artifact(candidate, output / f"source{suffix or '-db'}", role)
            )
    snapshot.unlink(missing_ok=True)

    keypair = _load_keypair(Path(keypair_path))
    signer_pubkey = str(keypair.pubkey())
    created_at = created_at_unix_ns or time.time_ns()
    unsigned = _checkpoint_unsigned(
        release_id=release_id,
        source_commit=source_commit,
        environment=environment,
        policy_bundle_hash=policy_bundle_hash,
        database_epoch=database_epoch,
        created_at_unix_ns=created_at,
        event_count=event_count,
        aggregate_heads=aggregate_heads,
        artifacts=tuple(artifacts),
        signer_pubkey=signer_pubkey,
    )
    checkpoint_digest = hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()
    signature = str(keypair.sign_message(_canonical_bytes(unsigned)))
    checkpoint = SignedAuditCheckpoint(
        schema_version=PR06_CHECKPOINT_SCHEMA,
        release_id=release_id,
        source_commit=source_commit,
        environment=environment,
        policy_bundle_hash=policy_bundle_hash,
        database_epoch=database_epoch,
        created_at_unix_ns=created_at,
        event_count=event_count,
        aggregate_heads=aggregate_heads,
        artifacts=tuple(artifacts),
        checkpoint_digest=checkpoint_digest,
        signer_pubkey=signer_pubkey,
        signature=signature,
    )
    _write_atomic(
        output / "audit-checkpoint.json",
        _canonical_bytes(checkpoint.to_dict()),
    )
    return checkpoint


def _parse_checkpoint(raw: bytes) -> SignedAuditCheckpoint:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditAnchorError("checkpoint manifest is invalid JSON") from exc
    if not isinstance(value, dict):
        raise AuditAnchorError("checkpoint manifest must be an object")
    try:
        return SignedAuditCheckpoint(
            schema_version=str(value["schema_version"]),
            release_id=str(value["release_id"]),
            source_commit=str(value["source_commit"]),
            environment=str(value["environment"]),
            policy_bundle_hash=str(value["policy_bundle_hash"]),
            database_epoch=str(value["database_epoch"]),
            created_at_unix_ns=int(value["created_at_unix_ns"]),
            event_count=int(value["event_count"]),
            aggregate_heads=tuple(
                AggregateHead(**item) for item in value["aggregate_heads"]
            ),
            artifacts=tuple(ForensicArtifact(**item) for item in value["artifacts"]),
            checkpoint_digest=str(value["checkpoint_digest"]),
            signer_pubkey=str(value["signer_pubkey"]),
            signature=str(value["signature"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuditAnchorError("checkpoint manifest fields are invalid") from exc


def _parse_receipt(raw: bytes) -> ExternalAnchorReceipt:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditAnchorError("anchor receipt is invalid JSON") from exc
    if not isinstance(value, dict):
        raise AuditAnchorError("anchor receipt must be an object")
    try:
        return ExternalAnchorReceipt(
            schema_version=str(value["schema_version"]),
            anchor_id=str(value["anchor_id"]),
            environment=str(value["environment"]),
            release_id=str(value["release_id"]),
            policy_bundle_hash=str(value["policy_bundle_hash"]),
            checkpoint_digest=str(value["checkpoint_digest"]),
            checkpoint_manifest_sha256=str(value["checkpoint_manifest_sha256"]),
            anchored_at_unix_ns=int(value["anchored_at_unix_ns"]),
            signer_pubkey=str(value["signer_pubkey"]),
            signature=str(value["signature"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuditAnchorError("anchor receipt fields are invalid") from exc


def create_external_anchor(
    *,
    checkpoint_path: str | os.PathLike[str],
    anchor_directory: str | os.PathLike[str],
    anchor_id: str,
    keypair_path: str | os.PathLike[str],
    anchored_at_unix_ns: int | None = None,
) -> tuple[ExternalAnchorReceipt, Path]:
    _require_text(anchor_id, "anchor_id")
    checkpoint_raw = _secure_read(
        Path(checkpoint_path), max_bytes=_MAX_MANIFEST_BYTES, require_owner_only=True
    )
    checkpoint = _parse_checkpoint(checkpoint_raw)
    blockers = _checkpoint_blockers(checkpoint, Path(checkpoint_path).parent)
    if blockers:
        raise AuditAnchorError("checkpoint is not anchorable: " + ",".join(blockers))
    manifest_hash = hashlib.sha256(checkpoint_raw).hexdigest()
    keypair = _load_keypair(Path(keypair_path))
    signer_pubkey = str(keypair.pubkey())
    anchored_at = anchored_at_unix_ns or time.time_ns()
    unsigned = _anchor_unsigned(
        anchor_id=anchor_id,
        environment=checkpoint.environment,
        release_id=checkpoint.release_id,
        policy_bundle_hash=checkpoint.policy_bundle_hash,
        checkpoint_digest=checkpoint.checkpoint_digest,
        checkpoint_manifest_sha256=manifest_hash,
        anchored_at_unix_ns=anchored_at,
        signer_pubkey=signer_pubkey,
    )
    receipt = ExternalAnchorReceipt(
        schema_version=PR06_ANCHOR_SCHEMA,
        anchor_id=anchor_id,
        environment=checkpoint.environment,
        release_id=checkpoint.release_id,
        policy_bundle_hash=checkpoint.policy_bundle_hash,
        checkpoint_digest=checkpoint.checkpoint_digest,
        checkpoint_manifest_sha256=manifest_hash,
        anchored_at_unix_ns=anchored_at,
        signer_pubkey=signer_pubkey,
        signature=str(keypair.sign_message(_canonical_bytes(unsigned))),
    )
    target = Path(anchor_directory) / f"{checkpoint.checkpoint_digest}.anchor.json"
    _write_create_only(target, _canonical_bytes(receipt.to_dict()))
    return receipt, target



def _artifact_path(bundle_directory: Path, relative: str) -> Path:
    candidate = Path(relative)
    if (
        not relative
        or candidate.is_absolute()
        or len(candidate.parts) != 1
        or candidate.name != relative
    ):
        raise AuditAnchorError("artifact path is not a bundle basename")
    return bundle_directory / candidate

def _checkpoint_blockers(
    checkpoint: SignedAuditCheckpoint,
    bundle_directory: Path,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if checkpoint.schema_version != PR06_CHECKPOINT_SCHEMA:
        blockers.append("CHECKPOINT_SCHEMA_INVALID")
    try:
        _require_sha256(checkpoint.policy_bundle_hash, "policy_bundle_hash")
        _require_sha256(checkpoint.checkpoint_digest, "checkpoint_digest")
    except AuditAnchorError:
        blockers.append("CHECKPOINT_IDENTITY_INVALID")
    unsigned = _checkpoint_unsigned(
        release_id=checkpoint.release_id,
        source_commit=checkpoint.source_commit,
        environment=checkpoint.environment,
        policy_bundle_hash=checkpoint.policy_bundle_hash,
        database_epoch=checkpoint.database_epoch,
        created_at_unix_ns=checkpoint.created_at_unix_ns,
        event_count=checkpoint.event_count,
        aggregate_heads=checkpoint.aggregate_heads,
        artifacts=checkpoint.artifacts,
        signer_pubkey=checkpoint.signer_pubkey,
    )
    observed_digest = hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()
    if observed_digest != checkpoint.checkpoint_digest:
        blockers.append("CHECKPOINT_DIGEST_MISMATCH")
    if not _verify_signature(
        checkpoint.signer_pubkey, checkpoint.signature, _canonical_bytes(unsigned)
    ):
        blockers.append("CHECKPOINT_SIGNATURE_INVALID")
    for artifact in checkpoint.artifacts:
        try:
            raw = _secure_read(
                _artifact_path(bundle_directory, artifact.path),
                max_bytes=max(artifact.size_bytes + 1, 1),
                require_owner_only=True,
            )
        except AuditAnchorError:
            blockers.append(f"ARTIFACT_UNREADABLE:{artifact.role}")
            continue
        if len(raw) != artifact.size_bytes:
            blockers.append(f"ARTIFACT_SIZE_MISMATCH:{artifact.role}")
        if hashlib.sha256(raw).hexdigest() != artifact.sha256:
            blockers.append(f"ARTIFACT_HASH_MISMATCH:{artifact.role}")
    snapshot = next(
        (item for item in checkpoint.artifacts if item.role == "snapshot"), None
    )
    if snapshot is None:
        blockers.append("CONSISTENT_SNAPSHOT_MISSING")
    else:
        try:
            epoch, count, heads = _verify_snapshot_chain(
                _artifact_path(bundle_directory, snapshot.path)
            )
        except AuditAnchorError:
            blockers.append("CONSISTENT_SNAPSHOT_CHAIN_INVALID")
        else:
            if epoch != checkpoint.database_epoch:
                blockers.append("DATABASE_EPOCH_MISMATCH")
            if count != checkpoint.event_count:
                blockers.append("EVENT_COUNT_MISMATCH")
            if heads != checkpoint.aggregate_heads:
                blockers.append("AGGREGATE_HEADS_MISMATCH")
    return tuple(dict.fromkeys(blockers))


def verify_checkpoint_and_anchor(
    *,
    checkpoint_path: str | os.PathLike[str],
    anchor_receipt_path: str | os.PathLike[str],
    expected_checkpoint_pubkey: str,
    expected_anchor_pubkey: str,
    expected_policy_bundle_hash: str,
    expected_environment: str,
) -> AuditAnchorVerification:
    blockers: list[str] = []
    checkpoint_raw: bytes | None = None
    receipt_raw: bytes | None = None
    checkpoint: SignedAuditCheckpoint | None = None
    receipt: ExternalAnchorReceipt | None = None
    try:
        checkpoint_raw = _secure_read(
            Path(checkpoint_path),
            max_bytes=_MAX_MANIFEST_BYTES,
            require_owner_only=True,
        )
        checkpoint = _parse_checkpoint(checkpoint_raw)
    except AuditAnchorError:
        blockers.append("CHECKPOINT_MANIFEST_INVALID")
    if checkpoint is not None:
        blockers.extend(_checkpoint_blockers(checkpoint, Path(checkpoint_path).parent))
        if checkpoint.signer_pubkey != expected_checkpoint_pubkey:
            blockers.append("CHECKPOINT_SIGNER_MISMATCH")
        if checkpoint.policy_bundle_hash != expected_policy_bundle_hash:
            blockers.append("CHECKPOINT_POLICY_MISMATCH")
        if checkpoint.environment != expected_environment:
            blockers.append("CHECKPOINT_ENVIRONMENT_MISMATCH")
    try:
        receipt_raw = _secure_read(
            Path(anchor_receipt_path),
            max_bytes=_MAX_MANIFEST_BYTES,
            require_owner_only=True,
        )
        receipt = _parse_receipt(receipt_raw)
    except AuditAnchorError:
        blockers.append("ANCHOR_RECEIPT_INVALID")
    if receipt is not None:
        if receipt.schema_version != PR06_ANCHOR_SCHEMA:
            blockers.append("ANCHOR_SCHEMA_INVALID")
        if receipt.signer_pubkey != expected_anchor_pubkey:
            blockers.append("ANCHOR_SIGNER_MISMATCH")
        unsigned = _anchor_unsigned(
            anchor_id=receipt.anchor_id,
            environment=receipt.environment,
            release_id=receipt.release_id,
            policy_bundle_hash=receipt.policy_bundle_hash,
            checkpoint_digest=receipt.checkpoint_digest,
            checkpoint_manifest_sha256=receipt.checkpoint_manifest_sha256,
            anchored_at_unix_ns=receipt.anchored_at_unix_ns,
            signer_pubkey=receipt.signer_pubkey,
        )
        if not _verify_signature(
            receipt.signer_pubkey, receipt.signature, _canonical_bytes(unsigned)
        ):
            blockers.append("ANCHOR_SIGNATURE_INVALID")
        if checkpoint is not None and checkpoint_raw is not None:
            if receipt.checkpoint_digest != checkpoint.checkpoint_digest:
                blockers.append("ANCHOR_CHECKPOINT_DIGEST_MISMATCH")
            manifest_hash = hashlib.sha256(checkpoint_raw).hexdigest()
            if receipt.checkpoint_manifest_sha256 != manifest_hash:
                blockers.append("ANCHOR_MANIFEST_HASH_MISMATCH")
            if receipt.release_id != checkpoint.release_id:
                blockers.append("ANCHOR_RELEASE_MISMATCH")
            if receipt.policy_bundle_hash != checkpoint.policy_bundle_hash:
                blockers.append("ANCHOR_POLICY_MISMATCH")
            if receipt.environment != checkpoint.environment:
                blockers.append("ANCHOR_ENVIRONMENT_MISMATCH")
    unique = tuple(dict.fromkeys(blockers))
    return AuditAnchorVerification(
        accepted=not unique,
        blockers=unique,
        checkpoint_digest=(checkpoint.checkpoint_digest if checkpoint else None),
        checkpoint_manifest_sha256=(
            hashlib.sha256(checkpoint_raw).hexdigest() if checkpoint_raw else None
        ),
        anchor_receipt_sha256=(
            hashlib.sha256(receipt_raw).hexdigest() if receipt_raw else None
        ),
        event_count=checkpoint.event_count if checkpoint else 0,
    )


def _print_json(value: Mapping[str, object]) -> None:
    print(json.dumps(dict(value), sort_keys=True, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flashloan-audit-anchor")
    commands = parser.add_subparsers(dest="command", required=True)

    capture = commands.add_parser("capture")
    capture.add_argument("--database", required=True)
    capture.add_argument("--output-directory", required=True)
    capture.add_argument("--release-id", required=True)
    capture.add_argument("--source-commit", required=True)
    capture.add_argument("--environment", required=True)
    capture.add_argument("--policy-bundle-hash", required=True)
    capture.add_argument("--keypair", required=True)

    anchor = commands.add_parser("anchor")
    anchor.add_argument("--checkpoint", required=True)
    anchor.add_argument("--anchor-directory", required=True)
    anchor.add_argument("--anchor-id", required=True)
    anchor.add_argument("--keypair", required=True)

    verify = commands.add_parser("verify")
    verify.add_argument("--checkpoint", required=True)
    verify.add_argument("--anchor-receipt", required=True)
    verify.add_argument("--checkpoint-pubkey", required=True)
    verify.add_argument("--anchor-pubkey", required=True)
    verify.add_argument("--policy-bundle-hash", required=True)
    verify.add_argument("--environment", required=True)

    args = parser.parse_args(argv)
    if args.command == "capture":
        checkpoint = capture_signed_checkpoint(
            database_path=args.database,
            output_directory=args.output_directory,
            release_id=args.release_id,
            source_commit=args.source_commit,
            environment=args.environment,
            policy_bundle_hash=args.policy_bundle_hash,
            keypair_path=args.keypair,
        )
        _print_json(checkpoint.to_dict())
        return 0
    if args.command == "anchor":
        receipt, path = create_external_anchor(
            checkpoint_path=args.checkpoint,
            anchor_directory=args.anchor_directory,
            anchor_id=args.anchor_id,
            keypair_path=args.keypair,
        )
        _print_json({**receipt.to_dict(), "receipt_path": str(path)})
        return 0
    result = verify_checkpoint_and_anchor(
        checkpoint_path=args.checkpoint,
        anchor_receipt_path=args.anchor_receipt,
        expected_checkpoint_pubkey=args.checkpoint_pubkey,
        expected_anchor_pubkey=args.anchor_pubkey,
        expected_policy_bundle_hash=args.policy_bundle_hash,
        expected_environment=args.environment,
    )
    _print_json(result.to_dict())
    return 0 if result.accepted else 2


__all__ = [
    "AggregateHead",
    "AuditAnchorError",
    "AuditAnchorVerification",
    "ExternalAnchorReceipt",
    "ForensicArtifact",
    "PR06_ANCHOR_SCHEMA",
    "PR06_CHECKPOINT_SCHEMA",
    "PR06_VERIFICATION_SCHEMA",
    "SignedAuditCheckpoint",
    "capture_signed_checkpoint",
    "create_external_anchor",
    "main",
    "verify_checkpoint_and_anchor",
]


if __name__ == "__main__":
    raise SystemExit(main())

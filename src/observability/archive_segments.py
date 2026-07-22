from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
from collections.abc import Mapping
from typing import Any
import uuid

from .archive import ArchiveCoordinator, ArchiveError, ExportClaim
from .archive_types import PR198_EXPORT_TOOL_VERSION

SEGMENT_NAME = re.compile(
    r"^segment=(?P<first>[0-9]+)-(?P<last>[0-9]+)-"
    r"(?P<checksum>[0-9a-f]{64})\.jsonl$"
)
TEMP_NAME = re.compile(r"^\.segment-(?P<claim>[0-9a-f]{32})-[0-9a-f]{32}\.tmp$")


def recover_orphan_segments(
    coordinator: ArchiveCoordinator,
    out: Path,
    *,
    exporter_id: str,
    lease_seconds: float,
    remote_required: bool,
) -> list[dict[str, object]]:
    recovered: list[dict[str, object]] = []
    for path in sorted(out.glob("date_utc=*/event_type=*/segment=*.jsonl")):
        if coordinator.manifest_for_path(str(path)) is not None:
            continue
        match = SEGMENT_NAME.fullmatch(path.name)
        if match is None:
            raise ArchiveError("ARCHIVE_SEGMENT_FILENAME_INVALID")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != match.group("checksum"):
            raise ArchiveError("ARCHIVE_ORPHAN_CHECKSUM_MISMATCH")
        event_ids = event_ids_from_jsonl(data)
        if not event_ids:
            raise ArchiveError("ARCHIVE_ORPHAN_EMPTY")
        try:
            claim = coordinator.claim_specific_events(
                exporter_id=f"{exporter_id}-recovery",
                event_ids=event_ids,
                lease_seconds=lease_seconds,
            )
        except ArchiveError as exc:
            if str(exc) == "ARCHIVE_RECOVERY_ROWS_NOT_CLAIMABLE":
                continue
            raise
        rows = coordinator.rows_for_claim(claim)
        manifest = build_manifest(
            out,
            path=path,
            data=data,
            claim=claim,
            rows=rows,
            remote_required=remote_required,
        )
        if segment_path(out, manifest) != path:
            raise ArchiveError("ARCHIVE_ORPHAN_PATH_IDENTITY_MISMATCH")
        coordinator.commit_segment(claim=claim, manifest=manifest, rows=rows)
        recovered.append(manifest)
    return recovered


def write_immutable_segment(
    out: Path,
    *,
    claim: ExportClaim,
    rows: list[Any],
    remote_required: bool,
) -> dict[str, object]:
    data = "".join(str(row["payload_json"]) + "\n" for row in rows).encode("utf-8")
    manifest = build_manifest(
        out,
        path=None,
        data=data,
        claim=claim,
        rows=rows,
        remote_required=remote_required,
    )
    final = segment_path(out, manifest)
    manifest["path"] = str(final)
    manifest["object_key"] = final.relative_to(out).as_posix()
    publish_no_replace(final, data=data, claim_id=claim.claim_id)
    return manifest


def build_manifest(
    out: Path,
    *,
    path: Path | None,
    data: bytes,
    claim: ExportClaim,
    rows: list[Any],
    remote_required: bool,
) -> dict[str, object]:
    if not rows:
        raise ArchiveError("ARCHIVE_EMPTY_SEGMENT")
    dates = {date_partition(int(row["occurred_at_utc_ns"])) for row in rows}
    event_types = {str(row["event_type"]) for row in rows}
    database_epochs = {str(row["database_epoch"]) for row in rows}
    release_ids = {str(row["release_id"]) for row in rows}
    policy_hashes = {str(row["policy_bundle_hash"]) for row in rows}
    schema_versions = {int(row["schema_version"]) for row in rows}
    redaction_versions = {str(row["redaction_version"]) for row in rows}
    dimensions = (
        dates,
        event_types,
        database_epochs,
        release_ids,
        policy_hashes,
        schema_versions,
        redaction_versions,
    )
    if any(len(values) != 1 for values in dimensions):
        raise ArchiveError("ARCHIVE_PARTITION_DIMENSION_MIXED")
    database_epoch = next(iter(database_epochs))
    if database_epoch != claim.database_epoch:
        raise ArchiveError("ARCHIVE_DATABASE_EPOCH_MISMATCH")

    event_ids = tuple(str(row["event_id"]) for row in rows)
    outbox_ids = tuple(int(row["outbox_id"]) for row in rows)
    manifest: dict[str, object] = {
        "checksum": hashlib.sha256(data).hexdigest(),
        "event_count": len(rows),
        "first_event_id": event_ids[0],
        "last_event_id": event_ids[-1],
        "first_outbox_id": min(outbox_ids),
        "last_outbox_id": max(outbox_ids),
        "date_utc": next(iter(dates)),
        "event_type": next(iter(event_types)),
        "database_epoch": database_epoch,
        "release_id": next(iter(release_ids)),
        "policy_bundle_hash": next(iter(policy_hashes)),
        "schema_version": next(iter(schema_versions)),
        "redaction_version": next(iter(redaction_versions)),
        "tool_version": PR198_EXPORT_TOOL_VERSION,
        "claim_id": claim.claim_id,
        "fencing_token": claim.fencing_token,
        "event_ids": event_ids,
        "remote_required": remote_required,
        "authoritative": True,
    }
    segment_id = hashlib.sha256(
        canonical_json(segment_identity(manifest, event_ids)).encode("utf-8")
    ).hexdigest()
    manifest["segment_id"] = segment_id
    manifest["manifest_id"] = segment_id
    effective_path = path or segment_path(out, manifest)
    manifest["path"] = str(effective_path)
    manifest["object_key"] = effective_path.relative_to(out).as_posix()
    return manifest


def segment_identity(
    manifest: Mapping[str, object],
    event_ids: tuple[str, ...],
) -> dict[str, object]:
    return {
        "database_epoch": str(manifest["database_epoch"]),
        "first_outbox_id": int(manifest["first_outbox_id"]),
        "last_outbox_id": int(manifest["last_outbox_id"]),
        "date_utc": str(manifest["date_utc"]),
        "event_type": str(manifest["event_type"]),
        "event_ids": event_ids,
        "checksum": str(manifest["checksum"]),
        "schema_version": int(manifest["schema_version"]),
        "redaction_version": str(manifest["redaction_version"]),
        "tool_version": str(manifest["tool_version"]),
        "release_id": str(manifest["release_id"]),
        "policy_bundle_hash": str(manifest["policy_bundle_hash"]),
    }


def segment_path(out: Path, manifest: Mapping[str, object]) -> Path:
    part = (
        out
        / f"date_utc={manifest['date_utc']}"
        / f"event_type={manifest['event_type']}"
    )
    return part / (
        f"segment={manifest['first_outbox_id']}-{manifest['last_outbox_id']}-"
        f"{manifest['checksum']}.jsonl"
    )


def publish_no_replace(final: Path, *, data: bytes, claim_id: str) -> None:
    secure_directory(final.parent)
    if final.exists():
        if final.read_bytes() != data:
            raise ArchiveError("ARCHIVE_IMMUTABLE_PATH_CONFLICT")
        return
    tmp = final.parent / f".segment-{claim_id}-{uuid.uuid4().hex}.tmp"
    descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, final)
        except FileExistsError:
            if final.read_bytes() != data:
                raise ArchiveError("ARCHIVE_IMMUTABLE_PATH_CONFLICT")
        except OSError as exc:
            raise ArchiveError("ARCHIVE_ATOMIC_NO_REPLACE_UNAVAILABLE") from exc
        fsync_dir(final.parent)
    finally:
        tmp.unlink(missing_ok=True)


def remove_stale_temp_files(coordinator: ArchiveCoordinator, out: Path) -> None:
    for tmp in out.glob("date_utc=*/event_type=*/.*.tmp"):
        match = TEMP_NAME.fullmatch(tmp.name)
        if match is not None and not coordinator.claim_is_active(match.group("claim")):
            tmp.unlink(missing_ok=True)


def event_ids_from_jsonl(data: bytes) -> tuple[str, ...]:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ArchiveError("ARCHIVE_JSONL_NOT_UTF8") from exc
    event_ids: list[str] = []
    for line in lines:
        if not line:
            raise ArchiveError("ARCHIVE_JSONL_EMPTY_LINE")
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ArchiveError("ARCHIVE_JSONL_PARSE_FAILED") from exc
        event_id = payload.get("event_id") if isinstance(payload, dict) else None
        if not isinstance(event_id, str) or not event_id:
            raise ArchiveError("ARCHIVE_JSONL_EVENT_ID_MISSING")
        event_ids.append(event_id)
    if len(set(event_ids)) != len(event_ids):
        raise ArchiveError("ARCHIVE_JSONL_DUPLICATE_EVENT")
    return tuple(event_ids)


def date_partition(utc_ns: int) -> str:
    return datetime.fromtimestamp(utc_ns / 1_000_000_000, tz=UTC).date().isoformat()


def canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def secure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def fsync_dir(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

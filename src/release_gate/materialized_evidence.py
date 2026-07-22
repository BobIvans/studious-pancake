"""O1 materialized release-evidence producer and Ed25519 verifier.

The producer never accepts artifact hashes from callers.  It reads the exact
materialized files, computes their hashes and signs the canonical manifest with a
dedicated release-attestation key (not a trading wallet key).
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Sequence

O1_EVIDENCE_SCHEMA = "o1.materialized-release-evidence.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class MaterializedArtifact:
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class MaterializedEvidenceManifest:
    schema_version: str
    source_commit: str
    release_digest: str
    policy_bundle_digest: str
    producer_id: str
    produced_at_unix_ns: int
    artifacts: tuple[MaterializedArtifact, ...]
    signer_pubkey: str
    signature: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_commit": self.source_commit,
            "release_digest": self.release_digest,
            "policy_bundle_digest": self.policy_bundle_digest,
            "producer_id": self.producer_id,
            "produced_at_unix_ns": self.produced_at_unix_ns,
            "artifacts": [asdict(item) for item in self.artifacts],
            "signer_pubkey": self.signer_pubkey,
            "signature": self.signature,
        }


@dataclass(frozen=True, slots=True)
class MaterializedEvidenceVerification:
    accepted: bool
    blockers: tuple[str, ...]
    release_digest: str | None
    manifest_sha256: str | None
    artifacts_verified: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _require_hash(name: str, value: str) -> None:
    if not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be lowercase sha256")


def _resolve_materialized(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("artifact path must be a relative child")
    root_resolved = root.resolve()
    target = (root_resolved / relative).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("artifact escapes approved root") from exc
    if target.is_symlink() or not target.is_file():
        raise ValueError("artifact must be a regular non-symlink file")
    stat_result = target.stat()
    if stat_result.st_nlink != 1:
        raise ValueError("artifact hardlinks are not accepted")
    return target


def collect_materialized_artifacts(
    root: str | os.PathLike[str],
    paths: Sequence[str],
) -> tuple[MaterializedArtifact, ...]:
    approved_root = Path(root)
    unique = tuple(dict.fromkeys(paths))
    if not unique:
        raise ValueError("at least one materialized artifact is required")
    output: list[MaterializedArtifact] = []
    for relative in sorted(unique):
        target = _resolve_materialized(approved_root, relative)
        raw = target.read_bytes()
        output.append(
            MaterializedArtifact(
                path=Path(relative).as_posix(),
                sha256=hashlib.sha256(raw).hexdigest(),
                size_bytes=len(raw),
            )
        )
    return tuple(output)


def _unsigned_payload(
    *,
    source_commit: str,
    release_digest: str,
    policy_bundle_digest: str,
    producer_id: str,
    produced_at_unix_ns: int,
    artifacts: tuple[MaterializedArtifact, ...],
    signer_pubkey: str,
) -> dict[str, Any]:
    return {
        "schema_version": O1_EVIDENCE_SCHEMA,
        "source_commit": source_commit,
        "release_digest": release_digest,
        "policy_bundle_digest": policy_bundle_digest,
        "producer_id": producer_id,
        "produced_at_unix_ns": produced_at_unix_ns,
        "artifacts": [asdict(item) for item in artifacts],
        "signer_pubkey": signer_pubkey,
    }


def _release_digest(
    *,
    source_commit: str,
    policy_bundle_digest: str,
    artifacts: tuple[MaterializedArtifact, ...],
) -> str:
    payload = {
        "domain": "o1-release",
        "source_commit": source_commit,
        "policy_bundle_digest": policy_bundle_digest,
        "artifacts": [asdict(item) for item in artifacts],
    }
    return "sha256:" + hashlib.sha256(_canonical_json(payload)).hexdigest()


def _load_attestation_keypair(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise ValueError("attestation key must be a regular file")
    if path.stat().st_mode & 0o077:
        raise ValueError("attestation key file must be owner-only")
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, list) or any(
        isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 255
        for item in values
    ):
        raise ValueError("attestation key must be a JSON byte array")
    from solders.keypair import Keypair

    return Keypair.from_bytes(bytes(values))


def produce_materialized_evidence(
    *,
    root: str | os.PathLike[str],
    paths: Sequence[str],
    source_commit: str,
    policy_bundle_digest: str,
    producer_id: str,
    keypair_path: str | os.PathLike[str],
    produced_at_unix_ns: int | None = None,
) -> MaterializedEvidenceManifest:
    if not _COMMIT.fullmatch(source_commit):
        raise ValueError("source_commit must be a full lowercase git SHA")
    _require_hash("policy_bundle_digest", policy_bundle_digest)
    if not producer_id.strip():
        raise ValueError("producer_id is required")
    artifacts = collect_materialized_artifacts(root, paths)
    release_digest = _release_digest(
        source_commit=source_commit,
        policy_bundle_digest=policy_bundle_digest,
        artifacts=artifacts,
    )
    keypair = _load_attestation_keypair(Path(keypair_path))
    signer_pubkey = str(keypair.pubkey())
    produced_at = produced_at_unix_ns or time.time_ns()
    unsigned = _unsigned_payload(
        source_commit=source_commit,
        release_digest=release_digest,
        policy_bundle_digest=policy_bundle_digest,
        producer_id=producer_id,
        produced_at_unix_ns=produced_at,
        artifacts=artifacts,
        signer_pubkey=signer_pubkey,
    )
    signature = str(keypair.sign_message(_canonical_json(unsigned)))
    return MaterializedEvidenceManifest(
        schema_version=O1_EVIDENCE_SCHEMA,
        source_commit=source_commit,
        release_digest=release_digest,
        policy_bundle_digest=policy_bundle_digest,
        producer_id=producer_id,
        produced_at_unix_ns=produced_at,
        artifacts=artifacts,
        signer_pubkey=signer_pubkey,
        signature=signature,
    )


def _load_manifest(path: Path) -> MaterializedEvidenceManifest:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("evidence manifest must be an object")
    expected_keys = {
        "schema_version",
        "source_commit",
        "release_digest",
        "policy_bundle_digest",
        "producer_id",
        "produced_at_unix_ns",
        "artifacts",
        "signer_pubkey",
        "signature",
    }
    if set(value) != expected_keys:
        raise ValueError("evidence manifest keys are not exact")
    raw_artifacts = value["artifacts"]
    if not isinstance(raw_artifacts, list):
        raise ValueError("artifacts must be an array")
    artifacts = tuple(MaterializedArtifact(**item) for item in raw_artifacts)
    return MaterializedEvidenceManifest(
        schema_version=str(value["schema_version"]),
        source_commit=str(value["source_commit"]),
        release_digest=str(value["release_digest"]),
        policy_bundle_digest=str(value["policy_bundle_digest"]),
        producer_id=str(value["producer_id"]),
        produced_at_unix_ns=int(value["produced_at_unix_ns"]),
        artifacts=artifacts,
        signer_pubkey=str(value["signer_pubkey"]),
        signature=str(value["signature"]),
    )


def verify_materialized_evidence(
    *,
    root: str | os.PathLike[str],
    manifest_path: str | os.PathLike[str],
    expected_policy_bundle_digest: str,
    expected_signer_pubkey: str,
) -> MaterializedEvidenceVerification:
    blockers: list[str] = []
    try:
        manifest = _load_manifest(Path(manifest_path))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return MaterializedEvidenceVerification(
            False,
            ("MANIFEST_INVALID",),
            None,
            None,
            0,
        )
    if manifest.schema_version != O1_EVIDENCE_SCHEMA:
        blockers.append("MANIFEST_SCHEMA_INVALID")
    if manifest.policy_bundle_digest != expected_policy_bundle_digest:
        blockers.append("POLICY_BUNDLE_DIGEST_MISMATCH")
    if manifest.signer_pubkey != expected_signer_pubkey:
        blockers.append("SIGNER_PUBKEY_MISMATCH")
    try:
        recomputed = collect_materialized_artifacts(
            root,
            tuple(item.path for item in manifest.artifacts),
        )
    except (OSError, ValueError):
        blockers.append("MATERIALIZED_ARTIFACT_INVALID")
        recomputed = ()
    if recomputed != manifest.artifacts:
        blockers.append("MATERIALIZED_ARTIFACT_HASH_MISMATCH")
    expected_release = _release_digest(
        source_commit=manifest.source_commit,
        policy_bundle_digest=manifest.policy_bundle_digest,
        artifacts=manifest.artifacts,
    )
    if manifest.release_digest != expected_release:
        blockers.append("RELEASE_DIGEST_MISMATCH")
    unsigned = _unsigned_payload(
        source_commit=manifest.source_commit,
        release_digest=manifest.release_digest,
        policy_bundle_digest=manifest.policy_bundle_digest,
        producer_id=manifest.producer_id,
        produced_at_unix_ns=manifest.produced_at_unix_ns,
        artifacts=manifest.artifacts,
        signer_pubkey=manifest.signer_pubkey,
    )
    try:
        from solders.pubkey import Pubkey
        from solders.signature import Signature

        signature_valid = Signature.from_string(manifest.signature).verify(
            Pubkey.from_string(manifest.signer_pubkey),
            _canonical_json(unsigned),
        )
    except (ImportError, ValueError):
        signature_valid = False
    if not signature_valid:
        blockers.append("PROVENANCE_SIGNATURE_INVALID")
    encoded = _canonical_json(manifest.to_dict())
    return MaterializedEvidenceVerification(
        accepted=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        release_digest=manifest.release_digest,
        manifest_sha256=hashlib.sha256(encoded).hexdigest(),
        artifacts_verified=len(recomputed),
    )


def write_manifest_atomic(
    path: str | os.PathLike[str],
    manifest: MaterializedEvidenceManifest,
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = _canonical_json(manifest.to_dict())
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flashloan-release-evidence")
    commands = parser.add_subparsers(dest="command", required=True)

    produce = commands.add_parser("produce")
    produce.add_argument("--root", required=True)
    produce.add_argument("--artifact", action="append", required=True)
    produce.add_argument("--source-commit", required=True)
    produce.add_argument("--policy-bundle-digest", required=True)
    produce.add_argument("--producer-id", required=True)
    produce.add_argument("--keypair", required=True)
    produce.add_argument("--output", required=True)

    verify = commands.add_parser("verify")
    verify.add_argument("--root", required=True)
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--expected-policy-bundle-digest", required=True)
    verify.add_argument("--expected-signer-pubkey", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "produce":
        manifest = produce_materialized_evidence(
            root=args.root,
            paths=args.artifact,
            source_commit=args.source_commit,
            policy_bundle_digest=args.policy_bundle_digest,
            producer_id=args.producer_id,
            keypair_path=args.keypair,
        )
        write_manifest_atomic(args.output, manifest)
        print(json.dumps(manifest.to_dict(), sort_keys=True))
        return 0

    report = verify_materialized_evidence(
        root=args.root,
        manifest_path=args.manifest,
        expected_policy_bundle_digest=args.expected_policy_bundle_digest,
        expected_signer_pubkey=args.expected_signer_pubkey,
    )
    print(json.dumps(report.to_dict(), sort_keys=True))
    return 0 if report.accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Deterministic manifest projections and atomic publication."""

from pathlib import Path
from .common import digest, save_json


def project_manifest(snapshot: dict) -> dict:
    payload = {k: snapshot[k] for k in ("schema", "repo_sha", "entries", "status")}
    return {**payload, "snapshot_id": digest(payload)}


def validate_manifest(manifest: dict) -> None:
    expected = project_manifest(manifest)
    if expected != manifest or manifest["status"] != "COMPLETE":
        raise ValueError("invalid manifest")


def project_part_index(manifest: dict) -> list[dict]:
    validate_manifest(manifest)
    return [
        {
            "path": e["path"],
            "sha256": e.get("sha256"),
            "start_byte": 0,
            "end_byte": e.get("bytes"),
            "status": e["status"],
        }
        for e in manifest["entries"]
    ]


def publish_manifest_atomic(manifest: dict, destination: str | Path) -> None:
    validate_manifest(manifest)
    save_json(Path(destination), manifest)

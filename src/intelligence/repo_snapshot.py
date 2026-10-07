"""Pinned Git objects, never working-tree execution or symlink traversal."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import re
import subprocess
import time

from .common import atomic_bytes, digest, file_hash, load_json, save_json


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args])


def _secret(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return (
        name == ".env"
        or name.startswith(".env.")
        and not name.endswith(("example", "sample", "template"))
        or name.endswith((".pem", ".key", ".p12", ".pfx"))
        or name in {"credentials", "id_rsa", "id_ed25519"}
    )


def _secret_bytes(data: bytes) -> bool:
    return bool(
        re.search(
            rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
            rb"gh[pousr]_[A-Za-z0-9]{30,}|"
            rb"AKIA[0-9A-Z]{16}",
            data,
        )
    )


def start_snapshot(
    repo: str | Path,
    destination: str | Path,
    *,
    ref: str = "HEAD",
    max_blob_bytes: int = 8 * 1024 * 1024,
    batch_size: int | None = None,
) -> dict:
    repo, destination = Path(repo).resolve(), Path(destination)
    if max_blob_bytes < 1 or batch_size is not None and batch_size < 1:
        raise ValueError("positive resource limits required")
    head = git(repo, "rev-parse", "--verify", ref + "^{commit}").decode().strip()
    entries = []
    for record in git(repo, "ls-tree", "-r", "-z", "--full-tree", head).split(b"\0"):
        if not record:
            continue
        meta, name = record.split(b"\t", 1)
        mode, kind, oid = meta.decode().split()
        path = name.decode("utf-8", "surrogateescape")
        entries.append({"path": path, "mode": mode, "kind": kind, "git_oid": oid})
    entries.sort(key=lambda x: x["path"])
    state = {
        "schema": "studious.repo-snapshot.v2",
        "repo_sha": head,
        "entries": entries,
        "max_blob_bytes": max_blob_bytes,
        "completed": 0,
        "status": "IN_PROGRESS",
    }
    state_path = destination / "state.json"
    if state_path.exists():
        old = load_json(state_path)
        if old["repo_sha"] != head or old["max_blob_bytes"] != max_blob_bytes:
            raise ValueError("snapshot destination identity conflict")
        return resume_snapshot(repo, destination, batch_size=batch_size)
    save_json(state_path, state)
    return resume_snapshot(repo, destination, batch_size=batch_size)


def resume_snapshot(
    repo: str | Path, destination: str | Path, *, batch_size: int | None = None
) -> dict:
    repo, destination = Path(repo), Path(destination)
    state = load_json(destination / "state.json")
    if batch_size is not None and batch_size < 1:
        raise ValueError("positive batch size required")
    start = time.monotonic()
    stop = (
        len(state["entries"])
        if batch_size is None
        else min(len(state["entries"]), state["completed"] + batch_size)
    )
    for index in range(state["completed"], stop):
        entry = state["entries"][index]
        if entry["kind"] != "blob" or entry["mode"] == "120000":
            entry["status"] = "SUBMODULE" if entry["kind"] == "commit" else "SYMLINK"
        else:
            size = int(git(repo, "cat-file", "-s", entry["git_oid"]))
            entry["bytes"] = size
            if _secret(entry["path"]):
                entry["status"] = "SECRET_METADATA_ONLY"
            elif size > state["max_blob_bytes"]:
                entry["status"] = "OVERSIZED"
            else:
                data = git(repo, "cat-file", "blob", entry["git_oid"])
                entry["sha256"] = hashlib.sha256(data).hexdigest()
                if _secret_bytes(data):
                    entry["status"] = "SECRET_METADATA_ONLY"
                else:
                    entry["status"] = "EXACT"
                    atomic_bytes(destination / "blobs" / entry["sha256"], data)
        state["completed"] = index + 1
        save_json(destination / "state.json", state)
    if state["completed"] == len(state["entries"]):
        state["status"] = "COMPLETE"
        manifest = {k: state[k] for k in ("schema", "repo_sha", "entries", "status")}
        manifest["snapshot_id"] = digest(manifest)
        save_json(destination / "manifest.json", manifest)
        save_json(destination / "state.json", state)
    save_json(
        destination / "RESOURCE_USAGE.json",
        {
            "processed_entries": state["completed"],
            "tracked_entries": len(state["entries"]),
            "retained_bytes": sum(
                e.get("bytes", 0)
                for e in state["entries"]
                if e.get("status") == "EXACT"
            ),
            "elapsed_seconds_this_batch": time.monotonic() - start,
            "max_blob_bytes": state["max_blob_bytes"],
            "repository_code_executed": False,
        },
    )
    return state


def snapshot_status(destination: str | Path) -> dict:
    return load_json(Path(destination) / "state.json")


def verify_snapshot_roundtrip(destination: str | Path) -> dict:
    root = Path(destination)
    manifest = load_json(root / "manifest.json")
    expected = manifest.pop("snapshot_id")
    if digest(manifest) != expected or manifest["status"] != "COMPLETE":
        raise ValueError("snapshot manifest identity mismatch")
    seen = set()
    for entry in manifest["entries"]:
        if entry["path"] in seen:
            raise ValueError("duplicate tracked path")
        seen.add(entry["path"])
        if entry["status"] == "EXACT":
            blob = root / "blobs" / entry["sha256"]
            if (
                blob.stat().st_size != entry["bytes"]
                or file_hash(blob) != entry["sha256"]
            ):
                raise ValueError("snapshot byte proof mismatch")
            header = f"blob {entry['bytes']}\0".encode()
            algorithm = hashlib.sha1 if len(entry["git_oid"]) == 40 else hashlib.sha256
            if algorithm(header + blob.read_bytes()).hexdigest() != entry["git_oid"]:
                raise ValueError("Git object proof mismatch")
    return {"snapshot_id": expected, "tracked_entries": len(seen), "verified": True}

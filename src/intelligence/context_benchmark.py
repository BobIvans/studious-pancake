"""Frozen snapshot oracle with exact byte retrieval outcomes."""

import hashlib
from pathlib import Path
from .common import load_json
from .repo_snapshot import verify_snapshot_roundtrip


def seed_oracle(snapshot: str | Path, *, count: int = 32) -> dict:
    root = Path(snapshot)
    verify_snapshot_roundtrip(root)
    manifest = load_json(root / "manifest.json")
    cases = [
        {"path": e["path"], "sha256": e["sha256"], "bytes": e["bytes"]}
        for e in manifest["entries"]
        if e["status"] == "EXACT"
    ][:count]
    if not cases:
        raise ValueError("zero-case benchmark")
    return {"snapshot_id": manifest["snapshot_id"], "cases": cases}


def benchmark_exact_retrieval(snapshot: str | Path, oracle: dict) -> dict:
    root = Path(snapshot)
    if load_json(root / "manifest.json")["snapshot_id"] != oracle["snapshot_id"]:
        raise ValueError("stale retrieval oracle")
    results = []
    for case in oracle["cases"]:
        data = (root / "blobs" / case["sha256"]).read_bytes()
        results.append(
            len(data) == case["bytes"]
            and hashlib.sha256(data).hexdigest() == case["sha256"]
        )
    return {
        "executed": len(results),
        "passed": sum(results),
        "failed": results.count(False),
    }


def benchmark_context_pack(snapshot: str | Path, pack: dict) -> dict:
    root = Path(snapshot)
    if load_json(root / "manifest.json")["snapshot_id"] != pack["snapshot_id"]:
        raise ValueError("stale context pack")
    outcomes = []
    for part in pack["parts"]:
        data = (root / "blobs" / part["sha256"]).read_bytes()
        outcomes.append(
            data[part["start_byte"] : part["end_byte"]]
            == bytes.fromhex(part["bytes_hex"])
        )
    return {
        "executed": len(outcomes),
        "passed": sum(outcomes),
        "failed": outcomes.count(False),
        "within_budget": pack["source_bytes"] <= pack["budget_bytes"],
    }

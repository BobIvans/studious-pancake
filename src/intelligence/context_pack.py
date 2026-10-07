"""Budgeted, snapshot-bound retrieval with resumable byte ranges."""

from pathlib import Path
from .common import digest, file_hash, load_json
from .repo_history import affected_dependents
from .repo_source import build_import_graph, analyze_source, resolve_reverse_imports
from .repo_snapshot import verify_snapshot_roundtrip

MODES = {
    "WHOLE_REPO",
    "WHOLE_REPO_INDEXED",
    "INTERCONNECTED_FILES",
    "RUNTIME_PATH",
    "TEST_IMPACT",
    "TECH_DEBT",
    "DELTA",
}
RUNTIME_SEEDS = {"paper-shadow": "src/paper_shadow/runner.py"}


def build_context_pack(
    snapshot: str | Path,
    *,
    mode: str = "WHOLE_REPO_INDEXED",
    seed: str | None = None,
    goal: str = "",
    budget_bytes: int = 64_000,
    continuation: dict | None = None,
    changed: list[str] = (),
) -> dict:
    if mode not in MODES or budget_bytes < 1:
        raise ValueError("invalid context mode/budget")
    root = Path(snapshot)
    verify_snapshot_roundtrip(root)
    manifest = load_json(root / "manifest.json")
    entries = {e["path"]: e for e in manifest["entries"] if e["status"] == "EXACT"}
    paths = sorted(entries)
    actual_seed = RUNTIME_SEEDS.get(seed, seed)
    if mode in {"INTERCONNECTED_FILES", "RUNTIME_PATH", "TEST_IMPACT", "DELTA"}:
        analyses = [
            analyze_source(p, (root / "blobs" / entries[p]["sha256"]).read_bytes())
            for p in paths
            if p.endswith(".py")
        ]
        graph = build_import_graph(analyses)
        if mode == "DELTA":
            selected = affected_dependents(
                list(changed), resolve_reverse_imports(graph)
            )
        elif mode == "TEST_IMPACT":
            if actual_seed not in entries:
                raise ValueError("seed missing from pinned snapshot")
            selected = affected_dependents(
                [actual_seed], resolve_reverse_imports(graph)
            )
        else:
            if actual_seed not in entries:
                raise ValueError("seed missing from pinned snapshot")
            selected = affected_dependents([actual_seed], graph)
        paths = [p for p in selected if p in entries]
    elif goal:
        words = goal.lower().split()
        paths.sort(key=lambda p: (-sum(w in p.lower() for w in words), p))
    identity = digest(
        {
            "snapshot": manifest["snapshot_id"],
            "mode": mode,
            "seed": seed,
            "goal": goal,
            "paths": paths,
        }
    )
    index, offset = 0, 0
    if continuation:
        if continuation.get("identity") != identity:
            raise ValueError("stale context continuation")
        index, offset = continuation["index"], continuation["offset"]
        if index < 0 or index >= len(paths) or offset < 0:
            raise ValueError("invalid continuation")
    remaining, parts = budget_bytes, []
    while index < len(paths) and remaining:
        path = paths[index]
        entry = entries[path]
        blob = root / "blobs" / entry["sha256"]
        if file_hash(blob) != entry["sha256"] or offset > entry["bytes"]:
            raise ValueError("invalid source proof")
        with blob.open("rb") as stream:
            stream.seek(offset)
            data = stream.read(remaining)
        # Hex preserves binary and partial UTF-8 bytes exactly.
        parts.append(
            {
                "path": path,
                "sha256": entry["sha256"],
                "start_byte": offset,
                "end_byte": offset + len(data),
                "bytes_hex": data.hex(),
            }
        )
        remaining -= len(data)
        offset += len(data)
        if offset == entry["bytes"]:
            index, offset = index + 1, 0
    return {
        "schema": "studious.context-pack.v2",
        "snapshot_id": manifest["snapshot_id"],
        "repo_sha": manifest["repo_sha"],
        "mode": mode,
        "seed": seed,
        "goal": goal,
        "parts": parts,
        "source_bytes": budget_bytes - remaining,
        "budget_bytes": budget_bytes,
        "selected_paths": paths,
        "continuation": (
            {"identity": identity, "index": index, "offset": offset}
            if index < len(paths)
            else None
        ),
    }


def continue_context_pack(snapshot: str | Path, pack: dict, **kwargs) -> dict:
    if pack["continuation"] is None:
        raise ValueError("context pack already complete")
    return build_context_pack(
        snapshot,
        mode=pack["mode"],
        seed=pack["seed"],
        goal=pack["goal"],
        continuation=pack["continuation"],
        **kwargs,
    )


def build_runtime_path_pack(snapshot, seed="paper-shadow", **kwargs):
    return build_context_pack(snapshot, mode="RUNTIME_PATH", seed=seed, **kwargs)


def build_test_impact_pack(snapshot, seed, **kwargs):
    return build_context_pack(snapshot, mode="TEST_IMPACT", seed=seed, **kwargs)

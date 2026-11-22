"""Graph build pipeline: snapshot -> inventory -> parse -> edges -> artifact.

Orchestrates the deterministic build. The canonical artifact is the set of
JSONL record files + manifest checksum; the SQLite index is a derived local
query cache and never the determinism target.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from ..repo_snapshot import start_snapshot, verify_snapshot_roundtrip
from . import edges as edges_mod
from . import extractors as extractors_mod
from . import parsers as parsers_mod
from . import schema
from . import symbols as symbols_mod
from .incremental import classify_tree_changes, load_cache, save_cache
from .inventory import build_inventory
from .schema import (
    COVERAGE_EXCLUDED_WITH_REASON,
    COVERAGE_INDEXED,
    COVERAGE_METADATA_ONLY,
    COVERAGE_PARSE_ERROR,
    COVERAGE_PARTIAL,
    COVERAGE_STRUCTURE_INDEXED,
    COVERAGE_TEXT_INDEXED,
    COVERAGE_UNSUPPORTED,
    GRAPH_SCHEMA_VERSION,
    PARSER_VERSION,
    SCHEMA_ID,
    canonical_jsonl,
)
from .store import write_artifact


def _blob_path(snapshot_root: str, blob_sha256: str) -> Path:
    return Path(snapshot_root) / "blobs" / blob_sha256


def build_graph(
    repo: str | Path,
    state_root: str | Path,
    *,
    ref: str = "HEAD",
    max_blob_bytes: int = 16 * 1024 * 1024,
) -> dict[str, Any]:
    """Build (or incrementally refresh) the repo graph for the pinned ref.

    Returns a build receipt. The build receipt contains wall-clock fields and
    is NOT part of the canonical checksum; canonical records never carry
    timestamps (contract hard guarantee 2).
    """
    repo_path = Path(repo)
    state_root = Path(state_root)
    started = time.monotonic()
    from ..repo_snapshot import git

    repo_sha = (
        git(repo_path, "rev-parse", "--verify", ref + "^{commit}").decode().strip()
    )
    # Snapshot destination is SHA-qualified: start_snapshot rejects identity
    # conflicts, so each generation keeps its own pinned object set.
    snapshot_root = state_root / "snapshots" / repo_sha[:16]
    start_snapshot(repo_path, snapshot_root, ref=ref, max_blob_bytes=max_blob_bytes)
    verify_snapshot_roundtrip(snapshot_root)

    inventory = build_inventory(str(snapshot_root))
    path_to_blob = {
        row["path"]: row["blob_sha256"] for row in inventory if row["blob_sha256"]
    }

    cache = load_cache(str(state_root))
    modules: dict[str, dict[str, Any]] = {}
    coverage_rows: list[dict[str, Any]] = []
    polyglot_nodes: list[dict[str, Any]] = []
    for row in inventory:
        coverage = dict(row)
        if (
            row["coverage"] == COVERAGE_INDEXED
            and row.get("language_class") == "python"
        ):
            classification = extractors_mod.classify_artifact(
                row["path"], row["snapshot_status"]
            )
            coverage["artifact_class"] = classification["artifact_class"]
            coverage["language"] = classification["language"]
            coverage["first_party"] = classification["first_party"]
            blob_sha = row["blob_sha256"]
            cache_key = f"{blob_sha}|{PARSER_VERSION}"
            cached = cache["entries"].get(cache_key)
            data = _blob_path(str(snapshot_root), blob_sha).read_bytes()
            try:
                if cached is not None:
                    analysis = _rebase_analysis(cached, row["path"])
                else:
                    analysis = symbols_mod.parse_python_module(row["path"], data)
                    cache["entries"][cache_key] = analysis
                modules[row["path"]] = analysis
                coverage["coverage"] = COVERAGE_STRUCTURE_INDEXED
                coverage["symbol_count"] = len(analysis["symbols"])
            except (SyntaxError, ValueError) as exc:
                coverage["coverage"] = COVERAGE_PARSE_ERROR
                coverage["reason"] = str(exc).splitlines()[0][:200]
        elif (
            row["coverage"] == COVERAGE_INDEXED
            and row.get("language_class") != "python"
        ):
            # OCA-W0B2 polyglot layer: artifact classification + structured
            # extraction (stdlib first, tree-sitter where grammars installed).
            classification = extractors_mod.classify_artifact(
                row["path"], row["snapshot_status"]
            )
            coverage["artifact_class"] = classification["artifact_class"]
            coverage["language"] = classification["language"]
            coverage["first_party"] = classification["first_party"]
            data = _blob_path(str(snapshot_root), row["blob_sha256"]).read_bytes()
            extracted, parser_id, status, reason = _index_non_python(
                row["path"], data, classification
            )
            coverage["coverage"] = status
            coverage["reason"] = reason
            coverage["parser"] = parser_id
            coverage["symbol_count"] = len(extracted)
            polyglot_nodes.extend(extracted)
        coverage_rows.append(coverage)
    save_cache(str(state_root), cache)

    edge_records = edges_mod.build_edges(modules)

    node_records = []
    for path in sorted(modules):
        node_records.extend(modules[path]["symbols"])
    node_records.extend(polyglot_nodes)
    # Deterministic global dedupe: repeated qualified names inside one
    # non-Python file (e.g. repeated markdown headings) disambiguate by
    # source order, matching the Python-module rule.
    node_records.sort(key=lambda item: (item["symbol_id"], item["start_byte"]))
    seen_ids: dict[str, int] = {}
    for node in node_records:
        base = node["symbol_id"]
        occurrence = seen_ids.get(base, 0)
        seen_ids[base] = occurrence + 1
        if occurrence:
            node["symbol_id"] = f"{base}#{occurrence}"

    coverage_rows.sort(key=lambda item: item["path"])
    canonical_nodes = canonical_jsonl(node_records)
    canonical_edges = canonical_jsonl(edge_records)
    canonical_coverage = canonical_jsonl(coverage_rows)
    checksum = hashlib.sha256(
        b"nodes|"
        + canonical_nodes
        + b"edges|"
        + canonical_edges
        + b"coverage|"
        + canonical_coverage
    ).hexdigest()
    generation = schema.graph_generation(repo_sha, checksum)

    counts = {
        "nodes": len(node_records),
        "edges": len(edge_records),
        "files_tracked": len(inventory),
        "modules_parsed": len(modules),
    }
    receipt = write_artifact(
        str(state_root),
        repo_sha=repo_sha,
        generation=generation,
        checksum=checksum,
        nodes=canonical_nodes,
        edges=canonical_edges,
        coverage=canonical_coverage,
        counts=counts,
        inventory=coverage_rows,
        path_to_blob=path_to_blob,
    )
    receipt["tree_changes"] = classify_tree_changes(
        _previous_paths(str(state_root), repo_sha), path_to_blob
    )
    receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return receipt


def _index_non_python(
    path: str, data: bytes, classification: dict[str, str]
) -> tuple[list[dict[str, Any]], str, str, str | None]:
    """Classify coverage and extract typed nodes for one non-Python file.

    Returns (nodes, parser_id, coverage_status, reason). Every outcome maps to
    an explicit status — no silent 'other' bucket (OCA-W0B2 acceptance).
    """
    artifact_class = classification["artifact_class"]
    language = classification["language"]
    if artifact_class == "vendor_reference":
        return [], "none", COVERAGE_METADATA_ONLY, "VENDOR_REFERENCE_NO_PARSE"
    if artifact_class == "other_tracked":
        return [], "none", COVERAGE_UNSUPPORTED, f"LANGUAGE_{language}"
    structured = extractors_mod.extract_structured(path, data)
    if structured is not None and structured["nodes"]:
        return (
            structured["nodes"],
            structured["parser"],
            COVERAGE_STRUCTURE_INDEXED,
            None,
        )
    if structured is not None and structured["parser"].endswith("PARSE_ERROR"):
        return [], structured["parser"], COVERAGE_PARSE_ERROR, "STRUCTURED_PARSE_ERROR"
    if language in parsers_mod.GRAMMAR_PACKS:
        parsed = parsers_mod.parse_structural(language, data)
        if parsed is not None:
            nodes = [
                {
                    "symbol_id": schema.stable_node_id(
                        language, path, decl["qualified_name"]
                    ),
                    "path": path,
                    "language": language,
                    "kind": decl["kind"],
                    "name": decl["name"],
                    "qualified_name": decl["qualified_name"],
                    "start_byte": decl["start_byte"],
                    "end_byte": decl["end_byte"],
                }
                for decl in parsed["declarations"]
            ]
            return (
                nodes,
                f"tree-sitter:{language}@{parsed['grammar_version']}",
                COVERAGE_STRUCTURE_INDEXED,
                None,
            )
        return (
            [],
            "none",
            COVERAGE_PARTIAL,
            f"TREE_SITTER_GRAMMAR_ABSENT:{language}",
        )
    if language in {"text", "other"} and artifact_class in {"doc", "config", "schema"}:
        return [], "none", COVERAGE_TEXT_INDEXED, None
    return [], "none", COVERAGE_METADATA_ONLY, "NO_EXTRACTOR_FOR_CLASS"


def _load_snapshot_manifest(snapshot_root: Path) -> dict[str, Any]:
    return json.loads((snapshot_root / "manifest.json").read_text(encoding="utf-8"))


def _rebase_analysis(analysis: dict[str, Any], new_path: str) -> dict[str, Any]:
    """Rebase a cached parse onto the current path (rename support).

    Cache entries are keyed by blob content, so a renamed file hits the same
    entry under a new path. Path-derived identity fields are rewritten here so
    incremental builds stay byte-identical to clean rebuilds.
    """
    old_path = analysis["path"]
    if old_path == new_path:
        return analysis
    old_module = symbols_mod.module_name(old_path)
    new_module = symbols_mod.module_name(new_path)
    rebased = dict(analysis)
    rebased["path"] = new_path
    rebased["module"] = new_module
    old_prefix = f"py::{old_path}::"
    new_prefix = f"py::{new_path}::"
    rebased["symbols"] = [
        {
            **symbol,
            "path": new_path,
            **(
                {
                    "symbol_id": new_prefix + new_module,
                    "name": new_module,
                    "qualified_name": new_module,
                }
                if symbol["kind"] == "module"
                else {"symbol_id": new_prefix + symbol["symbol_id"][len(old_prefix) :]}
            ),
        }
        for symbol in analysis["symbols"]
    ]
    rebased["defines"] = [symbol["symbol_id"] for symbol in rebased["symbols"]]
    return rebased


def _previous_paths(state_root: str, repo_sha: str) -> dict[str, str]:
    """Paths of the most recent OTHER artifact generation, for diff receipts."""
    from .store import artifact_dir

    root = artifact_dir(state_root)
    if not root.exists():
        return {}
    best: tuple[str, str] | None = None
    for child in sorted(path for path in root.iterdir() if path.is_dir()):
        manifest_path = child / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("repo_sha") == repo_sha:
            continue
        key = manifest.get("built_at") or manifest.get("generation") or ""
        if best is None or key > best[0]:
            best = (key, child.name)
    if best is None:
        return {}
    manifest = json.loads(
        (artifact_dir(state_root) / best[1] / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    return manifest.get("path_to_blob", {})


__all__ = ["build_graph", "SCHEMA_ID", "GRAPH_SCHEMA_VERSION"]

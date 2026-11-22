"""Content-addressed graph artifact storage and derived SQLite query cache."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .schema import GRAPH_SCHEMA_VERSION, SCHEMA_ID


def artifact_dir(state_root: str) -> Path:
    return Path(state_root) / "repo_graph" / "artifacts"


def artifact_path(state_root: str, repo_sha: str) -> Path:
    return artifact_dir(state_root) / repo_sha[:16]


def write_artifact(
    state_root: str,
    *,
    repo_sha: str,
    generation: str,
    checksum: str,
    nodes: bytes,
    edges: bytes,
    coverage: bytes,
    counts: dict[str, int],
    inventory: list[dict[str, Any]],
    path_to_blob: dict[str, str],
) -> dict[str, Any]:
    """Write the canonical artifact for one graph generation.

    Canonical record files carry no timestamps; ``built_at`` lives only in the
    manifest and is excluded from the checksum, so two clean builds at the same
    inputs stay byte-identical in their canonical records and checksum.
    """
    target = artifact_path(state_root, repo_sha)
    target.mkdir(parents=True, exist_ok=True)
    (target / "nodes.jsonl").write_bytes(nodes)
    (target / "edges.jsonl").write_bytes(edges)
    (target / "coverage.jsonl").write_bytes(coverage)
    manifest = {
        "schema": SCHEMA_ID,
        "graph_schema_version": GRAPH_SCHEMA_VERSION,
        "repo_sha": repo_sha,
        "generation": generation,
        "canonical_checksum": checksum,
        "counts": counts,
        "path_to_blob": path_to_blob,
        "inventory": inventory,
        "parser_version": "stdlib-ast-py3.13",
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    _build_sqlite_index(str(target), nodes, edges)
    receipt = {
        "repo_sha": repo_sha,
        "generation": generation,
        "canonical_checksum": checksum,
        "artifact_dir": str(target),
        "counts": counts,
        "_started": time.monotonic(),
    }
    return receipt


def load_manifest(state_root: str, repo_sha: str) -> dict[str, Any]:
    manifest_path = artifact_path(state_root, repo_sha) / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"no graph artifact for repo sha {repo_sha[:16]}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _build_sqlite_index(target: str, nodes: bytes, edges: bytes) -> None:
    """Derive the FTS query cache from canonical records (rebuildable cache)."""
    index_path = Path(target) / "graph.sqlite"
    if index_path.exists():
        index_path.unlink()
    connection = sqlite3.connect(index_path)
    try:
        connection.executescript("""
            CREATE TABLE nodes (
                symbol_id TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                qualified_name TEXT NOT NULL,
                parent_qualified TEXT,
                signature TEXT,
                start_byte INTEGER NOT NULL,
                end_byte INTEGER NOT NULL,
                signature_hash TEXT,
                body_hash TEXT
            );
            CREATE TABLE edges (
                relation TEXT NOT NULL,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                resolution TEXT,
                lineno INTEGER,
                provenance TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE node_fts USING fts5(
                name, qualified_name, path, content='nodes', content_rowid='rowid'
            );
            """)
        node_rows = []
        for line in nodes.decode("utf-8").splitlines():
            if not line:
                continue
            record = json.loads(line)
            node_rows.append(
                (
                    record["symbol_id"],
                    record["path"],
                    record["kind"],
                    record["name"],
                    record["qualified_name"],
                    record.get("parent_qualified"),
                    record.get("signature"),
                    record["start_byte"],
                    record["end_byte"],
                    record.get("signature_hash"),
                    record.get("body_hash"),
                )
            )
        connection.executemany(
            "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?)", node_rows
        )
        connection.executemany(
            "INSERT INTO node_fts(rowid, name, qualified_name, path) "
            "VALUES ((SELECT rowid FROM nodes WHERE symbol_id=?),?,?,?)",
            [(row[0], row[3], row[4], row[1]) for row in node_rows],
        )
        edge_rows = []
        for line in edges.decode("utf-8").splitlines():
            if not line:
                continue
            record = json.loads(line)
            edge_rows.append(
                (
                    record["relation"],
                    record["source"],
                    record["target"],
                    record.get("resolution"),
                    record.get("lineno"),
                    record["provenance"],
                )
            )
        connection.executemany("INSERT INTO edges VALUES (?,?,?,?,?,?)", edge_rows)
        connection.execute("CREATE INDEX idx_edges_source ON edges(source, relation)")
        connection.execute("CREATE INDEX idx_edges_target ON edges(target, relation)")
        connection.commit()
    finally:
        connection.close()


def dangling_edge_count(target: str) -> int:
    """Contract check: every edge endpoint must resolve to a node record."""
    connection = sqlite3.connect(Path(target) / "graph.sqlite")
    try:
        row = connection.execute("""
            SELECT COUNT(*) FROM edges e
            WHERE NOT EXISTS (SELECT 1 FROM nodes n WHERE n.symbol_id = e.source)
               OR NOT EXISTS (SELECT 1 FROM nodes n WHERE n.symbol_id = e.target)
            """).fetchone()
        assert row is not None
        return int(row[0])
    finally:
        connection.close()

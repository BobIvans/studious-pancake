"""Read-only query backend: task_context / expand_context / repo_card.

The single retrieval backend (contract: CLI, MCP and portable export must call
these functions — no divergent engines). Deterministic ranking: exact stable
IDs first, then FTS lexical, then typed-graph neighbours. Token counts are
labelled byte estimates (utf-8 bytes / 4); no tokenizer dependency.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .ranking import conditioned_boost
from .schema import SCHEMA_ID
from .store import artifact_path, load_manifest
from .tokenizers import resolve_tokenizer

TOKENIZER = "byte-estimate-v1 (utf-8 bytes / 4; no model tokenizer installed)"
DEFAULT_BUDGET_TOKENS = 2000

# Deterministic task-type routing (OCA-W4). Keyword rules pick the type; the
# boost table is prefix-based and never promotes provenance or verification
# state — it only reorders retrieval.
_TASK_KEYWORDS: dict[str, set[str]] = {
    "bug": {"bug", "error", "failure", "traceback", "crash", "exception", "fix"},
    "test": {"test", "tests", "coverage", "flaky", "assertion"},
    "provider": {"provider", "adapter", "endpoint", "quote", "rpc", "source"},
    "strategy": {"strategy", "arbitrage", "flash", "capital", "lender", "lending"},
    "refactor": {"refactor", "rename", "move", "cleanup", "split"},
    "architecture": {"architecture", "design", "dependency", "impact", "structure"},
}
TASK_TYPE_BOOSTS: dict[str, dict[str, float]] = {
    "bug": {"tests/": 3.0, "config/": 2.0},
    "test": {"tests/": 3.0},
    "provider": {
        "src/providers/": 3.0,
        "src/lending/": 3.0,
        "src/gpr_sui_shadow/": 3.0,
        "src/external_contracts/": 2.0,
        "src/provider_governance/": 2.0,
    },
    "strategy": {"src/strategy/": 3.0, "src/economics/": 2.0, "src/planning/": 2.0},
    "refactor": {},
    "architecture": {"src/intelligence/": 1.0},
    "generic": {},
}


def detect_task_type(task: str) -> str:
    words = set(re.split(r"[^a-z0-9_]+", task.lower())) - {""}
    for task_type in (
        "bug",
        "test",
        "provider",
        "strategy",
        "refactor",
        "architecture",
    ):
        if words & _TASK_KEYWORDS[task_type]:
            return task_type
    return "generic"


class GraphNotAvailable(RuntimeError):
    """Raised when no graph artifact exists for the requested repo SHA."""


def _token_estimate(data: bytes) -> int:
    return len(data) // 4


def _load_snapshot_blob(snapshot_root: str, blob_sha256: str) -> bytes:
    return (Path(snapshot_root) / "blobs" / blob_sha256).read_bytes()


def resolve_repo_sha(repo_root: str, repo_ref: str) -> str:
    """Resolve a ref once and return the pinned commit SHA."""
    from ..repo_snapshot import git

    head = git(Path(repo_root), "rev-parse", "--verify", repo_ref + "^{commit}")
    return head.decode().strip()


class QueryBackend:
    def __init__(self, state_root: str, repo_root: str | None = None) -> None:
        self._state_root = str(Path(state_root))
        self._repo_root = repo_root

    # -- freshness -------------------------------------------------------
    def freshness(self, repo_sha: str) -> dict[str, Any]:
        target = artifact_path(self._state_root, repo_sha)
        if not (target / "manifest.json").exists():
            return {
                "requested_sha": repo_sha,
                "indexed_sha": None,
                "status": "UNAVAILABLE",
                "note": "no graph artifact for requested SHA; build first",
            }
        manifest = load_manifest(self._state_root, repo_sha)
        if manifest["repo_sha"] != repo_sha:
            return {
                "requested_sha": repo_sha,
                "indexed_sha": manifest["repo_sha"],
                "status": "STALE",
            }
        return {
            "requested_sha": repo_sha,
            "indexed_sha": manifest["repo_sha"],
            "status": "FRESH",
            "generation": manifest["generation"],
            "canonical_checksum": manifest["canonical_checksum"],
        }

    # -- T0 card ---------------------------------------------------------
    def repo_card(self, repo_sha: str) -> dict[str, Any]:
        manifest = load_manifest(self._state_root, repo_sha)
        inventory = manifest["inventory"]
        indexed = [row for row in inventory if row["coverage"] == "INDEXED"]
        python_files = [row for row in indexed if row.get("language_class") == "python"]
        excluded = [
            row for row in inventory if row["coverage"] == "EXCLUDED_WITH_REASON"
        ]
        card = {
            "schema": SCHEMA_ID,
            "repo_sha": repo_sha,
            "generation": manifest["generation"],
            "files_tracked": len(inventory),
            "files_indexed": len(indexed),
            "python_modules": len(python_files),
            "symbols": manifest["counts"]["nodes"],
            "edges": manifest["counts"]["edges"],
            "excluded_with_reason": len(excluded),
            "exclusions_by_reason": _count_by(excluded, "reason"),
            "top_directories": _top_directories([row["path"] for row in indexed]),
        }
        card["token_estimate"] = _token_estimate(
            json.dumps(card, sort_keys=True).encode("utf-8")
        )
        return card

    # -- task_context ----------------------------------------------------
    def task_context(
        self,
        task: str,
        *,
        repo_sha: str,
        budget_tokens: int | None = None,
        dimensions: list[str] | None = None,
        must_include_refs: list[str] | None = None,
        exclude_refs: list[str] | None = None,
        continuation_cursor: dict[str, Any] | None = None,
        token_profile: str | None = None,
    ) -> dict[str, Any]:
        fresh = self.freshness(repo_sha)
        if fresh["status"] in {"UNAVAILABLE", "STALE"}:
            return {
                "status": fresh["status"],
                "freshness": fresh,
                "task": task,
                "included_refs": [],
                "omitted_refs": [],
                "next_expansions": [],
            }
        manifest = load_manifest(self._state_root, repo_sha)
        target = artifact_path(self._state_root, repo_sha)
        if budget_tokens is not None and budget_tokens <= 0:
            raise ValueError("budget_tokens must be positive")
        budget = (budget_tokens or DEFAULT_BUDGET_TOKENS) * 4
        must_include = list(must_include_refs or [])
        excluded = set(exclude_refs or [])
        dimensions = list(dimensions or ["auto"])
        resolved_directories = self._resolve_directory_refs(repo_sha, must_include)

        task_type = detect_task_type(task)
        continuation_offset_base = 0
        ranked = self._rank(target, manifest, task, must_include, task_type)
        adapter, tokenizer_meta = resolve_tokenizer(token_profile)
        if continuation_cursor:
            # P2-5: cursor binds task + SHA + budget + dimensions; offsets
            # beyond the ranked set are rejected instead of yielding empty.
            if continuation_cursor.get("task_hash") != _task_hash(
                task,
                repo_sha,
                budget_tokens or DEFAULT_BUDGET_TOKENS,
                tuple(dimensions),
                tuple(sorted(must_include)),
                tuple(sorted(excluded)),
            ):
                raise ValueError("stale task continuation cursor")
            offset = int(continuation_cursor.get("offset", 0))
            if offset < 0 or offset > len(ranked):
                raise ValueError("continuation offset out of range")
            continuation_offset_base = offset
            ranked = ranked[offset:] if offset < len(ranked) else []
        included: list[dict[str, Any]] = []
        omitted: list[dict[str, Any]] = []
        used = 0
        slots = [("FULL", 2), ("SKELETON", 4), ("REFERENCE", 6)]
        slot_index = 0
        slot_remaining = slots[0][1]
        for ref in ranked:
            path = ref["path"]
            if path in excluded:
                continue
            size = ref["bytes"]
            payload = {"path": path, "blob_sha256": ref["blob_sha256"], "bytes": size}
            if size > budget or used + size > budget:
                payload["needs_expansion"] = True
                payload["resolution"] = "NEEDS_EXPANSION"
                omitted.append(payload)
                continue
            if slot_remaining == 0 and slot_index + 1 < len(slots):
                slot_index += 1
                slot_remaining = slots[slot_index][1]
            if slot_remaining == 0:
                payload["needs_expansion"] = True
                payload["resolution"] = "NEEDS_EXPANSION"
                omitted.append(payload)
                continue
            resolution = slots[slot_index][0]
            slot_remaining -= 1
            data = _load_snapshot_blob(
                self._snapshot_root(repo_sha), ref["blob_sha256"]
            )
            if resolution == "FULL":
                content = data
            elif resolution == "SKELETON":
                content = self._skeleton(target, path, data).encode("utf-8")
            else:
                content = self._reference(target, path).encode("utf-8")
            used += len(content)
            payload["content_bytes"] = content
            payload["resolution"] = resolution
            payload["token_estimate"] = adapter.count(content)
            included.append(payload)
        neighbours = self._neighbours(target, [item["path"] for item in included])
        status = "BUDGET_LIMITED" if omitted else "FRESH"
        envelope = {
            "status": status,
            "schema": SCHEMA_ID,
            "task": task,
            "repo_sha": repo_sha,
            "graph_generation": manifest["generation"],
            "indexed_sha": manifest["repo_sha"],
            "freshness": fresh,
            "dimensions_used": dimensions,
            "task_type": task_type,
            "resolved_directory_refs": resolved_directories,
            "continuation_cursor": (
                {
                    "task_hash": _task_hash(
                        task,
                        repo_sha,
                        budget_tokens or DEFAULT_BUDGET_TOKENS,
                        tuple(dimensions),
                        tuple(sorted(must_include)),
                        tuple(sorted(excluded)),
                    ),
                    "offset": continuation_offset_base + len(ranked),
                }
                if omitted and ranked
                else None
            ),
            "budget_tokens": budget_tokens or DEFAULT_BUDGET_TOKENS,
            "budget_used_bytes": used,
            "budget_cap_bytes": budget,
            "tokenizer": tokenizer_meta["tokenizer"],
            "tokenizer_uncertainty": tokenizer_meta["tokenizer_uncertainty"],
            "tokenizer_degraded_reason": tokenizer_meta["degraded_reason"],
            "included_refs": [
                {key: value for key, value in item.items() if key != "content_bytes"}
                for item in included
            ],
            "omitted_refs": omitted,
            "next_expansions": [item["path"] for item in omitted][:10],
            "graph_neighbours": neighbours,
            "must_include_refs": must_include,
        }
        envelope["token_estimate"] = adapter.count(
            json.dumps(envelope, sort_keys=True).encode("utf-8")
        )
        envelope["_content"] = {
            item["path"]: item["content_bytes"].decode("utf-8", "replace")
            for item in included
        }
        return envelope

    # -- expand_context --------------------------------------------------
    def expand_context(
        self,
        refs: list[str],
        *,
        repo_sha: str,
        depth: str = "full",
    ) -> dict[str, Any]:
        fresh = self.freshness(repo_sha)
        if fresh["status"] in {"STALE", "UNAVAILABLE"}:
            return {"status": fresh["status"], "freshness": fresh, "refs": {}}
        manifest = load_manifest(self._state_root, repo_sha)
        snapshot_root = self._snapshot_root(repo_sha)
        blob_by_path = manifest["path_to_blob"]
        payload: dict[str, Any] = {}
        missing: list[str] = []
        for ref in refs:
            if ref in blob_by_path:
                data = _load_snapshot_blob(snapshot_root, blob_by_path[ref])
                payload[ref] = {
                    "kind": "file",
                    "bytes": len(data),
                    "token_estimate": _token_estimate(data),
                    "content": data.decode("utf-8", "replace"),
                }
                continue
            symbol = self._symbol(repo_sha, ref)
            if symbol is not None:
                data = _load_snapshot_blob(snapshot_root, blob_by_path[symbol["path"]])
                payload[ref] = {
                    "kind": "symbol",
                    "path": symbol["path"],
                    "qualified_name": symbol["qualified_name"],
                    "start_byte": symbol["start_byte"],
                    "end_byte": symbol["end_byte"],
                    "source": data[symbol["start_byte"] : symbol["end_byte"]].decode(
                        "utf-8", "replace"
                    ),
                }
                continue
            missing.append(ref)
        return {
            "status": "FRESH" if not missing else "PARTIAL",
            "repo_sha": repo_sha,
            "depth": depth,
            "refs": payload,
            "missing_refs": missing,
            "tokenizer": TOKENIZER,
        }

    # -- internals -------------------------------------------------------
    def _snapshot_root(self, repo_sha: str) -> str:
        return str(Path(self._state_root) / "snapshots" / repo_sha[:16])

    def _connection(self, repo_sha: str) -> sqlite3.Connection:
        return sqlite3.connect(
            artifact_path(self._state_root, repo_sha) / "graph.sqlite"
        )

    def _resolve_directory_refs(
        self, repo_sha: str, refs: list[str]
    ) -> dict[str, list[str]]:
        """Map directory refs to their contained tracked files (bounded)."""
        manifest = load_manifest(self._state_root, repo_sha)
        blob_by_path = manifest["path_to_blob"]
        resolved: dict[str, list[str]] = {}
        for ref in refs:
            if ref in blob_by_path:
                continue
            prefix = ref.rstrip("/") + "/"
            contained = sorted(path for path in blob_by_path if path.startswith(prefix))
            if contained:
                resolved[ref] = contained[:20]
        return resolved

    def _rank(
        self,
        target: Path,
        manifest: dict[str, Any],
        task: str,
        must_include: list[str],
        task_type: str = "generic",
    ) -> list[dict[str, Any]]:
        blob_by_path = manifest["path_to_blob"]
        inventory = {row["path"]: row for row in manifest["inventory"]}
        tokens = [
            token
            for token in re.split(r"[^a-z0-9_.]+", task.lower())
            if len(token) >= 3
        ]
        scored: dict[str, float] = {}
        for ref in must_include:
            if ref in blob_by_path:
                scored[ref] = 1_000.0
            else:
                prefix = ref.rstrip("/") + "/"
                contained = sorted(
                    path for path in blob_by_path if path.startswith(prefix)
                )
                for path in contained[:20]:
                    scored[path] = max(scored.get(path, 0.0), 900.0)
        connection = self._connection(manifest["repo_sha"])
        try:
            for token in tokens:
                like = f"%{token}%"
                rows = connection.execute(
                    """
                    SELECT path, COUNT(*) FROM nodes
                    WHERE name LIKE ? OR qualified_name LIKE ? OR path LIKE ?
                    GROUP BY path
                    """,
                    (like, like, like),
                ).fetchall()
                for path, hits in rows:
                    scored[path] = scored.get(path, 0.0) + 5.0 * hits
        finally:
            connection.close()
        for path in list(scored):
            base = path
            if path.startswith("src/"):
                test_path = f"tests/test_{Path(path).stem}.py"
            else:
                test_path = None
            if test_path and test_path in blob_by_path and test_path not in scored:
                scored[test_path] = scored[base] * 0.4
        for path, row in inventory.items():
            lowered = path.lower()
            weight = 0.0
            for token in tokens:
                if token in lowered:
                    weight += 1.0
            if weight and path not in scored:
                scored[path] = weight
        for path in scored:
            for prefix, boost in TASK_TYPE_BOOSTS.get(task_type, {}).items():
                if path.startswith(prefix):
                    scored[path] += boost
        # OCA-W4B: task-conditioned personalized PageRank as a bounded boost
        # over already-relevant candidates (never an authority by itself).
        connection = self._connection(manifest["repo_sha"])
        try:
            edge_rows = connection.execute("""
                SELECT n1.path, n2.path FROM edges e
                JOIN nodes n1 ON n1.symbol_id = e.source
                JOIN nodes n2 ON n2.symbol_id = e.target
                LIMIT 20000
                """).fetchall()
        finally:
            connection.close()
        path_edges = [(a, b) for a, b in edge_rows if a != b]
        seeds = {
            path: min(scored[path], 100.0)
            for path in sorted(scored, key=lambda item: -scored[item])[:20]
        }
        for path, boost in conditioned_boost({}, seeds, path_edges).items():
            scored[path] = scored.get(path, 0.0) + boost
        ranked = [
            {
                "path": path,
                "blob_sha256": blob_by_path[path],
                "bytes": inventory[path].get("bytes") or 0,
                "score": scored[path],
            }
            for path in sorted(scored, key=lambda item: (-scored[item], item))
        ]
        return ranked

    def _neighbours(self, target: Path, paths: list[str]) -> list[dict[str, Any]]:
        if not paths:
            return []
        connection = sqlite3.connect(target / "graph.sqlite")
        try:
            placeholders = ",".join("?" for _ in paths)
            rows = connection.execute(
                f"""
                SELECT DISTINCT e.relation, e.source, e.target FROM edges e
                JOIN nodes n1 ON n1.symbol_id = e.source
                JOIN nodes n2 ON n2.symbol_id = e.target
                WHERE n1.path IN ({placeholders}) OR n2.path IN ({placeholders})
                LIMIT 64
                """,
                (*paths, *paths),
            ).fetchall()
            return [
                {"relation": row[0], "source": row[1], "target": row[2]} for row in rows
            ]
        finally:
            connection.close()

    def _skeleton(self, target: Path, path: str, data: bytes) -> str:
        """Signature-only structural skeleton (never arbitrary truncation).

        Lines come from exact symbol ranges recorded in the graph; files
        without recorded symbols fall back to a REFERENCE listing instead.
        """
        connection = sqlite3.connect(target / "graph.sqlite")
        try:
            rows = connection.execute(
                "SELECT kind, name, start_byte FROM nodes "
                "WHERE path = ? AND kind IN ('function', 'class', 'heading', "
                "'config_key', 'schema_field', 'workflow_job') "
                "ORDER BY start_byte",
                (path,),
            ).fetchall()
        finally:
            connection.close()
        if not rows:
            return self._reference(target, path)
        lines = ["# skeleton of " + path]
        for _kind, _name, start_byte in rows:
            line_end = data.find(b"\n", start_byte)
            if line_end == -1:
                line_end = min(start_byte + 200, len(data))
            snippet = data[start_byte:line_end].decode("utf-8", "replace").rstrip()
            lines.append(snippet[:200])
        return "\n".join(lines[:80])

    def _reference(self, target: Path, path: str) -> str:
        """Minimal structural reference: path + declared symbol names only."""
        connection = sqlite3.connect(target / "graph.sqlite")
        try:
            rows = connection.execute(
                "SELECT kind, name FROM nodes WHERE path = ? "
                "ORDER BY start_byte LIMIT 40",
                (path,),
            ).fetchall()
        finally:
            connection.close()
        names = ", ".join(kind + ":" + name for kind, name in rows)
        return "reference " + path + ": " + names

    def _symbol(self, repo_sha: str, symbol_id: str) -> dict[str, Any] | None:
        connection = self._connection(repo_sha)
        try:
            row = connection.execute(
                """
                SELECT symbol_id, path, kind, name, qualified_name, start_byte, end_byte
                FROM nodes WHERE symbol_id = ?
                """,
                (symbol_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        keys = (
            "symbol_id",
            "path",
            "kind",
            "name",
            "qualified_name",
            "start_byte",
            "end_byte",
        )
        return dict(zip(keys, row))


def _task_hash(
    task: str,
    repo_sha: str,
    budget_tokens: int,
    dimensions: tuple,
    must_include: tuple = (),
    excluded: tuple = (),
) -> str:
    import hashlib

    payload = (
        f"{repo_sha}|{task}|{budget_tokens}|{','.join(dimensions)}"
        f"|{','.join(must_include)}|{','.join(sorted(excluded))}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key))
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _top_directories(paths: list[str], limit: int = 12) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in paths:
        head = path.split("/")[0]
        counts[head] = counts.get(head, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return dict(ordered[:limit])

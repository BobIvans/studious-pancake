"""Typed graph query operations over the shared backend (OCA-W11B).

Six bounded read-only operations used by the expanded MCP toolset: graph_query,
symbol_search, trace_path, impact_query, history_query, domain_catalog. Every
operation resolves through the single QueryBackend store for one pinned SHA and
reports unresolved/missing state honestly — never invented links.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from .store import artifact_path, load_manifest


def _connect(state_root: str, repo_sha: str) -> sqlite3.Connection:
    return sqlite3.connect(artifact_path(state_root, repo_sha) / "graph.sqlite")


def graph_query(
    state_root: str,
    repo_sha: str,
    *,
    relation: str | None = None,
    path_prefix: str | None = None,
    kind: str | None = None,
    limit: int = 20,
    cursor: int = 0,
) -> dict[str, Any]:
    """Paginated typed node/edge query. Cursor is a deterministic offset."""
    if limit <= 0 or cursor < 0:
        raise ValueError("limit must be positive and cursor non-negative")
    manifest = load_manifest(state_root, repo_sha)
    connection = _connect(state_root, repo_sha)
    try:
        clauses, params = [], []
        if relation:
            clauses.append("e.relation = ?")
            params.append(relation)
        if path_prefix:
            clauses.append("(n1.path LIKE ? OR n2.path LIKE ?)")
            params.extend([path_prefix + "%", path_prefix + "%"])
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = connection.execute(
            f"""
            SELECT e.relation, n1.path, n1.name, n2.path, n2.name, e.resolution
            FROM edges e
            JOIN nodes n1 ON n1.symbol_id = e.source
            JOIN nodes n2 ON n2.symbol_id = e.target
            {where}
            ORDER BY e.relation, n1.path, n2.path
            LIMIT ? OFFSET ?
            """,
            (*params, limit, cursor),
        ).fetchall()
        total = connection.execute(
            f"SELECT COUNT(*) FROM edges e "
            f"JOIN nodes n1 ON n1.symbol_id = e.source "
            f"JOIN nodes n2 ON n2.symbol_id = e.target {where}",
            params,
        ).fetchone()[0]
    finally:
        connection.close()
    next_cursor = cursor + limit if cursor + limit < total else None
    return {
        "edges": [
            {
                "relation": row[0],
                "source": f"{row[1]}::{row[2]}",
                "target": f"{row[3]}::{row[4]}",
                "resolution": row[5],
            }
            for row in rows
        ],
        "total": total,
        "cursor": cursor,
        "next_cursor": next_cursor,
        "graph_generation": manifest["generation"],
    }


def symbol_search(
    state_root: str,
    repo_sha: str,
    query: str,
    *,
    scope_prefix: str | None = None,
    kind: str | None = None,
    mode: str = "substring",
    limit: int = 20,
) -> dict[str, Any]:
    """symbol_search with exact > prefix > substring ranking (fuzzy = casefold)."""
    if mode not in {"exact", "prefix", "substring", "fuzzy"}:
        raise ValueError("mode must be exact|prefix|substring|fuzzy")
    manifest = load_manifest(state_root, repo_sha)
    connection = _connect(state_root, repo_sha)
    try:
        clauses, params = [], []
        if scope_prefix:
            clauses.append("path LIKE ?")
            params.append(scope_prefix + "%")
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if mode == "exact":
            clauses.append("name = ?")
            params.append(query)
        elif mode == "prefix":
            clauses.append("name LIKE ?")
            params.append(query + "%")
        elif mode == "substring":
            clauses.append("name LIKE ?")
            params.append("%" + query + "%")
        else:
            clauses.append("LOWER(name) LIKE ?")
            params.append("%" + query.lower() + "%")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = connection.execute(
            f"""
            SELECT symbol_id, path, kind, name, qualified_name,
                   CASE WHEN name = ? THEN 0
                        WHEN name LIKE ? THEN 1
                        ELSE 2 END AS rank
            FROM nodes {where}
            ORDER BY rank, path, start_byte
            LIMIT ?
            """,
            (query, query + "%", *params, limit),
        ).fetchall()
    finally:
        connection.close()
    return {
        "results": [
            {
                "symbol_id": row[0],
                "path": row[1],
                "kind": row[2],
                "name": row[3],
                "qualified_name": row[4],
                "match_rank": row[5],
            }
            for row in rows
        ],
        "graph_generation": manifest["generation"],
    }


def trace_path(
    state_root: str,
    repo_sha: str,
    start_ref: str,
    *,
    direction: str = "callees",
    max_hops: int = 2,
) -> dict[str, Any]:
    """Bounded evidence-backed path trace; unresolved hops are returned as-is."""
    if direction not in {"callers", "callees"}:
        raise ValueError("direction must be callers|callees")
    manifest = load_manifest(state_root, repo_sha)
    connection = _connect(state_root, repo_sha)
    try:
        frontier = [start_ref]
        hops: list[dict[str, Any]] = []
        seen: set[str] = {start_ref}
        for depth in range(max_hops):
            placeholders = ",".join("?" for _ in frontier)
            join_col = "e.target" if direction == "callers" else "e.source"
            out_col = "e.source" if direction == "callers" else "e.target"
            rows = connection.execute(
                f"""
                SELECT e.relation, {join_col} AS endpoint,
                       {out_col} AS reached, e.resolution, e.provenance
                FROM edges e
                WHERE {join_col} IN ({placeholders})
                LIMIT 200
                """,
                frontier,
            ).fetchall()
            level = []
            next_frontier: list[str] = []
            for relation, endpoint, reached, resolution, provenance in rows:
                symbol = connection.execute(
                    "SELECT path, name, kind FROM nodes WHERE symbol_id = ?",
                    (reached,),
                ).fetchone()
                if symbol is None:
                    # Unresolved endpoint (e.g. external module reference) is
                    # reported as-is, never dropped or invented.
                    level.append(
                        {
                            "depth": depth + 1,
                            "via": relation,
                            "from": endpoint,
                            "reached": reached,
                            "resolution": resolution,
                            "provenance": provenance,
                            "unresolved": True,
                        }
                    )
                    continue
                level.append(
                    {
                        "depth": depth + 1,
                        "via": relation,
                        "from": endpoint,
                        "reached": reached,
                        "path": symbol[0],
                        "name": symbol[1],
                        "kind": symbol[2],
                        "resolution": resolution,
                        "provenance": provenance,
                        "unresolved": False,
                    }
                )
                if symbol[0] not in seen:
                    seen.add(symbol[0])
                    next_frontier.append(reached)
            hops.append({"depth": depth + 1, "edges": level})
            frontier = next_frontier[:10]
    finally:
        connection.close()
    return {
        "start": start_ref,
        "direction": direction,
        "hops": hops,
        "graph_generation": manifest["generation"],
    }


def impact_query(
    state_root: str,
    repo_sha: str,
    target_ref: str,
) -> dict[str, Any]:
    """Static change impact: reverse callers + tests. Never labelled runtime."""
    manifest = load_manifest(state_root, repo_sha)
    connection = _connect(state_root, repo_sha)
    try:
        symbol = connection.execute(
            "SELECT symbol_id, path FROM nodes WHERE symbol_id = ? OR path = ?",
            (target_ref, target_ref),
        ).fetchone()
        if symbol is None:
            return {
                "status": "UNKNOWN",
                "reason": "TARGET_NOT_IN_GRAPH",
                "graph_generation": manifest["generation"],
            }
        symbol_id, path = symbol
        callers = connection.execute(
            """
            SELECT DISTINCT n1.path FROM edges e
            JOIN nodes n1 ON n1.symbol_id = e.source
            JOIN nodes n2 ON n2.symbol_id = e.target
            WHERE (e.target = ? OR n2.path = ?) AND e.relation IN
                  ('IMPORTS', 'CALLS_RESOLVED', 'CALLS_STATIC')
            ORDER BY n1.path LIMIT 40
            """,
            (symbol_id, path),
        ).fetchall()
        tests = connection.execute(
            """
            SELECT DISTINCT n2.path FROM edges e
            JOIN nodes n1 ON n1.symbol_id = e.source
            JOIN nodes n2 ON n2.symbol_id = e.target
            WHERE (e.source = ? OR n1.path = ?) AND e.relation = 'TESTED_BY'
            ORDER BY n2.path LIMIT 40
            """,
            (symbol_id, path),
        ).fetchall()
    finally:
        connection.close()
    return {
        "target": target_ref,
        "static_callers": [row[0] for row in callers],
        "tests": [row[0] for row in tests],
        "labelling": "STATIC_ONLY",
        "runtime_impact": "UNAVAILABLE until OCA-W10 producers are wired",
        "graph_generation": manifest["generation"],
    }


def history_query(
    repo_root: str,
    repo_sha: str,
    path: str,
    *,
    limit: int = 10,
    cursor: int = 0,
) -> dict[str, Any]:
    """Git history for one path (local read-only). PR/issue feed is
    permission-gated and reported UNAVAILABLE rather than guessed."""
    if limit <= 0 or cursor < 0:
        raise ValueError("limit must be positive and cursor non-negative")
    log = subprocess.check_output(
        [
            "git",
            "-C",
            repo_root,
            "log",
            f"-{limit + cursor}",
            "--skip",
            str(cursor),
            "--format=%H%x00%ad%x00%s",
            "--date=short",
            repo_sha,
            "--",
            path,
        ]
    ).decode("utf-8", "replace")
    commits = []
    for line in log.splitlines():
        if not line:
            continue
        commit_hash, date, subject = line.split("\x00", 2)
        commits.append(
            {"sha": commit_hash[:12], "date": date, "subject": subject[:120]}
        )
    next_cursor = cursor + limit if len(commits) == limit else None
    return {
        "path": path,
        "commits": commits,
        "cursor": cursor,
        "next_cursor": next_cursor,
        "prs_issues_feed": "UNAVAILABLE (permission-bounded separate feed; not wired)",
        "runtime_history": "UNAVAILABLE until OCA-W10/W2 supply evidence",
    }


def domain_catalog(
    state_root: str,
    repo_sha: str,
    kind: str,
    *,
    limit: int = 20,
    cursor: int = 0,
    repo_root: str | None = None,
) -> dict[str, Any]:
    """Bounded catalogue rows for providers/lenders/schemas/strategies.

    Providers come from the canonical catalog resource; schemas/strategies come
    from graph nodes. W13/W14 registry joins land via the W4C chain merge and
    are reported as unavailable until then.
    """
    manifest = load_manifest(state_root, repo_sha)
    rows: list[dict[str, Any]] = []
    unavailable_reason: str | None = None
    if limit <= 0 or cursor < 0:
        raise ValueError("limit must be positive and cursor non-negative")
    if kind in {"provider", "lender"}:
        base = Path(repo_root) if repo_root else Path.cwd()
        catalog_path = base / "src/resources/market_source_catalog.json"
        if catalog_path.exists():
            payload = json.loads(catalog_path.read_text(encoding="utf-8"))
            family = "lending-tool" if kind == "lender" else None
            for source in sorted(
                payload.get("sources", []), key=lambda item: item["source_id"]
            ):
                if family is None or source.get("family") == family:
                    rows.append(
                        {
                            "id": source["source_id"],
                            "label": source.get("label"),
                            "family": source.get("family"),
                            "access": source.get("access"),
                            "enabled": bool(source.get("enabled", False)),
                            "evidence": "CANONICAL_CATALOG_ROW (not an active connector)",
                        }
                    )
            total = len(rows)
            rows = rows[cursor : cursor + limit]
            next_cursor = cursor + limit if cursor + limit < total else None
        else:
            unavailable_reason = "CATALOG_RESOURCE_ABSENT"
    elif kind == "schema":
        connection = _connect(state_root, repo_sha)
        try:
            graph_rows = connection.execute(
                "SELECT path, name, kind FROM nodes WHERE kind IN "
                "('schema_field', 'config_key') ORDER BY path, name LIMIT ? OFFSET ?",
                (limit, cursor),
            ).fetchall()
        finally:
            connection.close()
        rows = [
            {
                "path": row[0],
                "name": row[1],
                "kind": row[2],
                "evidence": "STRUCTURE_INDEXED",
            }
            for row in graph_rows
        ]
        next_cursor = cursor + limit if len(rows) == limit else None
    elif kind == "strategy":
        unavailable_reason = "STRATEGY_CATALOGUE_PENDING_OCA_W4C (registry joins via W13/W14/W15 chain merge)"
    else:
        raise ValueError("kind must be provider|lender|schema|strategy")
    return {
        "kind": kind,
        "rows": rows,
        "cursor": cursor,
        "next_cursor": None if unavailable_reason else next_cursor,
        "unavailable_reason": unavailable_reason,
        "graph_generation": manifest["generation"],
    }

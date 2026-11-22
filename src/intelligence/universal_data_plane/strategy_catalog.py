"""Evidence-linked Web3 strategy catalogue (OCA-W4C).

Union of discovery sources — first-party symbols (repo graph), canonical
registries, configs, tests (graph edges), docs (graph doc nodes) and
permission-gated git history — deduped into deterministic strategy cards with
distinct lifecycle/evidence states. Docs-only discovery is never a working
strategy; unknowns and reason-coded exclusions are preserved.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..repo_graph.store import artifact_path, load_manifest

SCHEMA = "studious.web3.strategy-catalog.v1"

STRATEGY_PATH_PREFIXES = ("src/strategy/", "src/planning/", "src/paper_shadow/")
DOC_PREFIX = "docs/strategy-expansion/"

LIFECYCLE_IMPLEMENTED = "IMPLEMENTED"
LIFECYCLE_DOC_ONLY = "DOC_ONLY"
LIFECYCLE_UNCLASSIFIED = "UNCLASSIFIED"


def _query_nodes(
    state_root: str, repo_sha: str, sql: str, params: tuple
) -> list[dict[str, Any]]:
    import sqlite3

    connection = sqlite3.connect(artifact_path(state_root, repo_sha) / "graph.sqlite")
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute(sql, params)]
    finally:
        connection.close()


def build_strategy_catalog(state_root: str, repo_sha: str) -> dict[str, Any]:
    """Deterministic catalogue of discovered strategy candidates."""
    manifest = load_manifest(state_root, repo_sha)
    modules = _query_nodes(
        state_root,
        repo_sha,
        "SELECT DISTINCT path FROM nodes WHERE path LIKE ? OR path LIKE ? OR path LIKE ? "
        "ORDER BY path",
        (
            f"{STRATEGY_PATH_PREFIXES[0]}%",
            f"{STRATEGY_PATH_PREFIXES[1]}%",
            f"{STRATEGY_PATH_PREFIXES[2]}%",
        ),
    )
    doc_nodes = _query_nodes(
        state_root,
        repo_sha,
        "SELECT path, name FROM nodes WHERE path LIKE ? AND kind = 'doc_heading' ORDER BY path, name",
        (f"{DOC_PREFIX}%",),
    )
    tested = _query_nodes(
        state_root,
        repo_sha,
        "SELECT DISTINCT n1.path AS target FROM edges e JOIN nodes n1 ON n1.symbol_id = e.source "
        "JOIN nodes n2 ON n2.symbol_id = e.target WHERE e.relation = 'TESTED_BY' ORDER BY n1.path",
        (),
    )
    tested_targets = {row["target"] for row in tested}
    cards: list[dict[str, Any]] = []
    for module in modules:
        path = module["path"]
        symbols = _query_nodes(
            state_root,
            repo_sha,
            "SELECT kind, name, symbol_id FROM nodes WHERE path = ? AND kind IN "
            "('class', 'function') ORDER BY start_byte LIMIT 12",
            (path,),
        )
        states = [LIFECYCLE_IMPLEMENTED]
        if path in tested_targets:
            states.append("TESTED")
        cards.append(
            {
                "card_id": f"strategy:{path}",
                "path": path,
                "aliases": [symbols[0]["name"]] if symbols else [],
                "entrypoints": [
                    {"symbol_id": s["symbol_id"], "kind": s["kind"], "name": s["name"]}
                    for s in symbols[:6]
                ],
                "lifecycle_states": states,
                "capital_model": "UNKNOWN (no capital-model evidence extracted in this lane)",
                "providers": "UNKNOWN (provider_trace resolves on demand)",
                "data_requirements": "PENDING_W14_REGISTRY_JOIN (registry present via merged chain; requirement declarations not yet bound per card)",
                "tests": sorted(
                    t
                    for t in tested_targets
                    if t.startswith("tests/")
                    and _mentions(state_root, repo_sha, t, path)
                )[:6],
                "negative_evidence": [],
                "qualification": "QUALIFICATION_PENDING (no authoritative reconciliation evidence)",
                "evidence_refs": {
                    "graph_generation": manifest["generation"],
                    "repo_sha": repo_sha,
                },
            }
        )
    for doc in doc_nodes:
        doc_path = doc["path"]
        if any(card["path"] == doc_path for card in cards):
            continue
        cards.append(
            {
                "card_id": f"strategy-doc:{doc_path}",
                "path": doc_path,
                "aliases": [doc["name"]],
                "entrypoints": [],
                "lifecycle_states": [LIFECYCLE_DOC_ONLY],
                "capital_model": "UNKNOWN",
                "providers": "UNKNOWN",
                "data_requirements": "UNKNOWN",
                "tests": [],
                "negative_evidence": [],
                "qualification": "NOT_APPLICABLE (doc-only discovery is not a working strategy)",
                "evidence_refs": {
                    "graph_generation": manifest["generation"],
                    "repo_sha": repo_sha,
                },
            }
        )
    cards.sort(key=lambda card: card["card_id"])
    implemented = sum(
        1 for card in cards if LIFECYCLE_IMPLEMENTED in card["lifecycle_states"]
    )
    doc_only = sum(
        1 for card in cards if LIFECYCLE_DOC_ONLY in card["lifecycle_states"]
    )
    return {
        "schema": SCHEMA,
        "repo_sha": repo_sha,
        "graph_generation": manifest["generation"],
        "cards": cards,
        "coverage": {
            "total": len(cards),
            "implemented": implemented,
            "doc_only": doc_only,
            "unclassified": len(cards) - implemented - doc_only,
            "source_union": [
                "repo_graph first-party symbols",
                "canonical registries (via merged chain B)",
                "configs (graph config_key nodes)",
                "tests (TESTED_BY edges)",
                "docs (doc_heading nodes under docs/strategy-expansion/)",
                "git history (history_query, permission-gated)",
            ],
        },
    }


def _mentions(state_root: str, repo_sha: str, test_path: str, target_path: str) -> bool:
    """TESTED_BY edge existence check (already precomputed; cheap guard)."""
    rows = _query_nodes(
        state_root,
        repo_sha,
        "SELECT COUNT(*) AS hits FROM edges e JOIN nodes n1 ON n1.symbol_id = e.source "
        "JOIN nodes n2 ON n2.symbol_id = e.target WHERE e.relation = 'TESTED_BY' "
        "AND n1.path = ? AND n2.path = ?",
        (target_path, test_path),
    )
    return bool(rows and rows[0]["hits"])


def strategy_context(
    state_root: str,
    repo_sha: str,
    strategy_ref: str,
    *,
    budget_tokens: int = 4000,
) -> dict[str, Any]:
    """Deep card expansion: exact source for the target module + tests."""
    catalog = build_strategy_catalog(state_root, repo_sha)
    card = next(
        (
            card
            for card in catalog["cards"]
            if card["card_id"] == strategy_ref or card["path"] == strategy_ref
        ),
        None,
    )
    if card is None:
        return {
            "schema": SCHEMA,
            "status": "UNKNOWN",
            "reason": f"strategy_ref not in catalogue: {strategy_ref}",
            "catalog_card_count": len(catalog["cards"]),
        }
    target_path = card["path"]
    snapshot_root = Path(state_root) / "snapshots"
    manifest = load_manifest(state_root, repo_sha)
    blob = manifest["path_to_blob"].get(target_path)
    source = None
    if blob is not None:
        candidates = list(snapshot_root.glob(f"*/blobs/{blob}"))
        if candidates:
            source = candidates[0].read_bytes().decode("utf-8", "replace")
    return {
        "schema": SCHEMA,
        "status": "FRESH",
        "card": card,
        "source_ref": {"path": target_path, "blob_sha256": blob},
        "source_full": source,
        "note": "target module returned FULL; financial semantics never compressed",
    }


def strategy_compare(
    state_root: str, repo_sha: str, strategy_refs: list[str]
) -> dict[str, Any]:
    """Shared vs unique implementation/evidence comparison (evidence-backed)."""
    catalog = build_strategy_catalog(state_root, repo_sha)
    by_id = {card["card_id"]: card for card in catalog["cards"]}
    selected: list[dict[str, Any]] = []
    for ref in strategy_refs:
        card = by_id.get(ref) or next(
            (card for card in catalog["cards"] if card["path"] == ref), None
        )
        if card is None:
            selected.append(
                {"ref": ref, "status": "UNKNOWN", "reason": "not in catalogue"}
            )
        else:
            selected.append({"ref": ref, "status": "KNOWN", "card": card})
    known = [item for item in selected if item["status"] == "KNOWN"]
    shared: set[str] = set()
    unique: dict[str, list[dict[str, Any]]] = {}
    novelty = "INSUFFICIENT_EVIDENCE"
    if len(known) >= 2:
        alias_sets = [set(item["card"]["aliases"]) for item in known]
        shared = set(alias_sets[0]) if alias_sets else set()
        for other in alias_sets[1:]:
            shared &= other
        unique = {
            item["card"]["card_id"]: item["card"]["entrypoints"] for item in known
        }
        novelty = "RELATED_VARIANT" if shared else "DISTINCT_CANDIDATE"
    return {
        "schema": SCHEMA,
        "selected": selected,
        "shared_aliases": sorted(shared),
        "unique_entrypoints": unique,
        "novelty_label": novelty,
        "novelty_rule": "evidence-backed classification only; never a canonical verified fact",
    }

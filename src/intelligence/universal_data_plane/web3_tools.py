"""Two compact Web3 MCP tool operations over the shared backend (OCA-W4C).

``strategy_research`` (catalog/context/compare) and ``web3_data_trace``
(provider_trace/flash_capital_trace/operation_trace/performance_diagnostics).
All seven operations delegate to the single QueryBackend/owners; no third MCP
schema and no duplicate canonical stores.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..repo_graph.query_ops import domain_catalog, trace_path
from ..repo_graph.store import load_manifest
from .strategy_catalog import build_strategy_catalog, strategy_compare, strategy_context

CATALOG_RESOURCE = "src/resources/market_source_catalog.json"
PROVIDER_RESOURCE = (
    "docs/roadmap/r01-r02-live-capital-readers-2026-10-08/PROVIDER_CATALOG.json"
)


def _repo_file(repo_root: str | None, relative: str) -> Path:
    base = Path(repo_root) if repo_root else Path.cwd()
    return base / relative


def strategy_research(
    state_root: str,
    repo_sha: str,
    action: str,
    *,
    query: str | None = None,
    strategy_refs: list[str] | None = None,
    budget_tokens: int = 4000,
) -> dict[str, Any]:
    if action == "catalog":
        catalog = build_strategy_catalog(state_root, repo_sha)
        if query:
            lowered = query.lower()
            catalog["cards"] = [
                card
                for card in catalog["cards"]
                if lowered in json.dumps(card, sort_keys=True).lower()
            ]
            catalog["coverage"]["total"] = len(catalog["cards"])
        return catalog
    if action == "context":
        if not strategy_refs:
            raise ValueError("strategy_refs required for context")
        return strategy_context(
            state_root, repo_sha, strategy_refs[0], budget_tokens=budget_tokens
        )
    if action == "compare":
        if not strategy_refs or len(strategy_refs) < 2:
            raise ValueError("at least two strategy_refs required for compare")
        return strategy_compare(state_root, repo_sha, strategy_refs)
    raise ValueError("action must be catalog|context|compare")


def web3_data_trace(
    state_root: str,
    repo_sha: str,
    action: str,
    *,
    provider_ref: str | None = None,
    lender_ref: str | None = None,
    strategy_ref: str | None = None,
    target_ref: str | None = None,
    static_callers: list[str] | None = None,
    repo_root: str | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(state_root, repo_sha)
    if action == "provider_trace":
        rows = []
        catalog_file = _repo_file(repo_root, CATALOG_RESOURCE)
        if catalog_file.exists():
            payload = json.loads(catalog_file.read_text(encoding="utf-8"))
            for source in payload.get("sources", []):
                if provider_ref is None or source["source_id"] == provider_ref:
                    rows.append(
                        {
                            "provider_id": source["source_id"],
                            "declared": True,
                            "configured": False,
                            "tested": False,
                            "captured": False,
                            "runtime_observed": False,
                            "access": source.get("access"),
                            "evidence": "CANONICAL_CATALOG_ROW",
                        }
                    )
        return {
            "schema": "studious.web3.provider-trace.v1",
            "rows": rows[:20],
            "unavailable_reason": (
                None
                if rows
                else "CATALOG_RESOURCE_ABSENT (explicit; unknown is not zero)"
            ),
            "state_rules": "declared/configured/tested/captured/runtime-observed are distinct; a catalog row never implies live capability",
            "graph_generation": manifest["generation"],
        }
    if action == "flash_capital_trace":
        rows = []
        resource = _repo_file(repo_root, PROVIDER_RESOURCE)
        if resource.exists():
            payload = json.loads(resource.read_text(encoding="utf-8"))
            for entry in payload.get("entries", []):
                if lender_ref is None or entry.get("provider_id") == lender_ref:
                    rows.append(
                        {
                            "lender_id": entry.get("provider_id"),
                            "enabled": bool(entry.get("enabled", False)),
                            "effective_capacity": "UNKNOWN (advertised liquidity is not flash-borrow capacity)",
                            "fee_repayment_semantics": "UNKNOWN without pinned contract evidence",
                            "evidence": payload.get("status"),
                        }
                    )
        return {
            "schema": "studious.web3.flash-capital-trace.v1",
            "rows": rows[:20],
            "state_rules": "market liquidity and evidenced borrow capacity are separate; adapter presence never implies executable lender support",
            "graph_generation": manifest["generation"],
        }
    if action == "operation_trace":
        from ..operation_context import build_operation_episodes

        if repo_root is None:
            return {
                "schema": "studious.web3.operation-trace.v1",
                "status": "UNAVAILABLE",
                "missing": ["canonical event store not reachable without repo_root"],
            }
        store = _open_store(Path(repo_root))
        if store is None:
            return {
                "schema": "studious.web3.operation-trace.v1",
                "status": "UNAVAILABLE",
                "missing": ["no durable event store present in this checkout"],
            }
        projection = build_operation_episodes(store)
        return {
            "schema": "studious.web3.operation-trace.v1",
            "status": "PARTIAL",
            "episodes": projection["episodes"],
            "coverage": projection["coverage"],
            "missing_join": "runtime callsite linkage lands with W15/W20 temporal joins per route",
            "graph_generation": manifest["generation"],
        }
    if action == "performance_diagnostics":
        from ..performance_diagnostics import build_diagnostics

        if repo_root is None:
            return {
                "schema": "studious.web3.performance-diagnostics.v1",
                "status": "UNAVAILABLE",
                "missing": ["event store requires repo_root"],
            }
        store = _open_store(Path(repo_root))
        if store is None:
            return {
                "schema": "studious.web3.performance-diagnostics.v1",
                "status": "UNAVAILABLE",
                "missing": ["no durable event store present"],
            }
        result = build_diagnostics(
            store=store,
            repo_sha=repo_sha,
            config_checksum="unknown",
            strategy_ref=strategy_ref or "unspecified",
            static_callers=static_callers,
        )
        result["transport"] = (
            "web3_data_trace.performance_diagnostics (7th operation; no third MCP schema)"
        )
        return result
    raise ValueError(
        "action must be provider_trace|flash_capital_trace|operation_trace|performance_diagnostics"
    )


def _open_store(repo_root: Path):
    """Open the canonical event store if one exists (read-only diagnostics)."""
    candidates = list(Path(repo_root).glob("**/events.sqlite"))
    if not candidates:
        return None
    from ...observability.store import ObservabilityStore

    try:
        return ObservabilityStore(str(candidates[0]))
    except Exception:  # noqa: BLE001 - explicit UNAVAILABLE over fabrication
        return None


def bounded_domain_catalog(
    state_root: str, repo_sha: str, kind: str, *, limit: int = 20, cursor: int = 0
) -> dict[str, Any]:
    return domain_catalog(state_root, repo_sha, kind, limit=limit, cursor=cursor)


def bounded_trace_path(
    state_root: str, repo_sha: str, start_ref: str, **kwargs: Any
) -> dict[str, Any]:
    return trace_path(state_root, repo_sha, start_ref, **kwargs)

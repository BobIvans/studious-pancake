"""Deterministic edge extraction with explicit resolution statuses.

Static facts only: CALLS_RESOLVED requires structural evidence (same-module
symbol or exact import path). Same-name guesses stay CALLS_STATIC with
resolution AMBIGUOUS and are never promoted.
"""

from __future__ import annotations

from typing import Any

from .schema import (
    EDGE_DEFINES,
    EDGE_IMPORTS,
    EDGE_CALLS_RESOLVED,
    EDGE_CALLS_STATIC,
    EDGE_TESTED_BY,
    PROVENANCE_STATIC_EXTRACTED,
)
from .symbols import module_name


def _module_graph(modules: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Path -> imported repo-internal paths (mirrors repo_source semantics)."""
    path_by_module = {}
    for path, analysis in modules.items():
        path_by_module[analysis["module"]] = path
    graph: dict[str, list[str]] = {}
    for path, analysis in modules.items():
        dependencies: set[str] = set()
        for name in analysis["imports"]:
            while name:
                if name in path_by_module:
                    dependencies.add(path_by_module[name])
                    break
                name = name.rpartition(".")[0]
        graph[path] = sorted(dependencies)
    return graph


def build_edges(modules: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Build deterministic edge records across parsed modules.

    ``modules`` maps path -> parse_python_module() result. Edge identity is the
    (relation, source, target) triple; targets are stable symbol IDs where the
    relation is symbol-level, module-level paths otherwise.
    """
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(
        relation: str,
        source: str,
        target: str,
        *,
        resolution: str | None = None,
        lineno: int | None = None,
        target_expr: str | None = None,
    ) -> None:
        key = (relation, source, target)
        if key in seen:
            return
        seen.add(key)
        record: dict[str, Any] = {
            "relation": relation,
            "source": source,
            "target": target,
            "provenance": PROVENANCE_STATIC_EXTRACTED,
        }
        if relation == EDGE_DEFINES:
            record["resolution"] = "RESOLVED"
        elif relation == EDGE_IMPORTS:
            record["resolution"] = "RESOLVED"
        elif relation in {EDGE_CALLS_RESOLVED, EDGE_CALLS_STATIC}:
            record["resolution"] = resolution or "UNRESOLVED"
            record["lineno"] = lineno
            if target_expr is not None:
                record["target_expr"] = target_expr
        edges.append(record)

    graph = _module_graph(modules)

    # Module-name -> module symbol-id map for cross-module call resolution.
    module_symbol_ids: dict[str, str] = {}
    for path, analysis in modules.items():
        module_symbol_ids[analysis["module"]] = analysis["symbols"][0]["symbol_id"]

    for path in sorted(modules):
        analysis = modules[path]
        module_sym = analysis["symbols"][0]["symbol_id"]
        # DEFINES: module -> contained symbols (excluding the module itself).
        for symbol in analysis["symbols"][1:]:
            add(EDGE_DEFINES, module_sym, symbol["symbol_id"])
        # IMPORTS: module -> module (repo-internal import graph).
        for target_path in graph[path]:
            add(
                EDGE_IMPORTS,
                module_sym,
                modules[target_path]["symbols"][0]["symbol_id"],
            )
        # Calls: resolve against same-module symbols and imported module
        # roots. Every edge endpoint is a node ID; unresolved call targets are
        # attached to the caller's module node with target_expr evidence so
        # the dangling-edge check stays meaningful.
        known_last_names = {
            symbol["name"]: symbol for symbol in analysis["symbols"][1:]
        }
        imported_roots = set(analysis["imports"])
        for call in analysis["calls"]:
            target_expr = call["target_expr"]
            caller = call["caller_qualified"] or module_sym
            caller_id = (
                f"py::{path}::{caller}" if call["caller_qualified"] else module_sym
            )
            root = target_expr.split(".")[0]
            if root in known_last_names and "." not in target_expr:
                add(
                    EDGE_CALLS_RESOLVED,
                    caller_id,
                    known_last_names[root]["symbol_id"],
                    resolution="RESOLVED",
                    lineno=call["lineno"],
                )
                continue
            # Longest imported module-name match wins (dotted import paths).
            matched_module = ""
            for candidate in imported_roots:
                if target_expr == candidate or target_expr.startswith(candidate + "."):
                    if len(candidate) > len(matched_module):
                        matched_module = candidate
            if matched_module:
                target_id = module_symbol_ids.get(
                    module_name(f"{matched_module.replace('.', '/')}.py")
                )
                if target_id is not None:
                    add(
                        EDGE_CALLS_RESOLVED,
                        caller_id,
                        target_id,
                        resolution="RESOLVED",
                        lineno=call["lineno"],
                    )
                    continue
            add(
                EDGE_CALLS_STATIC,
                caller_id,
                module_sym,
                resolution="UNRESOLVED",
                lineno=call["lineno"],
                target_expr=target_expr,
            )

    # TESTED_BY: test module imports target module (structural, precise).
    for path in sorted(modules):
        if not path.startswith("tests/"):
            continue
        for target_path in graph[path]:
            if target_path.startswith("src/"):
                add(
                    EDGE_TESTED_BY,
                    modules[target_path]["symbols"][0]["symbol_id"],
                    modules[path]["symbols"][0]["symbol_id"],
                )

    edges.sort(key=lambda item: (item["relation"], item["source"], item["target"]))
    return edges

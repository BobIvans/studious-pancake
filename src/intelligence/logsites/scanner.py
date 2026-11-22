"""Stable, rename-safe callsite IDs for log/event emission sites (OCA-W3).

Static AST scanner; no LLM anywhere in the hot path (contract requirement).
Callsite identity is positional-ordinal within the enclosing scope, so IDs
survive line shifts; module renames are explicit records derived from blob
identity, never silent rewrites. Caller IDs reuse the OCA-W0B stable symbol
convention (``py::<path>::<qualified>``) — no second identity namespace.
"""

from __future__ import annotations

import ast
from typing import Any

MANIFEST_SCHEMA = "studious.logsite.manifest.v1"

# Canonical producer owners on the audited main (OCA-W0 trace, PR #680):
# make_event has zero production callsites; mapping records the owner so a
# wired producer (OCA-W10) joins by ID, not by name re-guessing.
PRODUCER_MAPPING = {
    "EventEnvelope": "src/observability/events.py",
    "make_event": "src/observability/events.py",
    "ObservabilityStore.append": "src/observability/store.py",
}

# Emission-target patterns considered RESOLVED producer sites. Anything else
# stays NEEDS_REVIEW (ambiguity is never silently promoted).
RESOLVED_TARGET_ROOTS = {"logging", "logger", "log", "_log", "print"}
RESOLVED_EMITTERS = {"make_event", "emit_event", "EventEnvelope"}
# Candidate emitter leaf names: dynamic/indirect dispatch through these names
# is recorded as NEEDS_REVIEW instead of skipped, so ambiguity is explicit.
EMITTER_NAME_WATCHLIST = {
    "log",
    "info",
    "debug",
    "warning",
    "warn",
    "error",
    "critical",
    "exception",
    "emit",
    "emit_event",
    "make_event",
    "trace",
}


def _qualified_stack(node: ast.AST) -> list[str]:
    parts: list[str] = []
    while node is not None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            parts.append(node.name)
        elif isinstance(node, ast.Module):
            break
        try:
            node = node.parent  # type: ignore[attr-defined]
        except AttributeError:
            break
    return list(reversed(parts))


class _CallsiteVisitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self._path = path
        self._stack: list[str] = []
        self.sites: list[dict[str, Any]] = []
        self._ordinals: dict[tuple[str, str, str], int] = {}

    def _caller_qualified(self) -> str:
        return ".".join(self._stack) if self._stack else ""

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        target = ast.unparse(node.func)
        root = target.split(".")[0]
        leaf = target.split(".")[-1]
        caller = self._caller_qualified()
        if leaf in RESOLVED_EMITTERS or root in RESOLVED_TARGET_ROOTS:
            resolution = "RESOLVED"
        elif leaf in EMITTER_NAME_WATCHLIST:
            # Dynamic dispatch, re-exports, indirection: explicit review state.
            resolution = "NEEDS_REVIEW"
        else:
            # Not an emission site; not part of this manifest.
            self.generic_visit(node)
            return
        key = (self._path, caller, target)
        ordinal = self._ordinals.get(key, 0)
        self._ordinals[key] = ordinal + 1
        self.sites.append(
            {
                "callsite_id": f"cs:{self._path}::{caller}:{target}:{ordinal}",
                "path": self._path,
                "caller_symbol_id": (
                    f"py::{self._path}::{caller}" if caller else f"py::{self._path}"
                ),
                "target_expr": target,
                "ordinal": ordinal,
                "lineno": node.lineno,
                "resolution": resolution,
            }
        )
        self.generic_visit(node)


def scan_module(path: str, data: bytes) -> dict[str, Any]:
    """Scan one Python module for emission callsites (deterministic)."""
    tree = ast.parse(data, filename=path)
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node  # type: ignore[attr-defined]
    visitor = _CallsiteVisitor(path)
    visitor.visit(tree)
    sites = sorted(
        visitor.sites,
        key=lambda item: (
            item["path"],
            item["caller_symbol_id"],
            item["target_expr"],
            item["ordinal"],
        ),
    )
    return {
        "path": path,
        "callsites": sites,
        "resolved_count": sum(1 for site in sites if site["resolution"] == "RESOLVED"),
        "needs_review_count": sum(
            1 for site in sites if site["resolution"] == "NEEDS_REVIEW"
        ),
    }


def build_manifest(
    modules: dict[str, bytes],
    *,
    blob_by_path: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the callsite manifest from path->bytes (deterministic output)."""
    entries: list[dict[str, Any]] = []
    for path in sorted(modules):
        scanned = scan_module(path, modules[path])
        for site in scanned["callsites"]:
            if blob_by_path is not None:
                site["blob_sha256"] = blob_by_path.get(path)
            entries.append(site)
    return {
        "schema": MANIFEST_SCHEMA,
        "entries": entries,
        "modules_scanned": len(modules),
        "resolved": sum(1 for entry in entries if entry["resolution"] == "RESOLVED"),
        "needs_review": sum(
            1 for entry in entries if entry["resolution"] == "NEEDS_REVIEW"
        ),
        "producer_mapping": dict(sorted(PRODUCER_MAPPING.items())),
    }

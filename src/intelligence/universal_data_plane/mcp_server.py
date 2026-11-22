"""Allowlisted read-only MCP server (stdlib JSON-RPC over stdio).

Tool surface is exactly: ``task_context``, ``expand_context``, ``repo_overview``.
No shell, edit, delete, admin, signer, sender, provider-enablement, or LIVE
capability is exposed (LLM-free contract 1.10 / universal API contract §7).

Protocol: JSON-RPC 2.0, one message per line. Methods: ``initialize``,
``tools/list``, ``tools/call``. All retrieval delegates to the universal data
plane facade — the same backend as the CLI and portable export.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable

from ..repo_graph import query_ops
from . import SCHEMA_ID
from .facade import UniversalDataPlane

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "studious-repo-intel"
SERVER_VERSION = "1.0.0"

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "task_context",
        "description": (
            "Bounded, SHA-bound, evidence-backed context pack for a task. "
            "Read-only; returns included/omitted refs, provenance and "
            "expansion cursors."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "repo_sha": {"type": "string"},
                "budget_tokens": {"type": "integer"},
                "must_include_refs": {"type": "array", "items": {"type": "string"}},
                "exclude_refs": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["task", "repo_sha"],
        },
    },
    {
        "name": "expand_context",
        "description": (
            "Exact payloads for stable refs (paths or py:: symbol IDs) at a "
            "pinned repo SHA. Read-only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "refs": {"type": "array", "items": {"type": "string"}},
                "repo_sha": {"type": "string"},
                "depth": {"type": "string"},
            },
            "required": ["refs", "repo_sha"],
        },
    },
    {
        "name": "graph_query",
        "description": "Paginated typed edge query over the pinned-SHA graph.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_sha": {"type": "string"},
                "relation": {"type": "string"},
                "path_prefix": {"type": "string"},
                "limit": {"type": "integer"},
                "cursor": {"type": "integer"},
            },
            "required": ["repo_sha"],
        },
    },
    {
        "name": "symbol_search",
        "description": "Exact/prefix/substring/fuzzy symbol search with scoping; exact ranks first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_sha": {"type": "string"},
                "query": {"type": "string"},
                "mode": {"type": "string"},
                "scope_prefix": {"type": "string"},
                "kind": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["repo_sha", "query"],
        },
    },
    {
        "name": "trace_path",
        "description": "Bounded evidence-backed path trace; unresolved hops returned as-is.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_sha": {"type": "string"},
                "start_ref": {"type": "string"},
                "direction": {"type": "string"},
                "max_hops": {"type": "integer"},
            },
            "required": ["repo_sha", "start_ref"],
        },
    },
    {
        "name": "impact_query",
        "description": "Static change impact: reverse callers + tests (STATIC_ONLY labelling).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_sha": {"type": "string"},
                "target_ref": {"type": "string"},
            },
            "required": ["repo_sha", "target_ref"],
        },
    },
    {
        "name": "history_query",
        "description": "Local git history for a path with cursor; PR/issue feed is permission-gated.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_sha": {"type": "string"},
                "path": {"type": "string"},
                "limit": {"type": "integer"},
                "cursor": {"type": "integer"},
            },
            "required": ["repo_sha", "path"],
        },
    },
    {
        "name": "domain_catalog",
        "description": "Bounded provider/lender/schema/strategy catalogue rows with explicit unavailability.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_sha": {"type": "string"},
                "kind": {"type": "string"},
                "limit": {"type": "integer"},
                "cursor": {"type": "integer"},
            },
            "required": ["repo_sha", "kind"],
        },
    },
    {
        "name": "repo_overview",
        "description": "T0 SHA-bound repo card plus data-plane store inventory.",
        "inputSchema": {
            "type": "object",
            "properties": {"repo_sha": {"type": "string"}},
            "required": ["repo_sha"],
        },
    },
]


class McpServer:
    def __init__(self, plane: UniversalDataPlane) -> None:
        self._plane = plane
        self._tools: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "task_context": self._tool_task_context,
            "expand_context": self._tool_expand_context,
            "repo_overview": self._tool_repo_overview,
            "graph_query": self._tool_graph_query,
            "symbol_search": self._tool_symbol_search,
            "trace_path": self._tool_trace_path,
            "impact_query": self._tool_impact_query,
            "history_query": self._tool_history_query,
            "domain_catalog": self._tool_domain_catalog,
        }

    # -- tool implementations (thin, read-only) --------------------------
    def _tool_task_context(self, args: dict[str, Any]) -> dict[str, Any]:
        envelope = self._plane.task_context(
            args["task"],
            repo_sha=args["repo_sha"],
            budget_tokens=args.get("budget_tokens"),
            must_include_refs=args.get("must_include_refs"),
            exclude_refs=args.get("exclude_refs"),
        )
        envelope.pop("_content", None)
        return envelope

    def _tool_expand_context(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._plane.expand_context(
            list(args["refs"]),
            repo_sha=args["repo_sha"],
            depth=args.get("depth", "full"),
        )

    def _tool_graph_query(self, args: dict[str, Any]) -> dict[str, Any]:
        return query_ops.graph_query(
            self._plane._backend._state_root,
            args["repo_sha"],
            relation=args.get("relation"),
            path_prefix=args.get("path_prefix"),
            limit=args.get("limit", 20),
            cursor=args.get("cursor", 0),
        )

    def _tool_symbol_search(self, args: dict[str, Any]) -> dict[str, Any]:
        return query_ops.symbol_search(
            self._plane._backend._state_root,
            args["repo_sha"],
            args["query"],
            mode=args.get("mode", "substring"),
            scope_prefix=args.get("scope_prefix"),
            kind=args.get("kind"),
            limit=args.get("limit", 20),
        )

    def _tool_trace_path(self, args: dict[str, Any]) -> dict[str, Any]:
        return query_ops.trace_path(
            self._plane._backend._state_root,
            args["repo_sha"],
            args["start_ref"],
            direction=args.get("direction", "callees"),
            max_hops=args.get("max_hops", 2),
        )

    def _tool_impact_query(self, args: dict[str, Any]) -> dict[str, Any]:
        return query_ops.impact_query(
            self._plane._backend._state_root, args["repo_sha"], args["target_ref"]
        )

    def _tool_history_query(self, args: dict[str, Any]) -> dict[str, Any]:
        return query_ops.history_query(
            self._plane.repo_root or ".",
            args["repo_sha"],
            args["path"],
            limit=args.get("limit", 10),
            cursor=args.get("cursor", 0),
        )

    def _tool_domain_catalog(self, args: dict[str, Any]) -> dict[str, Any]:
        return query_ops.domain_catalog(
            self._plane._backend._state_root,
            args["repo_sha"],
            args["kind"],
            limit=args.get("limit", 20),
            cursor=args.get("cursor", 0),
        )

    def _tool_repo_overview(self, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": SCHEMA_ID,
            "repo_card": self._plane.repo_card(args["repo_sha"]),
            "stores": self._plane.inventory()["stores"],
        }

    # -- JSON-RPC dispatch -----------------------------------------------
    def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "capabilities": {"tools": {}},
                },
            }
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": TOOL_DEFINITIONS},
            }
        if method == "tools/call":
            name = (message.get("params") or {}).get("name")
            handler = self._tools.get(name) if isinstance(name, str) else None
            if handler is None:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32602, "message": f"unknown tool: {name}"},
                }
            try:
                result = handler((message.get("params") or {}).get("arguments") or {})
            except FileNotFoundError as exc:
                result = {"status": "UNAVAILABLE", "reason": str(exc)}
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps(result, sort_keys=True)}
                    ]
                },
            }
        if request_id is None:
            return None  # notification
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"unknown method: {method}"},
        }

    def serve(self, stdin: Any = None, stdout: Any = None) -> int:
        incoming = stdin if stdin is not None else sys.stdin
        outgoing = stdout if stdout is not None else sys.stdout
        for line in incoming:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            response = self.handle_message(message)
            if response is not None:
                outgoing.write(json.dumps(response, sort_keys=True) + "\n")
                outgoing.flush()
        return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", default="artifacts/intelligence")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    plane = UniversalDataPlane(args.state_root, args.repo)
    return McpServer(plane).serve()


if __name__ == "__main__":
    raise SystemExit(main())

"""OCA-W11 tests: facade store inventory, MCP protocol, portable export."""

from __future__ import annotations

import json
from pathlib import Path

from src.intelligence.universal_data_plane import STORES
from src.intelligence.universal_data_plane.facade import UniversalDataPlane
from src.intelligence.universal_data_plane.mcp_server import (
    TOOL_DEFINITIONS,
    McpServer,
)
from src.intelligence.repo_graph.graph_build import build_graph
from src.intelligence.repo_graph.service import resolve_repo_sha

from tests.intelligence.test_repo_graph import fixture_repo  # noqa: F401


def test_inventory_reports_runtime_unavailable() -> None:
    plane = UniversalDataPlane("unused-state-root")
    inventory = plane.inventory()
    assert inventory["stores"]["observability"]["status"] == "READ_READY_NO_PRODUCERS"
    assert inventory["stores"]["repo_graph"]["status"] == "AVAILABLE"
    assert "OCA-W10" in inventory["note"]


def test_mcp_initialize_tools_list_and_call(fixture_repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "state"
    receipt = build_graph(fixture_repo, root)
    sha = receipt["repo_sha"]
    server = McpServer(UniversalDataPlane(str(root), str(fixture_repo)))

    init = server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert (
        init is not None
        and init["result"]["serverInfo"]["name"] == "studious-repo-intel"
    )

    tools = server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert tools is not None
    names = {tool["name"] for tool in tools["result"]["tools"]}
    assert names == {
        "task_context",
        "expand_context",
        "repo_overview",
        "graph_query",
        "symbol_search",
        "trace_path",
        "impact_query",
        "history_query",
        "domain_catalog",
        "strategy_research",
        "web3_data_trace",
    }
    assert len(TOOL_DEFINITIONS) == 11

    call = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "task_context",
                "arguments": {"task": "engine run normalise", "repo_sha": sha},
            },
        }
    )
    assert call is not None and "error" not in call
    payload = json.loads(call["result"]["content"][0]["text"])
    assert payload["status"] in {"FRESH", "BUDGET_LIMITED"}
    assert payload["repo_sha"] == sha
    assert set(STORES) >= {"repo_graph", "observability"}

    unknown = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "shell_exec", "arguments": {}},
        }
    )
    assert unknown is not None and unknown["error"]["code"] == -32602


def test_mcp_unknown_sha_is_unavailable_not_fatal(
    fixture_repo: Path, tmp_path: Path
) -> None:
    build_graph(fixture_repo, tmp_path / "state")
    server = McpServer(UniversalDataPlane(str(tmp_path / "state"), str(fixture_repo)))
    call = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "task_context",
                "arguments": {"task": "anything", "repo_sha": "0" * 40},
            },
        }
    )
    assert call is not None and "error" not in call
    payload = json.loads(call["result"]["content"][0]["text"])
    assert payload["status"] in {"STALE", "UNAVAILABLE"}


def test_portable_context_pack_export(fixture_repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "state"
    receipt = build_graph(fixture_repo, root)
    sha = receipt["repo_sha"]
    plane = UniversalDataPlane(str(root), str(fixture_repo))
    envelope = plane.task_context("engine run normalise", repo_sha=sha)
    out = tmp_path / "packs" / "context-pack.json"
    export = plane.export_context_pack(envelope, out)
    assert export["refs"] >= 1
    assert out.exists()
    bundle = json.loads(out.read_text(encoding="utf-8"))
    assert bundle["pack_sha256"] == export["pack_sha256"]
    assert bundle["envelope"]["repo_sha"] == sha
    assert bundle["contents"]
    assert resolve_repo_sha(str(fixture_repo), "HEAD") == sha

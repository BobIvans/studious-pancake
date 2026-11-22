"""OCA-W11B tests: six new MCP tools, repo_ref resolution, publication, smoke."""

from __future__ import annotations

import json
from pathlib import Path

from src.intelligence.repo_graph.graph_build import build_graph
from src.intelligence.universal_data_plane.client_setup import (
    health_check,
    smoke_test,
    write_local_config,
)
from src.intelligence.universal_data_plane.facade import UniversalDataPlane
from src.intelligence.universal_data_plane.mcp_server import McpServer

from tests.intelligence.test_repo_graph import fixture_repo  # noqa: F401


def _server_with_graph(
    fixture_repo: Path, tmp_path: Path
) -> tuple[McpServer, UniversalDataPlane, str]:
    root = tmp_path / "state"
    receipt = build_graph(fixture_repo, root)
    plane = UniversalDataPlane(str(root), str(fixture_repo))
    return McpServer(plane), plane, receipt["repo_sha"]


def test_graph_query_pagination(fixture_repo: Path, tmp_path: Path) -> None:
    server, _plane, sha = _server_with_graph(fixture_repo, tmp_path)
    page = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "graph_query",
                "arguments": {"repo_sha": sha, "relation": "DEFINES", "limit": 3},
            },
        }
    )
    assert page is not None and "error" not in page
    payload = json.loads(page["result"]["content"][0]["text"])
    assert payload["total"] > 3
    assert payload["next_cursor"] == 3
    page2 = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "graph_query",
                "arguments": {
                    "repo_sha": sha,
                    "relation": "DEFINES",
                    "limit": 3,
                    "cursor": 3,
                },
            },
        }
    )
    payload2 = json.loads(page2["result"]["content"][0]["text"])
    assert payload2["edges"][0] != payload["edges"][0]
    assert payload2["graph_generation"] == payload["graph_generation"]


def test_symbol_search_exact_ranks_first(fixture_repo: Path, tmp_path: Path) -> None:
    server, _plane, sha = _server_with_graph(fixture_repo, tmp_path)
    call = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "symbol_search",
                "arguments": {"repo_sha": sha, "query": "Engine", "mode": "prefix"},
            },
        }
    )
    payload = json.loads(call["result"]["content"][0]["text"])
    assert payload["results"]
    assert payload["results"][0]["match_rank"] == 0


def test_trace_path_reports_unresolved_honestly(
    fixture_repo: Path, tmp_path: Path
) -> None:
    server, _plane, sha = _server_with_graph(fixture_repo, tmp_path)
    call = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "trace_path",
                "arguments": {
                    "repo_sha": sha,
                    "start_ref": "py::src/pkg/core.py::src.pkg.core",
                    "direction": "callees",
                    "max_hops": 1,
                },
            },
        }
    )
    payload = json.loads(call["result"]["content"][0]["text"])
    assert payload["hops"]
    for edge in payload["hops"][0]["edges"]:
        assert edge["unresolved"] in {True, False}
        assert edge["provenance"] == "STATIC_EXTRACTED"


def test_impact_query_static_only_labelling(fixture_repo: Path, tmp_path: Path) -> None:
    server, _plane, sha = _server_with_graph(fixture_repo, tmp_path)
    call = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "impact_query",
                "arguments": {
                    "repo_sha": sha,
                    "target_ref": "py::src/pkg/core.py::src.pkg.core",
                },
            },
        }
    )
    payload = json.loads(call["result"]["content"][0]["text"])
    assert payload["labelling"] == "STATIC_ONLY"
    assert "OCA-W10" in payload["runtime_impact"]
    assert payload["tests"]


def test_history_query_and_permission_gate(fixture_repo: Path, tmp_path: Path) -> None:
    server, _plane, sha = _server_with_graph(fixture_repo, tmp_path)
    call = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "history_query",
                "arguments": {"repo_sha": sha, "path": "src/pkg/core.py", "limit": 5},
            },
        }
    )
    payload = json.loads(call["result"]["content"][0]["text"])
    assert payload["commits"], "fixture repo has at least one commit touching core.py"
    assert "UNAVAILABLE" in payload["prs_issues_feed"]
    assert "OCA-W10" in payload["runtime_history"]


def test_domain_catalog_explicit_unavailability(
    fixture_repo: Path, tmp_path: Path
) -> None:
    server, _plane, sha = _server_with_graph(fixture_repo, tmp_path)
    call = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "domain_catalog",
                "arguments": {"repo_sha": sha, "kind": "strategy"},
            },
        }
    )
    payload = json.loads(call["result"]["content"][0]["text"])
    assert "PENDING_OCA_W4C" in payload["unavailable_reason"]


def test_repo_ref_resolution_and_publication(
    fixture_repo: Path, tmp_path: Path
) -> None:
    plane = UniversalDataPlane(str(tmp_path / "state"), str(fixture_repo))
    # Missing index + auto_refresh triggers a local, repo-artifacts-only build.
    refreshed = plane.resolve_repo_ref("HEAD", auto_refresh=True)
    assert refreshed["auto_refreshed"] is True
    assert refreshed["freshness"]["status"] == "FRESH"
    # Second resolution hits the existing artifact (no rebuild).
    resolved = plane.resolve_repo_ref("HEAD")
    assert resolved["freshness"]["status"] == "FRESH"
    assert resolved["auto_refreshed"] is False
    assert resolved["repo_sha"] == refreshed["repo_sha"]
    published = plane.publish_index(resolved["repo_sha"])
    assert Path(published["published"]).exists()
    # Immutable: republishing the same SHA does not rewrite the manifest.
    republished = plane.publish_index(resolved["repo_sha"])
    assert republished["immutable"] == "already published"


def test_client_setup_and_connection_smoke(fixture_repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "state"
    build_graph(fixture_repo, root)
    config = write_local_config(fixture_repo, state_root=str(root))
    assert config.exists()
    health = health_check(config)
    assert health["installed"] is True
    assert health["connected"] is False  # installed ≠ connected
    pythonpath = str(Path(__file__).resolve().parents[2])
    smoke = smoke_test(config, fixture_repo, pythonpath=pythonpath)
    assert smoke["connected"] is True
    assert smoke["real_query_ok"] is True
    assert len(smoke["tools_listed"]) == 9
    # No global config writes: everything lives under the repo-local dir.
    assert ".repo-intel" in str(config)

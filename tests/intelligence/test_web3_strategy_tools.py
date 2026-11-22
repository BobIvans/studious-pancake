"""OCA-W4C tests: catalogue, six/seven operations, MCP tools, golden probes."""

from __future__ import annotations

import json
from pathlib import Path

from src.intelligence.repo_graph.graph_build import build_graph
import pytest

from src.intelligence.universal_data_plane import web3_tools
from src.intelligence.universal_data_plane.facade import UniversalDataPlane
from src.intelligence.universal_data_plane.mcp_server import McpServer
from src.intelligence.universal_data_plane.strategy_catalog import (
    build_strategy_catalog,
    strategy_compare,
    strategy_context,
)

from tests.intelligence.test_repo_graph import fixture_repo  # noqa: F401
from tests.intelligence.test_runtime_capture import VERTICAL_OPPORTUNITY

STRATEGY_MODULE = '''"""Fixture atomic vertical strategy."""

def plan_route(state):  # fixture strategy entrypoint
    return state
'''


@pytest.fixture()
def strategy_repo(fixture_repo: Path) -> Path:
    (fixture_repo / "src" / "strategy").mkdir(parents=True, exist_ok=True)
    (fixture_repo / "src" / "strategy" / "atomic_vertical.py").write_text(
        STRATEGY_MODULE, encoding="utf-8"
    )
    docs_dir = fixture_repo / "docs" / "strategy-expansion"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "sx-doc-only.md").write_bytes(
        b"# Doc-only strategy idea\n\nNot implemented.\n"
    )
    from tests.intelligence.test_repo_graph import _commit_all

    _commit_all(fixture_repo, "strategy fixture")
    return fixture_repo


def test_catalog_discovers_and_preserves_states(
    strategy_repo: Path, tmp_path: Path
) -> None:
    root = tmp_path / "state"
    receipt = build_graph(strategy_repo, root)
    catalog = build_strategy_catalog(str(root), receipt["repo_sha"])
    assert catalog["coverage"]["implemented"] >= 1
    paths = {card["path"] for card in catalog["cards"]}
    assert "src/strategy/atomic_vertical.py" in paths
    # Doc-only discovery keeps its honest state.
    assert any(
        card["lifecycle_states"] == ["DOC_ONLY"] or card["path"].startswith("docs/")
        for card in catalog["cards"]
    )


def test_strategy_context_returns_full_source(
    strategy_repo: Path, tmp_path: Path
) -> None:
    root = tmp_path / "state"
    receipt = build_graph(strategy_repo, root)
    context = strategy_context(
        str(root), receipt["repo_sha"], "strategy:src/strategy/atomic_vertical.py"
    )
    assert context["status"] == "FRESH"
    assert context["source_full"] is not None
    assert "plan_route" in context["source_full"]


def test_strategy_compare_labels_novelty_evidence_backed(
    strategy_repo: Path, tmp_path: Path
) -> None:
    root = tmp_path / "state"
    receipt = build_graph(strategy_repo, root)
    result = strategy_compare(
        str(root),
        receipt["repo_sha"],
        ["strategy:src/strategy/atomic_vertical.py", "strategy-doc:docs/adr-001.md"],
    )
    assert result["novelty_rule"].startswith("evidence-backed")
    missing = strategy_compare(str(root), receipt["repo_sha"], ["strategy:none"])
    assert missing["selected"][0]["status"] == "UNKNOWN"


def test_provider_and_flash_capital_trace_separate_states(
    strategy_repo: Path, tmp_path: Path
) -> None:
    root = tmp_path / "state"
    receipt = build_graph(strategy_repo, root)
    provider = web3_tools.web3_data_trace(
        str(root), receipt["repo_sha"], "provider_trace", provider_ref="jupiter"
    )
    row = provider["rows"][0]
    assert row["declared"] is True and row["runtime_observed"] is False
    capital = web3_tools.web3_data_trace(
        str(root), receipt["repo_sha"], "flash_capital_trace"
    )
    assert any(
        "not flash-borrow capacity" in r["effective_capacity"] for r in capital["rows"]
    )


def test_operation_trace_and_performance_diagnostics(
    strategy_repo: Path, tmp_path: Path
) -> None:
    from src.observability.runtime_capture import default_vertical_adapter, run_vertical

    root = tmp_path / "state"
    receipt = build_graph(strategy_repo, root)
    adapter = default_vertical_adapter(strategy_repo / "events.sqlite")
    run_vertical(
        adapter,
        logical_opportunity_id=VERTICAL_OPPORTUNITY,
        strategy_ref="fixture-vertical",
    )
    trace = web3_tools.web3_data_trace(
        str(root),
        receipt["repo_sha"],
        "operation_trace",
        repo_root=str(strategy_repo),
    )
    assert trace["status"] == "PARTIAL"
    assert trace["coverage"]["opportunities_observed"] >= 1
    diagnostics = web3_tools.web3_data_trace(
        str(root),
        receipt["repo_sha"],
        "performance_diagnostics",
        strategy_ref="fixture-vertical",
        repo_root=str(strategy_repo),
    )
    assert diagnostics["sections"]["function_callsite_health"]
    assert diagnostics["transport"].endswith("(7th operation; no third MCP schema)")


def test_mcp_two_web3_tools_registered(strategy_repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "state"
    receipt = build_graph(strategy_repo, root)
    server = McpServer(UniversalDataPlane(str(root), str(strategy_repo)))
    tools = server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {tool["name"] for tool in tools["result"]["tools"]}
    assert {"strategy_research", "web3_data_trace"} <= names
    call = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "strategy_research",
                "arguments": {"repo_sha": receipt["repo_sha"], "action": "catalog"},
            },
        }
    )
    assert "error" not in call
    payload = json.loads(call["result"]["content"][0]["text"])
    assert payload["coverage"]["implemented"] >= 1

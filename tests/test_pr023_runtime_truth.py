from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import arb_bot
from src.application import ConfigurationError, build_application
from src.capabilities import CapabilityMatrix

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]


def test_capability_matrix_is_machine_readable_and_paths_exist():
    matrix = CapabilityMatrix.load_default()
    assert matrix.schema_version == "pr023.capabilities.v1"
    assert matrix.product_state == "not-production-ready"
    assert matrix.supported_entrypoint == "flashloan-bot"
    assert matrix.validate_paths(ROOT) == ()
    assert {component.capability.value for component in matrix.components} <= {
        "implemented",
        "fixture-only",
        "shadow-ready",
        "live-ready",
        "disabled",
    }


def test_capability_matrix_matches_strategy_registry_exactly():
    matrix = CapabilityMatrix.load_default()
    app = build_application(capabilities=matrix)
    assert matrix.validate_strategy_registry(app.context.registry.all()) == ()
    matrix_names = {
        component.registry_name
        for component in matrix.components
        if component.kind == "strategy"
    }
    assert matrix_names == {entry.name for entry in app.manifest()}


def test_quarantined_components_are_disabled_only():
    matrix = CapabilityMatrix.load_default()
    quarantined = [
        component for component in matrix.components if component.quarantined
    ]
    assert quarantined
    assert all(component.allowed_modes == ("disabled",) for component in quarantined)
    assert all(
        not component.active_in_supported_entrypoint for component in quarantined
    )


@pytest.mark.asyncio
async def test_fixture_or_disabled_strategy_cannot_be_enabled_by_config_flag():
    class Config:
        strategy_modes = {"lst_depeg": "shadow"}
        opportunity_queue_size = 10
        shutdown_drain_timeout_seconds = 0.01

    app = build_application(Config())
    with pytest.raises(ConfigurationError, match="forbidden by capability contract"):
        await app.run()
    assert not app.context.strategy_runtime.supervisor.tasks


def test_default_startup_reports_no_executable_strategies(capsys):
    rc = arb_bot.main([])
    captured = capsys.readouterr()
    assert rc == arb_bot.EXIT_NO_EXECUTABLE_STRATEGIES
    assert "NO_EXECUTABLE_STRATEGIES" in captured.err
    assert "not-production-ready" in captured.out


def test_status_and_capabilities_json_are_stable(capsys):
    assert arb_bot.main(["status", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["diagnostic"] == "NO_EXECUTABLE_STRATEGIES"
    assert status["capability_contract_valid"] is True
    assert status["executable_strategies"] == []

    assert arb_bot.main(["capabilities", "--json"]) == 0
    capabilities = json.loads(capsys.readouterr().out)
    assert capabilities["schema_version"] == "pr023.capabilities.v1"


def test_canonical_paper_service_is_available_but_live_mode_fails_closed(
    capsys,
    tmp_path,
):
    db_path = tmp_path / "canonical-paper.sqlite3"

    assert arb_bot.main(["run", "--mode", "paper", "--db-path", str(db_path)]) == 0
    captured = capsys.readouterr()
    assert "CANONICAL_PAPER_CYCLE" in captured.out
    assert "outcome=PAPER_ACCEPTED" in captured.out
    assert "reason=paper_accepted" in captured.out
    assert "live=false signer=false sender=false" in captured.out
    assert db_path.is_file()

    assert arb_bot.main(["run", "--mode", "live"]) == arb_bot.EXIT_MODE_UNAVAILABLE
    assert "LIVE_MODE_UNAVAILABLE" in capsys.readouterr().err


def test_supported_composition_root_does_not_import_quarantined_execution():
    forbidden = {
        "src.legacy_arb_bot",
        "src.ingest.tx_builder",
        "src.ingest.execution_router",
        "src.ingest.jito_executor",
        "src.liquidation",
        "src.providers.orderbook",
        "src.venues.pump",
    }
    for relative in ("arb_bot.py", "src/cli.py", "src/application.py"):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        assert not any(
            imported == blocked or imported.startswith(f"{blocked}.")
            for imported in imports
            for blocked in forbidden
        )


def test_audit_snapshot_and_runtime_contract_are_present():
    assert (
        ROOT / "docs/audits/FLASHLOAN_BOT_PRODUCTION_AUDIT_AND_PR_ROADMAP_2026-07-19.md"
    ).is_file()
    assert (ROOT / "docs/runtime_contract_pr023.md").is_file()
    assert (ROOT / "docs/quarantine_pr023.md").is_file()

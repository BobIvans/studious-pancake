"""R08 runtime composition invariants (additive contract tests, true today).

These tests pin the composition-level truths recorded in
docs/roadmap/agent-execution-master-2026-11-13/reports/R08_RUNTIME_COMPOSITION_AUDIT_2026-11-14.md:

- the installed runtime owner hard-denies live mode before any runtime work;
- the supported composition roots never import quarantined execution owners;
- research/discovery canonical owners (Dynamic Universe, radar intake cadence,
  quote funnel probes, FlashCapitalGraph, unsigned builders, rent sponsor
  planner, qualification campaign, research graph) stay outside the supported
  composition roots (library-only today, binding requires the R08 integration
  plan steps);
- the evidence resolver and paper composition fail closed without external
  evidence (no synthetic fills, no network-capable RPC, no reservations);
- the machine-readable runtime authority and capability manifest keep the
  sender-free / live-denied contract and the flashloan-bot entrypoint truth;
- market source catalog rows remain non-connector records.

All tests are offline and use no network.
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path

import pytest

from src.config.runtime import load_runtime_config
from src.runtime.core_v1_composition import build_core_v1_composition
from src.runtime.core_v1_dependency_resolver import (
    _ResolverBlockedRpc,
    resolve_installed_core_v1_dependencies,
)
from src.runtime.core_v1_materializer import (
    CORE_V1_BLOCKED_EXTERNAL,
    CoreV1ReleaseProfile,
)

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]

COMPOSITION_ROOT_MODULES = (
    "src/runtime/core_v1_composition.py",
    "src/runtime/runtime_entrypoint.py",
    "src/runtime/core_v1_dependency_resolver.py",
    "src/runtime/core_v1_materializer.py",
    "src/paper_shadow/composition.py",
    "src/runtime_discovery_builder.py",
)

# Quarantined / sender-class owners (README quarantine section +
# config/capabilities.json component rows). Prefix-matched on dotted modules.
QUARANTINED_IMPORT_PREFIXES = (
    "src.ingest",
    "src.execution.senders",
    "src.execution.live_control",
    "src.execution.shadow",
    "src.legacy_arb_bot",
    "isolated_signer_service",
)

# Library-only canonical owners from the R08 audit matrix (section 2.2).
# Binding any of these into a supported composition root must be a conscious,
# evidence-gated integration PR that updates this list together with the report.
LIBRARY_ONLY_IMPORT_PREFIXES = (
    "src.discovery.dynamic_universe",
    "src.solana_parallel_radar",
    "src.economics.flash_capital_graph",
    "src.lending.unsigned_builders",
    "src.planning.rent_sponsor_planner",
    "src.research_economic_graph",
    "src.strategy.relation_generators",
    "src.research.correlation_ledger",
    "src.qualification_campaign",
)

CORE_JUPITER_LEND_PROFILE_ID = "core-jupiter-lend-jupiter-v1"
MANIFEST_REQUIRED_BLOCKER = "CORE_V1_FINANCING_EVIDENCE_MANIFEST_REQUIRED"

# Catalog access classifications that are not live connector grants.
NON_CONNECTOR_ACCESS = frozenset(
    {
        "access-not-verified",
        "open-source-rpc-or-host-required",
        "public-rate-limited",
        "free-tier-key-required",
    }
)


def _imported_modules(relative_path: str) -> set[str]:
    tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _matches_any_prefix(modules: set[str], prefixes: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for module in sorted(modules):
        for prefix in prefixes:
            if module == prefix or module.startswith(prefix + "."):
                hits.append(module)
    return hits


def _paper_config():
    return load_runtime_config(cli_overrides={"runtime.mode": "paper"})


def _profile(config, *, lender: str, profile_id: str) -> CoreV1ReleaseProfile:
    return CoreV1ReleaseProfile(
        profile_id=profile_id,
        strategy="circular_arbitrage",
        lender=lender,
        router="jupiter",
        cluster=config.cluster.name,
        genesis_hash=config.cluster.genesis_hash,
        transport="rpc",
        live_enabled=False,
    )


def test_runtime_entrypoint_hard_denies_live_mode(capsys) -> None:
    from src.runtime import runtime_entrypoint

    exit_code = runtime_entrypoint.main(["run", "--mode", "live"])
    captured = capsys.readouterr()
    assert exit_code == runtime_entrypoint.EXIT_MODE_UNAVAILABLE
    assert "LIVE_MODE_UNAVAILABLE" in captured.err


def test_composition_roots_import_no_quarantined_execution_owner() -> None:
    for relative in COMPOSITION_ROOT_MODULES:
        modules = _imported_modules(relative)
        assert _matches_any_prefix(modules, QUARANTINED_IMPORT_PREFIXES) == []


def test_library_only_owners_stay_outside_composition_roots() -> None:
    scanned = (*COMPOSITION_ROOT_MODULES, "src/cli.py")
    for relative in scanned:
        modules = _imported_modules(relative)
        assert _matches_any_prefix(modules, LIBRARY_ONLY_IMPORT_PREFIXES) == []


def test_resolver_fails_closed_without_evidence_manifest() -> None:
    config = _paper_config()
    marginfi_profile = _profile(
        config, lender="marginfi", profile_id="core-marginfi-jupiter-v1"
    )
    marginfi = resolve_installed_core_v1_dependencies(marginfi_profile, {})
    assert marginfi.dependencies is None
    assert marginfi.blocker == CORE_V1_BLOCKED_EXTERNAL
    assert marginfi.resolved is False

    jupiter_profile = _profile(
        config, lender="jupiter-lend", profile_id=CORE_JUPITER_LEND_PROFILE_ID
    )
    jupiter = resolve_installed_core_v1_dependencies(jupiter_profile, {})
    assert jupiter.dependencies is None
    assert jupiter.blocker == MANIFEST_REQUIRED_BLOCKER
    assert jupiter.resolved is False


async def test_resolver_rpc_port_is_blocked_offline() -> None:
    rpc = _ResolverBlockedRpc()
    with pytest.raises(RuntimeError, match=CORE_V1_BLOCKED_EXTERNAL):
        await rpc.call("getLatestBlockhash", [])


def test_generic_profile_blocked_composition_stays_fail_closed(tmp_path) -> None:
    config = _paper_config()
    profile = _profile(
        config, lender="jupiter-lend", profile_id=CORE_JUPITER_LEND_PROFILE_ID
    )
    composition = build_core_v1_composition(
        config,
        db_path=tmp_path / "r08-blocked-generic.sqlite3",
        profile=profile,
        dependencies=None,
        external_blocker=MANIFEST_REQUIRED_BLOCKER,
    )
    try:
        assert composition.admitted is False
        assert composition.blockers == (MANIFEST_REQUIRED_BLOCKER,)
        # The generic blocked composition binds no planner/simulator/orchestrator
        # until qualified dependencies exist; it must not fall back to the
        # legacy marginfi vertical for a different lender profile.
        assert composition.planner is None
        assert composition.simulator is None
        assert composition.vertical is None
        assert composition.orchestrator is None
        assert composition.runtime_cycle is None
        assert composition.materializer is None
        batch = composition.service.batch_source()
        assert batch.evidence.ready is False
        assert batch.evidence.blockers == (MANIFEST_REQUIRED_BLOCKER,)
        assert batch.items == ()
        assert (
            composition.authority.db.execute(
                "SELECT COUNT(*) FROM durable_reservations"
            ).fetchone()[0]
            == 0
        )
    finally:
        composition.close()


def test_runtime_authority_declares_sender_free_flashloan_bot_composition() -> None:
    authority = json.loads(
        (ROOT / "src/resources/runtime_authority.json").read_text(encoding="utf-8")
    )
    root = authority["active_composition_root"]
    assert root["entrypoint"] == "flashloan-bot"
    assert root["module"] == "src.cli_pr189"
    assert root["sender_free"] is True
    assert root["live_enabled"] is False
    assert (
        authority["lifecycle_authority"]
        == "src.durability.unified_authority_pr02:UnifiedLifecycleAuthority"
    )
    assert (
        authority["capital_authority"]
        == "src.economics.durable_reservations:DurableCapitalCoordinator"
    )
    assert authority["alternate_runtime_surfaces"]
    assert all(
        surface["active"] is False
        for surface in authority["alternate_runtime_surfaces"]
    )


def test_capability_manifest_keeps_live_unavailable_and_entrypoint_truth() -> None:
    capabilities = json.loads(
        (ROOT / "config/capabilities.json").read_text(encoding="utf-8")
    )
    assert capabilities["supported_entrypoint"] == "flashloan-bot"
    assert capabilities["product_state"] == "not-production-ready"
    modes = capabilities["runtime_modes"]
    assert modes["live"]["available"] is False
    assert modes["disabled"]["available"] is True
    assert modes["paper"]["available"] is True
    assert modes["shadow"]["available"] is True


def test_capability_manifest_providers_stay_out_of_execution() -> None:
    capabilities = json.loads(
        (ROOT / "config/capabilities.json").read_text(encoding="utf-8")
    )
    providers = {
        component["id"]: component
        for component in capabilities["components"]
        if component["kind"] == "provider"
    }
    assert providers, "capability manifest must declare provider components"
    for provider_id, component in providers.items():
        # No provider is executable in live mode; provider surfaces are
        # discovery/shadow-only or fully quarantined fixture records.
        assert "live" not in component["allowed_modes"], provider_id
    quarantined = {
        provider_id: component
        for provider_id, component in providers.items()
        if component["quarantined"]
    }
    assert {"provider.marginfi", "provider.kamino"} <= set(quarantined)
    for provider_id, component in quarantined.items():
        assert component["capability"] == "fixture-only", provider_id
        assert component["allowed_modes"] == ["disabled"], provider_id
        assert component["active_in_supported_entrypoint"] is False, provider_id


def test_market_source_catalog_rows_are_not_live_connectors() -> None:
    catalog = json.loads(
        (ROOT / "src/resources/market_source_catalog.json").read_text(encoding="utf-8")
    )
    assert catalog["schema_version"] == "shadow.market-source-catalog.v1"
    rows = catalog["sources"]
    assert rows
    for row in rows:
        assert row["access"] in NON_CONNECTOR_ACCESS, row["source_id"]
        assert "enabled" not in row, row["source_id"]

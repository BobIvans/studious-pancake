"""R08 composition contract tests (audit-first lane, offline, zero network).

Two parts, per ``docs/roadmap/agent-execution-master-2026-11-13/tasks/
R08_COMPOSITION_AUDIT_2026-11-14.md``:

Part A (always runs) pins the *current* runtime truth of the supported
composition roots: ``flashloan-bot`` -> ``src.cli_pr189:main`` ->
``src.runtime.runtime_entrypoint`` -> ``resolve_installed_core_v1_dependencies``
+ ``build_core_v1_composition`` (CORE-V1), and ``build_paper_shadow_runtime``
(PR-089/102).  It proves that a tree which already contains every new wave
owner (CAP-A/B/C/D readers, R-03 unsigned builders, RentSponsorPlanner, P0-3
decoders, TON ingestors, GPR-03 Sui, Stream H) still resolves to the
fail-closed paper/shadow truth and hard-denies live.

Part B (skip-if-unwired) guards each future wiring step.  The guard inspects
the five composition-root modules for the owner's import token; while the
owner is unwired the test skips with a typed reason, and the day a wiring PR
lands the same test executes and asserts the owner entered only through the
existing ports/gates (typed capacity blockers, build/capacity separation,
planner seam, evidence path, discovery plane) without importing any
signer/sender or flipping sign/send/live.
"""

from __future__ import annotations

import importlib
import inspect
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from src.config.runtime import load_runtime_config
from src.paper_shadow import (
    PR089_MISSING_ATOMIC_DEPENDENCIES,
    PaperShadowRunStatus,
    build_paper_shadow_runtime,
)
from src.runtime.core_v1_composition import build_core_v1_composition
from src.runtime.core_v1_dependency_resolver import (
    LEGACY_SCHEMA,
    MANIFEST_ENV,
    SCHEMA,
    resolve_installed_core_v1_dependencies,
)
from src.runtime.core_v1_materializer import (
    CORE_V1_BLOCKED_EXTERNAL,
    CORE_V1_PROFILE_ID,
    CoreV1AttemptMaterializer,
    CoreV1ReleaseProfile,
)
from src.lending.jupiter_lend import JUPITER_LEND_FLASHLOAN_PROGRAM_ID
from src.lending.slumlord import SLUMLORD_PROGRAM_ID
from src.runtime.trusted_time import TrustedTimeSnapshot
from src.strategy.domain import Opportunity

REPO_ROOT = Path(__file__).resolve().parents[1]

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_E = "e" * 64
TEST_NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


class _FixedClock:
    def snapshot(self) -> TrustedTimeSnapshot:
        return TrustedTimeSnapshot(monotonic_ns=1, utc=TEST_NOW, slot=102)


# Composition-root modules whose source defines what the supported entrypoint
# can reach.  Any new-owner wiring MUST appear here to count as "wired".
COMPOSITION_ROOT_MODULES: tuple[str, ...] = (
    "src.runtime.runtime_entrypoint",
    "src.runtime.core_v1_composition",
    "src.runtime.core_v1_dependency_resolver",
    "src.runtime.core_v1_materializer",
    "src.paper_shadow.composition",
)

# Tokens that must never appear in a composition root, in any wiring state.
FORBIDDEN_RUNTIME_TOKENS: tuple[str, ...] = (
    "src.execution.senders",
    "isolated_signer",
    "sendTransaction",
    "sendBundle",
)


def _composition_root_sources() -> dict[str, str]:
    sources: dict[str, str] = {}
    for module_name in COMPOSITION_ROOT_MODULES:
        module = importlib.import_module(module_name)
        sources[module_name] = inspect.getsource(module)
    return sources


def _owner_is_wired(owner_tokens: tuple[str, ...]) -> bool:
    """True only if a composition root references the owner module."""
    sources = _composition_root_sources()
    return any(token in source for source in sources.values() for token in owner_tokens)


def _require_wired(owner_tokens: tuple[str, ...], owner_label: str) -> None:
    if not _owner_is_wired(owner_tokens):
        pytest.skip(f"R08: {owner_label} not wired into composition root")


def _jupiter_lend_profile(config: Any) -> CoreV1ReleaseProfile:
    return CoreV1ReleaseProfile(
        profile_id="core-jupiter-lend-jupiter-v1",
        strategy="circular_arbitrage",
        lender="jupiter-lend",
        router="jupiter",
        cluster=config.cluster.name,
        genesis_hash=config.cluster.genesis_hash,
        transport="rpc",
        profile_generation=1,
    )


def _marginfi_profile(config: Any) -> CoreV1ReleaseProfile:
    return CoreV1ReleaseProfile(
        profile_id=CORE_V1_PROFILE_ID,
        strategy="circular_arbitrage",
        lender="marginfi",
        router="jupiter",
        cluster=config.cluster.name,
        genesis_hash=config.cluster.genesis_hash,
        transport="rpc",
        profile_generation=1,
    )


def _identity_payload(
    *,
    lender_id: str,
    program_id: str,
    qualified: bool,
    evidence_sha256: str,
) -> dict[str, object]:
    return {
        "lender_id": lender_id,
        "program_id": program_id,
        "deployment_generation": 1,
        "evidence_sha256": evidence_sha256,
        "decoder_identity": "agg03-decoder",
        "decoder_generation": 1,
        "qualified": qualified,
    }


def _manifest_payload(
    *,
    primary_qualified: bool,
    rent_qualified: bool,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA,
        "profile_id": "core-jupiter-lend-jupiter-v1",
        "profile_generation": 1,
        "primary": _identity_payload(
            lender_id="jupiter-lend",
            program_id=str(JUPITER_LEND_FLASHLOAN_PROGRAM_ID),
            qualified=primary_qualified,
            evidence_sha256=SHA_A,
        ),
        "rent": _identity_payload(
            lender_id="slumlord",
            program_id=str(SLUMLORD_PROGRAM_ID),
            qualified=rent_qualified,
            evidence_sha256=SHA_B,
        ),
    }


def _write_manifest(tmp_path: Path, payload: Mapping[str, object]) -> str:
    manifest_path = tmp_path / "evidence-manifest.json"
    manifest_path.write_text(json.dumps(dict(payload)), encoding="utf-8")
    return str(manifest_path)


# ---------------------------------------------------------------------------
# Part A1 — packaged runtime truth (capabilities + authority resources)
# ---------------------------------------------------------------------------


def test_capabilities_json_runtime_truth_is_unchanged() -> None:
    payload = json.loads(
        (REPO_ROOT / "config" / "capabilities.json").read_text(encoding="utf-8")
    )
    assert payload["supported_entrypoint"] == "flashloan-bot"
    assert payload["product_state"] == "not-production-ready"
    assert payload["default_command"] == "run --mode shadow"
    modes = payload["runtime_modes"]
    assert modes["live"]["available"] is False
    assert modes["paper"]["available"] is True
    assert modes["shadow"]["available"] is True
    assert modes["disabled"]["available"] is True
    assert modes["live"]["description"].startswith("Hard denied")


def test_runtime_authority_json_entrypoint_truth_is_unchanged() -> None:
    payload = json.loads(
        (REPO_ROOT / "src" / "resources" / "runtime_authority.json").read_text(
            encoding="utf-8"
        )
    )
    root = payload["active_composition_root"]
    assert root["entrypoint"] == "flashloan-bot"
    assert root["module"] == "src.cli_pr189"
    assert root["callable"] == "main"
    assert root["sender_free"] is True
    assert root["live_enabled"] is False
    dispositions = {
        surface["path"]: surface["disposition"]
        for surface in payload["alternate_runtime_surfaces"]
    }
    assert dispositions["src.execution.senders"] == "removed-from-package"
    assert dispositions["src.ingest.execution_router"] == "removed-from-package"


# ---------------------------------------------------------------------------
# Part A2 — resolver runtime truth (CORE-V1 evidence seam)
# ---------------------------------------------------------------------------


def test_resolver_marginfi_profile_is_unconditionally_blocked(
    tmp_path,
) -> None:
    config = load_runtime_config(cli_overrides={"runtime.mode": "paper"})
    profile = _marginfi_profile(config)
    # Even pointing the manifest env at a file must not change the verdict:
    # marginfi short-circuits before any manifest is read.
    manifest = _write_manifest(
        tmp_path, _manifest_payload(primary_qualified=True, rent_qualified=True)
    )
    for environment in ({}, {MANIFEST_ENV: manifest}):
        resolution = resolve_installed_core_v1_dependencies(
            profile,
            environment,
            config=config,
            trusted_time=_FixedClock(),
        )
        assert resolution.dependencies is None
        assert resolution.blocker == CORE_V1_BLOCKED_EXTERNAL
        assert resolution.resolved is False


def test_resolver_without_manifest_fails_closed() -> None:
    config = load_runtime_config(cli_overrides={"runtime.mode": "paper"})
    resolution = resolve_installed_core_v1_dependencies(
        _jupiter_lend_profile(config),
        {},
        config=config,
        trusted_time=_FixedClock(),
    )
    assert resolution.dependencies is None
    assert resolution.blocker == "CORE_V1_FINANCING_EVIDENCE_MANIFEST_REQUIRED"


def test_resolver_unknown_manifest_schema_hard_fails(tmp_path) -> None:
    config = load_runtime_config(cli_overrides={"runtime.mode": "paper"})
    payload = dict(_manifest_payload(primary_qualified=True, rent_qualified=True))
    payload["schema_version"] = "core-v1.financing-evidence-manifest.v99"
    manifest = _write_manifest(tmp_path, payload)
    with pytest.raises(
        ValueError, match="CORE_V1_FINANCING_EVIDENCE_MANIFEST_SCHEMA_MISMATCH"
    ):
        resolve_installed_core_v1_dependencies(
            _jupiter_lend_profile(config),
            {MANIFEST_ENV: manifest},
            config=config,
            trusted_time=_FixedClock(),
        )


def test_resolver_legacy_manifest_requires_admission_receipt(tmp_path) -> None:
    config = load_runtime_config(cli_overrides={"runtime.mode": "paper"})
    payload = dict(_manifest_payload(primary_qualified=True, rent_qualified=True))
    payload["schema_version"] = LEGACY_SCHEMA
    manifest = _write_manifest(tmp_path, payload)
    resolution = resolve_installed_core_v1_dependencies(
        _jupiter_lend_profile(config),
        {MANIFEST_ENV: manifest},
        config=config,
        trusted_time=_FixedClock(),
    )
    assert resolution.dependencies is None
    assert resolution.blocker == "CORE_V1_FINANCING_ADMISSION_RECEIPT_REQUIRED"


def test_resolver_unqualified_primary_deployment_is_blocked(tmp_path) -> None:
    config = load_runtime_config(cli_overrides={"runtime.mode": "paper"})
    manifest = _write_manifest(
        tmp_path,
        _manifest_payload(primary_qualified=False, rent_qualified=True),
    )
    resolution = resolve_installed_core_v1_dependencies(
        _jupiter_lend_profile(config),
        {MANIFEST_ENV: manifest},
        config=config,
        trusted_time=_FixedClock(),
    )
    assert resolution.dependencies is None
    assert resolution.blocker == "CORE_V1_PRIMARY_FINANCING_DEPLOYMENT_NOT_QUALIFIED"


def test_resolver_unqualified_rent_deployment_is_blocked(tmp_path) -> None:
    config = load_runtime_config(cli_overrides={"runtime.mode": "paper"})
    manifest = _write_manifest(
        tmp_path,
        _manifest_payload(primary_qualified=True, rent_qualified=False),
    )
    resolution = resolve_installed_core_v1_dependencies(
        _jupiter_lend_profile(config),
        {MANIFEST_ENV: manifest},
        config=config,
        trusted_time=_FixedClock(),
    )
    assert resolution.dependencies is None
    assert resolution.blocker == "CORE_V1_RENT_FINANCING_DEPLOYMENT_NOT_QUALIFIED"


def test_resolver_never_dynamically_imports_code() -> None:
    source = inspect.getsource(
        importlib.import_module("src.runtime.core_v1_dependency_resolver")
    )
    assert "importlib" not in source
    assert "__import__" not in source


# ---------------------------------------------------------------------------
# Part A3 — composition / materializer runtime truth
# ---------------------------------------------------------------------------


def test_generic_profile_without_dependencies_is_blocked_and_sender_free(
    tmp_path,
) -> None:
    config = load_runtime_config(cli_overrides={"runtime.mode": "paper"})
    composition = build_core_v1_composition(
        config,
        db_path=tmp_path / "r08-generic.sqlite3",
        profile=_jupiter_lend_profile(config),
        dependencies=None,
        external_blocker="CORE_V1_FINANCING_EVIDENCE_MANIFEST_REQUIRED",
    )
    try:
        assert composition.admitted is False
        assert composition.blockers == ("CORE_V1_FINANCING_EVIDENCE_MANIFEST_REQUIRED",)
        # The blocked composition must not construct any executable owner.
        assert composition.planner is None
        assert composition.simulator is None
        assert composition.vertical is None
        assert composition.orchestrator is None
        assert composition.runtime_cycle is None
        assert composition.materializer is None
        batch = composition.service.batch_source()
        assert batch.evidence.ready is False
        assert batch.evidence.blockers == (
            "CORE_V1_FINANCING_EVIDENCE_MANIFEST_REQUIRED",
        )
        assert batch.items == ()
        assert (
            composition.authority.db.execute(
                "SELECT COUNT(*) FROM durable_reservations"
            ).fetchone()[0]
            == 0
        )
        # One close must already be enough; a second is a no-op.
        composition.close()
    finally:
        composition.close()


def test_live_profile_is_invalid_by_construction() -> None:
    with pytest.raises(ValueError, match="CORE_V1_PROFILE_SCOPE_MISMATCH"):
        CoreV1ReleaseProfile(
            profile_id="core-jupiter-lend-jupiter-v1",
            strategy="circular_arbitrage",
            lender="jupiter-lend",
            router="jupiter",
            cluster="mainnet-beta",
            genesis_hash="genesis",
            transport="rpc",
            live_enabled=True,
            profile_generation=1,
        )


def test_materializer_refuses_non_paper_shadow_modes() -> None:
    config = load_runtime_config(
        cli_overrides={
            "runtime.mode": "disabled",
            "providers.jupiter.enabled": True,
        }
    )
    with pytest.raises(ValueError, match="CORE_V1_CIRCULAR_ARBITRAGE_NOT_ADMITTED"):
        CoreV1AttemptMaterializer(
            config,
            _jupiter_lend_profile(config),
            release_id="release-r08",
            policy_bundle_hash=SHA_E,
        )


def test_materializer_accepts_only_canonical_drafts() -> None:
    config = load_runtime_config(
        cli_overrides={
            "runtime.mode": "shadow",
            "strategies.circular_arbitrage": "shadow",
            "providers.jupiter.enabled": True,
        }
    )
    materializer = CoreV1AttemptMaterializer(
        config,
        _jupiter_lend_profile(config),
        release_id="release-r08",
        policy_bundle_hash=SHA_E,
    )
    with pytest.raises(TypeError, match="CORE_V1_CANONICAL_DRAFT_REQUIRED"):
        materializer.materialize(object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Part A4 — PR-089/102 paper/shadow runtime truth
# ---------------------------------------------------------------------------


class _StubEvidence:
    cycle_succeeded = True
    terminal_reason = "cycle_succeeded"
    degraded_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "test.r08-discovery-evidence.v1",
            "cycle_id": "cycle-r08",
            "cycle_succeeded": True,
            "terminal_reason": "cycle_succeeded",
            "degraded_reasons": [],
        }


class _StubDiscovery:
    def __init__(self, opportunities: tuple[Opportunity, ...]) -> None:
        self.opportunities = opportunities

    async def run_cycle(self) -> Any:
        return SimpleNamespace(
            opportunities=self.opportunities, evidence=_StubEvidence()
        )


def _opportunity() -> Opportunity:
    return Opportunity.create(
        strategy_name="fixture",
        opportunity_type="atomic-arb",
        detection_slot=900,
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        proposed_amount_base_units=1_000,
        expected_gross_profit=10,
        ttl_seconds=30.0,
        detected_at=1_750_000_000.0,
        metadata={"source": "r08-contract-fixture"},
    )


@pytest.mark.asyncio
async def test_paper_shadow_default_dependencies_block_all_stages(tmp_path) -> None:
    runtime = build_paper_shadow_runtime(
        object(),  # type: ignore[arg-type]
        journal_path=tmp_path / "r08-paper-shadow.jsonl",
        discovery=_StubDiscovery((_opportunity(),)),  # type: ignore[arg-type]
    )
    summary = await runtime.run_once()
    assert summary.status is PaperShadowRunStatus.BLOCKED
    assert summary.terminal_reason == PR089_MISSING_ATOMIC_DEPENDENCIES
    # The dependency gate must remain the handler for every required stage
    # while the new owners are unwired, and must record sender-free truth.
    events = runtime.runner.journal.read_events()
    blocked = [event for event in events if event["event_type"] == "stage_blocked"]
    assert blocked, "expected the PR-089 dependency gate to record blocked stages"
    details = blocked[0]["details"]
    assert details["sender_imported"] is False
    assert details["live_mutation_allowed"] is False
    assert details["missing_dependencies"] == [
        "atomic_stage_suite",
        "exact_fee_workflow",
        "verified_marginfi_provider",
        "jupiter_v2_build",
    ]


# ---------------------------------------------------------------------------
# Part A5 — composition roots stay sender-free in every wiring state
# ---------------------------------------------------------------------------


def test_composition_roots_import_no_signer_or_sender() -> None:
    sources = _composition_root_sources()
    assert len(sources) == len(COMPOSITION_ROOT_MODULES)
    for module_name, source in sources.items():
        for token in FORBIDDEN_RUNTIME_TOKENS:
            assert (
                token not in source
            ), f"R08 contract violation: {module_name} references {token!r}"


# ---------------------------------------------------------------------------
# Part B — skip-if-unwired per-owner wiring contracts
# ---------------------------------------------------------------------------


def test_cap_capacity_readers_enter_only_through_typed_gates() -> None:
    _require_wired(
        (
            "observe_token_reserve_capacity",
            "observe_kamino_reserve_capacity",
            "observe_navi_pool_capacity",
            "bank_discovery",
        ),
        "R02 CAP readers",
    )
    sources = _composition_root_sources().values()
    joined = "\n".join(sources)
    # Live capacity may only enter typed-blocked; readers must not fabricate it.
    assert "MISSING_EFFECTIVE_FLASH_CAP" in joined
    for token in FORBIDDEN_RUNTIME_TOKENS:
        assert token not in joined


def test_unsigned_builders_keep_build_and_capacity_status_separate() -> None:
    _require_wired(("unsigned_builders",), "R-03 unsigned builders")
    joined = "\n".join(_composition_root_sources().values())
    assert "BuildStatus" in joined
    assert "CapacityStatus" in joined
    assert "assert_no_execution_ready_capacity_member" in joined
    for token in FORBIDDEN_RUNTIME_TOKENS:
        assert token not in joined


def test_rent_sponsor_planner_enters_via_planner_seam() -> None:
    _require_wired(
        ("rent_sponsor_planner", "RentSponsorPlanner"),
        "RentSponsorPlanner",
    )
    joined = "\n".join(_composition_root_sources().values())
    # Route rent planning must reuse the existing planner/financing seam and
    # must not create a new authority.
    assert "atomic_marginfi_jupiter" in joined or "financing_planner_adapter" in joined
    for token in FORBIDDEN_RUNTIME_TOKENS:
        assert token not in joined


def test_p0_3_exact_decoders_feed_evidence_not_execution() -> None:
    _require_wired(
        ("raydium_clmm_native", "meteora_dlmm_native"),
        "P0-3 exact state decoders",
    )
    joined = "\n".join(_composition_root_sources().values())
    # Decoders may only enter as rooted evidence for materialization/verification.
    assert "CoreV1AttemptDraft" in joined or "draft_source" in joined
    for token in FORBIDDEN_RUNTIME_TOKENS:
        assert token not in joined


def test_dynamic_universe_enters_through_discovery_plane() -> None:
    _require_wired(
        ("dynamic_universe",),
        "Dynamic Universe / TON ingestors",
    )
    joined = "\n".join(_composition_root_sources().values())
    assert "RuntimeDiscoveryCoordinator" in joined or "runtime_discovery" in joined
    assert "TON_ASYNC_MULTI_CONTRACT" in joined or "DISCOVERY_ONLY" in joined
    for token in FORBIDDEN_RUNTIME_TOKENS:
        assert token not in joined


def test_stream_h_relations_cannot_self_promote_into_paper_gate() -> None:
    _require_wired(
        ("relation_generators", "correlation_ledger"),
        "Stream H relations/correlation",
    )
    joined = "\n".join(_composition_root_sources().values())
    assert "VerificationQueue" in joined or "verification" in joined
    for token in FORBIDDEN_RUNTIME_TOKENS:
        assert token not in joined


__all__ = [
    "COMPOSITION_ROOT_MODULES",
    "FORBIDDEN_RUNTIME_TOKENS",
]

from __future__ import annotations

import pytest

from src.config.runtime import load_runtime_config
from src.paper_shadow.a2_exact_attempt_runtime import A2PaperOutcomeStatus
from src.runtime.core_v1_composition import build_core_v1_composition
from src.runtime.core_v1_materializer import (
    CORE_V1_BLOCKED_EXTERNAL,
    CORE_V1_PROFILE_ID,
    CoreV1ReleaseProfile,
)


def _profile(config):
    return CoreV1ReleaseProfile(
        profile_id=CORE_V1_PROFILE_ID,
        strategy="circular_arbitrage",
        lender="marginfi",
        router="jupiter",
        cluster=config.cluster.name,
        genesis_hash=config.cluster.genesis_hash,
        transport="rpc",
        live_enabled=False,
    )


def test_blocked_installed_composition_reuses_one_authority(tmp_path) -> None:
    config = load_runtime_config(cli_overrides={"runtime.mode": "paper"})
    composition = build_core_v1_composition(
        config,
        db_path=tmp_path / "core-v1.sqlite3",
        profile=_profile(config),
        dependencies=None,
    )
    try:
        assert composition.admitted is False
        assert composition.blockers == (CORE_V1_BLOCKED_EXTERNAL,)
        assert composition.planner is not None
        assert composition.simulator is not None
        assert composition.vertical is not None
        assert composition.orchestrator is not None
        assert composition.runtime_cycle is not None
        assert composition.capital.store is composition.authority.lifecycle
        assert composition.orchestrator.authority is composition.authority
        assert composition.runtime_cycle.authority is composition.authority
        batch = composition.service.batch_source()
        assert batch.evidence.ready is False
        assert batch.evidence.blockers == (CORE_V1_BLOCKED_EXTERNAL,)
        assert batch.items == ()
        assert (
            composition.authority.db.execute(
                "SELECT COUNT(*) FROM durable_reservations"
            ).fetchone()[0]
            == 0
        )
    finally:
        composition.close()


@pytest.mark.asyncio
async def test_empty_exact_cycle_is_no_trade_without_rpc_or_reservation(tmp_path) -> None:
    config = load_runtime_config(cli_overrides={"runtime.mode": "paper"})
    composition = build_core_v1_composition(
        config,
        db_path=tmp_path / "core-v1-empty.sqlite3",
        profile=_profile(config),
        dependencies=None,
    )
    try:
        runtime = composition.runtime_cycle
        assert runtime is not None
        report = await runtime("healthy-empty-cycle", ())
        assert report.status is A2PaperOutcomeStatus.NO_TRADE
        assert report.ready_for_next_cycle is True
        assert report.records == ()
        assert (
            composition.authority.db.execute(
                "SELECT COUNT(*) FROM durable_reservations"
            ).fetchone()[0]
            == 0
        )
    finally:
        composition.close()

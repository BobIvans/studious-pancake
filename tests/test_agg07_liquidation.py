from __future__ import annotations

from src.liquidation.adapters import KaminoLiquidationAdapter
from src.liquidation.agg07 import (
    CollateralUnwindQuote,
    FinancingEvidence,
    LiquidationTriggerEvidence,
    build_flash_funded_liquidation_candidate,
    build_liquidation_watchlist,
    select_non_conflicting_liquidations,
)
from src.liquidation.models import (
    LendingProtocol,
    LiquidationSizingResult,
    LiquidationStatus,
    LiquidationTargetSnapshot,
    OracleSnapshot,
    PositionSnapshot,
    ProtocolDeploymentSpec,
    RiskConfigSnapshot,
)


H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64


def snapshot(
    *,
    target: str = "target-a",
    assets: int = 90,
    liabilities: int = 100,
    oracle_status: str = "fresh",
) -> LiquidationTargetSnapshot:
    deployment = ProtocolDeploymentSpec(
        protocol=LendingProtocol.KAMINO_LEND,
        cluster="mainnet-beta",
        program_id="kamino-program",
        supported_version="pinned-v1",
        pinned_source="kamino",
        pinned_commit="commit",
        idl_sha256=H1,
        verified_on="2026-09-20",
        enabled=True,
    )
    positions = (
        PositionSnapshot("debt-mint", "debt-reserve", 100, 6, "debt"),
        PositionSnapshot("coll-mint", "coll-reserve", 130, 6, "collateral"),
    )
    risk = RiskConfigSnapshot(
        close_factor_bps=5_000,
        max_liquidatable_value=None,
        liquidation_bonus_bps=1_000,
        protocol_fee_bps=50,
        insurance_fee_bps=0,
        health_assets_value=assets,
        health_liabilities_value=liabilities,
        risk_hash=H2,
    )
    oracle = OracleSnapshot(
        source="oracle",
        price_numerator=1,
        price_denominator=1,
        confidence_numerator=1,
        confidence_denominator=100,
        exponent=0,
        publish_slot=10,
        status=oracle_status,
        raw_hash=H3,
    )
    return LiquidationTargetSnapshot(
        protocol=LendingProtocol.KAMINO_LEND,
        deployment=deployment,
        market="market",
        target_account=target,
        slot=10,
        raw_hash=H4,
        positions=positions,
        risk=risk,
        oracles={"debt": oracle},
        indexer_health_assets=assets,
        indexer_health_liabilities=liabilities,
    )


def financing(*, resource: str = "lender-reserve") -> FinancingEvidence:
    return FinancingEvidence(
        lender_id="kamino-klend",
        combination_id="k1",
        principal_atomic=50,
        repayment_atomic=51,
        message_sha256=H1,
        simulation_message_sha256=H1,
        borrow_instruction_index=4,
        expected_borrow_instruction_index=4,
        qualified=True,
        shared_resource_ids=(resource,),
    )


def sizing() -> LiquidationSizingResult:
    return LiquidationSizingResult(
        status=LiquidationStatus.POTENTIALLY_LIQUIDATABLE,
        reason=None,
        repay_amount=50,
        min_collateral_seized=55,
        minimum_final_output=60,
        exact_flash_repayment=50,
        conservative_profit=10,
        sizing_hash=H2,
        bounds={"protocol_close_factor": 50},
    )


def unwind(*, resource: str = "exit-pool") -> CollateralUnwindQuote:
    return CollateralUnwindQuote(
        collateral_asset="coll-mint",
        repay_asset="debt-mint",
        input_atomic=55,
        minimum_output_atomic=60,
        route_capacity_atomic=100,
        state_sha256=H3,
        executable=True,
        shared_resource_ids=(resource,),
    )


def test_watchlist_requires_fresh_eligibility_and_forecast_is_not_permission():
    healthy = snapshot(target="healthy", assets=110, liabilities=100)
    unhealthy = snapshot(target="unhealthy", assets=90, liabilities=100)
    trigger = LiquidationTriggerEvidence(
        target_account="healthy",
        protocol=LendingProtocol.KAMINO_LEND,
        snapshot_hash=healthy.raw_hash,
        price_numerator=9,
        price_denominator=10,
        rule_hash=H1,
        oracle_fresh=True,
    )

    watch = build_liquidation_watchlist(
        (healthy, unhealthy),
        {LendingProtocol.KAMINO_LEND: KaminoLiquidationAdapter()},
        trigger_evidence={"healthy": trigger},
    )

    assert watch.entries[0].target_account == "unhealthy"
    assert watch.entries[0].eligible_now is True
    healthy_entry = watch.entries[1]
    assert healthy_entry.eligible_now is False
    assert healthy_entry.trigger_price_numerator == 9


def test_stale_oracle_is_rejected_even_when_health_is_below_threshold():
    stale = snapshot(oracle_status="stale")
    watch = build_liquidation_watchlist(
        (stale,),
        {LendingProtocol.KAMINO_LEND: KaminoLiquidationAdapter()},
    )
    assert watch.entries[0].eligible_now is False
    assert watch.entries[0].eligibility.reason is not None


def test_partial_liquidation_binds_exact_repayment_and_unwind():
    snap = snapshot()
    eligibility = KaminoLiquidationAdapter().evaluate(snap)
    candidate = build_flash_funded_liquidation_candidate(
        snap,
        eligibility,
        sizing(),
        financing(),
        unwind(),
    )
    assert candidate.accepted is True
    assert candidate.exact_financing_repayment_atomic == 51
    assert candidate.conservative_net_atomic == 9


def test_wrong_borrow_index_and_insufficient_exit_fail_closed():
    snap = snapshot()
    eligibility = KaminoLiquidationAdapter().evaluate(snap)
    bad_financing = FinancingEvidence(
        lender_id="kamino-klend",
        combination_id="k1",
        principal_atomic=50,
        repayment_atomic=61,
        message_sha256=H1,
        simulation_message_sha256=H1,
        borrow_instruction_index=3,
        expected_borrow_instruction_index=4,
        qualified=True,
    )
    candidate = build_flash_funded_liquidation_candidate(
        snap,
        eligibility,
        sizing(),
        bad_financing,
        unwind(),
    )
    assert candidate.accepted is False
    assert candidate.reason is not None
    assert "BORROW_INSTRUCTION_INDEX_MISMATCH" in candidate.reason
    assert "INSUFFICIENT_EXIT_FOR_REPAYMENT" in candidate.reason


def test_batch_never_double_spends_target_or_shared_resource():
    snap_a = snapshot(target="a")
    snap_b = snapshot(target="b")
    adapter = KaminoLiquidationAdapter()
    a = build_flash_funded_liquidation_candidate(
        snap_a,
        adapter.evaluate(snap_a),
        sizing(),
        financing(resource="shared-reserve"),
        unwind(resource="pool-a"),
    )
    b = build_flash_funded_liquidation_candidate(
        snap_b,
        adapter.evaluate(snap_b),
        sizing(),
        financing(resource="shared-reserve"),
        unwind(resource="pool-b"),
    )
    batch = select_non_conflicting_liquidations((a, b))
    assert len(batch.selected) == 1
    assert len(batch.rejected) == 1
    assert "SHARED_RESOURCE_CONFLICT" in batch.rejected[0][1]

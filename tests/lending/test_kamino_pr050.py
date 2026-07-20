from __future__ import annotations

from dataclasses import replace
import struct

import pytest

from src.config.chain_registry import (
    COMPUTE_BUDGET_PROGRAM_ADDRESS,
    NATIVE_SOL_MINT_ADDRESS,
    SYSTEM_PROGRAM_ADDRESS,
    TOKEN_2022_PROGRAM_ADDRESS,
    TOKEN_PROGRAM_ADDRESS,
)
from src.lending.kamino import (
    KAMINO_RESERVE_FIXTURE_DISCRIMINATOR,
    KaminoDeploymentProvenance,
    KaminoRegistryError,
    KaminoReserveFixture,
    KaminoShadowLiquidationPlanner,
    KaminoShadowPlanStatus,
    KaminoSupportedCombination,
    KaminoSupportedRegistry,
    ProtocolCostBreakdown,
    UntrustedKaminoLiquidationCandidate,
    estimate_liquidation_profitability,
    load_default_kamino_registry,
)

USDC_MINT = "EPjFWdd5AufqSSqeM2qP52kZmxdr4WjGmrrSSJbptN5"
KLEND_PROGRAM = "SLendK7ySfcEzyaFqy93gDnD3RtrpXJcnRwb6zFHJSh"
CLOCK_SYSVAR = "SysvarC1ock11111111111111111111111111111111"
RENT_SYSVAR = "SysvarRent111111111111111111111111111111111"
HEX_64 = "a" * 64


def _provenance() -> KaminoDeploymentProvenance:
    return KaminoDeploymentProvenance(
        source_url="https://github.com/Kamino-Finance/klend-sdk",
        sdk_package="@kamino-finance/klend-sdk",
        lending_program_id=KLEND_PROGRAM,
        idl_sha256=HEX_64,
        rpc_fixture_sha256="b" * 64,
        deployment_slot=1,
        reviewed_at="2026-07-20",
    ).validated()


def _combination(
    *,
    verified: bool = True,
    min_profit: int = 100_000,
) -> KaminoSupportedCombination:
    return KaminoSupportedCombination(
        combination_id="mainnet-sol-usdc",
        cluster="mainnet-beta",
        lending_program_id=KLEND_PROGRAM,
        market_address=SYSTEM_PROGRAM_ADDRESS,
        collateral_mint=NATIVE_SOL_MINT_ADDRESS,
        debt_mint=USDC_MINT,
        collateral_reserve=TOKEN_PROGRAM_ADDRESS,
        debt_reserve=TOKEN_2022_PROGRAM_ADDRESS,
        collateral_oracle=CLOCK_SYSVAR,
        debt_oracle=RENT_SYSVAR,
        liquidation_bonus_bps=500,
        protocol_fee_bps=25,
        flash_loan_fee_bps=9,
        min_net_profit_lamports=min_profit,
        writable_accounts=(
            SYSTEM_PROGRAM_ADDRESS,
            TOKEN_PROGRAM_ADDRESS,
            TOKEN_2022_PROGRAM_ADDRESS,
            COMPUTE_BUDGET_PROGRAM_ADDRESS,
        ),
        provenance=_provenance(),
        verified=verified,
    ).validated()


def _candidate(
    *,
    health_factor_bps: int = 9_500,
    bonus: int = 500_000,
) -> UntrustedKaminoLiquidationCandidate:
    return UntrustedKaminoLiquidationCandidate(
        combination_id="mainnet-sol-usdc",
        obligation_account=COMPUTE_BUDGET_PROGRAM_ADDRESS,
        health_factor_bps=health_factor_bps,
        max_repay_lamports=10_000_000,
        expected_bonus_lamports=bonus,
        costs=ProtocolCostBreakdown(
            network_fee_lamports=5_000,
            priority_fee_lamports=20_000,
            rent_lamports=50_000,
            slippage_lamports=10_000,
        ),
    )


def test_default_kamino_registry_is_empty_and_has_no_fallback() -> None:
    registry = load_default_kamino_registry()
    planner = KaminoShadowLiquidationPlanner(registry)

    plan = planner.plan(_candidate())

    assert registry.verified_combinations == ()
    assert plan.accepted is False
    assert plan.status is KaminoShadowPlanStatus.NO_VERIFIED_COMBINATION
    assert "no verified Kamino combinations" in plan.reason


def test_unverified_combination_is_not_supported() -> None:
    registry = KaminoSupportedRegistry((_combination(verified=False),))
    planner = KaminoShadowLiquidationPlanner(registry)

    plan = planner.plan(_candidate())

    assert plan.accepted is False
    assert plan.status is KaminoShadowPlanStatus.NO_VERIFIED_COMBINATION


def test_profitability_includes_protocol_flash_and_network_costs() -> None:
    combination = _combination(min_profit=100_000)
    estimate = estimate_liquidation_profitability(_candidate(), combination)

    assert estimate.gross_bonus_lamports == 500_000
    assert estimate.costs.protocol_fee_lamports == 25_000
    assert estimate.costs.flash_loan_fee_lamports == 9_000
    assert estimate.total_cost_lamports == 119_000
    assert estimate.net_profit_lamports == 381_000
    assert estimate.meets_min_profit is True


def test_shadow_planner_accepts_only_liquidatable_profitable_verified_candidate() -> None:
    combination = _combination(min_profit=100_000)
    registry = KaminoSupportedRegistry((combination,))
    planner = KaminoShadowLiquidationPlanner(registry)

    plan = planner.plan(_candidate())

    assert plan.accepted is True
    assert plan.status is KaminoShadowPlanStatus.ACCEPTED
    assert plan.net_profit_lamports == 381_000
    assert plan.writable_accounts == combination.writable_accounts


def test_shadow_planner_rejects_healthy_or_unprofitable_candidate() -> None:
    registry = KaminoSupportedRegistry((_combination(min_profit=100_000),))
    planner = KaminoShadowLiquidationPlanner(registry)

    healthy = planner.plan(_candidate(health_factor_bps=10_000))
    weak = planner.plan(_candidate(bonus=100_000))

    assert healthy.status is KaminoShadowPlanStatus.OBLIGATION_NOT_LIQUIDATABLE
    assert weak.status is KaminoShadowPlanStatus.NOT_PROFITABLE_AFTER_COSTS
    assert weak.net_profit_lamports < 100_000


def test_registry_rejects_bad_provenance_and_missing_writable_metas() -> None:
    with pytest.raises(KaminoRegistryError, match="Kamino-Finance"):
        KaminoDeploymentProvenance(
            source_url="https://github.com/random/fork",
            sdk_package="@kamino-finance/klend-sdk",
            lending_program_id=KLEND_PROGRAM,
            idl_sha256=HEX_64,
            rpc_fixture_sha256=HEX_64,
            deployment_slot=1,
            reviewed_at="2026-07-20",
        ).validated()

    broken = replace(
        _combination(),
        writable_accounts=(SYSTEM_PROGRAM_ADDRESS,),
    )
    with pytest.raises(KaminoRegistryError, match="writable_accounts"):
        broken.validated()


def test_reserve_fixture_decoder_fails_closed_on_bad_bytes() -> None:
    payload = struct.pack(
        "<8sQQQHHHH",
        KAMINO_RESERVE_FIXTURE_DISCRIMINATOR,
        1_000_000,
        2_000_000,
        1_234_567,
        6_000,
        8_000,
        25,
        500,
    )

    parsed = KaminoReserveFixture.parse(payload)

    assert parsed.available_liquidity_lamports == 1_000_000
    assert parsed.liquidation_threshold_bps == 8_000

    with pytest.raises(KaminoRegistryError, match="discriminator"):
        KaminoReserveFixture.parse(b"BADRESV!" + payload[8:])

    with pytest.raises(KaminoRegistryError, match="exactly"):
        KaminoReserveFixture.parse(payload[:-1])

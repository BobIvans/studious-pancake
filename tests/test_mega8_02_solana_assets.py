from __future__ import annotations

import pytest

from src.mega8_02.core import EvidenceBinding, Mega802Error
from src.mega8_02.pr177 import (
    ProgramChange,
    classify_upgrade_impact,
    trigger_protocol_requalification,
)
from src.mega8_02.pr178 import (
    OracleSample,
    detect_oracle_update_lag,
    model_oracle_publish_schedule,
)
from src.mega8_02.pr179 import (
    StablecoinRight,
    detect_stablecoin_parity_cycle,
    quote_stablecoin_conversion,
)
from src.mega8_02.pr180 import (
    VaultSemantics,
    detect_vault_share_parity,
    read_vault_nav_and_capacity,
)
from src.mega8_02.pr181 import (
    YieldExchangeRate,
    normalize_accrual_index,
    quote_immediate_yield_conversion,
)
from src.mega8_02.pr182 import (
    StakePool,
    model_exit_queue_capacity,
    rank_lender_independent_lst_edges,
)
from src.mega8_02.pr183 import (
    StakeAccountQuote,
    build_stake_account_route,
    simulate_stake_account_cycle,
)
from src.mega8_02.pr184 import LPPoolState, compute_lp_token_nav, detect_lp_nav_cycle
from src.mega8_02.pr185 import (
    InventoryEvent,
    collect_fee_sweep_events,
    estimate_inventory_release_impact,
)


def evidence() -> EvidenceBinding:
    return EvidenceBinding("state-1", "b" * 64, "schema-1", 10, 100)


def test_program_change_and_oracle_contracts() -> None:
    change = ProgramChange("program", "v1", "v2", "binary", evidence())
    assert classify_upgrade_impact(change) == "REQUALIFY_ALL_CAPABILITIES"
    assert len(trigger_protocol_requalification(change, now=20)) == 64

    samples = (
        OracleSample(10, 11, 100, 2),
        OracleSample(20, 21, 101, 2),
        OracleSample(30, 32, 102, 2),
    )
    assert model_oracle_publish_schedule(samples) == (10, 10)
    assert detect_oracle_update_lag(samples[-1], max_lag=2) == 2
    with pytest.raises(Mega802Error, match="ORACLE_UPDATE_LAG"):
        detect_oracle_update_lag(samples[-1], max_lag=1)


def test_stable_vault_yield_and_lp_are_capacity_bounded_integer_math() -> None:
    stable = StablecoinRight("USDX", "USDC", 1, 1, 1, 100, evidence())
    assert quote_stablecoin_conversion(stable, amount=10, now=20) == 9
    assert detect_stablecoin_parity_cycle(
        stable, amount=10, dex_guaranteed_out=11, now=20
    ) == 2
    with pytest.raises(Mega802Error, match="CAPACITY"):
        quote_stablecoin_conversion(stable, amount=101, now=20)

    vault = VaultSemantics(
        "vault", "vSHARE", 100, {"USDC": 200}, 50, 50, evidence()
    )
    nav, mint_cap, burn_cap = read_vault_nav_and_capacity(
        vault, {"USDC": 1_000_000}, now=20
    )
    assert (nav, mint_cap, burn_cap) == (2_000_000, 50, 50)
    assert detect_vault_share_parity(
        intrinsic_value=20, market_value=18
    ) == 2

    rate = YieldExchangeRate("y", "u", 105, 100, 1000, evidence())
    assert normalize_accrual_index(rate) == (21, 20)
    assert quote_immediate_yield_conversion(rate, amount=100, now=20) == 105

    lp = LPPoolState(
        "pool", 100, {"A": 50, "B": 50}, 20, 20, evidence()
    )
    assert compute_lp_token_nav(
        lp, {"A": 1_000_000, "B": 1_000_000}, now=20
    ) == 1_000_000
    assert detect_lp_nav_cycle(nav_value=100, secondary_market_value=90) == 10


def test_lst_stake_account_and_inventory_paths_remain_offline() -> None:
    pool = StakePool("p", "lst", 11, 10, 50, 500, evidence())
    assert model_exit_queue_capacity(pool, immediate_required=True) == 50
    assert model_exit_queue_capacity(pool, immediate_required=False) == 550
    assert rank_lender_independent_lst_edges((pool,)) == ("p",)

    quote = StakeAccountQuote("stake", 100, 110, 100, evidence())
    route_id = build_stake_account_route(quote, amount=50, now=20)
    assert len(route_id) == 64
    assert simulate_stake_account_cycle(
        quote, amount=50, dex_guaranteed_out=60, now=20
    ) == 5

    fee = InventoryEvent("proto", "USDC", 50, "fee_sweep", 40, evidence())
    other = InventoryEvent("proto", "USDC", 10, "reserve", 10, evidence())
    assert collect_fee_sweep_events((fee, other), now=20) == (fee,)
    assert estimate_inventory_release_impact(fee, depth=100) == 400_000


def test_stale_structural_evidence_fails_closed() -> None:
    stale = EvidenceBinding("state", "c" * 64, "schema", 1, 2)
    stable = StablecoinRight("A", "B", 1, 1, 0, 10, stale)
    with pytest.raises(Mega802Error, match="stale"):
        quote_stablecoin_conversion(stable, amount=1, now=2)

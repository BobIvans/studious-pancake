import pytest

from src.ingest.jito_bundle_handler import BackrunTrigger
from src.ingest.pump_fun_predictor import (
    PUMP_LEGACY_HEURISTIC_DISABLED,
    PumpFunBondingCurve,
    PumpLegacyHeuristicDisabled,
)
from src.strategy.interfaces import StrategyMode
from src.strategy.strategies import PumpMigrationStrategy
from src.venues.pump.adapter import (
    TOKEN_2022_PROGRAM,
    TOKEN_PROGRAM,
    PumpAdapter,
    PumpContractManifest,
)
from src.venues.pump.models import (
    PumpFamily,
    PumpLifecycle,
    RawAccount,
    ReasonCode,
    SwapDirection,
)


def pk(ch):
    return (ch.encode() * 32)[:32]


def bonding_data(complete=False):
    disc = bytes.fromhex("17b7f83760d8ac60")
    vals = [1_000_000, 2_000_000, 500_000, 800_000, 1_000_000_000]
    raw = (
        disc
        + b"".join(v.to_bytes(8, "little") for v in vals)
        + bytes([complete])
        + pk("B")
        + bytes([0, 0])
        + pk("Q")
    )
    return raw + bytes(137 - len(raw))


def pool_data(virtual=0):
    disc = bytes.fromhex("f19a6d0411b16dbc")
    body = (
        (1).to_bytes(1, "little")
        + (0).to_bytes(2, "little")
        + pk("C")
        + pk("B")
        + pk("Q")
        + pk("L")
        + pk("A")
        + pk("V")
        + (1_000_000).to_bytes(8, "little")
        + pk("O")
        + bytes([0, 0])
        + int(virtual).to_bytes(16, "little", signed=True)
    )
    return disc + body + bytes(261 - 8 - len(body))


def acct(data, family=PumpFamily.BONDING_CURVE, slot=100, owner=None):
    spec = PumpContractManifest.load().by_family(family)
    return RawAccount("acct", owner or spec.program_id, data, False, slot)


def test_contract_detection_and_layout_fail_closed():
    a = PumpAdapter()
    dec = a.decode_account(PumpFamily.BONDING_CURVE, acct(bonding_data()))
    assert dec.real_quote_reserves == 800_000 and dec.quote_mint == pk("Q").hex()
    with pytest.raises(ValueError, match=ReasonCode.PUMP_OWNER_MISMATCH.value):
        a.decode_account(PumpFamily.BONDING_CURVE, acct(bonding_data(), owner="bad"))
    with pytest.raises(ValueError, match=ReasonCode.PUMP_LAYOUT_SIZE_MISMATCH.value):
        a.decode_account(PumpFamily.BONDING_CURVE, acct(bonding_data()[:114]))
    with pytest.raises(ValueError, match=ReasonCode.PUMP_DISCRIMINATOR_MISMATCH.value):
        a.decode_account(PumpFamily.BONDING_CURVE, acct(b"0" * 137))


def test_lifecycle_and_snapshot_slot_consistency():
    a = PumpAdapter()
    active = a.build_snapshot(
        PumpFamily.BONDING_CURVE,
        "mint",
        (acct(bonding_data(False)),),
        {pk("B").hex(): TOKEN_PROGRAM},
    )
    assert active.lifecycle is PumpLifecycle.BONDING_ACTIVE
    pending = a.build_snapshot(
        PumpFamily.BONDING_CURVE,
        "mint",
        (acct(bonding_data(True)),),
        {},
    )
    assert pending.lifecycle is PumpLifecycle.BONDING_COMPLETE_PENDING_DESTINATION
    confirmed = a.build_snapshot(
        PumpFamily.BONDING_CURVE,
        "mint",
        (acct(bonding_data(True)),),
        {},
        destination_verified=True,
    )
    assert confirmed.lifecycle is PumpLifecycle.MIGRATION_CONFIRMED
    with pytest.raises(ValueError, match=ReasonCode.PUMP_MIXED_SLOT.value):
        a.build_snapshot(
            PumpFamily.BONDING_CURVE,
            "mint",
            (acct(bonding_data(), slot=100), acct(bonding_data(), slot=99)),
            {},
        )


def test_bonding_quote_and_instruction_order_shadow_only():
    a = PumpAdapter()
    snap = a.build_snapshot(
        PumpFamily.BONDING_CURVE,
        "mint",
        (acct(bonding_data()),),
        {pk("B").hex(): TOKEN_PROGRAM},
    )
    q = a.quote_exact_in(snap, SwapDirection.BUY, 1000, 1)
    assert q.executable_in_shadow and q.net_out_amount > 0
    metas = PumpContractManifest.load().by_family(PumpFamily.BONDING_CURVE).ordered_metas[
        "buy"
    ]
    accounts = {m: f"{m}_addr" for m in metas if m != "user"}
    ix, _ = a.build_swap_ix(snap, q, accounts, "user_addr")
    assert ix.kind == "pump_shadow_swap" and ix.name == "buy"
    assert ix.accounts == tuple(
        "user_addr" if m == "user" else accounts[m] for m in metas
    )
    assert "EXECUTABLE_LIVE" not in a.capabilities and a.live_capability is None


def test_pumpswap_virtual_quote_reserves_affects_quote():
    a = PumpAdapter()
    s0 = a.build_snapshot(
        PumpFamily.PUMPSWAP,
        "mint",
        (acct(pool_data(0), PumpFamily.PUMPSWAP),),
        {},
    )
    s1 = a.build_snapshot(
        PumpFamily.PUMPSWAP,
        "mint",
        (acct(pool_data(800_000), PumpFamily.PUMPSWAP),),
        {},
    )
    q0 = a.quote_exact_in(s0, SwapDirection.BUY, 1000, 1)
    q1 = a.quote_exact_in(s1, SwapDirection.BUY, 1000, 1)
    assert q0.reject_reason is ReasonCode.PUMP_FEE_STATE_INCOMPLETE
    assert q1.reject_reason is ReasonCode.PUMP_FEE_STATE_INCOMPLETE
    assert q0.net_out_amount == q1.net_out_amount == 0


def test_token_2022_policy_and_legacy_disabled():
    a = PumpAdapter()
    assert a.validate_token_policy(TOKEN_PROGRAM) is None
    assert (
        a.validate_token_policy(
            TOKEN_2022_PROGRAM,
            ("metadata_pointer",),
            allow_token_2022=True,
        )
        is None
    )
    assert (
        a.validate_token_policy(
            TOKEN_2022_PROGRAM,
            ("transfer_hook",),
            allow_token_2022=True,
        )
        is ReasonCode.PUMP_UNSUPPORTED_TOKEN_EXTENSION
    )
    with pytest.raises(PumpLegacyHeuristicDisabled):
        PumpFunBondingCurve("x").parse_state("")
    assert PUMP_LEGACY_HEURISTIC_DISABLED == "PUMP_LEGACY_HEURISTIC_DISABLED"


@pytest.mark.asyncio
async def test_backrun_and_strategy_disabled_shadow_only():
    s = PumpMigrationStrategy()
    assert s.mode is StrategyMode.DISABLED
    s2 = PumpMigrationStrategy(adapter_configured=True)
    assert s2.mode is StrategyMode.SHADOW
    r = await BackrunTrigger(object()).on_migration_event(
        signature="sig",
        base_mint="b",
        quote_mint="q",
        recent_blockhash="bad",
    )
    assert r["success"] is False and r["reason"] == "PUMP_LEGACY_HEURISTIC_DISABLED"

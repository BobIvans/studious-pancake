from dataclasses import replace
import pytest
from src.inventory.mm_replay import TapeTrade, replay_resting_order
from src.inventory.non_atomic import (
    DurableInventoryLedger,
    InstrumentIdentity,
    OrderIntent,
    OrderSide,
    InventoryError,
)


def test_queue_cancel_latency_adverse_selection_and_durable_inventory(tmp_path):
    ledger = DurableInventoryLedger(tmp_path / "inventory.db")
    intent = OrderIntent(
        "o",
        "mm",
        InstrumentIdentity("venue", "A-B", "B", "A-atoms"),
        OrderSide.BUY,
        10,
        100,
        10,
        "a" * 64,
    )
    tape = (
        TapeTrade("early", 11, 10, 20, OrderSide.SELL),
        TapeTrade("first", 20, 10, 6, OrderSide.SELL),
        TapeTrade("second", 30, 10, 4, OrderSide.SELL),
        TapeTrade("cancel-race", 40, 10, 10, OrderSide.SELL),
    )
    args = dict(
        ledger=ledger,
        intent=intent,
        tape=tape,
        limit_price_quote_atoms_per_base_atom=10,
        queue_ahead_base_atoms=5,
        arrival_latency_ns=5,
        cancel_acknowledged_at_ns=40,
        terminal_mid_quote_atoms_per_base_atom=9,
        fee_bps=0,
        hedge_cost_quote_atoms=2,
        wallet_available_base_atoms=0,
        wallet_available_quote_atoms=102,
    )
    result = replay_resting_order(**args)
    assert result.filled_base_atoms == 5
    assert result.markout_quote_atoms == -5
    assert result.terminal_marked_net_quote_atoms == -7
    assert ledger.position_for_order("o").signed_quantity_base_units == 5
    with pytest.raises(InventoryError, match="FLASH"):
        replay_resting_order(**{**args, "funding_mode": "flash"})
    ledger.close()
    ledger = DurableInventoryLedger(tmp_path / "inventory.db")
    assert ledger.position_for_order("o").signed_quantity_base_units == 5
    ledger.close()

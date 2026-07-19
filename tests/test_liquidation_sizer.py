from tests.test_liquidation_adapters import snap
from src.liquidation.adapters import KaminoLiquidationAdapter
from src.liquidation.sizer import LiquidationSizer, LiquidationSizingPolicy
from src.liquidation.models import *

def elig(): return KaminoLiquidationAdapter().evaluate(snap())
def liq(**kw):
    d=dict(debt_reserve_liquidity=20,flash_capacity=20,route_capacity=20,route_min_out=11,route_is_executable=True,token2022_transfer_fee_bps=0,slot=10,provenance='p')
    d.update(kw); return LiquiditySnapshot(**d)

def test_sizer_caps_and_profit_integer():
    r=LiquidationSizer().size(snap(), elig(), liq(), LiquidationSizingPolicy(20,1000,20_000_000,15_000_000))
    assert r.repay_amount == 10 and r.minimum_final_output >= r.exact_flash_repayment

def test_wallet_near_reserve_rejects():
    r=LiquidationSizer().size(snap(), elig(), liq(), LiquidationSizingPolicy(20,1000,15_000_000,15_000_000))
    assert r.reason is LiquidationReason.LIQUIDATION_STRATEGY_CAP_EXCEEDED

def test_unexecutable_route_rejects():
    assert LiquidationSizer().size(snap(), elig(), liq(route_is_executable=False), LiquidationSizingPolicy(20,0,20_000_000,15_000_000)).reason is LiquidationReason.UNWIND_ROUTE_NOT_EXECUTABLE

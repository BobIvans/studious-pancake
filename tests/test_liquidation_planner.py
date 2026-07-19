from tests.test_liquidation_adapters import snap
from tests.test_liquidation_sizer import elig, liq
from src.liquidation.adapters import KaminoLiquidationAdapter
from src.liquidation.planner import LiquidationPlanner
from src.liquidation.sizer import LiquidationSizer, LiquidationSizingPolicy
from src.liquidation.models import *

def test_plan_order_and_hash():
    s=snap(); e=elig(); z=LiquidationSizer().size(s,e,liq(),LiquidationSizingPolicy(20,0,20_000_000,15_000_000))
    p=LiquidationPlanner(KaminoLiquidationAdapter()).plan(s,e,z)
    assert [i.name for i in p.instructions] == ['start_flashloan','borrow','liquidate','unwind','repay','end_flashloan']
    assert p.end_flashloan_index == 5 and p.plan_hash

def test_unsupported_financing_rejects():
    s=snap(); e=elig(); z=LiquidationSizer().size(s,e,liq(),LiquidationSizingPolicy(20,0,20_000_000,15_000_000))
    assert LiquidationPlanner(KaminoLiquidationAdapter()).plan(s,e,z,financing='kamino_flash').reason is LiquidationReason.FINANCING_TARGET_COMBINATION_UNSUPPORTED

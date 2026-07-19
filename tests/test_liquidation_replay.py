from tests.test_liquidation_adapters import snap
from tests.test_liquidation_sizer import liq
from src.liquidation.adapters import KaminoLiquidationAdapter
from src.liquidation.eligibility import LiquidationEligibilityEngine
from src.liquidation.planner import LiquidationPlanner
from src.liquidation.simulation import LiquidationSimulationReconciler
from src.liquidation.sizer import LiquidationSizer, LiquidationSizingPolicy
from src.liquidation.strategy import ShadowLiquidationStrategy
from src.liquidation.models import *

def test_strategy_terminal_shadow_no_sender_flags():
    strat=ShadowLiquidationStrategy(LiquidationEligibilityEngine((KaminoLiquidationAdapter(),)),LiquidationSizer(),{LendingProtocol.KAMINO_LEND: LiquidationPlanner(KaminoLiquidationAdapter())},LiquidationSimulationReconciler(),LiquidationSizingPolicy(20,0,20_000_000,15_000_000))
    out=strat.evaluate_shadow(snap(), liq(), simulation_success=True, flash_repaid=True, postconditions_proven=True, simulated_profit=1)
    assert out.status is LiquidationStatus.SIMULATED_LIQUIDATION_RECONCILED
    assert not out.sent_transaction and not out.live_permit_issued

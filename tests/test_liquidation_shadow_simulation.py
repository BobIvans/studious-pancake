from src.liquidation.simulation import LiquidationSimulationReconciler
from src.liquidation.models import *

def plan(): return LiquidationInstructionPlan(LiquidationStatus.POTENTIALLY_LIQUIDATABLE,None,(),5,'m','p')
def test_reconciled_requires_repay_and_postconditions():
    ev=LiquidationSimulationReconciler().reconcile(plan(), success=True, flash_repaid=True, postconditions_proven=True, simulated_profit=1, simulation_slot=1)
    assert ev.status is LiquidationStatus.SIMULATED_LIQUIDATION_RECONCILED
    assert LiquidationSimulationReconciler().reconcile(plan(), success=True, flash_repaid=False, postconditions_proven=True, simulated_profit=1, simulation_slot=1).reason is LiquidationReason.SIMULATED_LIQUIDATION_REPAYMENT_FAILED
    assert LiquidationSimulationReconciler().reconcile(plan(), success=True, flash_repaid=True, postconditions_proven=False, simulated_profit=1, simulation_slot=1).reason is LiquidationReason.LIQUIDATION_POSTCONDITION_UNPROVEN

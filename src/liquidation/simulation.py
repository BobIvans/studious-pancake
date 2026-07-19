from __future__ import annotations
from .models import *

class LiquidationSimulationReconciler:
    def reconcile(self, plan: LiquidationInstructionPlan, *, success: bool, flash_repaid: bool, postconditions_proven: bool, simulated_profit: int, simulation_slot: int) -> LiquidationSimulationEvidence:
        if not success:
            status, reason = LiquidationStatus.SIMULATED_NOT_LIQUIDATABLE, LiquidationReason.LIQUIDATION_POSTCONDITION_UNPROVEN
        elif not flash_repaid:
            status, reason = LiquidationStatus.SIMULATED_REPAYMENT_FAILED, LiquidationReason.SIMULATED_LIQUIDATION_REPAYMENT_FAILED
        elif not postconditions_proven:
            status, reason = LiquidationStatus.PRE_SIMULATION_REJECTED, LiquidationReason.LIQUIDATION_POSTCONDITION_UNPROVEN
        elif simulated_profit < 0:
            status, reason = LiquidationStatus.SIMULATED_UNPROFITABLE, LiquidationReason.SIMULATED_LIQUIDATION_UNPROFITABLE
        else:
            status, reason = LiquidationStatus.SIMULATED_LIQUIDATION_RECONCILED, LiquidationReason.SIMULATED_LIQUIDATION_RECONCILED
        return LiquidationSimulationEvidence(status, reason, flash_repaid, postconditions_proven, simulated_profit, simulation_slot, canonical_hash({"plan": plan.plan_hash, "slot": simulation_slot, "profit": simulated_profit, "repaid": flash_repaid, "post": postconditions_proven}))

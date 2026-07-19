"""PR-023 QUARANTINE: fixture-only liquidation orchestration.

Shadow-only liquidation strategy orchestration.

No sender, signer, Jito, keypair, or live permit modules are imported here.
"""
from __future__ import annotations
from .eligibility import LiquidationEligibilityEngine
from .models import *
from .planner import LiquidationPlanner
from .simulation import LiquidationSimulationReconciler
from .sizer import LiquidationSizer, LiquidationSizingPolicy

class ShadowLiquidationStrategy:
    mode = "enabled_shadow"
    live_enabled = False
    def __init__(self, engine: LiquidationEligibilityEngine, sizer: LiquidationSizer, planner_by_protocol: dict[LendingProtocol, LiquidationPlanner], reconciler: LiquidationSimulationReconciler, policy: LiquidationSizingPolicy):
        self.engine=engine; self.sizer=sizer; self.planner_by_protocol=planner_by_protocol; self.reconciler=reconciler; self.policy=policy; self._seen=set()
    def candidate_key(self, snapshot: LiquidationTargetSnapshot) -> str:
        return canonical_hash({"protocol": snapshot.protocol.value, "target": snapshot.target_account, "slot": snapshot.slot, "raw": snapshot.raw_hash, "risk": snapshot.risk.risk_hash})
    def evaluate_shadow(self, snapshot: LiquidationTargetSnapshot, liquidity: LiquiditySnapshot, *, simulation_success=False, flash_repaid=False, postconditions_proven=False, simulated_profit=0) -> LiquidationShadowOutcome:
        key=self.candidate_key(snapshot)
        if key in self._seen:
            return LiquidationShadowOutcome(LiquidationStatus.PRE_SIMULATION_REJECTED, LiquidationReason.TARGET_STATE_STALE, snapshot.target_account, snapshot.protocol, None, None)
        self._seen.add(key)
        elig=self.engine.evaluate(snapshot)
        if elig.status is not LiquidationStatus.POTENTIALLY_LIQUIDATABLE:
            return LiquidationShadowOutcome(elig.status, elig.reason, snapshot.target_account, snapshot.protocol, None, None)
        sizing=self.sizer.size(snapshot, elig, liquidity, self.policy)
        planner=self.planner_by_protocol.get(snapshot.protocol)
        if planner is None:
            return LiquidationShadowOutcome(LiquidationStatus.PRE_SIMULATION_REJECTED, LiquidationReason.LIQUIDATION_PROTOCOL_UNSUPPORTED, snapshot.target_account, snapshot.protocol, None, None)
        plan=planner.plan(snapshot, elig, sizing)
        if plan.status is not LiquidationStatus.POTENTIALLY_LIQUIDATABLE:
            return LiquidationShadowOutcome(plan.status, plan.reason, snapshot.target_account, snapshot.protocol, plan.plan_hash, None)
        ev=self.reconciler.reconcile(plan, success=simulation_success, flash_repaid=flash_repaid, postconditions_proven=postconditions_proven, simulated_profit=simulated_profit, simulation_slot=snapshot.slot)
        return LiquidationShadowOutcome(ev.status, ev.reason, snapshot.target_account, snapshot.protocol, plan.plan_hash, ev.evidence_hash)

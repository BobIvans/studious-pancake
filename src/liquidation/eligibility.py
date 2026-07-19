from __future__ import annotations
from .adapters import LiquidationAdapter
from .models import LiquidationEligibility, LiquidationTargetSnapshot

class LiquidationEligibilityEngine:
    def __init__(self, adapters: tuple[LiquidationAdapter, ...], *, max_slot_skew: int = 0):
        self.adapters = {a.protocol: a for a in adapters}; self.max_slot_skew = max_slot_skew
    def evaluate(self, snapshot: LiquidationTargetSnapshot) -> LiquidationEligibility:
        adapter = self.adapters.get(snapshot.protocol)
        if adapter is None:
            from .models import LiquidationStatus, LiquidationReason
            return LiquidationEligibility(LiquidationStatus.PRE_SIMULATION_REJECTED, LiquidationReason.LIQUIDATION_PROTOCOL_UNSUPPORTED)
        return adapter.evaluate(snapshot, max_slot_skew=self.max_slot_skew)

"""Protocol-specific liquidation adapters backed by pinned snapshot evidence."""
from __future__ import annotations
from abc import ABC, abstractmethod
from .models import *

class LiquidationAdapter(ABC):
    protocol: LendingProtocol
    @abstractmethod
    def validate_deployment(self, snapshot: LiquidationTargetSnapshot) -> LiquidationReason | None: ...
    def evaluate(self, snapshot: LiquidationTargetSnapshot, *, max_slot_skew: int = 0) -> LiquidationEligibility:
        reason = self.validate_deployment(snapshot)
        if reason:
            return LiquidationEligibility(LiquidationStatus.PRE_SIMULATION_REJECTED, reason, trace=("deployment rejected",))
        if not snapshot.positions or not snapshot.oracles:
            return LiquidationEligibility(LiquidationStatus.PRE_SIMULATION_REJECTED, LiquidationReason.TARGET_SNAPSHOT_INCOMPLETE)
        if snapshot.risk.close_factor_bps is None:
            return LiquidationEligibility(LiquidationStatus.PRE_SIMULATION_REJECTED, LiquidationReason.CLOSE_FACTOR_UNKNOWN)
        if snapshot.risk.liquidation_bonus_bps is None:
            return LiquidationEligibility(LiquidationStatus.PRE_SIMULATION_REJECTED, LiquidationReason.LIQUIDATION_BONUS_UNKNOWN)
        for oracle in snapshot.oracles.values():
            if oracle.status != "fresh":
                return LiquidationEligibility(LiquidationStatus.PRE_SIMULATION_REJECTED, LiquidationReason.ORACLE_STALE)
            if oracle.confidence_numerator < 0 or oracle.confidence_denominator <= 0:
                return LiquidationEligibility(LiquidationStatus.PRE_SIMULATION_REJECTED, LiquidationReason.ORACLE_CONFIDENCE_INVALID)
            if abs(snapshot.slot - oracle.publish_slot) > max_slot_skew:
                return LiquidationEligibility(LiquidationStatus.PRE_SIMULATION_REJECTED, LiquidationReason.LIQUIDATION_SLOT_INCONSISTENT)
        if (snapshot.indexer_health_assets, snapshot.indexer_health_liabilities) != (snapshot.risk.health_assets_value, snapshot.risk.health_liabilities_value):
            return LiquidationEligibility(LiquidationStatus.PRE_SIMULATION_REJECTED, LiquidationReason.HEALTH_MODEL_MISMATCH)
        if not self._is_liquidatable(snapshot):
            return LiquidationEligibility(LiquidationStatus.PRE_SIMULATION_REJECTED, LiquidationReason.TARGET_NOT_LIQUIDATABLE)
        debt = next((p for p in snapshot.positions if p.role == "debt" and p.amount > 0), None)
        coll = next((p for p in snapshot.positions if p.role == "collateral" and p.amount > 0), None)
        if debt is None or coll is None:
            return LiquidationEligibility(LiquidationStatus.PRE_SIMULATION_REJECTED, LiquidationReason.DEBT_OR_COLLATERAL_NOT_ELIGIBLE)
        max_repay = debt.amount * snapshot.risk.close_factor_bps // 10_000
        if snapshot.risk.max_liquidatable_value is not None:
            max_repay = min(max_repay, snapshot.risk.max_liquidatable_value)
        return LiquidationEligibility(LiquidationStatus.POTENTIALLY_LIQUIDATABLE, None, debt, coll, max_repay, ("adapter-prefilter", self.protocol.value))
    @abstractmethod
    def _is_liquidatable(self, snapshot: LiquidationTargetSnapshot) -> bool: ...
    def liquidation_instruction(self, snapshot: LiquidationTargetSnapshot, eligibility: LiquidationEligibility, repay_amount: int) -> LiquidationInstruction:
        if not eligibility.debt or not eligibility.collateral:
            raise ValueError("eligible debt/collateral required")
        data = canonical_hash({"ix":"liquidate","protocol":self.protocol.value,"repay":repay_amount})[:16]
        return LiquidationInstruction(snapshot.deployment.program_id, "liquidate", (snapshot.target_account, eligibility.debt.bank_or_reserve, eligibility.collateral.bank_or_reserve), data)

class KaminoLiquidationAdapter(LiquidationAdapter):
    protocol = LendingProtocol.KAMINO_LEND
    def validate_deployment(self, snapshot):
        if snapshot.protocol is not self.protocol: return LiquidationReason.LIQUIDATION_PROTOCOL_UNSUPPORTED
        if not snapshot.deployment.enabled: return snapshot.deployment.disabled_reason or LiquidationReason.LIQUIDATION_PROTOCOL_UNSUPPORTED
        if snapshot.deployment.protocol is not self.protocol: return LiquidationReason.LIQUIDATION_DEPLOYMENT_MISMATCH
        if not snapshot.deployment.idl_sha256: return LiquidationReason.LIQUIDATION_IDL_VERSION_MISMATCH
        return None
    def _is_liquidatable(self, snapshot):
        return snapshot.risk.health_liabilities_value > snapshot.risk.health_assets_value

class MarginFiLiquidationAdapter(LiquidationAdapter):
    protocol = LendingProtocol.MARGINFI_V2
    def validate_deployment(self, snapshot):
        if snapshot.protocol is not self.protocol: return LiquidationReason.LIQUIDATION_PROTOCOL_UNSUPPORTED
        if not snapshot.deployment.enabled: return snapshot.deployment.disabled_reason or LiquidationReason.LIQUIDATION_PROTOCOL_UNSUPPORTED
        if snapshot.deployment.protocol is not self.protocol: return LiquidationReason.LIQUIDATION_DEPLOYMENT_MISMATCH
        if not snapshot.deployment.program_id or not snapshot.deployment.idl_sha256: return LiquidationReason.LIQUIDATION_IDL_VERSION_MISMATCH
        return None
    def _is_liquidatable(self, snapshot):
        # MarginFi docs expose liquidation at health <= 0%; snapshot supplies weighted integer health evidence.
        return snapshot.risk.health_assets_value <= snapshot.risk.health_liabilities_value

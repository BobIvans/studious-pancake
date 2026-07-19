from __future__ import annotations
from dataclasses import dataclass
from .models import *

@dataclass(frozen=True, slots=True)
class LiquidationSizingPolicy:
    strategy_cap: int
    fee_budget: int
    wallet_operational_lamports: int
    protected_reserve_lamports: int

class LiquidationSizer:
    """Conservative integer sizer; delegates wallet reserve boundary to PR-010-style policy inputs."""
    def size(self, snapshot: LiquidationTargetSnapshot, eligibility: LiquidationEligibility, liquidity: LiquiditySnapshot, policy: LiquidationSizingPolicy) -> LiquidationSizingResult:
        if eligibility.status is not LiquidationStatus.POTENTIALLY_LIQUIDATABLE:
            return LiquidationSizingResult(LiquidationStatus.PRE_SIMULATION_REJECTED, eligibility.reason)
        if not liquidity.route_is_executable:
            return LiquidationSizingResult(LiquidationStatus.PRE_SIMULATION_REJECTED, LiquidationReason.UNWIND_ROUTE_NOT_EXECUTABLE)
        if liquidity.slot != snapshot.slot:
            return LiquidationSizingResult(LiquidationStatus.PRE_SIMULATION_REJECTED, LiquidationReason.LIQUIDATION_SLOT_INCONSISTENT)
        if policy.wallet_operational_lamports - policy.fee_budget < policy.protected_reserve_lamports:
            return LiquidationSizingResult(LiquidationStatus.PRE_SIMULATION_REJECTED, LiquidationReason.LIQUIDATION_STRATEGY_CAP_EXCEEDED)
        bounds = {
            "target_liability": eligibility.debt.amount if eligibility.debt else 0,
            "protocol_close_factor": eligibility.max_repay,
            "debt_reserve_liquidity": liquidity.debt_reserve_liquidity,
            "flash_capacity": liquidity.flash_capacity,
            "route_capacity": liquidity.route_capacity,
            "strategy_cap": policy.strategy_cap,
        }
        repay = min(bounds.values())
        if repay <= 0: return LiquidationSizingResult(LiquidationStatus.PRE_SIMULATION_REJECTED, LiquidationReason.FLASH_LIQUIDITY_INSUFFICIENT, bounds=bounds)
        bonus_bps = snapshot.risk.liquidation_bonus_bps
        if bonus_bps is None: return LiquidationSizingResult(LiquidationStatus.PRE_SIMULATION_REJECTED, LiquidationReason.LIQUIDATION_BONUS_UNKNOWN, bounds=bounds)
        fee_bps = snapshot.risk.protocol_fee_bps + snapshot.risk.insurance_fee_bps + liquidity.token2022_transfer_fee_bps
        seized = repay * (10_000 + bonus_bps - fee_bps) // 10_000
        final_out = min(liquidity.route_min_out, seized)
        flash_repay = repay
        if final_out < flash_repay:
            return LiquidationSizingResult(LiquidationStatus.PRE_SIMULATION_REJECTED, LiquidationReason.UNWIND_SLIPPAGE_EXCESSIVE, repay, seized, final_out, flash_repay, final_out-flash_repay, bounds=bounds)
        h = canonical_hash({"snapshot": snapshot.raw_hash, "risk": snapshot.risk.risk_hash, "liq": liquidity.provenance, "repay": repay})
        return LiquidationSizingResult(LiquidationStatus.POTENTIALLY_LIQUIDATABLE, None, repay, seized, final_out, flash_repay, final_out-flash_repay, h, bounds)

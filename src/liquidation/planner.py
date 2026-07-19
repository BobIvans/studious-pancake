from __future__ import annotations
from .adapters import LiquidationAdapter
from .models import *

MARGINFI_FLASH_PROGRAM = "marginfi_flashloan_provider_pr009"

class LiquidationPlanner:
    def __init__(self, adapter: LiquidationAdapter, *, supported_financing: tuple[str, ...] = (MARGINFI_FLASH_PROGRAM,)):
        self.adapter = adapter; self.supported_financing = supported_financing
    def plan(self, snapshot: LiquidationTargetSnapshot, eligibility: LiquidationEligibility, sizing: LiquidationSizingResult, *, financing: str = MARGINFI_FLASH_PROGRAM) -> LiquidationInstructionPlan:
        if financing not in self.supported_financing:
            return LiquidationInstructionPlan(LiquidationStatus.PRE_SIMULATION_REJECTED, LiquidationReason.FINANCING_TARGET_COMBINATION_UNSUPPORTED, (), -1, "", "")
        if sizing.status is not LiquidationStatus.POTENTIALLY_LIQUIDATABLE:
            return LiquidationInstructionPlan(LiquidationStatus.PRE_SIMULATION_REJECTED, sizing.reason, (), -1, "", "")
        ixs = (
            LiquidationInstruction(financing, "start_flashloan", (snapshot.target_account,), "end_index:5"),
            LiquidationInstruction(financing, "borrow", (eligibility.debt.bank_or_reserve if eligibility.debt else "",), hex(sizing.repay_amount)[2:]),
            self.adapter.liquidation_instruction(snapshot, eligibility, sizing.repay_amount),
            LiquidationInstruction("route", "unwind", (eligibility.collateral.bank_or_reserve if eligibility.collateral else "",), hex(sizing.minimum_final_output)[2:]),
            LiquidationInstruction(financing, "repay", (eligibility.debt.bank_or_reserve if eligibility.debt else "",), hex(sizing.exact_flash_repayment)[2:]),
            LiquidationInstruction(financing, "end_flashloan", (), ""),
        )
        msg = canonical_hash(ixs)
        return LiquidationInstructionPlan(LiquidationStatus.POTENTIALLY_LIQUIDATABLE, None, ixs, 5, msg, canonical_hash({"msg": msg, "snapshot": snapshot.raw_hash, "sizing": sizing.sizing_hash}))

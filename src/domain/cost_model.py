"""Canonical immutable trade cost model."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from enum import Enum
from typing import Iterable, Optional

from .money import TokenAmount, Lamports, BasisPoints, FeeComponentKind, MonetaryUnitError, NATIVE_SOL_MINT


class DecisionReason(str, Enum):
    FEASIBLE_PRE_SIMULATION = "feasible_pre_simulation"
    EXECUTE = "execute"  # legacy facade only; canonical PR-010 decisions never submit
    NOT_PROFITABLE = "not_profitable"
    BELOW_SAFETY_BUFFER = "below_safety_buffer"
    STALE_QUOTE = "stale_quote"
    STALE_STATE = "stale_state"
    INSUFFICIENT_GAS_RESERVE = "insufficient_gas_reserve"
    ATA_RENT_RISK = "ata_rent_risk"
    INVALID_MONETARY_UNITS = "invalid_monetary_units"
    MISSING_CONVERSION_PRICE = "missing_conversion_price"


@dataclass(frozen=True)
class ExecutionDecision:
    should_execute: bool
    reason: DecisionReason
    breakdown: dict
    def to_dict(self) -> dict:
        out = dict(self.breakdown)
        out.update({"should_execute": self.should_execute, "reason": self.reason.value})
        return out


@dataclass(frozen=True)
class ConversionRate:
    base_mint: str
    quote_mint: str
    rate: Decimal
    source: str
    observed_at: datetime
    source_slot: int
    def is_stale(self, max_age: timedelta, now: Optional[datetime] = None) -> bool:
        return (now or datetime.now(timezone.utc)) - self.observed_at > max_age


@dataclass(frozen=True)
class ConversionSnapshot:
    rates: tuple[ConversionRate, ...]
    max_age: timedelta = timedelta(seconds=30)
    def get(self, base_mint: str, quote_mint: str, now: Optional[datetime] = None) -> ConversionRate:
        if base_mint == quote_mint:
            return ConversionRate(base_mint, quote_mint, Decimal("1"), "identity", now or datetime.now(timezone.utc), 0)
        for rate in self.rates:
            if rate.base_mint == base_mint and rate.quote_mint == quote_mint:
                if rate.is_stale(self.max_age, now):
                    raise TimeoutError(f"stale conversion rate {base_mint}->{quote_mint}")
                return rate
        raise KeyError(f"missing conversion rate {base_mint}->{quote_mint}")


@dataclass(frozen=True)
class FeeComponent:
    kind: FeeComponentKind
    amount: TokenAmount
    embedded_in_quote: bool = False
    description: str = ""


@dataclass(frozen=True)
class ATARequirement:
    mint: str
    exists: bool
    rent: Lamports
    def cost(self, settlement_mint: str, decimals: int) -> FeeComponent:
        lamports = 0 if self.exists else self.rent.value
        return FeeComponent(FeeComponentKind.ATA_CREATION, TokenAmount(NATIVE_SOL_MINT, lamports, 9), False, self.mint)


@dataclass(frozen=True)
class WalletCostState:
    native_sol_balance: Optional[Lamports]
    required_native_reserve: Lamports
    def validate(self) -> ExecutionDecision:
        if self.native_sol_balance is None:
            return ExecutionDecision(False, DecisionReason.INSUFFICIENT_GAS_RESERVE, {"wallet_balance_known": False})
        ok = self.native_sol_balance.value >= self.required_native_reserve.value
        return ExecutionDecision(ok, DecisionReason.EXECUTE if ok else DecisionReason.INSUFFICIENT_GAS_RESERVE, {"wallet_balance_lamports": self.native_sol_balance.value, "required_reserve_lamports": self.required_native_reserve.value})


@dataclass(frozen=True)
class FlashLoanTerms:
    provider: str
    borrowed_asset: str
    fee_bps: BasisPoints
    fixed_fee: Optional[TokenAmount] = None
    def required_repayment(self, principal: TokenAmount) -> TokenAmount:
        if principal.mint != self.borrowed_asset:
            raise MonetaryUnitError("flash-loan principal mint does not match terms")
        fee = self.fee_bps.apply_ceil(principal)
        total = principal + fee
        if self.fixed_fee:
            total = total + self.fixed_fee
        return total


@dataclass(frozen=True)
class TradeAmounts:
    input_amount: TokenAmount
    expected_output: TokenAmount
    guaranteed_minimum_output: TokenAmount
    simulated_output: Optional[TokenAmount] = None
    realized_output: Optional[TokenAmount] = None


class TradeCostModel:
    def evaluate(self, *, settlement_mint: str, amounts: TradeAmounts, flash_loan_terms: FlashLoanTerms, fees: Iterable[FeeComponent], conversions: ConversionSnapshot, min_net_profit: TokenAmount, safety_buffer: TokenAmount, now: Optional[datetime] = None, use_simulated: bool = False) -> ExecutionDecision:
        try:
            conservative_output = amounts.simulated_output if use_simulated and amounts.simulated_output else amounts.guaranteed_minimum_output
            for amt in (amounts.input_amount, amounts.expected_output, conservative_output, min_net_profit, safety_buffer):
                if amt.mint != settlement_mint or amt.decimals != amounts.input_amount.decimals:
                    raise MonetaryUnitError("all profitability amounts must use the declared settlement asset")
            repayment = flash_loan_terms.required_repayment(amounts.input_amount)
            gross = amounts.expected_output - amounts.input_amount
            conservative_gross = conservative_output - repayment
            external_cost = 0
            fee_rows = []
            for fee in fees:
                if fee.amount.mint != settlement_mint or fee.amount.decimals != amounts.input_amount.decimals:
                    rate = conversions.get(fee.amount.mint, settlement_mint, now)
                    converted = int((Decimal(fee.amount.base_units) * rate.rate).to_integral_value(rounding="ROUND_CEILING"))
                    fee_amount = TokenAmount(settlement_mint, converted, amounts.input_amount.decimals)
                else:
                    fee_amount = fee.amount
                deducted = 0 if fee.embedded_in_quote else fee_amount.base_units
                external_cost += deducted
                fee_rows.append({"kind": fee.kind.value, "amount_base_units": fee_amount.base_units, "embedded_in_quote": fee.embedded_in_quote, "deducted_base_units": deducted, "description": fee.description})
            total_cost = external_cost + safety_buffer.base_units
            net_units = conservative_gross.base_units - total_cost
            min_final = repayment.base_units + total_cost + min_net_profit.base_units
            roi = str(Decimal(net_units) / Decimal(amounts.input_amount.base_units)) if amounts.input_amount.base_units else "0"
            reason = DecisionReason.FEASIBLE_PRE_SIMULATION if net_units >= min_net_profit.base_units else DecisionReason.NOT_PROFITABLE
            if net_units < safety_buffer.base_units:
                reason = DecisionReason.BELOW_SAFETY_BUFFER
            return ExecutionDecision(reason == DecisionReason.FEASIBLE_PRE_SIMULATION, reason, {"settlement_mint": settlement_mint, "gross_profit_base_units": gross.base_units, "required_repayment_base_units": repayment.base_units, "external_cost_base_units": external_cost, "safety_buffer_base_units": safety_buffer.base_units, "total_cost_base_units": total_cost, "net_profit_base_units": net_units, "roi": roi, "minimum_acceptable_final_amount_base_units": min_final, "expected_output_base_units": amounts.expected_output.base_units, "guaranteed_minimum_output_base_units": amounts.guaranteed_minimum_output.base_units, "simulated_output_base_units": None if amounts.simulated_output is None else amounts.simulated_output.base_units, "realized_output_base_units": None if amounts.realized_output is None else amounts.realized_output.base_units, "fees": fee_rows})
        except KeyError as exc:
            return ExecutionDecision(False, DecisionReason.MISSING_CONVERSION_PRICE, {"error": str(exc)})
        except TimeoutError as exc:
            return ExecutionDecision(False, DecisionReason.STALE_QUOTE, {"error": str(exc)})
        except MonetaryUnitError as exc:
            return ExecutionDecision(False, DecisionReason.INVALID_MONETARY_UNITS, {"error": str(exc)})

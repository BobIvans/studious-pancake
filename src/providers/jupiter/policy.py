"""Adaptive Jupiter route policy helpers for two-leg flash-loan composition."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from src.domain.cost_model import TradeCostModel, TradeAmounts, FlashLoanTerms, ConversionSnapshot, FeeComponent
from src.domain.money import TokenAmount
from src.execution.models import Instruction, SimulationReport
from .router import JupiterInstructionBundle, JupiterRejectionReason

class FallbackAction(str, Enum):
    REMOVE_PROVEN_REDUNDANT_SETUP = "remove_proven_redundant_setup"
    REBUILD_SMALLER_ACCOUNT_BUDGET = "rebuild_smaller_account_budget"
    DIRECT_ROUTE_LAST_RESORT = "direct_route_last_resort_verified"

@dataclass(frozen=True)
class FallbackAttempt:
    trace_id: str
    action: FallbackAction
    max_accounts: int
    reason: JupiterRejectionReason

@dataclass(frozen=True)
class TwoLegJupiterPlan:
    setup: tuple[Instruction, ...]
    leg1: tuple[Instruction, ...]
    leg2: tuple[Instruction, ...]
    cleanup: tuple[Instruction, ...]
    other: tuple[Instruction, ...]
    lookup_table_addresses: tuple[str, ...]
    min_out_second_leg: int


def compose_two_leg_plan(first: JupiterInstructionBundle, second: JupiterInstructionBundle) -> TwoLegJupiterPlan:
    """Compose provider-only instructions; compiler/MarginFi inserts bracket later."""
    b1, b2 = first.execution_buckets(), second.execution_buckets()
    return TwoLegJupiterPlan(
        setup=(*b1["setup"], *b2["setup"]),
        leg1=b1["swap"],
        leg2=b2["swap"],
        cleanup=(*b1["cleanup"], *b2["cleanup"]),
        other=(*b1["other"], *b2["other"]),
        lookup_table_addresses=tuple(dict.fromkeys((*first.addresses_by_lookup_table_address.keys(), *second.addresses_by_lookup_table_address.keys()))),
        min_out_second_leg=second.other_amount_threshold,
    )


def fallback_sequence(trace_id: str, account_budget_steps: Iterable[int], *, allow_below_50: bool=False, direct_route_verified: bool=False) -> tuple[FallbackAttempt, ...]:
    attempts=[FallbackAttempt(trace_id, FallbackAction.REMOVE_PROVEN_REDUNDANT_SETUP, 64, JupiterRejectionReason.ACCOUNT_OVERFLOW)]
    for n in account_budget_steps:
        if n < 50 and not allow_below_50: continue
        if n < 64: attempts.append(FallbackAttempt(trace_id, FallbackAction.REBUILD_SMALLER_ACCOUNT_BUDGET, n, JupiterRejectionReason.ACCOUNT_OVERFLOW))
    if direct_route_verified: attempts.append(FallbackAttempt(trace_id, FallbackAction.DIRECT_ROUTE_LAST_RESORT, max(50, min(account_budget_steps)), JupiterRejectionReason.ACCOUNT_OVERFLOW))
    return tuple(attempts)


def choose_by_simulated_net(candidates, *, cost_model: TradeCostModel, flash_loan_terms: FlashLoanTerms, conversions: ConversionSnapshot, min_net_profit: TokenAmount, safety_buffer: TokenAmount, fees: Iterable[FeeComponent]=()):
    best=None; best_profit=None
    for quote, sim in candidates:
        if not isinstance(sim, SimulationReport) or not sim.success or sim.simulated_net_profit is None: continue
        amounts=TradeAmounts(quote.request.amount, quote.expected_output, quote.minimum_output, TokenAmount(quote.request.amount.mint, max(0, sim.simulated_net_profit.amount), quote.request.amount.decimals))
        decision=cost_model.evaluate(settlement_mint=quote.request.amount.mint, amounts=amounts, flash_loan_terms=flash_loan_terms, fees=fees, conversions=conversions, min_net_profit=min_net_profit, safety_buffer=safety_buffer, use_simulated=True)
        profit=decision.breakdown.get("net_profit_base_units", -1) if decision.should_execute else -1
        if profit >= 0 and (best_profit is None or profit > best_profit): best=quote; best_profit=profit
    return best

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from src.domain.money import *
from src.domain.cost_model import *


def test_token_amount_rejects_mint_or_decimal_mismatch():
    sol = TokenAmount.from_base_units(WSOL_MINT, 1, 9)
    usdc = TokenAmount.from_base_units(USDC_MINT, 1, 6)
    try:
        _ = sol + usdc
        assert False, "expected mismatch rejection"
    except MonetaryUnitError:
        pass
    try:
        _ = sol + TokenAmount.from_base_units(WSOL_MINT, 1, 6)
        assert False, "expected decimal mismatch rejection"
    except MonetaryUnitError:
        pass


def test_usdc_and_sol_decimals_registry():
    registry = TokenRegistry()
    assert registry.decimals(USDC_MINT) == 6
    assert registry.decimals(WSOL_MINT) == 9
    assert registry.get(NATIVE_SOL_MINT).is_native is True
    assert registry.get(WSOL_MINT).is_native is False


def test_native_sol_wrapped_sol_requires_explicit_helpers():
    lamports = Lamports.from_sol("1.25")
    wsol = lamports_to_wrapped_sol(lamports)
    assert wsol.mint == WSOL_MINT
    assert wrapped_sol_to_lamports(wsol) == lamports


def test_priority_fee_micro_lamports_regression_not_5000_times_sol():
    fee = ComputeBudget(200_000, ComputeUnitPrice(5_000)).priority_fee()
    assert fee.value == 1_000
    assert fee.value != 5_000 * LAMPORTS_PER_SOL


def test_flashloan_repayment_and_embedded_fees_not_double_deducted():
    amount = TokenAmount.from_base_units(USDC_MINT, 1_000_000_000, 6)
    out = TokenAmount.from_base_units(USDC_MINT, 1_010_000_000, 6)
    terms = FlashLoanTerms("provider", USDC_MINT, BasisPoints(5), TokenAmount.from_base_units(USDC_MINT, 10_000, 6))
    decision = TradeCostModel().evaluate(
        settlement_mint=USDC_MINT,
        amounts=TradeAmounts(amount, out, out),
        flash_loan_terms=terms,
        fees=[
            FeeComponent(FeeComponentKind.DEX, TokenAmount.from_base_units(USDC_MINT, 1_000_000, 6), True),
            FeeComponent(FeeComponentKind.NETWORK_BASE, TokenAmount.from_base_units(USDC_MINT, 50_000, 6), False),
            FeeComponent(FeeComponentKind.TOKEN_2022_TRANSFER, TokenAmount.from_base_units(USDC_MINT, 25_000, 6), False),
        ],
        conversions=ConversionSnapshot(tuple()),
        min_net_profit=TokenAmount.from_base_units(USDC_MINT, 1, 6),
        safety_buffer=TokenAmount.from_base_units(USDC_MINT, 1_000, 6),
    )
    assert decision.should_execute
    data = decision.to_dict()
    assert data["required_repayment_base_units"] == 1_000_510_000
    assert data["external_cost_base_units"] == 75_000
    assert data["fees"][0]["deducted_base_units"] == 0


def test_wallet_unknown_balance_fails_closed():
    decision = WalletCostState(None, Lamports(5000)).validate()
    assert not decision.should_execute
    assert decision.reason == DecisionReason.INSUFFICIENT_GAS_RESERVE


def test_missing_and_stale_conversion_rejects_execution():
    amount = TokenAmount.from_base_units(USDC_MINT, 100, 6)
    out = TokenAmount.from_base_units(USDC_MINT, 101, 6)
    stale = ConversionSnapshot((ConversionRate(WSOL_MINT, USDC_MINT, Decimal("150"), "test", datetime.now(timezone.utc)-timedelta(minutes=5), 1),), max_age=timedelta(seconds=1))
    decision = TradeCostModel().evaluate(
        settlement_mint=USDC_MINT,
        amounts=TradeAmounts(amount, out, out),
        flash_loan_terms=FlashLoanTerms("p", USDC_MINT, BasisPoints(0)),
        fees=[FeeComponent(FeeComponentKind.JITO_TIP, TokenAmount.from_base_units(WSOL_MINT, 1, 9), False)],
        conversions=stale,
        min_net_profit=TokenAmount.from_base_units(USDC_MINT, 0, 6),
        safety_buffer=TokenAmount.from_base_units(USDC_MINT, 0, 6),
    )
    assert decision.reason == DecisionReason.STALE_QUOTE

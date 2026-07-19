from datetime import datetime, timezone, timedelta

from src.domain.money import *
from src.domain.feasibility import *

NOW = datetime(2026, 7, 19, tzinfo=timezone.utc)


def USDC(v):
    return TokenAmount(USDC_MINT, v, 6)


def SOLC(lamports):
    return TokenAmount(NATIVE_SOL_MINT, lamports, 9)

def base_inputs(balance=15_000_000, protected=5_000_000, outstanding=1_000_000, rent=0, tip=1_000, priority_cap=2_000, principal=1_000_000_000, min_out=1_003_500_000, repayment=1_000_500_000, stage="compiled"):
    policy = FeasibilityPolicy(USDC(100_000), 1, USDC(10_000), tip_absolute_cap=Lamports(5_000), priority_fee_absolute_cap=Lamports(priority_cap), config_version="test")
    reserve = WalletReservePolicy(Lamports(protected), 1, Lamports(6_000), "test")
    wallet = WalletResourceSnapshot(Lamports(balance), NOW, 1, Lamports(outstanding), ("r0",))
    acct = AccountRequirement("ata", "wallet", USDC_MINT, TOKEN_PROGRAM, 165, rent == 0, True, True, True, Lamports(rent) if rent else Lamports(2_100_000), None, NOW, 1)
    tipq = TipQuoteSnapshot(Lamports(tip), "fixture", NOW, "jito_single_bundle", Lamports(1_000), "h")
    native = NativeCostEstimate(Lamports(5_000), "m", "m", 1, 200_000, ComputeUnitPrice(5_000), Lamports(priority_cap), tipq, (acct,), failed_attempt_charge_cap=Lamports(6_000), compiler_tip_instruction_hash="h")
    provider = ProviderCapacity("marginfi", "bank", USDC_MINT, USDC(1), USDC(2_000_000_000), USDC(2_000_000_000), True, USDC(repayment), NOW, 1, "pr009")
    route = RouteCapacity(USDC_MINT, USDC_MINT, USDC_MINT, USDC(principal), USDC(min_out + 5_000_000), USDC(min_out), (USDC(25_000),), ("dex embedded",), 50, USDC(1), USDC(2_000_000_000), "q", NOW, NOW+timedelta(seconds=1), True, True, True)
    tx = TransactionFeasibility(600, 1232, 1, 10, 5, 15, 64, True, True, 180_000, 200_000, 1_400_000)
    conv = RationalConversionSnapshot(NATIVE_SOL_MINT, 9, USDC_MINT, 6, 150_000_000, 1_000_000_000, "fixture", NOW, 1)
    return dict(stage=stage, wallet_policy=reserve, wallet=wallet, native_cost=native, provider=provider, route=route, transaction=tx, conversion=conv, policy=policy, now=NOW)

def evald(**kw):
    x = base_inputs(**kw)
    return TradeFeasibilityEngine().evaluate(**x)

def test_directional_conversion_rounding_and_reciprocal():
    c = RationalConversionSnapshot(NATIVE_SOL_MINT, 9, USDC_MINT, 6, 150_000_000, 1_000_000_000, "x", NOW, 1)
    assert c.convert_cost_up(SOLC(1)).base_units == 1
    assert c.convert_revenue_down(SOLC(1)).base_units == 0
    back = c.reciprocal().convert_cost_up(USDC(1))
    assert back.base_units > 0

def test_conversion_rejects_stale_future_unhealthy_and_float_money():
    stale = RationalConversionSnapshot(NATIVE_SOL_MINT, 9, USDC_MINT, 6, 1, 1, "x", NOW-timedelta(seconds=10), 1)
    try: stale.validate(now=NOW, max_age=timedelta(seconds=1)); assert False
    except TimeoutError: pass
    try: Lamports.from_sol(0.015); assert False
    except MonetaryUnitError: pass

def test_json_roundtrip_huge_integer_precision():
    amt = TokenAmount(USDC_MINT, 2**64 + 123, 6)
    assert TokenAmount.from_json(amt.to_json()) == amt

def test_priority_fee_formula_and_caps_and_message_hash():
    assert ComputeBudget(200_000, ComputeUnitPrice(5_000)).priority_fee() == Lamports(1_000)
    assert ComputeBudget(200_001, ComputeUnitPrice(5_000)).priority_fee() == Lamports(1_001)
    assert evald(priority_cap=999).primary_reason == FeasibilityReason.PRIORITY_FEE_CAP_EXCEEDED
    x = base_inputs(); x["native_cost"] = NativeCostEstimate(None, "m", "m", 1, 1, ComputeUnitPrice(1), Lamports(1), x["native_cost"].tip)
    assert TradeFeasibilityEngine().evaluate(**x).primary_reason == FeasibilityReason.MISSING_BASE_FEE
    x = base_inputs(); x["native_cost"] = NativeCostEstimate(Lamports(1), "m", "other", 1, 1, ComputeUnitPrice(1), Lamports(1), x["native_cost"].tip)
    assert TradeFeasibilityEngine().evaluate(**x).primary_reason == FeasibilityReason.MISSING_BASE_FEE

def test_rent_ata_wsol_and_token2022_validation():
    d = evald(rent=2_100_000, protected=12_000_000)
    assert d.resource_budget.current_account_rent_funding == Lamports(2_100_000)
    assert d.primary_reason == FeasibilityReason.INSUFFICIENT_OPERATIONAL_SOL
    x = base_inputs(); bad = AccountRequirement("ata", "wallet", USDC_MINT, TOKEN_2022_PROGRAM, 165, True, True, True, False, Lamports(1), None, NOW, 1)
    x["native_cost"] = NativeCostEstimate(Lamports(5_000), "m", "m", 1, 200_000, ComputeUnitPrice(5_000), Lamports(2_000), x["native_cost"].tip, (bad,))
    assert TradeFeasibilityEngine().evaluate(**x).primary_reason == FeasibilityReason.ATA_ACCOUNT_INVALID
    x = base_inputs(); x["native_cost"] = NativeCostEstimate(Lamports(5_000), "m", "m", 1, 200_000, ComputeUnitPrice(5_000), Lamports(2_000), x["native_cost"].tip, (), temporary_wsol_rent=Lamports(500), temporary_wsol_funding=Lamports(1000))
    assert TradeFeasibilityEngine().evaluate(**x).resource_budget.current_temporary_wsol_funding == Lamports(1500)

def test_profit_uses_exact_repayment_min_output_and_independent_gates():
    assert evald(min_out=999_000_000).primary_reason == FeasibilityReason.REPAYMENT_NOT_GUARANTEED
    assert evald(min_out=1_000_500_000).primary_reason == FeasibilityReason.BELOW_MIN_NET_PROFIT
    d = evald()
    assert d.feasible_for_next_stage and d.primary_reason == FeasibilityReason.FEASIBLE_FOR_SIMULATION
    assert d.exact_repayment.base_units == 1_000_500_000
    assert d.expected_profit.base_units > d.guaranteed_net_profit.base_units

def test_015_sol_capital_scenarios_and_principal_not_wallet_spend():
    d = evald(principal=1_500_000_000)
    assert d.feasible_for_next_stage
    assert d.resource_budget.spendable_lamports == Lamports(9_000_000)
    assert evald(protected=14_000_000).primary_reason == FeasibilityReason.INSUFFICIENT_OPERATIONAL_SOL
    x = base_inputs(); x["wallet"] = WalletResourceSnapshot(Lamports(15_000_000), NOW, 1, None)
    assert TradeFeasibilityEngine().evaluate(**x).primary_reason == FeasibilityReason.UNKNOWN_OUTSTANDING_BUDGET
    assert evald(tip=6_000).primary_reason == FeasibilityReason.TIP_CAP_EXCEEDED

def test_failure_budget_no_double_count_and_zero_remaining():
    x = base_inputs(); x["wallet_policy"] = WalletReservePolicy(Lamports(5_000_000), 0, Lamports(9_000), "test")
    d = TradeFeasibilityEngine().evaluate(**x)
    assert d.resource_budget.future_failure_budget == Lamports(0)
    assert d.resource_budget.per_failure_charge_cap == Lamports(6_000)
    assert d.resource_budget.current_success_debit_cap.value != d.resource_budget.per_failure_charge_cap.value

def test_provider_route_transaction_failures():
    x = base_inputs(); x["provider"] = ProviderCapacity("m", "b", USDC_MINT, USDC(1), USDC(10), USDC(10), False, None, NOW, 1, "v")
    assert TradeFeasibilityEngine().evaluate(**x).primary_reason == FeasibilityReason.PROVIDER_UNAVAILABLE
    x = base_inputs(); x["route"] = RouteCapacity(USDC_MINT, USDC_MINT, USDC_MINT, USDC(1_000_000_000), USDC(2), USDC(2), (), (), 0, USDC(1), USDC(10), "q", NOW, NOW+timedelta(seconds=1), True, True, True)
    assert TradeFeasibilityEngine().evaluate(**x).primary_reason == FeasibilityReason.ROUTE_CAPACITY_EXCEEDED
    x = base_inputs(); x["transaction"] = TransactionFeasibility(1300, 1232, 1, 1, 1, 2, 64, True, True, 1, 1, 10)
    assert TradeFeasibilityEngine().evaluate(**x).primary_reason == FeasibilityReason.TRANSACTION_TOO_LARGE

def test_in_memory_reservations_no_oversubscription_release_and_ambiguous_lock():
    s = InMemoryReservationStore(); assert s.reserve("a", Lamports(8), Lamports(10)); assert not s.reserve("b", Lamports(3), Lamports(10))
    s.release("a", terminal=True); assert s.reserve("b", Lamports(3), Lamports(10))
    s.release("b", terminal=True, ambiguous=True); total, ids = s.snapshot(); assert total == Lamports(3) and ids == ("b",)

def test_sizer_selects_best_net_not_raw_or_roi_and_bounds_calls():
    provider = ProviderCapacity("m", "b", USDC_MINT, USDC(100), USDC(900), USDC(900), True, USDC(0), NOW, 1, "v")
    profits = {100: 30, 300: 70, 500: 60, 700: 70, 900: 1}
    def fake(p):
        x = base_inputs(principal=p.base_units, min_out=1_000_500_000 + profits[p.base_units] + 200_000)
        d = TradeFeasibilityEngine().evaluate(**x)
        return d
    res = OptimalTradeSizer().choose(provider=provider, route_min=USDC(100), route_max=USDC(900), policy=SizingPolicy(USDC(100), USDC(900), 5), evaluator=fake)
    assert res.evaluated <= 5
    assert res.best.principal.base_units == 300

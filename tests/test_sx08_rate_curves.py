"""SX-08 utilization/rate-curve + refinance model tests (deterministic, offline).

Every expected value below is hand-computed with exact rational arithmetic.
No network, no fixtures from live sources, no protocol-specific curve pins.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from src.lending_indexer.models import LendingProtocol
from src.lending_indexer.rate_curves import (
    CurveProvenance,
    CurveSide,
    DebtPosition,
    DuplicatePositionKeyError,
    ExecutionClass,
    FlashFinancingNotAllowedError,
    FlashFinancingTerms,
    HealthFactorPostcondition,
    Horizon,
    RateCurveRejection,
    RateSpreadOpportunity,
    RefinanceCandidateSet,
    RefinanceDecisionStatus,
    RefinanceEvaluator,
    RefinanceKind,
    SameTxPostconditions,
    UtilizationRateCurve,
    CarryRisk,
)

pytestmark = pytest.mark.unit

# Fully pinned curve: base=0, slope_low=1/10, slope_high=1, kink=4/5, fee=1/10.
PINNED_PROVENANCE = CurveProvenance(
    curve_id="sx08-test-curve-a",
    source="offline_test_vector_hand_computed",
    note="not a protocol pin",
)

CURVE_A = UtilizationRateCurve(
    base_rate=Fraction(0),
    slope_low=Fraction(1, 10),
    slope_high=Fraction(1),
    kink_utilization=Fraction(4, 5),
    protocol_fee=Fraction(1, 10),
    provenance=PINNED_PROVENANCE,
)


def _proven_hf(hf_after: Fraction | None = Fraction(3, 2)) -> HealthFactorPostcondition:
    return HealthFactorPostcondition(
        position_key="pos-1",
        hf_after=hf_after,
        source="external_risk_engine:maintenance:offline",
    )


class _StaticHFProvider:
    """Injected provider returning precomputed results (model computes none)."""

    def __init__(self, results: dict[str, HealthFactorPostcondition]) -> None:
        self._results = results

    def postcondition_for(self, position_key: str) -> HealthFactorPostcondition | None:
        return self._results.get(position_key)


def _hf_provider(
    hf_after: Fraction | None = Fraction(3, 2), key: str = "pos-1"
) -> _StaticHFProvider:
    if hf_after is None:
        return _StaticHFProvider({})
    return _StaticHFProvider({key: _proven_hf(hf_after)})


def _carry_opportunity(
    *,
    curve: UtilizationRateCurve = CURVE_A,
    current_apr: Fraction = Fraction(9, 100),
    horizon: Horizon | None = None,
    financing: FlashFinancingTerms | None = None,
    entry_fee: Fraction | None = Fraction(1, 10_000),
    exit_fee: Fraction | None = Fraction(0),
    hf_provider: _StaticHFProvider | None = None,
) -> RateSpreadOpportunity:
    return RateSpreadOpportunity(
        opportunity_id="opp-1",
        position=DebtPosition(
            position_key="pos-1",
            asset="asset-usdc",
            balance=1_000_000,
            current_borrow_apr=current_apr,
        ),
        refinance_kind=RefinanceKind.MULTI_PERIOD_CARRY,
        target_curve=curve,
        target_utilization=Fraction(1, 2),
        horizon=horizon if horizon is not None else Horizon(seconds=15_768_000),
        flash_financing=financing,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        carry_risk=CarryRisk(
            funding_risk="utilization_drift_over_horizon",
            withdrawal_risk="supply_withdrawal_delay",
        ),
    )


# --- 1/2. kink curve + supply curve: exact hand-computed values ------------


def test_kink_curve_exact_hand_computed_values() -> None:
    # below kink: 0 + (1/10) * (2/5)/(4/5) = 1/20
    below = CURVE_A.borrow_apy(Fraction(2, 5))
    assert below.proven and below.side is CurveSide.BORROW
    assert below.apy == Fraction(1, 20)
    # at the kink: base + slope_low = 1/10 (exactly continuous)
    at_kink = CURVE_A.borrow_apy(Fraction(4, 5))
    assert at_kink.apy == Fraction(1, 10)
    # above kink: 1/10 + 1 * ((9/10 - 4/5)/(1/5)) = 1/10 + 1/2 = 3/5
    above = CURVE_A.borrow_apy(Fraction(9, 10))
    assert above.apy == Fraction(3, 5)
    # u == 1 is allowed (only u > 1 is rejected): 1/10 + 1 = 11/10
    at_full = CURVE_A.borrow_apy(Fraction(1))
    assert at_full.apy == Fraction(11, 10)
    assert CURVE_A.curve_id == "sx08-test-curve-a"


def test_supply_curve_applies_protocol_fee_exactly() -> None:
    # borrow(1/2) = (1/10) * (1/2)/(4/5) = 1/16
    # supply(1/2) = (1/16) * (1/2) * (1 - 1/10) = 9/320
    supply = CURVE_A.supply_apy(Fraction(1, 2))
    assert supply.proven and supply.side is CurveSide.SUPPLY
    assert supply.apy == Fraction(9, 320)


# --- 3. missing parameters -> typed block (never defaulted to zero) --------


def test_missing_curve_parameters_typed_block() -> None:
    partial = UtilizationRateCurve(
        base_rate=Fraction(0),
        slope_low=Fraction(1, 10),
        kink_utilization=Fraction(4, 5),
        # slope_high missing, protocol_fee missing
    )
    borrow = partial.borrow_apy(Fraction(9, 10))
    assert borrow.apy is None
    assert borrow.rejection is RateCurveRejection.CURVE_PARAMETERS_UNKNOWN
    assert not borrow.proven
    # supply additionally requires protocol_fee: missing fee blocks supply
    supply = partial.supply_apy(Fraction(1, 2))
    assert supply.rejection is RateCurveRejection.CURVE_PARAMETERS_UNKNOWN
    # a curve with every borrow parameter but no fee still borrows exactly
    no_fee = UtilizationRateCurve(
        base_rate=Fraction(0),
        slope_low=Fraction(1, 10),
        slope_high=Fraction(1),
        kink_utilization=Fraction(4, 5),
    )
    assert no_fee.borrow_apy(Fraction(1, 2)).apy == Fraction(1, 16)
    assert no_fee.supply_apy(Fraction(1, 2)).rejection is (
        RateCurveRejection.CURVE_PARAMETERS_UNKNOWN
    )


# --- 4. utilization cliffs: u > 1 rejected, u < 0 rejected, u == 1 fine ----


def test_utilization_above_one_rejected() -> None:
    quote = CURVE_A.borrow_apy(Fraction(101, 100))
    assert quote.apy is None
    assert quote.rejection is RateCurveRejection.UTILIZATION_ABOVE_ONE
    negative = CURVE_A.borrow_apy(Fraction(-1, 100))
    assert negative.rejection is RateCurveRejection.UTILIZATION_NEGATIVE
    # u == 1 stays inside the model
    assert CURVE_A.borrow_apy(Fraction(1)).rejection is None


# --- 5. no float drift: float inputs rejected outright ---------------------


def test_float_parameters_rejected_no_float_drift() -> None:
    with pytest.raises(TypeError):
        UtilizationRateCurve(base_rate=0.1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        DebtPosition(
            position_key="pos-f",
            asset="asset-x",
            balance=1_000_000,
            current_borrow_apr=0.09,  # type: ignore[arg-type]
        )
    # exact decimal string is accepted and equals the exact rational
    exact = UtilizationRateCurve(
        base_rate="0.02",
        slope_low="0.1",
        slope_high="1",
        kink_utilization="0.8",
        protocol_fee="0.1",
    )
    assert exact.base_rate == Fraction(1, 50)
    assert exact.kink_utilization == Fraction(4, 5)


# --- 6. spread horizon arithmetic: exact integer seconds/blocks ------------


def test_spread_horizon_arithmetic_exact_candidate() -> None:
    # target curve at u=1/2 with base=1/50: 1/50 + (1/10)*(5/8) = 33/400
    target_curve = UtilizationRateCurve(
        base_rate=Fraction(1, 50),
        slope_low=Fraction(1, 10),
        slope_high=Fraction(1),
        kink_utilization=Fraction(4, 5),
        protocol_fee=Fraction(1, 10),
    )
    carry = _carry_opportunity(
        curve=target_curve,
        entry_fee=Fraction(1, 10_000),
        exit_fee=Fraction(0),
    )
    evaluator = RefinanceEvaluator(_hf_provider(Fraction(3, 2)))
    decision = evaluator.evaluate(carry)

    # 1_000_000 * (9/100 - 33/400) * (15_768_000/31_536_000) = 1_000_000
    # * (3/400) * (1/2) = 3750 exactly
    assert decision.status is RefinanceDecisionStatus.CANDIDATE
    assert decision.interest_saving == Fraction(3750)
    # known costs: entry 1_000_000/10_000 = 100; exit 0; (no flash on carry)
    assert decision.known_switch_costs == Fraction(100)
    assert decision.unknown_switch_cost_fields == ()
    assert decision.net_saving_over_known_costs == Fraction(3650)
    assert decision.hf_after == Fraction(3, 2)
    assert decision.execution_class is ExecutionClass.HEDGED_NON_ATOMIC
    assert decision.target_borrow_apr == Fraction(33, 400)
    assert decision.horizon_seconds == 15_768_000
    assert decision.actionable

    # same arithmetic via an integer block horizon: 26280 blocks * 600s
    block_horizon = Horizon(blocks=26_280, seconds_per_block=600)
    by_blocks = RefinanceEvaluator(_hf_provider()).evaluate(
        _carry_opportunity(curve=target_curve)
    )
    same_via_blocks = RefinanceEvaluator(_hf_provider()).evaluate(
        RateSpreadOpportunity(
            opportunity_id="opp-1",
            position=carry.position,
            refinance_kind=RefinanceKind.MULTI_PERIOD_CARRY,
            target_curve=target_curve,
            target_utilization=Fraction(1, 2),
            horizon=block_horizon,
            entry_fee=Fraction(1, 10_000),
            exit_fee=Fraction(0),
            carry_risk=carry.carry_risk,
        )
    )
    assert block_horizon.to_seconds() == 15_768_000
    assert by_blocks == same_via_blocks


# --- 7. negative saving -> typed no-trade result (not an exception) --------


def test_negative_saving_no_trade_typed_not_exception() -> None:
    target_curve = UtilizationRateCurve(
        base_rate=Fraction(1, 50),
        slope_low=Fraction(1, 10),
        slope_high=Fraction(1),
        kink_utilization=Fraction(4, 5),
        protocol_fee=Fraction(1, 10),
    )
    # current 8/100 = 32/400 < target 33/400 -> saving is negative
    opportunity = _carry_opportunity(curve=target_curve, current_apr=Fraction(8, 100))
    decision = RefinanceEvaluator(_hf_provider()).evaluate(opportunity)
    assert decision.status is RefinanceDecisionStatus.NO_TRADE
    assert decision.rejection is None  # typed result, not an exception path
    assert decision.interest_saving == Fraction(-1250)
    assert decision.known_switch_costs == Fraction(100)
    assert decision.net_saving_over_known_costs == Fraction(-1350)
    assert not decision.actionable
    assert decision.execution_class is ExecutionClass.HEDGED_NON_ATOMIC


# --- 8. unknown switch costs flagged, never zeroed -------------------------


def test_unknown_switch_costs_flagged_not_zeroed() -> None:
    target_curve = UtilizationRateCurve(
        base_rate=Fraction(1, 50),
        slope_low=Fraction(1, 10),
        slope_high=Fraction(1),
        kink_utilization=Fraction(4, 5),
        protocol_fee=Fraction(1, 10),
    )
    opportunity = _carry_opportunity(
        curve=target_curve,
        entry_fee=Fraction(1, 1000),
        exit_fee=None,  # unknown
    )
    decision = RefinanceEvaluator(_hf_provider()).evaluate(opportunity)
    # saving 3750 > known costs 1000, but unknown costs can never make a
    # candidate look better -> blocked, not candidate
    assert decision.status is RefinanceDecisionStatus.BLOCKED
    assert decision.rejection is RateCurveRejection.SWITCH_COSTS_UNKNOWN
    assert decision.unknown_switch_cost_fields == ("exit_fee",)
    # the unknown exit fee was NOT treated as zero: known costs are 1000,
    # net over known costs is 2750, and the decision is still not actionable
    assert decision.known_switch_costs == Fraction(1000)
    assert decision.net_saving_over_known_costs == Fraction(2750)
    assert decision.interest_saving == Fraction(3750)
    assert not decision.actionable


# --- 9. missing horizon -> typed block -------------------------------------


def test_missing_horizon_typed_block() -> None:
    opportunity = _carry_opportunity(horizon=Horizon())  # nothing provided
    decision = RefinanceEvaluator(_hf_provider()).evaluate(opportunity)
    assert decision.status is RefinanceDecisionStatus.BLOCKED
    assert decision.rejection is RateCurveRejection.HORIZON_UNPROVIDED
    assert decision.horizon_seconds is None
    assert decision.interest_saving is None


# --- 10. intra-tx atomic requires proven financing + postconditions --------


def test_atomic_requires_proven_financing_and_postconditions() -> None:
    target_curve = UtilizationRateCurve(
        base_rate=Fraction(1, 50),
        slope_low=Fraction(1, 10),
        slope_high=Fraction(1),
        kink_utilization=Fraction(4, 5),
        protocol_fee=Fraction(1, 10),
    )

    def atomic(
        financing: FlashFinancingTerms | None,
        postconditions: SameTxPostconditions | None,
    ) -> RateSpreadOpportunity:
        return RateSpreadOpportunity(
            opportunity_id="opp-atomic",
            position=DebtPosition(
                position_key="pos-1",
                asset="asset-usdc",
                balance=1_000_000,
                current_borrow_apr=Fraction(9, 100),
            ),
            refinance_kind=RefinanceKind.INTRA_TX_ATOMIC,
            target_curve=target_curve,
            target_utilization=Fraction(1, 2),
            horizon=Horizon(seconds=15_768_000),
            flash_financing=financing,
            same_tx_postconditions=postconditions,
            entry_fee=Fraction(1, 10_000),
            exit_fee=Fraction(0),
        )

    evaluator = RefinanceEvaluator(_hf_provider())

    unproven = evaluator.evaluate(
        atomic(
            FlashFinancingTerms(
                provider="stub", proven=False, flash_fee=Fraction(1, 2000)
            ),
            SameTxPostconditions(repayment_proven=True),
        )
    )
    assert unproven.status is RefinanceDecisionStatus.BLOCKED
    assert unproven.rejection is RateCurveRejection.FLASH_FINANCING_UNPROVEN

    missing = evaluator.evaluate(
        atomic(None, SameTxPostconditions(repayment_proven=True))
    )
    assert missing.rejection is RateCurveRejection.FLASH_FINANCING_UNPROVEN

    unknown_fee = evaluator.evaluate(
        atomic(
            FlashFinancingTerms(provider="stub", proven=True, flash_fee=None),
            SameTxPostconditions(repayment_proven=True),
        )
    )
    assert unknown_fee.rejection is RateCurveRejection.FLASH_FEE_UNKNOWN

    no_repayment = evaluator.evaluate(
        atomic(
            FlashFinancingTerms(
                provider="stub", proven=True, flash_fee=Fraction(1, 2000)
            ),
            None,
        )
    )
    assert no_repayment.rejection is RateCurveRejection.REPAYMENT_UNPROVEN

    proven = evaluator.evaluate(
        atomic(
            FlashFinancingTerms(
                provider="stub", proven=True, flash_fee=Fraction(1, 2000)
            ),
            SameTxPostconditions(repayment_proven=True),
        )
    )
    assert proven.status is RefinanceDecisionStatus.CANDIDATE
    assert proven.execution_class is ExecutionClass.LOCAL_ATOMIC_CANDIDATE
    # flash fee cost = 1_000_000 * 1/2000 = 500; + entry 100 -> known = 600
    assert proven.known_switch_costs == Fraction(600)
    assert proven.net_saving_over_known_costs == Fraction(3150)


# --- 11. carry is always non-atomic; flash principal guard raises ----------


def test_carry_guard_raises_on_flash_financing_attempt() -> None:
    with pytest.raises(FlashFinancingNotAllowedError):
        RateSpreadOpportunity(
            opportunity_id="opp-carry-flash",
            position=DebtPosition(
                position_key="pos-1",
                asset="asset-usdc",
                balance=1_000_000,
                current_borrow_apr=Fraction(9, 100),
            ),
            refinance_kind=RefinanceKind.MULTI_PERIOD_CARRY,
            target_curve=CURVE_A,
            target_utilization=Fraction(1, 2),
            horizon=Horizon(seconds=15_768_000),
            flash_financing=FlashFinancingTerms(
                provider="stub", proven=True, flash_fee=Fraction(1, 2000)
            ),
        )


# --- 12. missing health factor -> blocked ----------------------------------


def test_missing_health_factor_blocked() -> None:
    target_curve = UtilizationRateCurve(
        base_rate=Fraction(1, 50),
        slope_low=Fraction(1, 10),
        slope_high=Fraction(1),
        kink_utilization=Fraction(4, 5),
        protocol_fee=Fraction(1, 10),
    )
    opportunity = _carry_opportunity(curve=target_curve)
    no_result = RefinanceEvaluator(_StaticHFProvider({})).evaluate(opportunity)
    assert no_result.status is RefinanceDecisionStatus.BLOCKED
    assert no_result.rejection is RateCurveRejection.HEALTH_FACTOR_UNPROVEN
    assert no_result.hf_after is None

    unproven_result = RefinanceEvaluator(_hf_provider(hf_after=None)).evaluate(
        opportunity
    )
    assert unproven_result.rejection is RateCurveRejection.HEALTH_FACTOR_UNPROVEN
    # the model never computes a health factor itself
    assert unproven_result.hf_after is None


# --- 13. duplicate position key -> error (collateral double-count guard) ---


def test_duplicate_position_key_error() -> None:
    position = DebtPosition(
        position_key="pos-dup",
        asset="asset-usdc",
        balance=1_000_000,
        current_borrow_apr=Fraction(9, 100),
    )
    with pytest.raises(DuplicatePositionKeyError):
        RefinanceCandidateSet.build((position, position))
    # unique keys build fine and evaluate in deterministic order
    other = DebtPosition(
        position_key="pos-other",
        asset="asset-usdt",
        balance=500_000,
        current_borrow_apr=Fraction(9, 100),
    )
    candidate_set = RefinanceCandidateSet.build((position, other))
    assert candidate_set.positions == (position, other)


# --- 14. determinism --------------------------------------------------------


def test_determinism_repeat_evaluations_identical() -> None:
    target_curve = UtilizationRateCurve(
        base_rate=Fraction(1, 50),
        slope_low=Fraction(1, 10),
        slope_high=Fraction(1),
        kink_utilization=Fraction(4, 5),
        protocol_fee=Fraction(1, 10),
    )
    opportunity = _carry_opportunity(curve=target_curve)
    evaluator = RefinanceEvaluator(_hf_provider())
    first = evaluator.evaluate(opportunity)
    second = evaluator.evaluate(opportunity)
    assert first == second
    # curve quotes are deterministic too
    assert CURVE_A.borrow_apy(Fraction(9, 10)) == CURVE_A.borrow_apy(Fraction(9, 10))
    assert CURVE_A.supply_apy(Fraction(1, 2)) == CURVE_A.supply_apy(Fraction(1, 2))
    # batch evaluation is deterministic and order-stable
    other = RateSpreadOpportunity(
        opportunity_id="opp-2",
        position=DebtPosition(
            position_key="pos-2",
            asset="asset-usdt",
            balance=250_000,
            current_borrow_apr=Fraction(9, 100),
        ),
        refinance_kind=RefinanceKind.MULTI_PERIOD_CARRY,
        target_curve=target_curve,
        target_utilization=Fraction(1, 2),
        horizon=Horizon(seconds=15_768_000),
        entry_fee=Fraction(1, 10_000),
        exit_fee=Fraction(0),
        carry_risk=None,
    )
    batch = (opportunity, other)
    assert evaluator.evaluate_all(batch) == evaluator.evaluate_all(batch)
    assert len(evaluator.evaluate_all(batch)) == 2


# --- vocabulary alignment sanity --------------------------------------------


def test_health_factor_vocabulary_uses_rational() -> None:
    from src.lending_indexer import risk

    # aligned vocabulary: risk.health_factor returns Rational or None
    assert risk.health_factor(Fraction(3), Fraction(2)) == Fraction(3, 2)
    assert risk.health_factor(Fraction(3), Fraction(0)) is None
    # the lending protocol vocabulary is untouched by this module
    assert {p.value for p in LendingProtocol} == {"kamino", "marginfi"}

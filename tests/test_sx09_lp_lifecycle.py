"""Deterministic offline tests for the SX-09 LP lifecycle research model.

Covers: exact mint/add/remove token conservation, exact fee collect/compound
reinvestment, close-then-open range shift with recorded costs (unknown costs
stay None), hand-computed CPMM IL vectors on a pinned synthetic price path,
the valuation_model_unproven typed exclusion, persistent-capital flash
refusal, fee accrued-vs-collected conservation and markout, state-generation
mismatch rejection, and full determinism.
"""

from __future__ import annotations

import dataclasses

import pytest

from src.research.common import stable_json
from src.research.lp_lifecycle.position_lifecycle import (
    FeeConservationError,
    FlashFinancingTerms,
    ImpermanentLossEvaluator,
    InexactReinvestment,
    InvalidLpLifecycleInput,
    LPPositionState,
    MarkoutHorizonUnavailable,
    PersistentCapitalLock,
    PersistentLpNotFlashFinancable,
    StateGenerationMismatch,
    ValuationModelUnproven,
    accrue_fees,
    add_liquidity,
    build_fee_harvest_summary,
    collect_fees,
    compound_fees,
    evaluate_impermanent_loss,
    mint_position,
    remove_liquidity,
    shift_range,
    verify_receipt,
)

PRICE_SCALE = 1_000_000
ASSETS = ("BASE", "QUOTE")


def _range(seed: str) -> dict[str, object]:
    return {
        "kind": "clmm_tick_range",
        "lower_tick": -276320,
        "upper_tick": 276320,
        "provenance": {
            "source": "offline-synthetic-fixture",
            "schema": "sx09.range.synthetic.v1",
            "note": seed,
        },
    }


def _accrual_provenance(seed: str) -> dict[str, str]:
    return {
        "source": "offline-venue-accounting-replay",
        "schema": "sx09.fee_accrual.synthetic.v1",
        "note": seed,
    }


def _flash_terms() -> FlashFinancingTerms:
    return FlashFinancingTerms(
        provider="offline-flash-lender",
        principal_asset="QUOTE",
        principal_amount=1_000_000,
        fee_amount=900,
    )


def _mint() -> tuple[LPPositionState, object]:
    return mint_position(
        position_id="sx09-pos-1",
        venue="offline-research-venue",
        pool_key="pool/sx09/1",
        assets=ASSETS,
        range_descriptor=_range("mint"),
        liquidity=1_000_000_000,
        amounts=(1_000_000, 1_000_000),
    )


def test_mint_add_remove_conservation_exact() -> None:
    state, mint_receipt = _mint()
    assert state.state_generation == 1
    assert state.amounts == (1_000_000, 1_000_000)
    assert mint_receipt.inflows == (1_000_000, 1_000_000)
    assert mint_receipt.outflows == (0, 0)
    assert mint_receipt.conservation_holds() is True
    assert verify_receipt(state, mint_receipt) is True

    state2, add_receipt = add_liquidity(
        state,
        liquidity_delta=200_000_000,
        amount_deltas=(100_000, 50_000),
    )
    assert state2.amounts == (1_100_000, 1_050_000)
    assert state2.liquidity == 1_200_000_000
    assert state2.state_generation == 2
    assert add_receipt.inflows == (100_000, 50_000)
    assert add_receipt.amount_deltas == (100_000, 50_000)
    assert add_receipt.conservation_holds() is True
    assert verify_receipt(state2, add_receipt) is True

    state3, remove_receipt = remove_liquidity(
        state2,
        liquidity_delta=150_000_000,
        amount_deltas=(150_000, 75_000),
    )
    assert state3.amounts == (950_000, 975_000)
    assert state3.liquidity == 1_050_000_000
    assert state3.state_generation == 3
    assert remove_receipt.outflows == (150_000, 75_000)
    assert remove_receipt.amount_deltas == (-150_000, -75_000)
    assert remove_receipt.conservation_holds() is True
    assert verify_receipt(state3, remove_receipt) is True

    with pytest.raises(InvalidLpLifecycleInput):
        remove_liquidity(
            state3,
            liquidity_delta=1,
            amount_deltas=(950_001, 0),
        )
    with pytest.raises(InvalidLpLifecycleInput):
        remove_liquidity(
            state3,
            liquidity_delta=state3.liquidity + 1,
            amount_deltas=(1, 1),
        )


def test_collect_and_compound_reinvest_exactly() -> None:
    state, _ = mint_position(
        position_id="sx09-pos-2",
        venue="offline-research-venue",
        pool_key="pool/sx09/2",
        assets=ASSETS,
        range_descriptor=_range("compound"),
        liquidity=500_000_000,
        amounts=(1_000, 2_000),
    )
    state2, accrue_receipt = accrue_fees(
        state,
        fee_deltas=(1_000, 2_500),
        accrual_provenance=_accrual_provenance("compound"),
    )
    assert state2.unclaimed_fees == (1_000, 2_500)
    assert accrue_receipt.inflows == (1_000, 2_500)
    assert verify_receipt(state2, accrue_receipt) is True

    state3, collect_receipt = collect_fees(state2, claimed_amounts=(400, 500))
    assert state3.unclaimed_fees == (600, 2_000)
    assert state3.amounts == (1_000, 2_000)
    assert collect_receipt.outflows == (400, 500)
    assert verify_receipt(state3, collect_receipt) is True

    state4, compound_receipt = compound_fees(state3, liquidity_delta=10_000_000)
    assert state4.amounts == (1_600, 4_000)
    assert state4.unclaimed_fees == (0, 0)
    assert state4.liquidity == 510_000_000
    assert state4.state_generation == 4
    assert compound_receipt.inflows == (0, 0)
    assert compound_receipt.outflows == (0, 0)
    assert compound_receipt.detail["fees_collected"] == (600, 2_000)
    assert compound_receipt.detail["fees_reinvested"] == (600, 2_000)
    assert compound_receipt.detail["reinvestment_dust"] == (0, 0)
    assert compound_receipt.conservation_holds() is True
    assert verify_receipt(state4, compound_receipt) is True

    with pytest.raises(InexactReinvestment):
        compound_fees(
            state3,
            liquidity_delta=1,
            reinvest_amounts=(500, 2_000),
        )


def test_shift_range_closes_then_opens_conserving_with_costs() -> None:
    state, _ = _mint()
    state2, shift_receipt = shift_range(
        state,
        new_range_descriptor=_range("shifted"),
        new_liquidity=900_000_000,
        new_amounts=(800_000, 1_250_000),
        costs=(12, None),
    )
    assert state2.amounts == (800_000, 1_250_000)
    assert state2.liquidity == 900_000_000
    assert state2.state_generation == 2
    assert shift_receipt.inflows == (800_000, 1_250_000)
    assert shift_receipt.outflows == (1_000_000, 1_000_000)
    assert shift_receipt.detail["closed_amounts"] == (1_000_000, 1_000_000)
    assert shift_receipt.detail["opened_amounts"] == (800_000, 1_250_000)
    assert shift_receipt.detail["reused_amounts"] == (800_000, 1_000_000)
    assert shift_receipt.costs == (12, None)
    assert shift_receipt.conservation_holds() is True
    assert verify_receipt(state2, shift_receipt) is True
    assert (
        shift_receipt.range_descriptor_hash_after
        != shift_receipt.range_descriptor_hash_before
    )
    assert state2.range_descriptor_hash() == shift_receipt.range_descriptor_hash_after


def test_unknown_cost_stays_none() -> None:
    state, _ = _mint()
    state_a, receipt_none = shift_range(
        state,
        new_range_descriptor=_range("costs-none"),
        new_liquidity=900_000_000,
        new_amounts=(900_000, 1_100_000),
    )
    assert receipt_none.costs == (None, None)
    state_b, receipt_partial = shift_range(
        state,
        new_range_descriptor=_range("costs-partial"),
        new_liquidity=900_000_000,
        new_amounts=(900_000, 1_100_000),
        costs=(None, 7),
    )
    assert receipt_partial.costs == (None, 7)
    assert 0 not in receipt_none.costs
    assert receipt_none.conservation_holds() is True
    assert verify_receipt(state_a, receipt_none) is True
    assert verify_receipt(state_b, receipt_partial) is True


def test_il_exact_hand_computed_cpmm_flagged() -> None:
    price_path = (
        (0, 1_000_000),
        (60, 2_000_000),
        (120, 500_000),
    )
    steps = evaluate_impermanent_loss(
        price_path,
        (1_000_000, 1_000_000),
        valuation_model="cpmm",
        price_scale=PRICE_SCALE,
    )
    assert [step.t for step in steps] == [0, 60, 120]
    # Hand-computed exact integers (k = 10**12, scale = 10**6).
    assert [step.hold_value_scaled for step in steps] == [
        2_000_000_000_000,
        3_000_000_000_000,
        1_500_000_000_000,
    ]
    assert [step.lp_value_scaled for step in steps] == [
        2_000_000_000_000,
        2_828_427_124_746,
        1_414_213_562_372,
    ]
    assert [step.impermanent_loss_scaled for step in steps] == [
        0,
        -171_572_875_254,
        -85_786_437_628,
    ]

    evaluator = ImpermanentLossEvaluator(
        price_path,
        (1_000_000, 1_000_000),
        valuation_model="cpmm",
        price_scale=PRICE_SCALE,
    )
    assert evaluator.valuation_model == "cpmm"
    assert evaluator.impermanent_loss_scaled() == (
        0,
        -171_572_875_254,
        -85_786_437_628,
    )
    assert evaluator.step(1).t == 60


def test_valuation_model_unproven_exclusion() -> None:
    price_path = ((0, 1_000_000), (60, 2_000_000))
    for unproven in ("clmm", "dlmm-bin", "unproven", "v3"):
        with pytest.raises(ValuationModelUnproven):
            evaluate_impermanent_loss(
                price_path,
                (1_000_000, 1_000_000),
                valuation_model=unproven,
                price_scale=PRICE_SCALE,
            )
        with pytest.raises(ValuationModelUnproven):
            ImpermanentLossEvaluator(
                price_path,
                (1_000_000, 1_000_000),
                valuation_model=unproven,
                price_scale=PRICE_SCALE,
            )


def test_supplied_valuations_mode() -> None:
    price_path = ((0, 1_000_000), (60, 2_000_000))
    steps = evaluate_impermanent_loss(
        price_path,
        (1_000_000, 1_000_000),
        valuation_model="supplied",
        price_scale=PRICE_SCALE,
        lp_values_scaled=(2_000_000_000_000, 2_900_000_000_000),
    )
    assert [step.hold_value_scaled for step in steps] == [
        2_000_000_000_000,
        3_000_000_000_000,
    ]
    assert [step.impermanent_loss_scaled for step in steps] == [
        0,
        -100_000_000_000,
    ]
    with pytest.raises(InvalidLpLifecycleInput):
        evaluate_impermanent_loss(
            price_path,
            (1_000_000, 1_000_000),
            valuation_model="supplied",
            price_scale=PRICE_SCALE,
        )
    with pytest.raises(InvalidLpLifecycleInput):
        evaluate_impermanent_loss(
            price_path,
            (1_000_000, 1_000_000),
            valuation_model="supplied",
            price_scale=PRICE_SCALE,
            lp_values_scaled=(2_000_000_000_000,),
        )
    with pytest.raises(InvalidLpLifecycleInput):
        evaluate_impermanent_loss(
            price_path,
            (1_000_000, 1_000_000),
            valuation_model="cpmm",
            price_scale=PRICE_SCALE,
            lp_values_scaled=(1, 2),
        )


def test_flash_financed_lp_transition_raises() -> None:
    terms = _flash_terms()
    state, _ = _mint()
    with pytest.raises(PersistentLpNotFlashFinancable):
        mint_position(
            position_id="sx09-flash",
            venue="offline-research-venue",
            pool_key="pool/sx09/3",
            assets=ASSETS,
            range_descriptor=_range("flash"),
            liquidity=1,
            amounts=(1, 1),
            financing=terms,
        )
    with pytest.raises(PersistentLpNotFlashFinancable):
        add_liquidity(state, liquidity_delta=1, amount_deltas=(1, 1), financing=terms)
    with pytest.raises(PersistentLpNotFlashFinancable):
        remove_liquidity(
            state, liquidity_delta=1, amount_deltas=(1, 1), financing=terms
        )
    with pytest.raises(PersistentLpNotFlashFinancable):
        accrue_fees(
            state,
            fee_deltas=(1, 1),
            accrual_provenance=_accrual_provenance("flash"),
            financing=terms,
        )
    with pytest.raises(PersistentLpNotFlashFinancable):
        collect_fees(state, claimed_amounts=(1, 1), financing=terms)
    with pytest.raises(PersistentLpNotFlashFinancable):
        compound_fees(state, liquidity_delta=1, financing=terms)
    with pytest.raises(PersistentLpNotFlashFinancable):
        shift_range(
            state,
            new_range_descriptor=_range("flash-shift"),
            new_liquidity=1_000_000_000,
            new_amounts=(1_000_000, 1_000_000),
            financing=terms,
        )
    # Pure model: the refused transitions leave the state untouched.
    assert state.state_generation == 1
    assert state.amounts == (1_000_000, 1_000_000)

    persistent_lock = PersistentCapitalLock.for_position(state)
    with pytest.raises(PersistentLpNotFlashFinancable):
        persistent_lock.ensure_transition_financable("add_liquidity", terms)
    persistent_lock.ensure_transition_financable("add_liquidity", None)
    assert persistent_lock.capital_class == "PERSISTENT_INVENTORY"
    assert persistent_lock.position_id == state.position_id


def test_fees_accrued_vs_collected_conservation_and_markout() -> None:
    summary = build_fee_harvest_summary(
        (1_000, 500),
        (700, 500),
        (300, 0),
        assets=ASSETS,
        price_path=((0, 1_000_000), (60, 2_000_000)),
        collection_step_index=0,
        horizons=(1,),
        price_scale=PRICE_SCALE,
    )
    assert summary.conservation_ok is True
    assert summary.markouts[0].markout_scaled == 700_000_000
    assert summary.markouts[0].from_t == 0
    assert summary.markouts[0].to_t == 60

    with pytest.raises(FeeConservationError):
        build_fee_harvest_summary(
            (1_000, 500),
            (700, 500),
            (400, 0),
            assets=ASSETS,
            price_path=((0, 1_000_000), (60, 2_000_000)),
            collection_step_index=0,
            horizons=(1,),
            price_scale=PRICE_SCALE,
        )
    with pytest.raises(MarkoutHorizonUnavailable):
        build_fee_harvest_summary(
            (1_000, 500),
            (700, 500),
            (300, 0),
            assets=ASSETS,
            price_path=((0, 1_000_000), (60, 2_000_000)),
            collection_step_index=1,
            horizons=(1,),
            price_scale=PRICE_SCALE,
        )
    with pytest.raises(MarkoutHorizonUnavailable):
        build_fee_harvest_summary(
            (1_000, 500),
            (700, 500),
            (300, 0),
            assets=ASSETS,
            price_path=((0, 1_000_000), (60, 2_000_000)),
            collection_step_index=0,
            horizons=(5,),
            price_scale=PRICE_SCALE,
        )


def test_state_generation_mismatch_rejected() -> None:
    state, mint_receipt = _mint()
    state2, add_receipt = add_liquidity(
        state, liquidity_delta=200_000_000, amount_deltas=(10, 20)
    )
    assert verify_receipt(state, mint_receipt) is True
    assert verify_receipt(state2, add_receipt) is True
    with pytest.raises(StateGenerationMismatch):
        verify_receipt(state2, mint_receipt)
    with pytest.raises(StateGenerationMismatch):
        verify_receipt(state, add_receipt)
    tampered = dataclasses.replace(add_receipt, to_generation=99)
    with pytest.raises(StateGenerationMismatch):
        verify_receipt(state2, tampered)


def test_determinism() -> None:
    def run() -> tuple[LPPositionState, list[object], tuple[int, ...]]:
        receipts: list[object] = []
        s0, r0 = _mint()
        receipts.append(r0)
        s1, r1 = accrue_fees(
            s0,
            fee_deltas=(1_000, 2_500),
            accrual_provenance=_accrual_provenance("determinism"),
        )
        receipts.append(r1)
        s2, r2 = collect_fees(s1, claimed_amounts=(400, 500))
        receipts.append(r2)
        s3, r3 = compound_fees(s2, liquidity_delta=10_000_000)
        receipts.append(r3)
        s4, r4 = shift_range(
            s3,
            new_range_descriptor=_range("determinism-shift"),
            new_liquidity=900_000_000,
            new_amounts=(1_200_000, 3_500_000),
            costs=(12, None),
        )
        receipts.append(r4)
        il = ImpermanentLossEvaluator(
            ((0, 1_000_000), (60, 2_000_000)),
            (1_000_000, 1_000_000),
            valuation_model="cpmm",
            price_scale=PRICE_SCALE,
        ).impermanent_loss_scaled()
        return s4, receipts, il

    state_a, receipts_a, il_a = run()
    state_b, receipts_b, il_b = run()
    assert state_a == state_b
    assert receipts_a == receipts_b
    assert il_a == il_b
    assert stable_json(receipts_a) == stable_json(receipts_b)
    for receipt in receipts_a:
        assert receipt.capital_class == "PERSISTENT_INVENTORY"
        assert receipt.flash_financed is False
    assert state_a.range_descriptor_hash() == state_b.range_descriptor_hash()

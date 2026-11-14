"""SX-07 deterministic offline tests for conditional outcome-vector claims.

Research model only: every case is exact integer arithmetic on typed vectors
(CLAIM-COMPLETE-SET / CONDITIONAL_HYPEREDGE). No network, no protocol claims,
no executable rights. Hand-computed expectations are asserted exactly.
"""

from __future__ import annotations

import pytest

from src.strategy_evolution.conditional_claims import (
    NON_ATOMIC,
    PROTOCOL_DOSSIER_GATE,
    REDEMPTION_ATOMICITY,
    CompleteSetArbCandidate,
    CompleteSetArbEvaluator,
    ConditionalClaimError,
    MergeReceipt,
    OutcomeVectorClaim,
    RedemptionReceipt,
    ResolutionEvent,
    SplitReceipt,
    claims_conserved,
    merge_outcome_vector,
    redeem_winning_shares,
    require_non_atomic,
    split_outcome_vector,
)

COLLATERAL = "TEST_COLLATERAL"
PER_SET = 1_000_000
ASKS = {"A": 300_000, "B": 350_000, "C": 250_000}  # exact hand-computed total


def _claim(
    outcome_ids: tuple[str, ...] = ("A", "B", "C"),
    collateral_per_set: int | None = PER_SET,
    mutually_exclusive: bool = True,
    exhaustive: bool = True,
) -> OutcomeVectorClaim:
    return OutcomeVectorClaim(
        market_id="research/sx07-market-001",
        outcome_ids=outcome_ids,
        mutually_exclusive=mutually_exclusive,
        exhaustive=exhaustive,
        collateral_asset=COLLATERAL,
        collateral_per_set=collateral_per_set,
        settlement_rights=(
            "research-only: winning share redeems 1 collateral unit "
            "post-dispute; protocol dossier pending"
        ),
    )


def _resolution(finalized: bool = True) -> ResolutionEvent:
    return ResolutionEvent(
        settlement_oracle="research-oracle",
        resolution_slot=100,
        dispute_window_end_slot=200,
        finalized=finalized,
    )


def _arb_candidate_kwargs(
    atomicity: str = NON_ATOMIC,
    legs: tuple[tuple[str, tuple[tuple[str, int], ...]], ...] | None = None,
) -> dict[str, object]:
    claim = _claim()
    total = sum(ASKS[outcome] for outcome in claim.outcome_ids)
    profit = PER_SET - total
    if legs is None:
        legs = (
            (
                "buy_complete_set",
                (
                    (COLLATERAL, -total),
                    ("A", 1),
                    ("B", 1),
                    ("C", 1),
                ),
            ),
            (
                "redeem_complete_set_non_atomic",
                (
                    (COLLATERAL, claim.collateral_per_set),
                    ("A", -1),
                    ("B", -1),
                    ("C", -1),
                ),
            ),
        )
    profit_vector = (
        (COLLATERAL, profit),
        ("A", 0),
        ("B", 0),
        ("C", 0),
    )
    return {
        "market_id": claim.market_id,
        "outcome_ids": claim.outcome_ids,
        "collateral_asset": claim.collateral_asset,
        "asks": dict(ASKS),
        "total_ask_cost": total,
        "collateral_per_set": claim.collateral_per_set,
        "profit_per_set": profit,
        "profit_vector": profit_vector,
        "legs": legs,
        "conservation_proof": profit_vector,
        "atomicity": atomicity,
    }


# ---------------------------------------------------------------------------
# split / merge conservation (exact integers, per-asset vector)
# ---------------------------------------------------------------------------


def test_split_mints_every_outcome_and_conserves_exactly() -> None:
    claim = _claim()
    receipt = split_outcome_vector(claim, 500_000)
    assert isinstance(receipt, SplitReceipt)
    assert dict(receipt.shares) == {"A": 500_000, "B": 500_000, "C": 500_000}
    assert receipt.collateral_amount == 500_000
    assert receipt.conservation_proof == (
        (COLLATERAL, -500_000),
        ("A", 500_000),
        ("B", 500_000),
        ("C", 500_000),
    )
    assert claims_conserved(claim, -500_000, dict(receipt.shares)) is True
    # Split atomicity is protocol-specific and stays UNKNOWN (never asserted).
    assert receipt.atomicity is None


def test_merge_complete_vector_returns_exact_collateral() -> None:
    claim = _claim()
    receipt = merge_outcome_vector(claim, {"A": 250_000, "B": 250_000, "C": 250_000})
    assert isinstance(receipt, MergeReceipt)
    assert receipt.collateral_minted == 250_000
    assert dict(receipt.shares_burned) == {
        "A": -250_000,
        "B": -250_000,
        "C": -250_000,
    }
    assert receipt.conservation_proof == (
        (COLLATERAL, 250_000),
        ("A", -250_000),
        ("B", -250_000),
        ("C", -250_000),
    )
    assert receipt.atomicity is None


def test_merge_missing_share_typed_rejection() -> None:
    claim = _claim()
    with pytest.raises(ConditionalClaimError, match="incomplete_outcome_vector"):
        merge_outcome_vector(claim, {"A": 100_000, "C": 100_000})
    with pytest.raises(ConditionalClaimError, match="outcome_unknown"):
        merge_outcome_vector(
            claim, {"A": 100_000, "B": 100_000, "C": 100_000, "X": 100_000}
        )
    with pytest.raises(ConditionalClaimError, match="incomplete_outcome_vector"):
        merge_outcome_vector(claim, {"A": 100_000, "B": 0, "C": 100_000})


def test_merge_unequal_vector_typed_rejection() -> None:
    claim = _claim()
    with pytest.raises(ConditionalClaimError, match="incomplete_outcome_vector"):
        merge_outcome_vector(claim, {"A": 250_000, "B": 249_999, "C": 250_000})


def test_split_rejects_invalid_collateral_amounts() -> None:
    claim = _claim()
    for bad in (0, -1, True, 1.5, "100", None):
        with pytest.raises(ConditionalClaimError, match="invalid_collateral_amount"):
            split_outcome_vector(claim, bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# complete-set arbitrage evaluator (exact hand-computed vector)
# ---------------------------------------------------------------------------


def test_complete_set_arb_exact_hand_computed_vector() -> None:
    claim = _claim()
    evaluator = CompleteSetArbEvaluator(claim)
    candidate = evaluator.evaluate(ASKS)
    assert candidate is not None
    # Hand-computed: 300_000 + 350_000 + 250_000 = 900_000 < 1_000_000.
    assert candidate.total_ask_cost == 900_000
    assert candidate.profit_per_set == 100_000
    assert candidate.profit_vector == (
        (COLLATERAL, 100_000),
        ("A", 0),
        ("B", 0),
        ("C", 0),
    )
    assert candidate.legs == (
        (
            "buy_complete_set",
            ((COLLATERAL, -900_000), ("A", 1), ("B", 1), ("C", 1)),
        ),
        (
            "redeem_complete_set_non_atomic",
            ((COLLATERAL, 1_000_000), ("A", -1), ("B", -1), ("C", -1)),
        ),
    )
    assert candidate.conservation_proof == candidate.profit_vector
    assert candidate.atomicity == NON_ATOMIC
    assert evaluator.redemption_atomicity() == NON_ATOMIC


def test_arb_no_trade_at_or_above_par() -> None:
    claim = _claim()
    evaluator = CompleteSetArbEvaluator(claim)
    par = {"A": 300_000, "B": 350_000, "C": 350_000}  # total == 1_000_000
    assert evaluator.evaluate(par) is None
    above = {"A": 300_000, "B": 350_000, "C": 350_001}  # total > 1_000_000
    assert evaluator.evaluate(above) is None


def test_unknown_price_blocked_never_treated_as_zero() -> None:
    claim = _claim()
    evaluator = CompleteSetArbEvaluator(claim)
    # If the unknown B ask were silently treated as 0, the set would cost
    # 550_000 < 1_000_000 and a fake candidate would appear; it must not.
    with pytest.raises(ConditionalClaimError, match="price_unknown"):
        evaluator.evaluate({"A": 300_000, "B": None, "C": 250_000})
    with pytest.raises(ConditionalClaimError, match="price_unknown"):
        evaluator.evaluate({"A": 300_000, "B": 350_000})  # C missing
    with pytest.raises(ConditionalClaimError, match="invalid_price"):
        evaluator.evaluate({"A": -1, "B": 350_000, "C": 250_000})
    with pytest.raises(ConditionalClaimError, match="invalid_price"):
        evaluator.evaluate({"A": "300000", "B": 350_000, "C": 250_000})  # type: ignore[dict-item]
    with pytest.raises(ConditionalClaimError, match="outcome_unknown"):
        evaluator.evaluate({"A": 300_000, "B": 350_000, "C": 250_000, "D": 1})


def test_non_exhaustive_or_non_mutually_exclusive_fail_closed() -> None:
    evaluator = CompleteSetArbEvaluator(_claim(exhaustive=False))
    with pytest.raises(ConditionalClaimError, match="outcome_set_incomplete"):
        evaluator.evaluate(ASKS)
    evaluator = CompleteSetArbEvaluator(_claim(mutually_exclusive=False))
    with pytest.raises(ConditionalClaimError, match="outcome_set_incomplete"):
        evaluator.evaluate(ASKS)
    # Settlement side fails closed on the same unproven flags.
    with pytest.raises(ConditionalClaimError, match="outcome_set_incomplete"):
        redeem_winning_shares(
            _claim(exhaustive=False),
            {"A": 100_000},
            winning_outcome_id="A",
            resolution=_resolution(),
            at_slot=250,
        )


def test_collateral_unknown_blocks_evaluator() -> None:
    claim = _claim(collateral_per_set=None)
    evaluator = CompleteSetArbEvaluator(claim)
    with pytest.raises(ConditionalClaimError, match="collateral_unknown"):
        evaluator.evaluate(ASKS)


# ---------------------------------------------------------------------------
# settlement: resolution, dispute window, non-atomic classification
# ---------------------------------------------------------------------------


def test_redemption_before_dispute_window_blocked() -> None:
    claim = _claim()
    shares = {"A": 100_000}
    # Resolution not finalized at all.
    with pytest.raises(ConditionalClaimError, match="dispute_window_open"):
        redeem_winning_shares(
            claim,
            shares,
            winning_outcome_id="A",
            resolution=_resolution(finalized=False),
            at_slot=999,
        )
    # Finalized but the end slot itself is still inside the window.
    with pytest.raises(ConditionalClaimError, match="dispute_window_open"):
        redeem_winning_shares(
            claim,
            shares,
            winning_outcome_id="A",
            resolution=_resolution(),
            at_slot=200,
        )
    with pytest.raises(ConditionalClaimError, match="dispute_window_open"):
        redeem_winning_shares(
            claim,
            shares,
            winning_outcome_id="A",
            resolution=_resolution(),
            at_slot=150,
        )


def test_redemption_non_atomic_classification_enforced() -> None:
    claim = _claim()
    receipt = redeem_winning_shares(
        claim,
        {"A": 250_000},
        winning_outcome_id="A",
        resolution=_resolution(),
        at_slot=250,
    )
    assert isinstance(receipt, RedemptionReceipt)
    assert receipt.payout_amount == 250_000
    assert receipt.conservation_proof == (
        ("A", -250_000),
        (COLLATERAL, 250_000),
    )
    assert receipt.atomicity == NON_ATOMIC
    assert REDEMPTION_ATOMICITY == NON_ATOMIC
    assert CompleteSetArbEvaluator.REDEMPTION_ATOMICITY == NON_ATOMIC
    assert require_non_atomic(NON_ATOMIC) == NON_ATOMIC


def test_atomicity_misclassification_guard() -> None:
    with pytest.raises(ConditionalClaimError, match="atomicity_misclassified"):
        require_non_atomic("ATOMIC")
    with pytest.raises(ConditionalClaimError, match="atomicity_misclassified"):
        RedemptionReceipt(
            market_id="research/sx07-market-001",
            collateral_asset=COLLATERAL,
            winning_outcome_id="A",
            share_amount=100_000,
            payout_amount=100_000,
            at_slot=250,
            dispute_window_end_slot=200,
            conservation_proof=(("A", -100_000), (COLLATERAL, 100_000)),
            atomicity="ATOMIC",
        )
    with pytest.raises(ConditionalClaimError, match="atomicity_misclassified"):
        CompleteSetArbCandidate(**_arb_candidate_kwargs(atomicity="ATOMIC"))


def test_double_redemption_rejected() -> None:
    claim = _claim()
    shares = {"A": 100_000}
    first = redeem_winning_shares(
        claim,
        shares,
        winning_outcome_id="A",
        resolution=_resolution(),
        at_slot=250,
        already_redeemed=(),
    )
    assert first.share_amount == 100_000
    with pytest.raises(ConditionalClaimError, match="already_redeemed"):
        redeem_winning_shares(
            claim,
            shares,
            winning_outcome_id="A",
            resolution=_resolution(),
            at_slot=250,
            already_redeemed=("A",),
        )


def test_wrong_share_redemption_rejected() -> None:
    claim = _claim()
    with pytest.raises(ConditionalClaimError, match="not_winning_share"):
        redeem_winning_shares(
            claim,
            {"B": 100_000},
            winning_outcome_id="A",
            resolution=_resolution(),
            at_slot=250,
        )
    with pytest.raises(ConditionalClaimError, match="not_winning_share"):
        redeem_winning_shares(
            claim,
            {"A": 100_000, "B": 1},
            winning_outcome_id="A",
            resolution=_resolution(),
            at_slot=250,
        )
    with pytest.raises(ConditionalClaimError, match="incomplete_outcome_vector"):
        redeem_winning_shares(
            claim,
            {"B": 0},
            winning_outcome_id="A",
            resolution=_resolution(),
            at_slot=250,
        )
    with pytest.raises(ConditionalClaimError, match="invalid_share_count"):
        redeem_winning_shares(
            claim,
            {"A": -5},
            winning_outcome_id="A",
            resolution=_resolution(),
            at_slot=250,
        )


def test_merge_after_resolution_policy_rejection() -> None:
    claim = _claim()
    shares = {"A": 100_000, "B": 100_000, "C": 100_000}
    with pytest.raises(ConditionalClaimError, match="merge_after_resolution"):
        merge_outcome_vector(claim, shares, resolution=_resolution())
    # Without a resolution event the merge stays allowed (policy is fail
    # closed only once resolution exists).
    receipt = merge_outcome_vector(claim, shares)
    assert receipt.collateral_minted == 100_000


# ---------------------------------------------------------------------------
# per-asset conservation: scalar fake swaps never pass
# ---------------------------------------------------------------------------


def test_per_asset_conservation_rejects_scalar_fake_swap() -> None:
    claim = _claim()
    # Scalar sum of |share deltas| equals |collateral|, but outcome B got 0
    # and A got the double amount: per-asset conservation must fail.
    fake = {"A": 200_000, "B": 0, "C": 0}
    assert claims_conserved(claim, -200_000, fake) is False
    real = {"A": 200_000, "B": 200_000, "C": 200_000}
    assert claims_conserved(claim, -200_000, real) is True
    # Forged arbitrage legs that only scalar-net correctly are rejected at
    # construction (B nets +1, C nets -1; scalar net still equals profit).
    scalar_forged_legs = (
        (
            "buy_complete_set",
            ((COLLATERAL, -900_000), ("A", 1), ("B", 2), ("C", 0)),
        ),
        (
            "redeem_complete_set_non_atomic",
            ((COLLATERAL, 1_000_000), ("A", -1), ("B", -1), ("C", -1)),
        ),
    )
    with pytest.raises(ConditionalClaimError, match="conservation_violated"):
        CompleteSetArbCandidate(**_arb_candidate_kwargs(legs=scalar_forged_legs))
    # Forged split receipt with a tampered conservation proof is rejected.
    with pytest.raises(ConditionalClaimError, match="conservation_violated"):
        SplitReceipt(
            market_id=claim.market_id,
            collateral_asset=COLLATERAL,
            collateral_amount=100_000,
            shares={"A": 100_000, "B": 100_000, "C": 100_000},
            conservation_proof=(
                (COLLATERAL, -100_000),
                ("A", 100_000),
                ("B", 0),
                ("C", 100_000),
            ),
        )


# ---------------------------------------------------------------------------
# determinism and the one-protocol-dossier gate
# ---------------------------------------------------------------------------


def test_determinism_exact_repeat_and_digest() -> None:
    claim = _claim()
    evaluator = CompleteSetArbEvaluator(claim)
    first = evaluator.evaluate(ASKS)
    second = evaluator.evaluate(ASKS)
    assert first is not None and second is not None
    assert first == second
    assert first.digest() == second.digest()
    assert first.digest() == first.digest()
    split_a = split_outcome_vector(claim, 400_000)
    split_b = split_outcome_vector(claim, 400_000)
    assert split_a == split_b
    assert dict(split_a.shares) == dict(split_b.shares)


def test_protocol_dossier_gate_documented_and_atomicity_unknown() -> None:
    assert "dossier" in PROTOCOL_DOSSIER_GATE
    assert "immutable versioned dossier" in PROTOCOL_DOSSIER_GATE
    # Split/merge atomicity stays UNKNOWN (None) pending the dossier gate.
    claim = _claim()
    assert split_outcome_vector(claim, 10_000).atomicity is None
    assert (
        merge_outcome_vector(claim, {"A": 10_000, "B": 10_000, "C": 10_000}).atomicity
        is None
    )

"""SX-02 offline tests: flash-mint vs lender-flashloan financing economics.

All vectors are exact integer expectations computed by hand from the pinned
terms; timestamps are pinned, so every test is deterministic and offline.
"""

from dataclasses import replace

import pytest

from src.economics.flash_capital_graph.flash_mint_options import (
    INVARIANTS,
    LOCAL_ATOMIC_ATOMICITY,
    LOCAL_ATOMIC_UNPROVEN_ATOMICITY,
    FinancingBlockReason,
    FlashMintFinancingOption,
    FlashMintTerms,
    LenderFlashLoanOption,
    ProtocolDocsPin,
    compare_options,
)

T0 = 1_700_000_000.0
NOW = T0 + 10.0
FRESHNESS_S = 30.0

DOCS_PIN = ProtocolDocsPin(
    url="https://issuer.example/flash-mint",
    version="docs-v1.2.3",
    license="MIT",
    accessed_at=1_690_000_000.0,
)


def mint_terms(**changes):
    terms = FlashMintTerms(
        protocol="issuer-flash-mint",
        asset="mint:issuer-usdx",
        settlement_domain="solana",
        source_revision="docs@2026-11-14",
        protocol_docs_pin=DOCS_PIN,
        caller_eligibility=True,
        eligibility_evidence="dossier:issuer-eligibility@rev1",
        receiver_callback_required=True,
        receiver_callback_supported=True,
        fee_bps=9,
        max_mint_cap=1_000_000,
        observed_capacity=800_000,
        capacity_source="chain_state_read",
        capacity_observed_at=T0,
        evidence_freshness_s=FRESHNESS_S,
        same_tx_burn_required=True,
        same_tx_burn_proven=True,
    )
    return replace(terms, **changes)


def lender_option(**changes):
    option = LenderFlashLoanOption(
        provider="project0",
        asset="USDC-solana",
        settlement_domain="solana",
        atomicity_class="LOCAL_ATOMIC_CANDIDATE",
        source_revision="edge@5769b074",
        fee_bps=10,
        capacity=900_000,
        capacity_source="chain_state_read",
        capacity_observed_at=T0,
        evidence_freshness_s=FRESHNESS_S,
    )
    return replace(option, **changes)


def evaluate_mint(amount, *, now=NOW, **changes):
    return FlashMintFinancingOption(mint_terms(**changes)).evaluate(amount, now=now)


def evaluate_lender(amount, *, now=NOW, **changes):
    return lender_option(**changes).evaluate(amount, now=now)


def reasons(quote):
    return [blocker.reason for blocker in quote.blockers]


def test_flash_mint_exact_floor_fee_and_repayment_vectors():
    quote = evaluate_mint(9999, fee_bps=5)
    assert quote.fee_amount == 4  # floor(9999*5/10000) = 4, not ceil 5
    assert quote.repayment_amount == 9999 + 4 == 10003
    assert quote.fee_rounding == "floor_bps_erc3156"
    assert quote.capacity_limit == 800_000  # min(cap 1_000_000, observed)
    assert quote.is_actionable
    assert quote.atomicity_class == LOCAL_ATOMIC_ATOMICITY
    assert quote.atomicity_proof == (
        "flash_mint_same_tx_burn:issuer-flash-mint:docs@2026-11-14"
    )
    quote = evaluate_mint(789_654)
    assert quote.fee_amount == 710  # floor(789654*9/10000) = 710
    assert quote.repayment_amount == 790_364
    quote = evaluate_mint(10_000, fee_bps=0)
    assert quote.fee_amount == 0  # pinned zero fee, distinct from unknown
    assert quote.repayment_amount == 10_000
    assert quote.is_actionable


def test_unknown_mint_fee_blocks_and_is_never_zero():
    quote = evaluate_mint(10_000, fee_bps=None)
    assert reasons(quote) == [FinancingBlockReason.MINT_FEE_UNKNOWN]
    assert quote.fee_amount is None  # unknown is never coerced to zero
    assert quote.repayment_amount is None
    assert not quote.is_actionable


def test_mint_cap_exceeded_and_binding_capacity():
    quote = evaluate_mint(800_001)
    assert reasons(quote) == [FinancingBlockReason.MINT_CAP_EXCEEDED]
    quote = evaluate_mint(800_000)
    assert quote.blockers == ()
    assert quote.capacity_limit == 800_000
    # Cap-only terms: no observation, the pinned protocol cap still bounds.
    quote = evaluate_mint(
        1001,
        observed_capacity=None,
        capacity_source=None,
        capacity_observed_at=None,
        evidence_freshness_s=None,
        max_mint_cap=1000,
    )
    assert reasons(quote) == [FinancingBlockReason.MINT_CAP_EXCEEDED]
    assert quote.capacity_limit == 1000
    assert quote.freshness_margin_s is None
    quote = evaluate_mint(
        1000,
        observed_capacity=None,
        capacity_source=None,
        capacity_observed_at=None,
        evidence_freshness_s=None,
        max_mint_cap=1000,
    )
    assert quote.blockers == ()
    assert quote.is_actionable


def test_caller_ineligible_and_unproven_eligibility():
    quote = evaluate_mint(10_000, caller_eligibility=False)
    assert reasons(quote) == [FinancingBlockReason.CALLER_INELIGIBLE]
    assert not quote.is_actionable
    quote = evaluate_mint(10_000, eligibility_evidence=None)
    assert reasons(quote) == [FinancingBlockReason.CALLER_ELIGIBILITY_UNPROVEN]
    assert not quote.is_actionable


def test_receiver_callback_unsupported():
    quote = evaluate_mint(10_000, receiver_callback_supported=False)
    assert reasons(quote) == [FinancingBlockReason.RECEIVER_CALLBACK_UNSUPPORTED]
    assert not quote.is_actionable
    assert evaluate_mint(10_000).blockers == ()


def test_same_tx_repay_unproven_blocks_local_atomic():
    quote = evaluate_mint(10_000, same_tx_burn_proven=False)
    assert reasons(quote) == [FinancingBlockReason.SAME_TX_REPAY_UNPROVEN]
    assert quote.atomicity_class == LOCAL_ATOMIC_UNPROVEN_ATOMICITY
    assert quote.atomicity_proof is None
    assert not quote.is_actionable
    # Unproven repayment closure blocks LOCAL_ATOMIC even when the protocol
    # does not flag the burn as required (fail closed).
    quote = evaluate_mint(
        10_000, same_tx_burn_required=False, same_tx_burn_proven=False
    )
    assert reasons(quote) == [FinancingBlockReason.SAME_TX_REPAY_UNPROVEN]


def test_stale_capacity_freshness_window():
    quote = evaluate_mint(10_000, now=T0 + FRESHNESS_S)
    assert quote.blockers == ()  # boundary age == freshness stays fresh
    quote = evaluate_mint(10_000, now=T0 + FRESHNESS_S + 0.5)
    assert reasons(quote) == [FinancingBlockReason.CAPACITY_STALE]
    assert quote.fee_amount == 9  # fee stays exact; the option is blocked
    assert quote.repayment_amount == 10_009
    assert not quote.is_actionable
    quote = evaluate_mint(10_000, now=T0 - 1.0)  # observation in the future
    assert reasons(quote) == [FinancingBlockReason.CAPACITY_STALE]


def test_lender_unknown_fee_and_capacity_block():
    quote = evaluate_lender(10_000, fee_bps=None)
    assert reasons(quote) == [FinancingBlockReason.LENDER_FEE_UNKNOWN]
    assert quote.fee_amount is None
    assert quote.repayment_amount is None
    assert not quote.is_actionable
    quote = evaluate_lender(
        10_000,
        capacity=None,
        capacity_source=None,
        capacity_observed_at=None,
        evidence_freshness_s=None,
    )
    assert reasons(quote) == [FinancingBlockReason.LENDER_CAPACITY_UNKNOWN]
    quote = evaluate_lender(
        10_000,
        fee_bps=None,
        capacity=None,
        capacity_source=None,
        capacity_observed_at=None,
        evidence_freshness_s=None,
    )
    assert set(reasons(quote)) == {
        FinancingBlockReason.LENDER_FEE_UNKNOWN,
        FinancingBlockReason.LENDER_CAPACITY_UNKNOWN,
    }


def test_lender_stale_capacity_exceeded_and_ceiling_fee():
    quote = evaluate_lender(10_000, capacity_observed_at=T0 - 31.0)
    assert reasons(quote) == [FinancingBlockReason.LENDER_CAPACITY_STALE]
    quote = evaluate_lender(900_001)
    assert reasons(quote) == [FinancingBlockReason.LENDER_CAPACITY_EXCEEDED]
    # Capital-edge conservative ceiling: floor would give 9, ceiling gives 10.
    quote = evaluate_lender(9999)
    assert quote.fee_amount == 10
    assert quote.repayment_amount == 10_009
    assert quote.fee_rounding == "ceil_bps_flash_capital_edge"
    assert quote.atomicity_class == LOCAL_ATOMIC_ATOMICITY
    assert quote.atomicity_proof == (
        "flash_capital_edge:project0:USDC-solana:LOCAL_ATOMIC_CANDIDATE"
    )
    quote = evaluate_lender(10_000)
    assert quote.fee_amount == 10
    assert quote.repayment_amount == 10_010
    assert quote.blockers == ()


def test_lender_refuses_non_local_atomic_and_unqualified_inputs():
    with pytest.raises(ValueError, match="unsupported capital atomicity"):
        lender_option(atomicity_class="HEDGED_NON_ATOMIC")
    with pytest.raises(ValueError, match="unqualified capital provider"):
        lender_option(provider="unqualified-pool")
    with pytest.raises(ValueError, match="capital provider/chain mismatch"):
        lender_option(provider="project0", settlement_domain="sui")
    with pytest.raises(ValueError, match="fee_bps"):
        mint_terms(fee_bps=-1)
    with pytest.raises(ValueError, match="fee_bps"):
        lender_option(fee_bps=-5)


def test_compare_options_deterministic_winner_and_blocked_never_wins():
    lender = lender_option()
    mint = FlashMintFinancingOption(mint_terms())
    comparison = compare_options(lender, mint, 100_000, now=NOW)
    assert comparison.winner_kind == "flash_mint"
    assert comparison.winner_reason == "repayment_asc"
    assert comparison.selection_key == (
        100_090,
        -20.0,
        "docs@2026-11-14",
        "flash_mint",
    )
    assert comparison.lender_quote.repayment_amount == 100_100
    assert comparison.flash_mint_quote.repayment_amount == 100_090
    # Determinism: identical inputs produce an identical comparison.
    assert compare_options(lender, mint, 100_000, now=NOW) == comparison
    # A blocked flash-mint can never win.
    blocked_mint = FlashMintFinancingOption(mint_terms(fee_bps=None))
    comparison = compare_options(lender, blocked_mint, 100_000, now=NOW)
    assert comparison.winner_kind == "lender_flashloan"
    assert comparison.winner_reason == "only_actionable_option"
    assert not comparison.flash_mint_quote.is_actionable
    # No actionable option at all: no winner is reported.
    both_blocked = compare_options(
        lender_option(fee_bps=None),
        FlashMintFinancingOption(mint_terms(fee_bps=None)),
        100_000,
        now=NOW,
    )
    assert both_blocked.winner_kind is None
    assert both_blocked.winner_reason == "no_actionable_option"
    assert both_blocked.selection_key is None


def test_comparison_tie_break_freshness_then_revision_then_kind():
    # Equal repayments (amount 10_000, both 10 bps): mint is fresher.
    comparison = compare_options(
        lender_option(),
        FlashMintFinancingOption(mint_terms(fee_bps=10, capacity_observed_at=T0 + 5.0)),
        10_000,
        now=NOW,
    )
    assert comparison.lender_quote.repayment_amount == 10_010
    assert comparison.flash_mint_quote.repayment_amount == 10_010
    assert comparison.winner_kind == "flash_mint"
    assert comparison.winner_reason == "freshness_desc"
    # Equal repayment and freshness: lexicographic source revision decides.
    comparison = compare_options(
        lender_option(source_revision="a@1", capacity_observed_at=T0 + 5.0),
        FlashMintFinancingOption(
            mint_terms(
                fee_bps=10,
                source_revision="b@1",
                capacity_observed_at=T0 + 5.0,
            )
        ),
        10_000,
        now=NOW,
    )
    assert comparison.winner_kind == "lender_flashloan"
    assert comparison.winner_reason == "source_revision_lexicographic"
    comparison = compare_options(
        lender_option(source_revision="c@1", capacity_observed_at=T0 + 5.0),
        FlashMintFinancingOption(
            mint_terms(
                fee_bps=10,
                source_revision="b@1",
                capacity_observed_at=T0 + 5.0,
            )
        ),
        10_000,
        now=NOW,
    )
    assert comparison.winner_kind == "flash_mint"
    assert comparison.winner_reason == "source_revision_lexicographic"
    # Full tie: final deterministic component is the option kind.
    comparison = compare_options(
        lender_option(source_revision="r@1", capacity_observed_at=T0 + 5.0),
        FlashMintFinancingOption(
            mint_terms(
                fee_bps=10,
                source_revision="r@1",
                capacity_observed_at=T0 + 5.0,
            )
        ),
        10_000,
        now=NOW,
    )
    assert comparison.winner_kind == "flash_mint"
    assert comparison.winner_reason == "option_kind_lexicographic"


def test_repayment_never_below_minted_and_no_negative_fee():
    amounts = (1, 9999, 10_000, 789_654)
    for bps in (0, 1, 7, 9, 250, 9999):
        for amount in amounts:
            mint_quote = evaluate_mint(amount, fee_bps=bps)
            assert mint_quote.fee_amount >= 0
            assert mint_quote.repayment_amount == amount + mint_quote.fee_amount
            assert mint_quote.repayment_amount >= amount
            lender_quote = evaluate_lender(amount, fee_bps=bps)
            assert lender_quote.fee_amount >= 0
            assert lender_quote.repayment_amount == amount + lender_quote.fee_amount
            assert lender_quote.repayment_amount >= amount
    with pytest.raises(ValueError):
        mint_terms(fee_bps=-1)
    with pytest.raises(ValueError):
        lender_option(fee_bps=-1)


def test_evaluate_is_idempotent():
    mint = FlashMintFinancingOption(mint_terms())
    first = mint.evaluate(50_000, now=NOW)
    second = mint.evaluate(50_000, now=NOW)
    assert first == second
    assert first.blockers == second.blockers == ()
    lender = lender_option()
    assert lender.evaluate(50_000, now=NOW) == lender.evaluate(50_000, now=NOW)
    blocked = FlashMintFinancingOption(mint_terms(fee_bps=None))
    assert blocked.evaluate(50_000, now=NOW) == blocked.evaluate(50_000, now=NOW)


def test_no_cross_domain_funding_and_invariant_flags():
    with pytest.raises(ValueError, match="cross-domain financing"):
        compare_options(
            lender_option(),
            FlashMintFinancingOption(mint_terms(settlement_domain="sui")),
            10_000,
            now=NOW,
        )
    comparison = compare_options(
        lender_option(),
        FlashMintFinancingOption(mint_terms()),
        10_000,
        now=NOW,
    )
    assert comparison.settlement_domain == "solana"
    assert comparison.lender_quote.settlement_domain == "solana"
    assert comparison.flash_mint_quote.settlement_domain == "solana"
    assert (
        comparison.invariants
        == INVARIANTS
        == (
            "no_tvl_proxies",
            "no_cross_domain_funding",
            "unknown_never_coerced",
        )
    )

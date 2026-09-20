from __future__ import annotations

import pytest

from src.lending.agg07 import (
    Agg07LendingError,
    CapitalVariant,
    CapacityReleaseEvent,
    KaminoFlashLoanEvidence,
    ProtocolResearchEvidence,
    RateMarketFrame,
    RateMarketKind,
    RateVenueQuote,
    ResearchDisposition,
    StripMergeQuote,
    build_kamino_loan_plan,
    compare_rate_venues,
    evaluate_capacity_release,
    evaluate_strip_merge,
    select_capital_variant,
)
from src.lending.controlled_expansion import (
    ExpansionCandidateIdentity,
    LenderCapability,
    LenderFeeObligation,
    QualifiedLenderCandidate,
)


H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64


def qualified_candidate(
    *,
    cid: str,
    combo: str,
    gross: int,
    wallet_cost: int,
    amount: int,
) -> QualifiedLenderCandidate:
    capability = LenderCapability.from_mapping(
        {
            "capability_id": cid,
            "profile": "agg07-test",
            "status": "production_qualified",
            "blockers": [],
            "combination_ids": [combo],
        }
    )
    return QualifiedLenderCandidate(
        identity=ExpansionCandidateIdentity(
            candidate_id=f"{cid}-{amount}",
            capability_id=cid,
            combination_id=combo,
            combination_digest=H1,
            message_sha256=H2,
            simulation_sha256=H2,
        ),
        capability=capability,
        gross_edge_atomic=gross,
        obligation=LenderFeeObligation(
            principal_atomic=amount,
            repayment_atomic=amount + 1,
            protocol_fee_atomic=1,
            wallet_cost_atomic=wallet_cost,
        ),
        repayment_proven=True,
        simulation_message_sha256=H2,
    )


def research(**overrides: object) -> ProtocolResearchEvidence:
    values: dict[str, object] = {
        "protocol": "exponent",
        "official_source": "https://github.com/exponent-finance/exponent-core",
        "immutable_source_ref": "deadbeef",
        "license_id": "BSL-1.1",
        "deployment_id": "deployment",
        "abi_or_idl_sha256": H1,
        "executable_abi_verified": True,
        "current_liquidity_verified": True,
        "production_reuse_allowed": True,
    }
    values.update(overrides)
    return ProtocolResearchEvidence(**values)  # type: ignore[arg-type]


def test_unproven_save_or_exponent_stays_blocked_protocol():
    evidence = research(
        protocol="save",
        deployment_id=None,
        executable_abi_verified=False,
        current_liquidity_verified=False,
    )
    assert evidence.disposition is ResearchDisposition.BLOCKED_PROTOCOL
    assert "DEPLOYMENT_IDENTITY_MISSING" in evidence.blockers
    assert "EXECUTABLE_ABI_UNVERIFIED" in evidence.blockers


def test_kamino_plan_binds_final_prefix_index_fee_and_message():
    evidence = KaminoFlashLoanEvidence(
        combination_id="k1",
        reserve_id="reserve",
        reserve_enabled=True,
        capacity_atomic=1_000,
        principal_atomic=500,
        repayment_atomic=503,
        borrow_instruction_sha256=H1,
        repay_instruction_sha256=H2,
        reserve_state_sha256=H3,
        fee_config_sha256=H4,
        final_message_sha256=H1,
        simulation_message_sha256=H1,
        prefix_instruction_count=4,
        borrow_instruction_index=4,
        conformance_qualified=True,
        observed_slot=100,
        expires_at_slot=120,
    )
    plan = build_kamino_loan_plan(evidence, current_slot=110)
    assert plan.protocol_fee_atomic == 3
    assert plan.borrow_instruction_index == 4

    bad = KaminoFlashLoanEvidence(
        combination_id="k1",
        reserve_id="reserve",
        reserve_enabled=True,
        capacity_atomic=1_000,
        principal_atomic=500,
        repayment_atomic=503,
        borrow_instruction_sha256=H1,
        repay_instruction_sha256=H2,
        reserve_state_sha256=H3,
        fee_config_sha256=H4,
        final_message_sha256=H1,
        simulation_message_sha256=H1,
        prefix_instruction_count=5,
        borrow_instruction_index=4,
        conformance_qualified=True,
        observed_slot=100,
        expires_at_slot=120,
    )
    with pytest.raises(Agg07LendingError, match="BORROW_INSTRUCTION_INDEX_MISMATCH"):
        build_kamino_loan_plan(bad, current_slot=110)


def test_allocator_chooses_best_feasible_net_not_largest_principal():
    small = qualified_candidate(
        cid="kamino",
        combo="k1",
        gross=120,
        wallet_cost=10,
        amount=100,
    )
    large = qualified_candidate(
        cid="save",
        combo="s1",
        gross=130,
        wallet_cost=40,
        amount=500,
    )
    variants = (
        CapitalVariant(
            candidate=large,
            amount_atomic=500,
            reserve_capacity_atomic=1_000,
            rent_peak_atomic=20,
            compute_units=200_000,
            message_bytes=800,
            borrow_instruction_index=3,
            expected_borrow_instruction_index=3,
            observed_slot=100,
            expires_at_slot=120,
            prefix_solvent=True,
            lender_resource_ids=("save-reserve",),
        ),
        CapitalVariant(
            candidate=small,
            amount_atomic=100,
            reserve_capacity_atomic=200,
            rent_peak_atomic=5,
            compute_units=150_000,
            message_bytes=700,
            borrow_instruction_index=2,
            expected_borrow_instruction_index=2,
            observed_slot=100,
            expires_at_slot=120,
            prefix_solvent=True,
            lender_resource_ids=("kamino-reserve",),
        ),
    )
    selected = select_capital_variant(
        variants,
        current_slot=110,
        max_compute_units=300_000,
        max_message_bytes=1_000,
    )
    assert selected.selected.candidate is small


def test_allocator_rejects_shared_reserve_double_count():
    candidate = qualified_candidate(
        cid="kamino",
        combo="k1",
        gross=100,
        wallet_cost=5,
        amount=100,
    )
    variant = CapitalVariant(
        candidate=candidate,
        amount_atomic=100,
        reserve_capacity_atomic=200,
        rent_peak_atomic=0,
        compute_units=100,
        message_bytes=100,
        borrow_instruction_index=2,
        expected_borrow_instruction_index=2,
        observed_slot=100,
        expires_at_slot=120,
        prefix_solvent=True,
        lender_resource_ids=("same-reserve",),
        exit_resource_ids=("same-reserve",),
    )
    with pytest.raises(Agg07LendingError, match="no feasible"):
        select_capital_variant(
            (variant,),
            current_slot=110,
            max_compute_units=1_000,
            max_message_bytes=1_000,
        )


def frame(
    *,
    kind: RateMarketKind = RateMarketKind.CAPACITY_RELEASE,
) -> RateMarketFrame:
    return RateMarketFrame(
        market_id="market-a",
        kind=kind,
        underlying_asset="USDC",
        maturity_unix=2_000,
        observed_unix=1_000,
        capacity_atomic=1_000,
        shared_resource_id="reserve-a",
        state_sha256=H1,
        pt_asset="PT" if kind is RateMarketKind.EXPONENT_PT_YT else None,
        yt_asset="YT" if kind is RateMarketKind.EXPONENT_PT_YT else None,
    )


def test_capacity_release_requires_observed_release_and_closed_route():
    event = CapacityReleaseEvent(
        market_id="market-a",
        shared_resource_id="reserve-a",
        before_capacity_atomic=100,
        after_capacity_atomic=300,
        event_sha256=H2,
    )
    candidate = evaluate_capacity_release(
        frame(),
        event,
        route_input_atomic=100,
        route_min_output_atomic=120,
        route_cost_atomic=5,
    )
    assert candidate.accepted is True
    assert candidate.released_capacity_atomic == 200
    assert candidate.conservative_net_atomic == 15

    double_count = evaluate_capacity_release(
        frame(),
        event,
        route_input_atomic=100,
        route_min_output_atomic=120,
        route_cost_atomic=5,
        exit_resource_ids=("reserve-a",),
    )
    assert double_count.accepted is False
    assert double_count.reason is not None
    assert "SHARED_RESERVE_DOUBLE_COUNT" in double_count.reason


def test_exponent_source_permission_is_independent_from_market_math():
    quote = StripMergeQuote(
        market_id="market-a",
        maturity_unix=2_000,
        direction="merge",
        input_underlying_atomic=0,
        input_pt_atomic=100,
        input_yt_atomic=100,
        immediate_output_underlying_atomic=110,
        transaction_cost_atomic=2,
        depth_atomic=200,
        quote_sha256=H2,
    )
    blocked = evaluate_strip_merge(
        frame(kind=RateMarketKind.EXPONENT_PT_YT),
        quote,
        research=research(production_reuse_allowed=False),
    )
    assert blocked.accepted is False
    assert blocked.reason is not None
    assert "PRODUCTION_SOURCE_REUSE_NOT_ALLOWED" in blocked.reason


def test_future_yield_does_not_create_immediate_rate_arbitrage():
    left = RateVenueQuote(
        market_id="book",
        maturity_unix=2_000,
        immediate_input_atomic=100,
        immediate_output_atomic=99,
        future_cashflow_atomic=1_000,
        executable_depth_atomic=100,
        transaction_cost_atomic=1,
        quote_convention="exact-token-cashflow",
        quote_sha256=H2,
        fresh=True,
    )
    right = RateVenueQuote(
        market_id="clmm",
        maturity_unix=2_000,
        immediate_input_atomic=100,
        immediate_output_atomic=99,
        future_cashflow_atomic=2_000,
        executable_depth_atomic=100,
        transaction_cost_atomic=1,
        quote_convention="exact-token-cashflow",
        quote_sha256=H3,
        fresh=True,
    )
    candidate = compare_rate_venues(left, right, research=research())
    assert candidate.accepted is False
    assert candidate.conservative_immediate_net_atomic < 0

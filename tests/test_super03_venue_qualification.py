from __future__ import annotations

import pytest

from src.direct_venue.mpr2617 import CapabilityState, VenueFamily
from src.direct_venue.super03 import (
    BandQuoteVector,
    BenchmarkObservation,
    ConformanceStatus,
    CpmmQuoteVector,
    GenerationBoundSolverCache,
    InstructionConformance,
    SolverCacheKey,
    Super03Error,
    UpstreamAdmission,
    VenueIdentityEvidence,
    build_amount_bound_leg,
    build_fixed_workload_benchmark,
    qualify_band_venue_offline,
    qualify_cpmm_offline,
)
from src.production_qualification import AGG04CampaignPolicy
from src.strategies.stable_peg.math import LiquidityBand
from src.strategy.multihop_solver import (
    SearchEdge,
    SearchStopReason,
    search_bounded_cycles,
)

D1 = "1" * 64
D2 = "2" * 64
D3 = "3" * 64
D4 = "4" * 64
D5 = "5" * 64
P1 = "1" * 32
P2 = "2" * 32
P3 = "3" * 32
P4 = "4" * 32


def upstream(*, approved: bool = True) -> UpstreamAdmission:
    return UpstreamAdmission(
        repository="https://github.com/example/upstream",
        commit="a" * 40,
        symbol="quote_and_build",
        license_decision="reviewed fixture decision",
        reuse_mode="REFERENCE",
        license_review_approved=approved,
    )


def identity(
    venue: VenueFamily,
    *,
    deployment_verified: bool = True,
    complete: bool = True,
) -> VenueIdentityEvidence:
    return VenueIdentityEvidence(
        venue=venue,
        program_id=P1,
        pool_or_market=P2,
        input_mint=P3,
        output_mint=P4,
        genesis_sha256=D1,
        deployment_generation="deployment-1",
        account_layout_version="layout-1",
        state_generation="state-9",
        state_sha256=D2,
        dependency_account_sha256=(D3, D4),
        deployment_verified=deployment_verified,
        dependency_closure_complete=complete,
    )


def instruction(*, match: bool = True) -> InstructionConformance:
    return InstructionConformance(
        instruction_data_sha256=D3,
        instruction_accounts_sha256=D4,
        reference_instruction_data_sha256=D3 if match else D5,
        reference_instruction_accounts_sha256=D4,
    )


def test_cpmm_integer_transfer_fee_vector_builds_offline_capability() -> None:
    vector = CpmmQuoteVector(
        amount_in=1_000,
        reserve_in=100_000,
        reserve_out=50_000,
        trade_fee_numerator=3_000,
        trade_fee_denominator=1_000_000,
        input_transfer_fee=10,
        output_transfer_fee=2,
        reference_amount_out=486,
        reference_trade_fee=3,
        reference_vector_sha256=D5,
    )
    assert vector.local_quote() == (486, 3)

    result = qualify_cpmm_offline(
        upstream=upstream(),
        identity=identity(VenueFamily.RAYDIUM_CPMM),
        quote=vector,
        instruction=instruction(),
        expires_at_unix=2_000_000_000,
    )

    assert result.status is ConformanceStatus.OFFLINE_VERIFIED
    assert result.blockers == ()
    assert result.live_enabled is False
    assert result.capability is not None
    assert result.capability.state is CapabilityState.OFFLINE_VERIFIED
    assert result.capability.venue is VenueFamily.RAYDIUM_CPMM
    leg = build_amount_bound_leg(result)
    assert leg.amount_in == 1_000
    assert leg.guaranteed_min_out == 486
    assert leg.capability_hash == result.capability.capability_hash


def test_cpmm_reference_mismatch_fails_closed() -> None:
    vector = CpmmQuoteVector(
        amount_in=1_000,
        reserve_in=100_000,
        reserve_out=50_000,
        trade_fee_numerator=3_000,
        trade_fee_denominator=1_000_000,
        input_transfer_fee=10,
        output_transfer_fee=2,
        reference_amount_out=487,
        reference_trade_fee=3,
        reference_vector_sha256=D5,
    )
    result = qualify_cpmm_offline(
        upstream=upstream(),
        identity=identity(VenueFamily.RAYDIUM_CPMM),
        quote=vector,
        instruction=instruction(),
        expires_at_unix=2_000_000_000,
    )
    assert result.status is ConformanceStatus.BLOCKED_EXTERNAL
    assert result.capability is None
    assert "RAYDIUM_CPMM_REFERENCE_VECTOR_MISMATCH" in result.blockers
    with pytest.raises(Super03Error, match="blocked conformance"):
        build_amount_bound_leg(result)


def test_missing_license_deployment_or_instruction_proof_cannot_qualify() -> None:
    vector = CpmmQuoteVector(
        amount_in=1_000,
        reserve_in=100_000,
        reserve_out=50_000,
        trade_fee_numerator=0,
        trade_fee_denominator=1_000_000,
        input_transfer_fee=0,
        output_transfer_fee=0,
        reference_amount_out=495,
        reference_trade_fee=0,
        reference_vector_sha256=D5,
    )
    result = qualify_cpmm_offline(
        upstream=upstream(approved=False),
        identity=identity(
            VenueFamily.RAYDIUM_CPMM,
            deployment_verified=False,
            complete=False,
        ),
        quote=vector,
        instruction=instruction(match=False),
        expires_at_unix=2_000_000_000,
    )
    assert result.capability is None
    assert set(result.blockers) >= {
        "UPSTREAM_LICENSE_REUSE_NOT_APPROVED",
        "DEPLOYMENT_IDENTITY_NOT_VERIFIED",
        "STATE_DEPENDENCY_CLOSURE_INCOMPLETE",
        "INSTRUCTION_REFERENCE_MISMATCH",
    }


def test_clmm_decoded_bands_require_complete_arrays_and_dynamic_fee() -> None:
    bands = (
        LiquidityBand(50, 2, 1, "tick-a"),
        LiquidityBand(50, 1, 1, "tick-b"),
    )
    vector = BandQuoteVector(
        amount_in=100,
        bands=bands,
        fee_numerator=0,
        fee_denominator=1_000_000,
        reference_amount_out=150,
        reference_fee=0,
        reference_consumed_input=100,
        reference_vector_sha256=D5,
        dynamic_fee_verified=True,
        arrays_complete=True,
    )
    assert vector.local_quote() == (150, 0, ("tick-a", "tick-b"))

    result = qualify_band_venue_offline(
        upstream=upstream(),
        identity=identity(VenueFamily.RAYDIUM_CLMM),
        quote=vector,
        instruction=instruction(),
        expires_at_unix=2_000_000_000,
    )
    assert result.status is ConformanceStatus.OFFLINE_VERIFIED
    assert result.capability is not None
    assert result.capability.venue is VenueFamily.RAYDIUM_CLMM


def test_meteora_partial_input_or_unverified_dynamic_fee_stays_blocked() -> None:
    vector = BandQuoteVector(
        amount_in=100,
        bands=(LiquidityBand(100, 1, 1, "bin-a"),),
        fee_numerator=0,
        fee_denominator=1_000_000,
        reference_amount_out=100,
        reference_fee=0,
        reference_consumed_input=90,
        reference_vector_sha256=D5,
        dynamic_fee_verified=False,
        arrays_complete=True,
    )
    result = qualify_band_venue_offline(
        upstream=upstream(),
        identity=identity(VenueFamily.METEORA_DLMM),
        quote=vector,
        instruction=instruction(),
        expires_at_unix=2_000_000_000,
    )
    assert result.status is ConformanceStatus.BLOCKED_EXTERNAL
    assert result.capability is None
    assert "VENUE_PARTIAL_INPUT_CONSUMPTION" in result.blockers
    assert "VENUE_DYNAMIC_FEE_UNVERIFIED" in result.blockers


def test_missing_band_coverage_is_not_linearized_or_silently_partial() -> None:
    vector = BandQuoteVector(
        amount_in=100,
        bands=(LiquidityBand(25, 1, 1, "bin-a"),),
        fee_numerator=0,
        fee_denominator=1_000_000,
        reference_amount_out=25,
        reference_fee=0,
        reference_consumed_input=100,
        reference_vector_sha256=D5,
        dynamic_fee_verified=True,
        arrays_complete=False,
    )
    result = qualify_band_venue_offline(
        upstream=upstream(),
        identity=identity(VenueFamily.METEORA_DLMM),
        quote=vector,
        instruction=instruction(),
        expires_at_unix=2_000_000_000,
    )
    assert result.capability is None
    assert "VENUE_TICK_BIN_ARRAY_CLOSURE_INCOMPLETE" in result.blockers
    assert "VENUE_LOCAL_BAND_COVERAGE_INSUFFICIENT" in result.blockers


def test_solver_cache_binds_amount_generation_adapter_policy_and_negative_ttl() -> None:
    cache = GenerationBoundSolverCache()
    key = SolverCacheKey(D1, 100, "state-1", "adapter-1", D2)
    other_generation = SolverCacheKey(D1, 100, "state-2", "adapter-1", D2)

    cache.put(
        key,
        value_sha256=D3,
        negative=True,
        now_ns=1_000,
        negative_ttl_ns=50,
    )
    assert cache.get(key, now_ns=1_049) is not None
    assert cache.get(key, now_ns=1_050) is None
    assert cache.get(other_generation, now_ns=1_050) is None

    cache.put(
        key,
        value_sha256=D4,
        negative=False,
        now_ns=2_000,
    )
    assert cache.invalidate_state_generation("state-1") == 1
    assert cache.get(key, now_ns=2_001) is None


def test_negative_cache_requires_bounded_ttl() -> None:
    cache = GenerationBoundSolverCache()
    with pytest.raises(Super03Error, match="bounded TTL"):
        cache.put(
            SolverCacheKey(D1, 1, "state", "adapter", D2),
            value_sha256=D3,
            negative=True,
            now_ns=0,
        )


def test_fixed_workload_benchmark_refuses_different_denominators() -> None:
    baseline = (
        BenchmarkObservation("a", "g1", True, True, 10, 1, 10),
        BenchmarkObservation("b", "g1", False, False, None, 1, 10),
    )
    challenger = (
        BenchmarkObservation("a", "g1", True, True, 12, 1, 8),
        BenchmarkObservation("b", "g1", True, False, -1, 1, 8),
    )
    report = build_fixed_workload_benchmark(baseline, challenger)
    assert report.case_count == 2
    assert report.baseline_feasible == 1
    assert report.challenger_feasible == 2
    assert report.baseline_work_units == 20
    assert report.challenger_work_units == 16

    with pytest.raises(Super03Error, match="identical"):
        build_fixed_workload_benchmark(
            baseline,
            challenger[:1],
        )


def test_super03_reuses_agg04_and_agg05_owners_instead_of_reimplementing() -> None:
    policy = AGG04CampaignPolicy(
        campaign_id="super03",
        profile_id="offline",
        source_commit="main",
        policy_version="v1",
        allowed_assets=("asset-a",),
        allowed_venues=("venue-a",),
        allowed_lenders=("lender-a",),
    )
    assert policy.policy_sha256

    edges = (
        SearchEdge("ab", "A", "B", "pool-ab", 2, 1, "g1"),
        SearchEdge("ba", "B", "A", "pool-ba", 1, 1, "g1"),
    )
    result = search_bounded_cycles(edges, start_asset="A", max_expansions=20)
    assert result.stop_reason is SearchStopReason.COMPLETE
    assert len(result.routes) == 1

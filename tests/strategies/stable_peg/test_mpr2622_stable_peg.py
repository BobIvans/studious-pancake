import pytest
from src.strategies.stable_peg import *


def asset(mint="A", allowed=True):
    return StableAssetEvidence(mint, "spl-token", 6, "stablecoin", "reg-1", f"admit-{mint}", "authorities-reviewed", "rooted-registry", allowed)

def ref(price=1_000_000, confidence=100, publish=900, fresh=True):
    return PegReferenceEvidence("pyth", "feed", "pyth-core-2026-08-26", publish, 99, price, -6, confidence, fresh, True, f"ref-{price}-{confidence}-{publish}")

def leg(inp, out, amount_in, amount_out, digest):
    return ExecutableLegQuote("venue", inp, out, amount_in, amount_out, 1, digest, "accounts", "ix", 120, "decoded-rooted")


def test_bool_rejected_as_integer():
    with pytest.raises(Exception):
        PegReferenceEvidence("p", "f", "g", 1, 1, True, -6, 1, True, True, "d")


def test_clmm_requires_tick_arrays_and_dlmm_requires_bins():
    with pytest.raises(Exception):
        PoolStateEvidence("Orca", "prog", "pool", ("A","B"), ("spl","spl"), ("v1","v2"), 1, "fork", ("raw",), "v1", 1, 1000, "state", "CLMM", sqrt_price_x64=1, tick_current=0, active_liquidity=1, tick_spacing=1)
    with pytest.raises(Exception):
        PoolStateEvidence("Meteora", "prog", "pool", ("A","B"), ("spl","spl"), ("v1","v2"), 1, "fork", ("raw",), "v1", 1, 1000, "state", "DLMM", active_bin=0, bin_step=1)


def test_exact_band_traversal_rounds_output_down_fee_up():
    out, fee, used = traverse_bands_exact(1000, (LiquidityBand(600, 1001, 1000, "t1"), LiquidityBand(500, 1002, 1000, "t2")), fee_numerator=501)
    assert fee == 1
    assert out == (600*1001)//1000 + (399*1002)//1000
    assert used == ("t1", "t2")


def test_insufficient_tick_bin_coverage_fails_closed():
    with pytest.raises(Exception):
        traverse_bands_exact(100, (LiquidityBand(50, 1, 1, "x"),))


def test_amount_coupling_and_candidate_hash_drift():
    good = make_candidate(principal_mint="A", repayment_mint="A", legs=(leg("A","B",100,110,"p1"),leg("B","A",110,105,"p2")), asset_digests=("a",), reference_digests=("r",), pool_digests=("p1","p2"), conservative_surplus=5)
    bad = make_candidate(principal_mint="A", repayment_mint="A", legs=(leg("A","B",100,110,"p1"),leg("B","A",109,105,"p2")), asset_digests=("a",), reference_digests=("r",), pool_digests=("p1","p2"), conservative_surplus=5)
    drift = make_candidate(principal_mint="A", repayment_mint="A", legs=(leg("A","B",100,110,"p1x"),leg("B","A",110,105,"p2")), asset_digests=("a",), reference_digests=("r",), pool_digests=("p1x","p2"), conservative_surplus=5)
    assert good.classification == CandidateClass.CANDIDATE
    assert bad.classification == CandidateClass.BLOCKED
    assert good.candidate_hash != drift.candidate_hash


def test_non_positive_surplus_is_no_trade():
    c = make_candidate(principal_mint="A", repayment_mint="A", legs=(leg("A","A",100,100,"p"),), asset_digests=("a",), reference_digests=("r",), pool_digests=("p",), conservative_surplus=0)
    assert c.classification == CandidateClass.NO_TRADE


def test_bounded_sizer_terminates_and_rejects_negative_only():
    result = bounded_best_size(max_principal=1000, evaluate=lambda n: 50 - abs(n-128), max_iterations=32)
    assert result.iterations <= 32
    assert result.principal > 0 and result.conservative_surplus > 0
    none = bounded_best_size(max_principal=100, evaluate=lambda n: -1, max_iterations=16)
    assert none.no_trade


def test_reference_stale_wide_disagreement_fail_closed():
    p = PegRiskPolicy(now_ns=1000, max_age_ns=50, max_confidence_ratio_ppm=1000, max_reference_disagreement_ppm=100, pyth_generation="pyth-core-2026-08-26")
    blockers = validate_references((ref(price=1_000_000, publish=900), ref(price=999_000, confidence=10_000, publish=1000)), p)
    assert Reason.REFERENCE_STALE in blockers
    assert Reason.REFERENCE_CONFIDENCE_WIDE in blockers
    assert Reason.REFERENCE_DISAGREEMENT in blockers


def test_qualification_never_grants_live_release_or_production():
    c = make_candidate(principal_mint="A", repayment_mint="A", legs=(leg("A","A",100,105,"p"),), asset_digests=("a",), reference_digests=("r",), pool_digests=("p",), conservative_surplus=5, recorded_offline=True)
    p = PegRiskPolicy(now_ns=1000, max_age_ns=200, max_confidence_ratio_ppm=1000, max_reference_disagreement_ppm=1000, pyth_generation="pyth-core-2026-08-26")
    q = qualify(candidate=c, assets=(asset(),), references=(ref(publish=950),), policy=p, source_commit="sha", release_id="rel", config_digest="cfg", policy_digest="pol")
    assert q.status == "RECORDED_OFFLINE"
    assert not q.live_enabled and not q.release_claim_allowed and not q.production_ready

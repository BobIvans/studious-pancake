from __future__ import annotations

import hashlib
import pytest

from src.market_economic_kernel_pr154 import (
    AssetEvidence, AtaWsolEvidence, Blocker, CostLedger, Decision, KernelEvidence,
    MarginFiEvidence, MarketKernelError, OpportunityEvidence, QuotaEvidence,
    RouteEvidence, RouteLeg, SizingEvidence, assert_pr154_exact_candidate,
    evaluate_pr154_market_kernel,
)

PROG = "JUPITER1111111111111111111111111111111111"
SOL = "So11111111111111111111111111111111111111112"


def h(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


def leg(i=1_000_000, o=1_040_000, expires=150, programs=(PROG,)):
    return RouteLeg(i, o, h(f"req{i}{o}"), h(f"res{i}{o}"), programs, expires)


def fixture(**overrides):
    first = leg()
    second = RouteLeg(1_040_000, 1_060_000, h("req2"), h("res2"), (PROG,), 150)
    values = dict(
        route=RouteEvidence(first, second, h("final-req"), h("final-res"), True),
        opportunity=OpportunityEvidence("opp-sol-usdc-1000000", h("identity"), True, True),
        quota=QuotaEvidence(h("quota"), True, True, True, True),
        marginfi=MarginFiEvidence(h("idl"), h("acct"), h("ix"), h("rpc"), h("gbvo"), 100, 99, False, True, True, True, True),
        assets=(AssetEvidence(SOL, h("owner"), h("ext"), h("auth"), h("rent"), h("fee"), True, True),),
        sizing=SizingEvidence("adaptive_grid", (500_000, 1_000_000, 1_500_000), 1_000_000, True),
        ledger=CostLedger(1_000_000, 3_000, 1_003_000, 5_000, 0, 1_000, 1_000, 2_000, 0, 4_000, 2_000, 4_000),
        ata_wsol=AtaWsolEvidence(True, True, True, True, True, True, True),
        attested_program_ids=frozenset({PROG}),
        now_slot=120,
        min_profit_atoms=1,
    )
    values.update(overrides)
    return KernelEvidence(**values)


def test_complete_evidence_returns_exact_candidate():
    result = evaluate_pr154_market_kernel(fixture())
    assert result.decision is Decision.EXACT_CANDIDATE
    assert result.candidate_allowed is True
    assert result.sender_submission_allowed is False
    assert result.live_claim_allowed is False
    assert len(result.evidence_hash) == 64


def test_second_leg_must_use_exact_first_leg_output():
    bad_second = RouteLeg(1, 1_060_000, h("bad-req2"), h("bad-res2"), (PROG,), 150)
    base = fixture()
    result = evaluate_pr154_market_kernel(fixture(route=RouteEvidence(base.route.first_leg, bad_second, h("f1"), h("f2"), True)))
    assert Blocker.ROUTE_AMOUNT_MISMATCH.value in result.blockers


def test_stale_route_blocks_candidate():
    assert Blocker.ROUTE_STALE.value in evaluate_pr154_market_kernel(fixture(now_slot=151)).blockers


def test_unattested_program_blocks_candidate():
    result = evaluate_pr154_market_kernel(fixture(attested_program_ids=frozenset()))
    assert any(x.startswith(Blocker.ROUTE_UNATTESTED_PROGRAM.value) for x in result.blockers)


def test_random_identity_and_missing_dedup_block():
    result = evaluate_pr154_market_kernel(fixture(opportunity=OpportunityEvidence("random-uuid", h("id"), False, False)))
    assert Blocker.RANDOM_OR_MISSING_OPPORTUNITY_ID.value in result.blockers
    assert Blocker.MISSING_PERSISTENT_DEDUP.value in result.blockers


def test_quota_requires_final_build_and_shared_limiter():
    result = evaluate_pr154_market_kernel(fixture(quota=QuotaEvidence(h("quota"), False, False, True, True)))
    assert Blocker.FINAL_BUILD_QUOTA_NOT_RESERVED.value in result.blockers
    assert Blocker.RATE_LIMITER_NOT_SHARED.value in result.blockers


def test_marginfi_must_be_complete_and_reviewed():
    bad = MarginFiEvidence("", h("acct"), h("ix"), h("rpc"), h("gbvo"), 100, 99, False, False, True, False, False)
    result = evaluate_pr154_market_kernel(fixture(marginfi=bad))
    assert Blocker.MARGINFI_INCOMPLETE.value in result.blockers
    assert Blocker.MARGINFI_NOT_REVIEWED.value in result.blockers


def test_mixed_slot_marginfi_blocks():
    bad = MarginFiEvidence(h("idl"), h("acct"), h("ix"), h("rpc"), h("gbvo"), 100, 99, True, True, True, True, True)
    assert Blocker.MARGINFI_MIXED_SLOT.value in evaluate_pr154_market_kernel(fixture(marginfi=bad)).blockers


def test_asset_attestation_and_lst_policy_required():
    bad = AssetEvidence(SOL, h("owner"), h("ext"), h("auth"), h("rent"), h("fee"), False, False)
    result = evaluate_pr154_market_kernel(fixture(assets=(bad,)))
    assert any(x.startswith(Blocker.ASSET_UNATTESTED.value) for x in result.blockers)
    assert any(x.startswith(Blocker.LST_OPTIONAL_NOT_DISABLED.value) for x in result.blockers)


def test_monotonic_sizing_assumption_blocks():
    result = evaluate_pr154_market_kernel(fixture(sizing=SizingEvidence("binary_monotonic", (1_000_000,), 1_000_000, False)))
    assert Blocker.MONOTONIC_SIZING_ASSUMED.value in result.blockers


def test_cost_ledger_requires_repayment_and_reserved_sol():
    ledger = CostLedger(1_000_000, 3_000, 1_000_000, 5_000, 0, 1_000, 1_000, 2_000, 1_000, 4_000, 2_000, 1)
    result = evaluate_pr154_market_kernel(fixture(ledger=ledger))
    assert Blocker.COST_LEDGER_INCOMPLETE.value in result.blockers
    assert Blocker.WALLET_SOL_UNRESERVED.value in result.blockers


def test_ata_wsol_lifecycle_required():
    result = evaluate_pr154_market_kernel(fixture(ata_wsol=AtaWsolEvidence(True, True, False, True, True, True, True)))
    assert Blocker.ATA_WSOL_LIFECYCLE_INCOMPLETE.value in result.blockers


def test_complete_but_unprofitable_evidence_is_no_trade():
    result = evaluate_pr154_market_kernel(fixture(min_profit_atoms=1_000_000_000))
    assert result.decision is Decision.NO_TRADE
    assert result.blockers == (Blocker.PROFIT_BELOW_THRESHOLD.value,)


def test_assert_helper_raises_on_blocked():
    with pytest.raises(MarketKernelError, match="PR154_BLOCKED"):
        assert_pr154_exact_candidate(fixture(now_slot=151))

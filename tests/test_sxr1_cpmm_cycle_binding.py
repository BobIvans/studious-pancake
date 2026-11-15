"""R10-1 pre-API market -> route -> paper qualification binding tests.

All fixtures are offline deterministic states; pytest-socket keeps the suite
network-free.  No signer, sender, wallet, borrowing or submission appears
anywhere in this module.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time

import pytest
from solders.pubkey import Pubkey

from src.durability import DurableLifecycleStore
from src.economics.capital import CapitalPolicy, NativeCostBreakdown
from src.economics.durable_reservations import (
    DurableCapitalCoordinator,
    WalletBalanceSnapshot,
)
from src.economics.non_monotonic_sizing import (
    PR118AssetAmount,
    PR118CostComponentKind,
    PR118CostLedgerEntry,
    PR118FlashRepaymentTerms,
    PR118TypedCostLedger,
)
from src.execution.quote_build_kernel import PoolIdentity, PoolIdentityKind
from src.market.observations import ObservationGeneration
from src.strategy.arbitrage_graph import VenueIdentity
from src.strategy.cpmm_cycle_binding import (
    BlockedVenueCandidate,
    CpmmBindingError,
    CpmmBindingRejection,
    PaperGateInputs,
    PoolLineage,
    RouteQualificationStatus,
    RouteSupport,
    VenueKind,
    classify_route_support,
    conservative_net_for_ledger,
    evaluate_exact_two_leg_route,
    evaluate_paper_gate,
    run_pre_api_route_qualification_replay,
)
from src.strategy.exact_cpmm_capacity import (
    CapacityEconomics,
    QualifiedCpmmState,
    RAYDIUM_CPMM_PROGRAM_ID,
    SolanaAssetIdentity,
)

pytestmark = pytest.mark.unit

NOW = 1_000.0
GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
GENERATION = ObservationGeneration(
    genesis_hash=GENESIS,
    provider_generation="fixture-provider-v1",
    asset_generation="fixture-assets-v1",
    policy_generation="shadow-only-v1",
    code_generation="r10-1-binding-v1",
)


def _asset(mint: str, **changes: object) -> SolanaAssetIdentity:
    values: dict[str, object] = {
        "domain": "solana-mainnet",
        "genesis_hash": GENESIS,
        "mint": mint,
        "token_program": TOKEN_PROGRAM,
        "token_revision": "spl-token-v1",
        "decimals": 9,
    }
    values.update(changes)
    return SolanaAssetIdentity(**values)  # type: ignore[arg-type]


WSOL = _asset("So11111111111111111111111111111111111111112")
B, C, D = (
    _asset(mint)
    for mint in (
        str(Pubkey.from_bytes(bytes([2]) * 32)),
        str(Pubkey.from_bytes(bytes([3]) * 32)),
        str(Pubkey.from_bytes(bytes([4]) * 32)),
    )
)


def _pool(
    market_id: str,
    asset_a: SolanaAssetIdentity,
    asset_b: SolanaAssetIdentity,
    reserves: tuple[int, int],
    **changes: object,
) -> QualifiedCpmmState:
    values: dict[str, object] = {
        "venue": VenueIdentity(RAYDIUM_CPMM_PROGRAM_ID, market_id),
        "asset_a": asset_a,
        "asset_b": asset_b,
        "reserve_a": reserves[0],
        "reserve_b": reserves[1],
        "fee_bps": 25,
        "slot": 100,
        "observed_at": NOW - 1,
        "expires_at": NOW + 1,
        "generation": GENERATION,
    }
    values.update(changes)
    return QualifiedCpmmState(**values)  # type: ignore[arg-type]


def _lineage(market_id: str, **changes: object) -> PoolLineage:
    values: dict[str, object] = {
        "correlation_group": f"raydium-cpmm:{market_id}",
        "aggregator_lineage": (),
        "pool_ids": (PoolIdentity(PoolIdentityKind.POOL_ADDRESS, market_id),),
    }
    values.update(changes)
    return PoolLineage(**values)  # type: ignore[arg-type]


def _policy() -> CapitalPolicy:
    return CapitalPolicy(
        protected_reserve_lamports=0,
        minimum_net_profit_lamports=1,
        maximum_priority_fee_lamports=10_000,
        maximum_jito_tip_lamports=10_000,
        maximum_peak_rent_lamports=10_000,
        contingency_lamports=0,
        maximum_flash_loan_lamports=1_000_000,
    )


def _coordinator(tmp_path: Path, name: str) -> DurableCapitalCoordinator:
    return DurableCapitalCoordinator(
        store=DurableLifecycleStore(tmp_path / f"capital-{name}.db"),
        policy=_policy(),
    )


def _wallet() -> WalletBalanceSnapshot:
    return WalletBalanceSnapshot(
        wallet_pubkey="wallet111111111111111111111111111111111111",
        native_lamports=10_000_000,
        context_slot=100,
        captured_at_ns=time.time_ns(),
        cluster_genesis=GENESIS,
    )


def _economics(network_fee: int = 0) -> CapacityEconomics:
    return CapacityEconomics(
        settlement_asset_id="WSOL",
        flash_fee_bps=0,
        protocol_rounding_atoms=0,
        native_costs=NativeCostBreakdown(base_network_fee_lamports=network_fee),
    )


def _replay(pools, tmp_path: Path, name: str, **changes: object):
    """Run the deterministic replay with default lineage for every pool."""

    lineage = {pool.venue: _lineage(pool.venue.market_id) for pool in pools}
    lineage.update(changes.pop("lineage_by_venue", {}))
    return run_pre_api_route_qualification_replay(
        pools=pools,
        settlement_asset=WSOL,
        now=NOW,
        probe_amount=changes.pop("probe_amount", 100),
        economics=changes.pop("economics", _economics()),
        coordinator=_coordinator(tmp_path, name),
        wallet_snapshot=_wallet(),
        lineage_by_venue=lineage,
        **changes,
    )


def _records_by_kind(report, kind: str):
    return [record for record in report.records if record.route_kind == kind]


# ---------------------------------------------------------------------------
# Positive paths
# ---------------------------------------------------------------------------


def test_positive_two_leg_route_is_exact_qualified_and_paper_blocked(
    tmp_path: Path,
) -> None:
    pools = (
        _pool("pool-1", WSOL, B, (1_000, 2_000)),
        _pool("pool-2", B, WSOL, (1_000, 2_000)),
    )
    report = _replay(pools, tmp_path, "two-leg")

    metrics = report.metrics
    assert metrics.discovered_market_count == 2
    assert metrics.identity_verified_market_count == 2
    assert metrics.rooted_state_count == 2
    assert metrics.topology_route_count == 1
    assert metrics.unique_semantic_route_count == 1
    assert metrics.exact_qualified_route_count == 1
    assert metrics.net_positive_route_count == 1
    assert metrics.capital_eligible_count == 1
    assert metrics.paper_attempt_count == 1
    assert metrics.paper_complete_count == 0
    assert metrics.paper_rejected_count == 1

    route_records = _records_by_kind(report, "two-leg")
    assert len(route_records) == 1
    record = route_records[0]
    assert record.support is RouteSupport.EXACT_SUPPORTED
    assert record.status is RouteQualificationStatus.PAPER_BLOCKED
    assert record.rejection is CpmmBindingRejection.NO_QUALIFIED_LENDER_EDGE
    assert record.selected_amount == 100
    assert record.gross_profit_atoms is not None and record.gross_profit_atoms > 0
    # Market candidates remain distinct from flashloan-eligible candidates.
    assert metrics.market_candidate_count == metrics.exact_qualified_route_count
    assert metrics.flashloan_eligible_count == metrics.capital_eligible_count


def test_positive_three_pool_triangle_selects_non_monotonic_optimum(
    tmp_path: Path,
) -> None:
    # Known integer vectors: gross outputs 6/9/8 for amounts 10/20/30; with a
    # 7-atom network fee only 20 and 30 survive and PR118 must pick 20.
    pools = (
        _pool("pool-1", WSOL, B, (333, 9_170)),
        _pool("pool-2", B, C, (2_350, 6_118)),
        _pool("pool-3", C, WSOL, (8_573, 266)),
    )
    report = _replay(
        pools,
        tmp_path,
        "triangle",
        amount_grid=(30, 10, 20),
        economics=_economics(network_fee=7),
    )

    # Both directed cycles of the triangle appear in topology; both run the
    # full exact grid, but only the profitable direction survives net costs.
    assert report.metrics.topology_route_count == 2
    assert report.metrics.exact_qualified_route_count == 2
    assert report.metrics.size_grid_evaluated_count == 6
    assert report.metrics.net_positive_route_count == 1
    route = [
        r
        for r in _records_by_kind(report, "3-pool-cycle")
        if r.status is RouteQualificationStatus.PAPER_BLOCKED
    ][0]
    assert route.selected_amount == 20
    assert route.conservative_net_atoms == 2


def test_positive_four_pool_cycle_is_exact_qualified(tmp_path: Path) -> None:
    pools = (
        _pool("pool-1", WSOL, B, (1_000, 2_000)),
        _pool("pool-2", B, C, (1_000, 2_000)),
        _pool("pool-3", C, D, (1_000, 2_000)),
        _pool("pool-4", D, WSOL, (1_000, 2_000)),
    )
    report = _replay(pools, tmp_path, "four", amount_grid=(10,))

    four_hop = [
        r
        for r in _records_by_kind(report, "4-pool-cycle")
        if r.hop_count == 4 and r.support is RouteSupport.EXACT_SUPPORTED
    ]
    assert four_hop
    assert any(r.status is RouteQualificationStatus.PAPER_BLOCKED for r in four_hop)
    assert report.metrics.exact_qualified_route_count >= 1


def test_positive_two_leg_exact_propagates_previous_leg_conservative_output() -> None:
    first = _pool("pool-1", WSOL, B, (1_000_000, 2_000_000))
    second = _pool("pool-2", B, WSOL, (1_000_000, 2_000_000))
    evaluation = evaluate_exact_two_leg_route(
        first,
        second,
        settlement_asset=WSOL,
        input_amount=10_000,
        now=NOW,
    )
    leg_two_input = evaluation.legs[1].requested_input
    assert leg_two_input == evaluation.legs[0].conservative_output
    assert leg_two_input != 10_000  # sequential amounts, never the probe again


# ---------------------------------------------------------------------------
# Economic negatives
# ---------------------------------------------------------------------------


def test_gross_positive_route_can_be_net_negative_after_costs(tmp_path: Path) -> None:
    pools = (
        _pool("pool-1", WSOL, B, (333, 9_170)),
        _pool("pool-2", B, C, (2_350, 6_118)),
        _pool("pool-3", C, WSOL, (8_573, 266)),
    )
    report = _replay(
        pools,
        tmp_path,
        "net-negative",
        amount_grid=(10, 20, 30),
        economics=_economics(network_fee=5_000),
    )

    assert report.metrics.exact_qualified_route_count >= 1
    assert report.metrics.net_positive_route_count == 0
    assert report.metrics.paper_attempt_count == 0
    rejected = [
        r for r in report.records if r.rejection is CpmmBindingRejection.NET_NEGATIVE
    ]
    assert rejected


def test_marginal_shortlist_rejected_by_exact_evaluator(tmp_path: Path) -> None:
    # Flat reserves make the marginal-rate product exactly 1, so the AGG-05
    # shortlist accepts the cycle; the exact fee-accounted evaluation loses.
    pools = (
        _pool("pool-1", WSOL, B, (1_000, 1_000)),
        _pool("pool-2", B, C, (1_000, 1_000)),
        _pool("pool-3", C, WSOL, (1_000, 1_000)),
    )
    report = _replay(pools, tmp_path, "shortlist-reject")

    assert report.metrics.shortlist_route_count >= 1
    reasons = dict(report.metrics.rejections)
    # Marginal-rate acceptance is topology only: the exact fee-accounted
    # evaluation is negative at every grid point and PR118 rejects the route.
    assert reasons.get(CpmmBindingRejection.NET_NEGATIVE.value, 0) >= 1
    assert report.metrics.net_positive_route_count == 0


def test_non_monotonic_grid_zero_point_does_not_abort_profitable_points(
    tmp_path: Path,
) -> None:
    pools = (
        _pool("pool-1", WSOL, B, (333, 9_170)),
        _pool("pool-2", B, C, (2_350, 6_118)),
        _pool("pool-3", C, WSOL, (8_573, 266)),
    )
    report = _replay(pools, tmp_path, "zero-point", amount_grid=(1, 10, 20))

    rejected_points = [
        r
        for r in report.records
        if r.rejection is CpmmBindingRejection.NEGATIVE_GROSS_OUTPUT
    ]
    assert not rejected_points  # amount-local point rejection stays in PR118
    assert report.metrics.net_positive_route_count == 1
    route = [
        r
        for r in _records_by_kind(report, "3-pool-cycle")
        if r.status is RouteQualificationStatus.PAPER_BLOCKED
    ][0]
    assert route.selected_amount == 20


def test_unknown_cost_denomination_blocks_instead_of_defaulting_to_zero() -> None:
    ledger = PR118TypedCostLedger(
        min_out=PR118AssetAmount("WSOL", 2_000),
        flash_repayment=PR118FlashRepaymentTerms("WSOL", 1_000, 5, 0),
        entries=(
            PR118CostLedgerEntry("USDC", PR118CostComponentKind.PROVIDER_FEE, 10),
        ),
        route_provenance_hash="a" * 64,
    )
    with pytest.raises(CpmmBindingError) as error:
        conservative_net_for_ledger(ledger)
    assert error.value.reason is CpmmBindingRejection.UNKNOWN_COST_DENOMINATION


# ---------------------------------------------------------------------------
# State / identity negatives
# ---------------------------------------------------------------------------


def test_stale_pool_state_is_typed_blocked(tmp_path: Path) -> None:
    pools = (
        _pool("pool-1", WSOL, B, (1_000, 2_000), observed_at=NOW - 10),
        _pool("pool-2", B, WSOL, (1_000, 2_000)),
    )
    report = _replay(pools, tmp_path, "stale")
    pool_records = _records_by_kind(report, "pool")
    assert any(
        r.rejection is CpmmBindingRejection.STALE_OR_FUTURE_STATE for r in pool_records
    )
    assert report.metrics.net_positive_route_count == 0


def test_mixed_observation_generation_never_shares_one_route(tmp_path: Path) -> None:
    other_generation = ObservationGeneration(
        genesis_hash=GENESIS, code_generation="other-code-generation"
    )
    pools = (
        _pool("pool-1", WSOL, B, (1_000, 2_000)),
        _pool("pool-2", B, WSOL, (1_000, 2_000), generation=other_generation),
    )
    report = _replay(pools, tmp_path, "generation")
    assert (
        dict(report.metrics.rejections).get(
            CpmmBindingRejection.MIXED_GENERATION.value, 0
        )
        == 1
    )
    assert report.metrics.topology_route_count == 0


def test_slot_skew_is_typed_rejected(tmp_path: Path) -> None:
    pools = (
        _pool("pool-1", WSOL, B, (1_000, 2_000), slot=100),
        _pool("pool-2", B, WSOL, (1_000, 2_000), slot=105),
    )
    report = _replay(pools, tmp_path, "skew")
    skew_records = [
        r
        for r in report.records
        if r.rejection is CpmmBindingRejection.SLOT_SKEW_EXCEEDED
    ]
    assert skew_records
    assert report.metrics.net_positive_route_count == 0


def test_identity_failures_are_typed_blocked(tmp_path: Path) -> None:
    wrong_program = replace(
        _pool("pool-1", WSOL, B, (1_000, 2_000)),
        venue=VenueIdentity("other-program", "pool-1"),
    )
    wrong_decimals = replace(
        _pool("pool-1", WSOL, B, (1_000, 2_000)),
        asset_a=replace(WSOL, decimals=6),
    )
    for bad_pool, expected_detail in (
        (wrong_program, "wrong-program"),
        (wrong_decimals, "invalid-asset-identity"),
    ):
        pools = (bad_pool, _pool("pool-2", B, WSOL, (1_000, 2_000)))
        report = _replay(pools, tmp_path, "identity")
        pool_records = _records_by_kind(report, "pool")
        assert any(
            r.rejection is CpmmBindingRejection.IDENTITY_UNQUALIFIED
            and r.detail is not None
            and expected_detail in r.detail
            for r in pool_records
        )
        assert report.metrics.identity_verified_market_count == 1


def test_non_closed_two_leg_path_is_rejected() -> None:
    first = _pool("pool-1", WSOL, B, (1_000, 2_000))
    uncoupled = _pool("pool-2", B, C, (1_000, 2_000))
    with pytest.raises(CpmmBindingError) as error:
        evaluate_exact_two_leg_route(
            first,
            uncoupled,
            settlement_asset=WSOL,
            input_amount=100,
            now=NOW,
        )
    assert error.value.reason is CpmmBindingRejection.NON_CLOSED_PATH


def test_repeated_venue_two_leg_route_is_rejected() -> None:
    pool = _pool("pool-1", WSOL, B, (1_000, 2_000))
    with pytest.raises(CpmmBindingError) as error:
        evaluate_exact_two_leg_route(
            pool,
            pool,
            settlement_asset=WSOL,
            input_amount=100,
            now=NOW,
        )
    assert error.value.reason is CpmmBindingRejection.NON_UNIQUE_PHYSICAL_POOL


# ---------------------------------------------------------------------------
# Pool identity / aggregator overlap negatives
# ---------------------------------------------------------------------------


def test_same_pool_alias_across_aggregators_is_correlated_not_independent(
    tmp_path: Path,
) -> None:
    shared = PoolIdentity(PoolIdentityKind.POOL_ADDRESS, "shared-physical-pool")
    pools = (
        _pool("agg-jupiter-view", WSOL, B, (1_000, 2_000)),
        _pool("agg-0x-view", WSOL, B, (1_000, 2_000)),
    )
    lineage = {
        pools[0].venue: PoolLineage(
            correlation_group="jupiter-aggregator", pool_ids=(shared,)
        ),
        pools[1].venue: PoolLineage(
            correlation_group="zero-x-aggregator", pool_ids=(shared,)
        ),
    }
    report = _replay(pools, tmp_path, "alias", lineage_by_venue=lineage)

    pool_records = _records_by_kind(report, "pool")
    assert [
        r.rejection is CpmmBindingRejection.POOL_ALIAS_CORRELATED for r in pool_records
    ].count(True) == 2
    assert report.metrics.provider_overlap_cluster_count >= 1
    assert report.metrics.unique_semantic_route_count == 0
    assert report.metrics.net_positive_route_count == 0


def test_unknown_lineage_blocks_independence(tmp_path: Path) -> None:
    pools = (
        _pool("pool-1", WSOL, B, (1_000, 2_000)),
        _pool("pool-2", B, WSOL, (1_000, 2_000)),
    )
    lineage = {
        pools[0].venue: _lineage("pool-1"),
        # Second venue declares a group but no pool ids: lineage UNKNOWN.
        pools[1].venue: PoolLineage(correlation_group="raydium-cpmm:pool-2"),
    }
    report = _replay(pools, tmp_path, "unknown-lineage", lineage_by_venue=lineage)
    pool_records = _records_by_kind(report, "pool")
    assert any(
        r.rejection is CpmmBindingRejection.POOL_LINEAGE_UNKNOWN for r in pool_records
    )
    assert report.metrics.net_positive_route_count == 0


# ---------------------------------------------------------------------------
# Route support matrix / blocked venue families
# ---------------------------------------------------------------------------


def test_route_support_matrix_exact_shortlist_and_blocked() -> None:
    assert (
        classify_route_support(venue_kind=VenueKind.RAYDIUM_CPMM, hop_count=2)
        is RouteSupport.EXACT_SUPPORTED
    )
    assert (
        classify_route_support(venue_kind=VenueKind.RAYDIUM_CPMM, hop_count=4)
        is RouteSupport.EXACT_SUPPORTED
    )
    assert (
        classify_route_support(venue_kind=VenueKind.RAYDIUM_CPMM, hop_count=5)
        is RouteSupport.SHORTLIST_ONLY
    )
    assert (
        classify_route_support(venue_kind=VenueKind.RAYDIUM_CLMM, hop_count=3)
        is RouteSupport.BLOCKED
    )
    assert (
        classify_route_support(venue_kind=VenueKind.METEORA_DLMM, hop_count=3)
        is RouteSupport.BLOCKED
    )
    assert (
        classify_route_support(venue_kind=VenueKind.ORDERBOOK, hop_count=2)
        is RouteSupport.BLOCKED
    )


def test_blocked_venue_families_stay_typed_blocked(tmp_path: Path) -> None:
    pools = (_pool("pool-1", WSOL, B, (1_000, 2_000)),)
    blocked = (
        BlockedVenueCandidate(
            label="clmm-position",
            venue_kind=VenueKind.RAYDIUM_CLMM,
            missing_evidence="missing tick-array/bitmap state for exact math",
        ),
        BlockedVenueCandidate(
            label="dlmm-position",
            venue_kind=VenueKind.METEORA_DLMM,
            missing_evidence="missing direction-specific bin arrays",
        ),
        BlockedVenueCandidate(
            label="clob-market",
            venue_kind=VenueKind.ORDERBOOK,
            missing_evidence="no verified sequence/depth fill semantics",
        ),
    )
    report = _replay(pools, tmp_path, "blocked", blocked_candidates=blocked)

    blocked_records = _records_by_kind(report, "blocked-venue")
    assert len(blocked_records) == 3
    assert blocked_records[2].rejection is CpmmBindingRejection.UNSUPPORTED_VENUE_KIND
    assert blocked_records[0].rejection is CpmmBindingRejection.MISSING_VENUE_STATE
    assert set(report.blocked_venue_kinds) == {
        "raydium-clmm",
        "meteora-dlmm",
        "orderbook",
    }
    matrix_kinds = {row[0] for row in report.route_support_matrix}
    assert "blocked-venue" in matrix_kinds
    assert report.metrics.exact_qualified_route_count == 0


def test_five_hop_shortlist_is_never_exact_promoted(tmp_path: Path) -> None:
    E = _asset(str(Pubkey.from_bytes(bytes([5]) * 32)))
    chain = (
        _pool("pool-1", WSOL, B, (1_000, 2_000)),
        _pool("pool-2", B, C, (1_000, 2_000)),
        _pool("pool-3", C, D, (1_000, 2_000)),
        _pool("pool-4", D, E, (1_000, 2_000)),
        _pool("pool-5", E, WSOL, (1_000, 2_000)),
    )
    report = _replay(chain, tmp_path, "five-hop", amount_grid=(10,))

    five_hop_records = [
        r
        for r in report.records
        if r.route_kind == "multihop-shortlist"
        and r.rejection is CpmmBindingRejection.EXACT_UNSUPPORTED_HOP_COUNT
        and r.hop_count == 5
    ]
    assert five_hop_records, "expected a 5-hop shortlist topology rejection"
    long_cycles = [
        r
        for r in report.records
        if r.hop_count >= 5 and r.support is RouteSupport.EXACT_SUPPORTED
    ]
    assert not long_cycles


# ---------------------------------------------------------------------------
# Paper seam gate
# ---------------------------------------------------------------------------


def test_paper_gate_progression_is_typed_and_fail_closed() -> None:
    assert (
        evaluate_paper_gate(PaperGateInputs())
        is CpmmBindingRejection.NO_QUALIFIED_LENDER_EDGE
    )
    assert (
        evaluate_paper_gate(PaperGateInputs(qualified_lender_edge_count=1))
        is CpmmBindingRejection.BUILDER_UNQUALIFIED
    )
    assert (
        evaluate_paper_gate(
            PaperGateInputs(
                qualified_lender_edge_count=1, builder_conformance_passed=True
            )
        )
        is CpmmBindingRejection.SIMULATION_SOURCE_BLOCKED
    )
    assert (
        evaluate_paper_gate(
            PaperGateInputs(
                qualified_lender_edge_count=1,
                builder_conformance_passed=True,
                simulation_available=True,
            )
        )
        is CpmmBindingRejection.QPR_NOT_READY
    )
    # Even a fully-ready claim cannot complete paper evidence in an offline
    # replay: no R05 simulation evidence owner exists here.
    assert (
        evaluate_paper_gate(
            PaperGateInputs(
                qualified_lender_edge_count=1,
                builder_conformance_passed=True,
                simulation_available=True,
                qpr_ready=True,
            )
        )
        is CpmmBindingRejection.PAPER_COMPLETE_UNAVAILABLE_OFFLINE
    )


def test_paper_gate_blocked_candidates_are_preserved_with_reasons(
    tmp_path: Path,
) -> None:
    pools = (
        _pool("pool-1", WSOL, B, (1_000, 2_000)),
        _pool("pool-2", B, WSOL, (1_000, 2_000)),
    )
    report = _replay(pools, tmp_path, "paper-gate")
    blocked = [
        r for r in report.records if r.status is RouteQualificationStatus.PAPER_BLOCKED
    ]
    assert blocked
    assert all(
        r.rejection is CpmmBindingRejection.NO_QUALIFIED_LENDER_EDGE for r in blocked
    )


# ---------------------------------------------------------------------------
# Determinism / evidence scope / safety
# ---------------------------------------------------------------------------


def test_replay_is_deterministic_across_runs(tmp_path: Path) -> None:
    pools = (
        _pool("pool-1", WSOL, B, (333, 9_170)),
        _pool("pool-2", B, C, (2_350, 6_118)),
        _pool("pool-3", C, WSOL, (8_573, 266)),
    )
    first = _replay(pools, tmp_path, "det-1", amount_grid=(30, 10, 20))
    second = _replay(pools, tmp_path, "det-2", amount_grid=(30, 10, 20))
    assert first.replay_digest == second.replay_digest
    assert first.to_json() == second.to_json()


def test_changed_state_changes_the_replay_digest(tmp_path: Path) -> None:
    pools = (
        _pool("pool-1", WSOL, B, (333, 9_170)),
        _pool("pool-2", B, C, (2_350, 6_118)),
        _pool("pool-3", C, WSOL, (8_573, 266)),
    )
    base = _replay(pools, tmp_path, "digest-base", amount_grid=(10,))
    changed_pools = (
        pools[0],
        _pool("pool-2", B, C, (2_500, 6_118)),
        pools[2],
    )
    changed = _replay(changed_pools, tmp_path, "digest-changed", amount_grid=(10,))
    assert base.replay_digest != changed.replay_digest


def test_report_marks_fixture_scope_and_no_execution_authority(
    tmp_path: Path,
) -> None:
    pools = (
        _pool("pool-1", WSOL, B, (1_000, 2_000)),
        _pool("pool-2", B, WSOL, (1_000, 2_000)),
    )
    report = _replay(pools, tmp_path, "scope")
    payload = report.to_json()
    metrics_json = payload["metrics"]
    assert metrics_json["evidence_scope"] == "fixture-replay"
    assert metrics_json["contains_live_evidence"] is False
    assert payload["sign_enabled"] is False
    assert payload["send_enabled"] is False
    assert payload["live_mode"] is False
    for record in payload["records"]:
        assert record["provenance"] == "fixture-replay"


def test_metrics_ratio_keys_are_separate_not_one_success_rate(tmp_path: Path) -> None:
    pools = (
        _pool("pool-1", WSOL, B, (1_000, 2_000)),
        _pool("pool-2", B, WSOL, (1_000, 2_000)),
    )
    report = _replay(pools, tmp_path, "ratios")
    ratios = report.metrics.to_json()["ratios"]
    assert set(ratios) == {
        "exact_qualification",
        "economic_survival",
        "capital_eligibility",
        "simulation_pass",
        "paper_completion",
    }
    assert ratios["paper_completion"] == "0.000000"  # attempts exist, none complete
    assert ratios["exact_qualification"] == "1.000000"
